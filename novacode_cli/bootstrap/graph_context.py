"""Graph context middleware for injecting project graph knowledge into system prompts.

This middleware loads the project graph from `.nova/project-graph.json` (created
by `/init`) on the first agent turn and injects a small **legend** into every
system prompt: the total node/edge counts and the module (community) names. That
is just enough orientation for the agent to know a graph exists and what the
module boundaries are called.

Everything richer — god nodes (central hubs), cross-module connections, key
files, and per-symbol locations/communities — is **intentionally NOT injected**.
It lives behind the `query_project_graph` tool so the agent looks it up on demand
instead of reasoning from a stale, heuristic summary standing in every prompt
(which both taxes context on every call and suppresses tool use).

Enabled by default when `.nova/project-graph.json` exists; silently skipped
when no graph is available.

The graph parsing logic lives in :mod:`novacode_cli.bootstrap.graph_reader`
so it is reusable outside the middleware stack (TUI dashboard, CLI reports).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from langchain.agents.middleware.types import (
    AgentMiddleware,
    AgentState,
    ModelRequest,
    ModelResponse,
)
from langchain_core.messages import SystemMessage

from novacode_cli.bootstrap.graph_reader import ProjectGraphReader

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from langchain_core.messages.tool import ToolMessage
    from langchain_core.tools import Command
    from langgraph.prebuilt.tool_node import ToolCallRequest


class GraphContextMiddleware(AgentMiddleware):
    """Inject a minimal project-graph legend into the system prompt.

    Loads `.nova/project-graph.json` on the first turn and caches it for the
    session. Injects only the node/edge counts and module (community) names —
    plus a pointer to `query_project_graph` for everything else (hubs,
    connections, key files, per-symbol locations).

    This gives the agent cheap architectural orientation without standing a
    heavy, heuristic summary in every prompt — the detail is fetched on demand
    through the tool.
    """

    state_schema = AgentState

    def __init__(
        self,
        *,
        workspace_root: str,
        enabled: bool | None = None,
    ) -> None:
        """Initialize the graph context middleware.

        Args:
            workspace_root: Path to the project workspace root.
            enabled: If False, this middleware is a no-op. Defaults to True.
        """
        self._reader = ProjectGraphReader(workspace_root)
        self._enabled = enabled if enabled is not None else True

    def before_agent(  # type: ignore[override]
        self,
        state: AgentState,  # noqa: ARG002
    ) -> None:
        """Pre-warm the instance cache on session start."""
        if not self._enabled:
            return
        import asyncio
        try:
            loop = asyncio.get_running_loop()
            loop.run_in_executor(None, self._reader.load)
        except RuntimeError:
            self._reader.load()

    def _inject(self, request: ModelRequest) -> ModelRequest:
        """Inject graph context into the system prompt."""
        if not self._enabled:
            return request

        summary = self._reader.load()
        if not summary:
            return request

        graph_context = summary.to_prompt_section()
        if not graph_context:
            return request

        block = (
            f"[Project Graph]\n{graph_context}\n"
            "This is a legend only — module names above, nothing else. The graph "
            "also knows each file/symbol's location, which community it belongs "
            "to, its blast radius (high-degree hubs), and cross-module "
            "connections — but none of that is listed here. Call "
            '`query_project_graph("<file or symbol>")` to look up those details '
            "on demand instead of inferring them from the module list.\n"
            "[/Project Graph]"
        )
        system_prompt = request.system_prompt
        new_prompt = (system_prompt + "\n\n" + block) if system_prompt else block
        return request.override(system_message=SystemMessage(new_prompt))

    async def _inject_async(self, request: ModelRequest) -> ModelRequest:
        """Inject graph context into the system prompt asynchronously."""
        if not self._enabled:
            return request

        import asyncio
        try:
            loop = asyncio.get_running_loop()
            summary = await loop.run_in_executor(None, self._reader.load)
        except RuntimeError:
            summary = self._reader.load()

        if not summary:
            return request

        graph_context = summary.to_prompt_section()
        if not graph_context:
            return request

        block = (
            f"[Project Graph]\n{graph_context}\n"
            "This is a legend only — module names above, nothing else. The graph "
            "also knows each file/symbol's location, which community it belongs "
            "to, its blast radius (high-degree hubs), and cross-module "
            "connections — but none of that is listed here. Call "
            '`query_project_graph("<file or symbol>")` to look up those details '
            "on demand instead of inferring them from the module list.\n"
            "[/Project Graph]"
        )
        system_prompt = request.system_prompt
        new_prompt = (system_prompt + "\n\n" + block) if system_prompt else block
        return request.override(system_message=SystemMessage(new_prompt))

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        """Inject graph context into the system prompt."""
        return handler(self._inject(request))

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        """Async variant — required when the agent runs via ``ainvoke``/``astream``.

        We load the graph asynchronously to avoid blocking the TUI event loop.
        """
        injected = await self._inject_async(request)
        return await handler(injected)

    # ------------------------------------------------------------------
    # File-read annotation (Phase 2 of graph-awareness design)
    # ------------------------------------------------------------------

    def _annotate_read_file(self, request: ToolCallRequest) -> ToolCallRequest:
        """Inject a one-line community annotation when the agent reads a file.

        Looks up the file path in the graph index and, if found, appends a
        compact community note to the system prompt. Scoped to one turn —
        the annotation is dropped after the model call completes.

        Args:
            request: The tool call request to annotate.

        Returns:
            The (possibly annotated) request.
        """
        if not self._enabled:
            return request

        tool_call = request.tool_call
        tool_name = tool_call.get("name", "")
        if tool_name != "read_file":
            return request

        args = tool_call.get("args", {})
        file_path = args.get("file_path", args.get("path", ""))
        if not file_path:
            return request

        # Load the index for O(1) file lookups
        index = self._reader._load_index()
        if index is None:
            return request

        file_map = index.get("file_map", {})
        entry = file_map.get(file_path)
        if entry is None:
            return request

        label = entry.get("community_label", f"Community {entry.get('community', '?')}")
        count = entry.get("symbols", [])
        connections = entry.get("connections", 0)
        annotation = (
            f"Note: {file_path} → community {label} "
            f"({len(count)} components, {connections} connections)"
        )

        # Inject into system prompt — scoped to this turn only
        system_prompt = request.system_prompt or ""
        new_prompt = system_prompt + "\n" + annotation
        return request.override(system_message=SystemMessage(new_prompt))

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command[Any]],
    ) -> ToolMessage | Command[Any]:
        """Synchronous wrapper — annotate read_file calls."""
        annotated = self._annotate_read_file(request)
        return handler(annotated)

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        """Async wrapper — annotate read_file calls."""
        annotated = self._annotate_read_file(request)
        return await handler(annotated)

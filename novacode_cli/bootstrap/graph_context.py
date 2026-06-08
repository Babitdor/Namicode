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

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from langchain.agents.middleware.types import (
    AgentMiddleware,
    AgentState,
    ModelRequest,
    ModelResponse,
)
from langchain_core.messages import SystemMessage

from novacode_cli.bootstrap.graph_reader import ProjectGraphReader


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
        state: AgentState,
    ) -> None:
        """Pre-warm the instance cache on session start."""
        if not self._enabled:
            return None
        self._reader.load()
        return None

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

        ``_inject`` is synchronous (it reads the cached graph), so we just inject
        and await the downstream handler. Without this, LangChain raises
        ``NotImplementedError`` for async invocations.
        """
        return await handler(self._inject(request))

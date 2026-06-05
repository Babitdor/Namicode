"""Middleware for integrating MCP servers with the agent.

This middleware loads MCP server configurations, discovers their tools,
and makes them available to the agent as callable functions.

Uses langchain-mcp-adapters for robust MCP client management with
persistent connections for stateful MCP servers.
"""

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, NotRequired, TypedDict

from langchain.agents.middleware.types import (
    AgentMiddleware,
    AgentState,
    ModelRequest,
    ModelResponse,
)
from langchain_core.tools import BaseTool
from langgraph.runtime import Runtime
from mcp.client.session import ClientSession

from novacode_cli.config.config import console
from novacode_cli.mcp.client import MultiServerMCPClient
from novacode_cli.mcp.config import MCPConfig
from novacode_cli.prompts import render_template

logger = logging.getLogger(__name__)


def _wrap_tool_error_handling(tool: BaseTool) -> BaseTool:
    """Make an MCP tool failure non-fatal to the agent run.

    MCP servers run over anyio task groups, so a tool-side failure (a
    server-side ``ERR_CONNECTION_REFUSED`` from playwright, a crashed server,
    a timeout) can surface as an exception — sometimes a
    ``BaseExceptionGroup`` — that escapes LangGraph's ToolNode error handling
    (which only catches ``Exception``) and aborts the entire turn.

    Wrapping the tool's coroutine/func to catch ``BaseException`` and return a
    readable error string means the model just sees the failure as the tool's
    result and can recover (retry, start the server, or report) instead of the
    run dying. ``KeyboardInterrupt``/``SystemExit`` are re-raised so Ctrl-C and
    shutdown still work.
    """

    # MCP tools are loaded with response_format="content_and_artifact", so they
    # must return a (content, artifact) two-tuple — returning a bare string for
    # those raises "a two-tuple ... is expected". Match the tool's declared
    # format so the error result is well-formed either way.
    response_format = getattr(tool, "response_format", "content")

    def _error_result(exc: BaseException) -> Any:
        # Plain ASCII (no emoji) so the result can't trip a cp1252 console.
        msg = f"[MCP error] tool '{tool.name}' failed: {exc}"
        if response_format == "content_and_artifact":
            return (msg, None)
        return msg

    orig_coroutine = getattr(tool, "coroutine", None)
    if orig_coroutine is not None:

        async def _safe_coroutine(*args: Any, **kwargs: Any) -> Any:
            try:
                return await orig_coroutine(*args, **kwargs)
            except (KeyboardInterrupt, SystemExit):
                raise
            except BaseException as exc:  # noqa: BLE001
                logger.warning("MCP tool '%s' failed: %s", tool.name, exc)
                return _error_result(exc)

        try:
            tool.coroutine = _safe_coroutine
        except Exception:  # noqa: BLE001
            pass

    orig_func = getattr(tool, "func", None)
    if orig_func is not None:

        def _safe_func(*args: Any, **kwargs: Any) -> Any:
            try:
                return orig_func(*args, **kwargs)
            except (KeyboardInterrupt, SystemExit):
                raise
            except BaseException as exc:  # noqa: BLE001
                logger.warning("MCP tool '%s' failed: %s", tool.name, exc)
                return _error_result(exc)

        try:
            tool.func = _safe_func
        except Exception:  # noqa: BLE001
            pass

    return tool


class MCPState(AgentState):
    """State for the MCP middleware."""

    mcp_tools: NotRequired[list[dict[str, Any]]]  # type: ignore[misc]
    """List of MCP tools metadata (name, description, server)."""


class MCPStateUpdate(TypedDict):
    """State update for the MCP middleware."""

    mcp_tools: list[dict[str, Any]]
    """List of MCP tools metadata."""


# MCP system prompt loaded from: NovaCode_cli/prompts/mcp.jinja


class MCPMiddleware(AgentMiddleware):
    """Middleware for integrating MCP servers with the agent.

    This middleware:
    - Loads MCP server configurations from ~/.nova/mcp.json
    - Discovers tools from configured MCP servers using langchain-mcp-adapters
    - Maintains persistent sessions for stateful MCP servers
    - Registers MCP tools with the agent

    Args:
        config_path: Optional path to mcp.json config file
    """

    state_schema = MCPState

    def __init__(self, config_path: Path | None = None) -> None:
        """Initialize the MCP middleware.

        Uses lazy discovery - tools are discovered on first use instead of at init time.
        This significantly speeds up agent startup by deferring MCP server connections.

        Args:
            config_path: Optional path to mcp.json config file.
                       Defaults to ~/.nova/mcp.json
        """
        self.mcp_config = MCPConfig(config_path)
        self._client: MultiServerMCPClient | None = None
        self._tools_cache: list[dict[str, Any]] = []
        self.tools: list[BaseTool] = []
        # Track persistent sessions for stateful servers
        self._sessions: dict[str, ClientSession] = {}
        self._session_contexts: list[contextlib.AbstractAsyncContextManager[Any]] = []

        # Lazy discovery - tools are discovered on first use
        self._tools_discovered = False
        self._discovery_lock = asyncio.Lock()
        # Cache for rendered MCP section to avoid re-rendering on every request
        self._mcp_section_cache: str | None = None
        self._mcp_section_cache_time: float = 0
        self._mcp_section_cache_ttl: float = 30.0  # 30 seconds TTL

    async def _ensure_tools_discovered(self) -> None:
        """Ensure tools are discovered before first use.

        This lazy discovery pattern defers MCP server connections until
        the first tool call, significantly speeding up agent startup.
        """
        if self._tools_discovered:
            return

        async with self._discovery_lock:
            if self._tools_discovered:
                return
            await self._discover_tools_async()
            self._tools_discovered = True

    def _discover_tools_sync(self) -> None:
        """Discover tools synchronously by running async discovery in a dedicated thread.

        Uses ``concurrent.futures.ThreadPoolExecutor`` to run ``asyncio.run()`` in a
        *separate* thread with its own event loop, avoiding the need for
        ``nest_asyncio`` and preventing blocking the main event loop.

        This is safe to call from:
        - A sync CLI command handler (no running loop)
        - A Textual worker thread (``@work(thread=True)``)
        - Any context where a loop *is* running (the dedicated thread handles it)
        """
        servers = self.mcp_config.list_servers()

        if not servers:
            return

        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(asyncio.run, self._discover_tools_async())
            # 90-second blanket timeout — discovery involves network I/O and
            # cold process starts for stdio servers (e.g. ``npx``/``uvx`` may
            # download packages on first run). A short timeout abandons the
            # result while the worker is still spawning servers, leaving
            # ``self.tools`` empty so MCP tools never register.
            future.result(timeout=90)

    async def _discover_tools_async(self) -> None:
        """Async implementation of tool discovery using MultiServerMCPClient.

        Uses the recommended stateless pattern from langchain-mcp-adapters:
        - Creates fresh sessions for each tool invocation
        - Uses load_mcp_tools with server_name for proper attribution
        - Handles errors gracefully with proper logging

        Discovery is parallelised across servers with a concurrency cap
        (``asyncio.Semaphore``) so that N servers are discovered concurrently
        instead of sequentially.
        """
        from langchain_mcp_adapters.tools import load_mcp_tools

        from novacode_cli.mcp.client import build_mcp_config_dict

        servers = self.mcp_config.list_servers()

        if not servers:
            return

        # Build combined config for all servers
        config_dict = build_mcp_config_dict(self.mcp_config)

        if not config_dict:
            return

        # Create the combined client
        self._client = MultiServerMCPClient(config_dict)

        # Reset the metadata cache so a re-run cannot accumulate duplicates.
        self._tools_cache = []

        # Cap concurrent discovery to avoid overwhelming the host
        _discovery_semaphore = asyncio.Semaphore(3)

        async def _discover_one(
            server_name: str, connection: dict[str, Any]
        ) -> list[BaseTool]:
            """Discover tools for a single MCP server."""
            async with _discovery_semaphore:
                try:
                    server_tools = await load_mcp_tools(
                        session=None,  # Stateless - creates fresh session per invocation
                        connection=connection,
                        server_name=server_name,
                        # Prefix tool names with the server name (e.g.
                        # ``serena_read_file``) so MCP tools never collide with
                        # the agent's built-in tools. Without this, servers like
                        # serena expose a bare ``read_file`` (which takes
                        # ``relative_path``) that shadows the built-in
                        # ``read_file`` (which takes ``file_path``), causing
                        # "Field required: relative_path" validation errors.
                        tool_name_prefix=True,
                    )

                    if server_tools:
                        # Make tool failures non-fatal: an MCP/anyio error (e.g.
                        # a playwright ERR_CONNECTION_REFUSED) can surface as a
                        # BaseExceptionGroup that escapes LangGraph's ToolNode
                        # error handling and aborts the whole turn. Wrapping each
                        # tool so it returns the error as a string lets the model
                        # see the failure and recover instead.
                        server_tools = [
                            _wrap_tool_error_handling(t) for t in server_tools
                        ]
                        # Build metadata cache with correct server attribution
                        for tool in server_tools:
                            input_schema = {}
                            if hasattr(tool, "args_schema") and tool.args_schema:
                                try:
                                    schema = tool.args_schema.model_json_schema()  # type: ignore
                                    input_schema = schema.get("properties", {})
                                except Exception:
                                    pass

                            self._tools_cache.append(
                                {
                                    "name": tool.name,
                                    "description": tool.description or "",
                                    "server": server_name,
                                    "input_schema": input_schema,
                                }
                            )

                    return server_tools

                except Exception as e:
                    # Log the error but continue with other servers
                    error_msg = str(e)
                    if "TaskGroup" in error_msg or "unhandled errors" in error_msg:
                        error_msg = "Connection timeout or initialization error"
                    console.print(
                        f"[yellow]Warning: Failed to connect to "
                        f"MCP server '{server_name}': {error_msg}[/yellow]"
                    )
                    return []

        # Discover all servers in parallel with concurrency cap
        tasks = [
            _discover_one(name, conn)
            for name, conn in config_dict.items()
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Flatten results — each _discover_one returns a list or an exception
        all_tools: list[BaseTool] = []
        for r in results:
            if isinstance(r, list):
                all_tools.extend(r)

        # Store all tools for the agent
        self.tools = all_tools  # type: ignore

        # Mark discovery as complete to avoid re-discovering on every message
        self._tools_discovered = True

    async def abefore_agent(
        self,
        state: MCPState,
        runtime: Runtime,
    ) -> MCPStateUpdate | None:
        """Store MCP tools metadata in state before the agent run starts.

        ``abefore_agent`` is a valid ``AgentMiddleware`` hook — the previous
        ``on_session_start`` name was NOT a recognised hook, so it never fired,
        which left ``mcp_tools`` state empty and the MCP doc section missing.

        Tools are normally discovered eagerly at agent-build time so they are
        registered with the graph; this hook defensively ensures discovery has
        run and exposes the metadata via state for the system-prompt section.

        Args:
            state: Current agent state.
            runtime: The LangGraph runtime instance.

        Returns:
            State update with MCP tools metadata, or None if no tools.
        """
        await self._ensure_tools_discovered()

        if not self._tools_cache:
            return None

        return {"mcp_tools": self._tools_cache}

    def _format_servers_list(
        self,
        servers: dict[str, Any],
        tools_metadata: list[dict[str, Any]],
    ) -> str:
        """Format MCP servers and their tools for display in system prompt.

        Uses O(n) algorithm by pre-grouping tools by server name.

        Args:
            servers: Dictionary of server configurations
            tools_metadata: List of tool metadata

        Returns:
            Formatted string for system prompt
        """
        lines = []

        # O(n) - Group tools by server name using dict
        tools_by_server: dict[str, list[dict[str, Any]]] = {}
        for tool in tools_metadata:
            server_name = tool.get("server", "")
            if server_name not in tools_by_server:
                tools_by_server[server_name] = []
            tools_by_server[server_name].append(tool)

        for name, config in servers.items():
            lines.append(f"\n**{name}** ({config.transport})")

            if config.description:
                lines.append(f"  {config.description}")

            # O(1) - Get tools for this server from pre-grouped dict
            server_tools = tools_by_server.get(name, [])

            if server_tools:
                lines.append(f"  Tools ({len(server_tools)}):")
                for tool in server_tools:
                    # Format tool with parameters
                    tool_line = f"    - {tool['name']}: {tool['description']}"
                    lines.append(tool_line)

                    # Show required parameters from input schema
                    input_schema = tool.get("input_schema", {})
                    if input_schema:
                        param_names = list(input_schema.keys())
                        if param_names:
                            params_str = ", ".join(param_names)
                            lines.append(f"      Parameters: {params_str}")
            else:
                lines.append("  (No tools available)")

            lines.append("")

        return "\n".join(lines)

    def _inject_mcp_section(
        self, request: ModelRequest
    ) -> ModelRequest:
        """Inject MCP documentation into the system prompt (shared by sync/async paths).

        Uses a TTL-backed cache (``_mcp_section_cache``) to avoid re-rendering the
        Jinja template on every model turn. The cache has a sliding window — each
        hit extends its lifetime — so active sessions keep the section hot without
        re-rendering, while idle sessions let the cache expire naturally.

        Args:
            request: The model request to modify.

        Returns:
            The request with MCP section injected into ``system_prompt``, or the
            original request unchanged if no MCP tools are configured.
        """
        # Prefer tools recorded in agent state, but fall back to the discovery
        # cache. State is only populated by the (now-removed) session-start hook;
        # the cache is filled by eager discovery at agent-build time, so this
        # fallback keeps the MCP doc section working regardless.
        mcp_tools = request.state.get("mcp_tools") or self._tools_cache
        if not mcp_tools:
            return request

        import time
        current_time = time.time()

        # Sliding-window cache: refresh on access to keep hot during active use
        if (
            self._mcp_section_cache is not None
            and current_time - self._mcp_section_cache_time < self._mcp_section_cache_ttl
        ):
            self._mcp_section_cache_time = current_time
            mcp_section = self._mcp_section_cache
        else:
            servers = self.mcp_config.list_servers()
            servers_list = self._format_servers_list(servers, mcp_tools)
            mcp_section = render_template("mcp.jinja", servers_list=servers_list)

            self._mcp_section_cache = mcp_section
            self._mcp_section_cache_time = current_time

        # Track context usage (best-effort)
        try:
            from novacode_cli.context import ContextManager

            budget = ContextManager().budget()
            tokens_added = budget.track_middleware("MCPMiddleware", mcp_section)
            logger.debug(
                f"MCPMiddleware added {tokens_added} tokens to context "
                f"(total: {budget.total_tokens}/{budget.max_tokens})"
            )
        except ImportError:
            pass

        system_prompt = (
            request.system_prompt + "\n\n" + mcp_section
            if request.system_prompt
            else mcp_section
        )
        return request.override(system_prompt=system_prompt)  # type: ignore

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        """Inject MCP tool information into the model request system prompt.

        MCP tools are registered statically via ``self.tools`` at init time, so
        they are already present in ``request.tools``. This method only injects
        the MCP documentation section into the system prompt.

        Delegates to the shared ``_inject_mcp_section()`` so that the sync and
        async paths stay in lockstep (same caching, same injection logic).
        """
        return handler(self._inject_mcp_section(request))

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        """(async) Inject MCP tool information into the model request system prompt.

        Delegates to the shared ``_inject_mcp_section()`` so that the sync and
        async paths stay in lockstep (same caching, same injection logic).
        """
        return await handler(self._inject_mcp_section(request))


__all__ = ["MCPMiddleware"]

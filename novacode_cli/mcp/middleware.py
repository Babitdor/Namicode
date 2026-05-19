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
        """Discover tools synchronously - kept for backwards compatibility.

        DEPRECATED: Use _ensure_tools_discovered() instead for lazy loading.
        This method is kept for any code that still needs synchronous discovery.
        """
        servers = self.mcp_config.list_servers()

        if not servers:
            return

        # Use nest_asyncio to allow nested event loops
        # This avoids ThreadPoolExecutor issues with Docker stdio on Windows
        import nest_asyncio

        nest_asyncio.apply()

        # Run async discovery
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        loop.run_until_complete(self._discover_tools_async())
        self._tools_discovered = True

    async def _discover_tools_async(self) -> None:
        """Async implementation of tool discovery using MultiServerMCPClient.

        Uses the recommended stateless pattern from langchain-mcp-adapters:
        - Creates fresh sessions for each tool invocation
        - Uses load_mcp_tools with server_name for proper attribution
        - Handles errors gracefully with proper logging
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

        all_tools: list[BaseTool] = []

        # Load tools from each server with proper attribution
        # Use load_mcp_tools with server_name parameter for proper tool attribution
        for server_name, connection in config_dict.items():
            try:
                # Load tools with server name for proper attribution
                # This follows the langchain-mcp-adapters best practices
                server_tools = await load_mcp_tools(
                    session=None,  # Stateless - creates fresh session per invocation
                    connection=connection,
                    server_name=server_name,
                )

                if server_tools:
                    all_tools.extend(server_tools)

                    # Build metadata cache with correct server attribution
                    for tool in server_tools:
                        # Extract input schema for better parameter documentation
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

            except Exception as e:
                # Log the error but continue with other servers
                error_msg = str(e)
                if "TaskGroup" in error_msg or "unhandled errors" in error_msg:
                    error_msg = "Connection timeout or initialization error"
                console.print(
                    f"[yellow]Warning: Failed to connect to "
                    f"MCP server '{server_name}': {error_msg}[/yellow]"
                )

        # Store all tools for the agent
        self.tools = all_tools  # type: ignore
        
        # Mark discovery as complete to avoid re-discovering on every message
        self._tools_discovered = True

    async def on_session_start(
        self,
        runtime: Runtime,
        *,
        state: MCPState,
    ) -> MCPStateUpdate | None:
        """Store MCP tools metadata in state at session start.

        Uses lazy discovery - tools are discovered on first session start,
        not at __init__ time, to speed up agent startup.

        Args:
            runtime: The LangGraph runtime instance
            state: Current agent state

        Returns:
            State update with MCP tools metadata, or None if no tools
        """
        # Lazy discovery - discover tools on first use
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

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        """Inject MCP tool information into the model request system prompt.

        MCP tools are already registered statically via self.tools at init time,
        so they are already present in request.tools. This method only injects
        the MCP documentation section into the system prompt.

        Args:
            request: The model request being processed
            handler: The handler function to call with the modified request

        Returns:
            The model response from the handler
        """
        # Get MCP tools metadata from state
        mcp_tools = request.state.get("mcp_tools", [])

        # Build updated request
        updated_request = request

        # Inject MCP info into system prompt if we have tools
        if mcp_tools:
            import time
            current_time = time.time()
            
            # Use cached MCP section if still valid (sliding window: refreshes on access)
            if (
                self._mcp_section_cache is not None
                and current_time - self._mcp_section_cache_time < self._mcp_section_cache_ttl
            ):
                # Sliding window: reset timer on access to keep cache alive during active use
                self._mcp_section_cache_time = current_time
                mcp_section = self._mcp_section_cache
            else:
                # Get servers configuration
                servers = self.mcp_config.list_servers()

                # Format the MCP section using Jinja template
                servers_list = self._format_servers_list(servers, mcp_tools)
                mcp_section = render_template("mcp.jinja", servers_list=servers_list)
                
                # Cache the rendered section
                self._mcp_section_cache = mcp_section
                self._mcp_section_cache_time = current_time

            # Track context usage
            try:
                from novacode_cli.utils.context_budget import get_context_budget
                budget = get_context_budget()
                tokens_added = budget.track_middleware("MCPMiddleware", mcp_section)
                logger.debug(
                    f"MCPMiddleware added {tokens_added} tokens to context "
                    f"(total: {budget.total_tokens}/{budget.max_tokens})"
                )
            except ImportError:
                # Context budget tracking not available
                pass

            # Inject into system prompt
            if updated_request.system_prompt:
                system_prompt = updated_request.system_prompt + "\n\n" + mcp_section
            else:
                system_prompt = mcp_section

            updated_request = updated_request.override(system_prompt=system_prompt)  # type: ignore

        return handler(updated_request)

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        """(async) Inject MCP tool information into the model request system prompt.

        MCP tools are already registered statically via self.tools at init time,
        so they are already present in request.tools. This method only injects
        the MCP documentation section into the system prompt.

        Args:
            request: The model request being processed
            handler: The handler function to call with the modified request

        Returns:
            The model response from the handler
        """
        # Get MCP tools metadata from state
        mcp_tools = request.state.get("mcp_tools", [])

        # Build updated request
        updated_request = request

        # Inject MCP info into system prompt if we have tools
        if mcp_tools:
            # Get servers configuration
            servers = self.mcp_config.list_servers()

            # Format the MCP section using Jinja template
            servers_list = self._format_servers_list(servers, mcp_tools)
            mcp_section = render_template("mcp.jinja", servers_list=servers_list)

            # Inject into system prompt
            if updated_request.system_prompt:
                system_prompt = updated_request.system_prompt + "\n\n" + mcp_section
            else:
                system_prompt = mcp_section

            updated_request = updated_request.override(system_prompt=system_prompt)  # type: ignore

        return await handler(updated_request)


__all__ = ["MCPMiddleware"]

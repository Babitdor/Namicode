"""Middleware for integrating MCP servers with the agent.

This middleware loads MCP server configurations, discovers their tools,
and makes them available to the agent as callable functions.

Uses langchain-mcp-adapters for robust MCP client management with
persistent connections.
"""

import asyncio
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

from namicode_cli.config import console
from namicode_cli.mcp.client import MultiServerMCPClient, create_mcp_client
from namicode_cli.mcp.config import MCPConfig


class MCPState(AgentState):
    """State for the MCP middleware."""

    mcp_tools: NotRequired[list[dict[str, Any]]]  # type: ignore[misc]
    """List of MCP tools metadata (name, description, server)."""


class MCPStateUpdate(TypedDict):
    """State update for the MCP middleware."""

    mcp_tools: list[dict[str, Any]]
    """List of MCP tools metadata."""


MCP_SYSTEM_PROMPT = """

## MCP (Model Context Protocol) Tools Available

You have access to external tools provided by MCP servers. These extend your capabilities beyond built-in tools.

**Connected MCP Servers:**

{servers_list}

**How to Use MCP Tools:**

1. **Tool Naming**: MCP tools are namespaced by server name
   - Format: `servername__toolname`
   - Example: `docs-langchain__search` calls the `search` tool from the `docs-langchain` server

2. **Discovery**: All available MCP tools are listed above with their descriptions
   - Check the tool descriptions to understand what each tool does
   - Review the input schema if you need to know what parameters are required

3. **Invocation**: Call MCP tools exactly like built-in tools
   - The middleware automatically routes calls to the appropriate MCP server
   - You don't need to manage connections or authentication
   - Results are returned just like any other tool call

**When to Use MCP Tools:**

- **Domain-Specific Knowledge**: When you need specialized information (e.g., documentation search, API lookups)
- **External Data Access**: When the task requires data from external systems or databases
- **Specialized Capabilities**: When MCP tools offer functionality not available in built-in tools
- **User's Domain**: When the user's request clearly maps to an MCP server's domain (check descriptions above)

**Best Practices:**

- Read tool descriptions carefully to understand capabilities and limitations
- Prefer MCP tools when they're specifically designed for the task
- Combine MCP tools with built-in tools for comprehensive solutions
- If an MCP tool fails, explain the error and try alternative approaches

**Important Notes:**

- MCP servers may become unavailable - handle tool call failures gracefully
- Some tools may have rate limits or require specific permissions
- Tool availability is shown above - only use tools that are currently listed

Remember: MCP tools are powerful extensions that give you access to specialized knowledge and capabilities. Use them when they match the user's needs!
"""


class MCPMiddleware(AgentMiddleware):
    """Middleware for integrating MCP servers with the agent.

    This middleware:
    - Loads MCP server configurations from ~/.nami/mcp.json
    - Discovers tools from configured MCP servers using langchain-mcp-adapters
    - Registers MCP tools with the agent
    - Handles tool calls by routing them to the appropriate MCP server

    Args:
        config_path: Optional path to mcp.json config file
    """

    state_schema = MCPState

    def __init__(self, config_path: Path | None = None) -> None:
        """Initialize the MCP middleware.

        Discovers MCP tools synchronously at init time so they can be
        registered with the agent.

        Args:
            config_path: Optional path to mcp.json config file.
                       Defaults to ~/.nami/mcp.json
        """
        self.mcp_config = MCPConfig(config_path)
        self._client: MultiServerMCPClient | None = None
        self._tools_cache: list[dict[str, Any]] = []
        self.tools: list[BaseTool] = []

        # Discover tools synchronously at init time
        self._discover_tools_sync()

    def _discover_tools_sync(self) -> None:
        """Discover tools from all configured MCP servers synchronously.

        This runs at __init__ time to ensure tools are available when
        the middleware is registered with the agent.
        """
        servers = self.mcp_config.list_servers()

        if not servers:
            return

        # Run async discovery in a sync context
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # If we're already in an async context, create a new loop in a thread
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(asyncio.run, self._discover_tools_async())
                    future.result(timeout=120)  # 120 second timeout
            else:
                loop.run_until_complete(self._discover_tools_async())
        except RuntimeError:
            # No event loop exists, create one
            asyncio.run(self._discover_tools_async())

    async def _discover_tools_async(self) -> None:
        """Async implementation of tool discovery using MultiServerMCPClient."""
        try:
            # Create the MCP client
            self._client = create_mcp_client(self.mcp_config)

            # Get tools from all configured servers
            mcp_tools = await self._client.get_tools()

            if not mcp_tools:
                return

            # Store tools for the agent
            self.tools = list(mcp_tools)

            # Build tools metadata cache for system prompt
            servers = self.mcp_config.list_servers()
            for tool in mcp_tools:
                # Extract server name from tool name (format: server__toolname)
                tool_name = tool.name
                server_name = None

                # Try to match tool to a server
                for name in servers:
                    if tool_name.startswith(f"{name}__"):
                        server_name = name
                        break

                if server_name is None:
                    # Fallback: use first part before __ as server name
                    parts = tool_name.split("__", 1)
                    server_name = parts[0] if len(parts) > 1 else "unknown"

                self._tools_cache.append({
                    "name": tool_name,
                    "description": tool.description or "",
                    "server": server_name,
                })

            # Count tools per server for status message
            server_counts: dict[str, int] = {}
            for tool_meta in self._tools_cache:
                server = tool_meta["server"]
                server_counts[server] = server_counts.get(server, 0) + 1

            for server, count in server_counts.items():
                console.print(f"[dim]MCP: Connected ({count} tools)[/dim]")

        except Exception as e:
            console.print(f"[yellow]Warning: Failed to initialize MCP client: {e}[/yellow]")

    async def on_session_start(
        self,
        runtime: Runtime,
        *,
        state: MCPState,
    ) -> MCPStateUpdate | None:
        """Store MCP tools metadata in state at session start.

        Tools are already discovered at __init__ time, so this just
        stores the metadata in state for use in system prompt injection.

        Args:
            runtime: The LangGraph runtime instance
            state: Current agent state

        Returns:
            State update with MCP tools metadata, or None if no tools
        """
        if not self._tools_cache:
            return None

        return {"mcp_tools": self._tools_cache}

    def _format_servers_list(
        self,
        servers: dict[str, Any],
        tools_metadata: list[dict[str, Any]],
    ) -> str:
        """Format MCP servers and their tools for display in system prompt.

        Args:
            servers: Dictionary of server configurations
            tools_metadata: List of tool metadata

        Returns:
            Formatted string for system prompt
        """
        lines = []

        for name, config in servers.items():
            lines.append(f"\n**{name}** ({config.transport})")

            if config.description:
                lines.append(f"  {config.description}")

            # List tools from this server
            server_tools = [t for t in tools_metadata if t["server"] == name]

            if server_tools:
                lines.append(f"  Tools ({len(server_tools)}):")
                for tool in server_tools:
                    lines.append(f"    - {tool['name']}: {tool['description']}")
            else:
                lines.append("  (No tools available)")

            lines.append("")

        return "\n".join(lines)

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        """Inject MCP information into the system prompt.

        This runs on every model call to ensure MCP tools info is always available.

        Args:
            request: The model request being processed
            handler: The handler function to call with the modified request

        Returns:
            The model response from the handler
        """
        # Get MCP tools metadata from state
        mcp_tools = request.state.get("mcp_tools", [])

        if not mcp_tools:
            # No MCP tools available, skip injection
            return handler(request)

        # Get servers configuration
        servers = self.mcp_config.list_servers()

        # Format the MCP section
        servers_list = self._format_servers_list(servers, mcp_tools)
        mcp_section = MCP_SYSTEM_PROMPT.format(servers_list=servers_list)

        # Inject into system prompt
        if request.system_prompt:
            system_prompt = request.system_prompt + "\n\n" + mcp_section
        else:
            system_prompt = mcp_section

        return handler(request.override(system_prompt=system_prompt))

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        """(async) Inject MCP information into the system prompt.

        Args:
            request: The model request being processed
            handler: The handler function to call with the modified request

        Returns:
            The model response from the handler
        """
        # Get MCP tools metadata from state
        mcp_tools = request.state.get("mcp_tools", [])

        if not mcp_tools:
            # No MCP tools available, skip injection
            return await handler(request)

        # Get servers configuration
        servers = self.mcp_config.list_servers()

        # Format the MCP section
        servers_list = self._format_servers_list(servers, mcp_tools)
        mcp_section = MCP_SYSTEM_PROMPT.format(servers_list=servers_list)

        # Inject into system prompt
        if request.system_prompt:
            system_prompt = request.system_prompt + "\n\n" + mcp_section
        else:
            system_prompt = mcp_section

        return await handler(request.override(system_prompt=system_prompt))


__all__ = ["MCPMiddleware"]

"""MCP (Model Context Protocol) integration for deepagents-cli.

Uses langchain-mcp-adapters for robust MCP client management with
support for multiple transport mechanisms (stdio, SSE, HTTP).
"""

from namicode_cli.mcp.config import MCPConfig, MCPServerConfig
from namicode_cli.mcp.middleware import MCPMiddleware

# Shared MCPMiddleware singleton - avoids reconnecting for each subagent
_shared_mcp_middleware: "MCPMiddleware | None" = None


def get_shared_mcp_middleware() -> "MCPMiddleware":
    """Get or create the shared MCPMiddleware instance.

    This singleton pattern ensures MCP servers are only connected once,
    even when multiple agents (main + subagents) are created.

    Returns:
        The shared MCPMiddleware instance.
    """
    global _shared_mcp_middleware
    if _shared_mcp_middleware is None:
        from namicode_cli.mcp.middleware import MCPMiddleware

        _shared_mcp_middleware = MCPMiddleware()
    return _shared_mcp_middleware


def reset_shared_mcp_middleware() -> None:
    """Reset the shared MCPMiddleware instance.

    Call this when starting a new session or when MCP config changes.
    """
    global _shared_mcp_middleware
    _shared_mcp_middleware = None


__all__ = [
    "MCPConfig",
    "MCPServerConfig",
    "get_shared_mcp_middleware",
    "reset_shared_mcp_middleware",
]

"""MCP (Model Context Protocol) integration for deepagents-cli.

Uses langchain-mcp-adapters for robust MCP client management with
support for multiple transport mechanisms (stdio, SSE, HTTP).

LAZY LOADING: This module uses lazy imports to reduce context footprint.
Only load what you need when you need it.
"""

# Lazy imports to reduce context footprint
# These are only loaded when actually needed
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from novacode_cli.mcp.middleware import MCPMiddleware

__all__ = [
    "MCPConfig",
    "MCPServerConfig",
    "get_shared_mcp_middleware",
    "reset_shared_mcp_middleware",
]


def __getattr__(name: str):
    """Lazy import to reduce context footprint.
    
    This ensures that MCP modules are only loaded when actually needed,
    reducing the initial context size from ~77 KB to ~2 KB.
    """
    if name == "MCPConfig":
        from novacode_cli.mcp.config import MCPConfig
        return MCPConfig
    elif name == "MCPServerConfig":
        from novacode_cli.mcp.config import MCPServerConfig
        return MCPServerConfig
    elif name == "MCPMiddleware":
        from novacode_cli.mcp.middleware import MCPMiddleware
        return MCPMiddleware
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# Shared MCPMiddleware singleton - avoids reconnecting for each subagent
_shared_mcp_middleware: "MCPMiddleware | None" = None


def get_shared_mcp_middleware() -> "MCPMiddleware":
    """Get or create the shared MCPMiddleware instance.

    This singleton pattern ensures MCP servers are only connected once,
    even when multiple agents (main + subagents) are created.
    
    Uses lazy loading to reduce context footprint - the middleware is only
    loaded when this function is called, not at module import time.

    Returns:
        The shared MCPMiddleware instance.
    """
    global _shared_mcp_middleware
    if _shared_mcp_middleware is None:
        from novacode_cli.mcp.middleware import MCPMiddleware

        _shared_mcp_middleware = MCPMiddleware()
    return _shared_mcp_middleware


def reset_shared_mcp_middleware() -> None:
    """Reset the shared MCPMiddleware instance.

    Call this when starting a new session or when MCP config changes.
    """
    global _shared_mcp_middleware
    _shared_mcp_middleware = None

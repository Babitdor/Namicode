"""MCP (Model Context Protocol) integration for deepagents-cli.

Uses langchain-mcp-adapters for robust MCP client management with
support for multiple transport mechanisms (stdio, SSE, HTTP).
"""

from namicode_cli.mcp.client import (
    MultiServerMCPClient,
    build_mcp_config_dict,
    check_server_connection,
    create_mcp_client,
)
from namicode_cli.mcp.config import MCPConfig, MCPServerConfig
from namicode_cli.mcp.middleware import MCPMiddleware

__all__ = [
    "MCPConfig",
    "MCPMiddleware",
    "MCPServerConfig",
    "MultiServerMCPClient",
    "build_mcp_config_dict",
    "check_server_connection",
    "create_mcp_client",
]

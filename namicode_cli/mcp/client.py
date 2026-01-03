"""MCP client for connecting to and managing MCP servers.

This module provides functionality to connect to MCP servers using the
langchain-mcp-adapters library, which supports persistent connections
and multiple transport mechanisms (stdio, SSE, HTTP).
"""

from typing import Any

from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.sessions import (
    Connection,
    SSEConnection,
    StdioConnection,
)

from namicode_cli.mcp.config import MCPConfig, MCPServerConfig


def build_mcp_server_config(
    config: MCPServerConfig,
) -> Connection:
    """Convert MCPServerConfig to langchain-mcp-adapters connection format.

    Args:
        config: Server configuration

    Returns:
        Connection configuration for MultiServerMCPClient
    """
    if config.transport == "stdio":
        connection: Connection = StdioConnection(
            transport="stdio",
            command=config.command or "",
            args=config.args or [],
            env=config.env if config.env else None,
        )
    elif config.transport == "http":
        # langchain-mcp-adapters uses "sse" for HTTP/SSE transport
        headers: dict[str, Any] | None = None
        if config.env:
            headers = {}
            for key, value in config.env.items():
                if key.startswith("HTTP_HEADER_"):
                    header_name = key[12:].replace("_", "-")
                    headers[header_name] = value
            if not headers:
                headers = None

        connection = SSEConnection(
            transport="sse",
            url=config.url or "",
            headers=headers,
        )
    else:
        msg = f"Unsupported transport type: {config.transport}"
        raise ValueError(msg)

    return connection


def build_mcp_config_dict(mcp_config: MCPConfig) -> dict[str, Connection]:
    """Build configuration dictionary for MultiServerMCPClient.

    Args:
        mcp_config: MCP configuration manager

    Returns:
        Configuration dict for MultiServerMCPClient
    """
    servers = mcp_config.list_servers()
    config_dict: dict[str, Connection] = {}

    for name, config in servers.items():
        try:
            config_dict[name] = build_mcp_server_config(config)
        except ValueError:
            # Skip servers with invalid configuration
            continue

    return config_dict


def create_mcp_client(
    mcp_config: MCPConfig | None = None,
) -> MultiServerMCPClient:
    """Create a MultiServerMCPClient from MCP configuration.

    Args:
        mcp_config: MCP configuration manager. If None, loads from default path.

    Returns:
        Configured MultiServerMCPClient instance
    """
    if mcp_config is None:
        mcp_config = MCPConfig()

    config_dict = build_mcp_config_dict(mcp_config)

    if not config_dict:
        # Return empty client if no servers configured
        return MultiServerMCPClient(None)

    return MultiServerMCPClient(config_dict)


async def check_server_connection(name: str, config: MCPServerConfig) -> tuple[bool, str]:
    """Check connection to an MCP server.

    This function tests whether a connection can be established to the given
    MCP server configuration.

    Args:
        name: Server name/identifier
        config: Server configuration

    Returns:
        Tuple of (success, message)
    """
    try:
        server_config = build_mcp_server_config(config)
        client = MultiServerMCPClient({name: server_config})

        tools = await client.get_tools()
        return True, f"Connected successfully. Found {len(tools)} tools."

    except Exception as e:
        return False, f"Connection failed: {e}"


__all__ = [
    "Connection",
    "MultiServerMCPClient",
    "build_mcp_config_dict",
    "build_mcp_server_config",
    "check_server_connection",
    "create_mcp_client",
]

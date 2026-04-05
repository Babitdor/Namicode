"""Unit tests for MCP middleware functionality."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from novacode_cli.mcp.config import MCPConfig, MCPServerConfig
from novacode_cli.mcp.middleware import MCPMiddleware


class TestMCPMiddlewareInit:
    """Test MCPMiddleware initialization."""

    def test_init_default_config_path(self, tmp_path: Path):
        """Test initialization with empty config — tools_cache should be empty."""
        config_path = tmp_path / "mcp.json"
        middleware = MCPMiddleware(config_path=config_path)
        assert middleware.mcp_config is not None
        # .clients was removed; use ._client (MultiServerMCPClient) instead
        assert middleware._tools_cache == []

    def test_init_custom_config_path(self, tmp_path: Path):
        """Test initialization with custom config path."""
        config_path = tmp_path / "custom_mcp.json"
        middleware = MCPMiddleware(config_path=config_path)
        assert middleware.mcp_config.config_path == config_path


class TestMCPMiddlewareFormatServersList:
    """Test _format_servers_list method."""

    def test_format_empty_servers(self, tmp_path: Path):
        """Test formatting with no servers."""
        middleware = MCPMiddleware(config_path=tmp_path / "mcp.json")
        result = middleware._format_servers_list({}, [])
        assert result == ""

    def test_format_single_server_no_tools(self, tmp_path: Path):
        """Test formatting a single server with no tools."""
        middleware = MCPMiddleware(config_path=tmp_path / "mcp.json")

        servers = {
            "test-server": MCPServerConfig(
                transport="http",
                url="https://example.com/mcp",
                description="Test server description",
            )
        }

        result = middleware._format_servers_list(servers, [])

        assert "**test-server**" in result
        assert "(http)" in result
        assert "Test server description" in result
        assert "(No tools available)" in result

    def test_format_server_with_tools(self, tmp_path: Path):
        """Test formatting a server with tools."""
        middleware = MCPMiddleware(config_path=tmp_path / "mcp.json")

        servers = {
            "docs": MCPServerConfig(
                transport="http",
                url="https://docs.example.com/mcp",
            )
        }

        tools = [
            {"name": "search", "description": "Search documentation", "server": "docs"},
            {"name": "fetch", "description": "Fetch a page", "server": "docs"},
        ]

        result = middleware._format_servers_list(servers, tools)

        assert "**docs**" in result
        assert "Tools (2):" in result
        assert "search: Search documentation" in result
        assert "fetch: Fetch a page" in result

    def test_format_multiple_servers(self, tmp_path: Path):
        """Test formatting multiple servers."""
        middleware = MCPMiddleware(config_path=tmp_path / "mcp.json")

        servers = {
            "server1": MCPServerConfig(transport="http", url="https://one.com"),
            "server2": MCPServerConfig(transport="stdio", command="python"),
        }

        tools = [
            {"name": "tool1", "description": "Tool from server1", "server": "server1"},
            {"name": "tool2", "description": "Tool from server2", "server": "server2"},
        ]

        result = middleware._format_servers_list(servers, tools)

        assert "**server1**" in result
        assert "**server2**" in result
        assert "(http)" in result
        assert "(stdio)" in result


class TestMCPMiddlewareWrapModelCall:
    """Test wrap_model_call and awrap_model_call methods."""

    def test_wrap_model_call_no_mcp_tools(self, tmp_path: Path):
        """Test wrap_model_call skips injection when no MCP tools."""
        middleware = MCPMiddleware(config_path=tmp_path / "mcp.json")

        mock_request = MagicMock()
        mock_request.state = {}  # No mcp_tools
        mock_request.system_prompt = "Original prompt"

        mock_handler = MagicMock(return_value="response")

        result = middleware.wrap_model_call(mock_request, mock_handler)

        # Handler should be called with original request (no override)
        mock_handler.assert_called_once_with(mock_request)
        assert result == "response"

    def test_wrap_model_call_with_mcp_tools(self, tmp_path: Path):
        """Test wrap_model_call injects MCP section into prompt."""
        config_path = tmp_path / "mcp.json"
        middleware = MCPMiddleware(config_path=config_path)

        # Add a server to config
        middleware.mcp_config.add_server(
            "test",
            MCPServerConfig(transport="http", url="https://example.com"),
        )

        mock_request = MagicMock()
        mock_request.state = {
            "mcp_tools": [{"name": "search", "description": "Search docs", "server": "test"}]
        }
        mock_request.system_prompt = "Original prompt"

        modified_request = MagicMock()
        mock_request.override = MagicMock(return_value=modified_request)

        mock_handler = MagicMock(return_value="response")

        result = middleware.wrap_model_call(mock_request, mock_handler)

        # Handler should be called with modified request
        mock_handler.assert_called_once_with(modified_request)
        mock_request.override.assert_called_once()

        # Check the system_prompt argument
        call_kwargs = mock_request.override.call_args[1]
        new_prompt = call_kwargs["system_prompt"]
        assert "Original prompt" in new_prompt
        assert "MCP" in new_prompt
        assert "test" in new_prompt

    @pytest.mark.asyncio
    async def test_awrap_model_call_no_mcp_tools(self, tmp_path: Path):
        """Test awrap_model_call skips injection when no MCP tools."""
        middleware = MCPMiddleware(config_path=tmp_path / "mcp.json")

        mock_request = MagicMock()
        mock_request.state = {}

        mock_handler = AsyncMock(return_value="response")

        result = await middleware.awrap_model_call(mock_request, mock_handler)

        mock_handler.assert_called_once_with(mock_request)
        assert result == "response"

    @pytest.mark.asyncio
    async def test_awrap_model_call_with_mcp_tools(self, tmp_path: Path):
        """Test awrap_model_call injects MCP section into prompt."""
        config_path = tmp_path / "mcp.json"
        middleware = MCPMiddleware(config_path=config_path)

        middleware.mcp_config.add_server(
            "test",
            MCPServerConfig(transport="http", url="https://example.com"),
        )

        mock_request = MagicMock()
        mock_request.state = {
            "mcp_tools": [{"name": "fetch", "description": "Fetch page", "server": "test"}]
        }
        mock_request.system_prompt = "Base prompt"

        modified_request = MagicMock()
        mock_request.override = MagicMock(return_value=modified_request)

        mock_handler = AsyncMock(return_value="async response")

        result = await middleware.awrap_model_call(mock_request, mock_handler)

        mock_handler.assert_called_once_with(modified_request)
        assert result == "async response"


@pytest.mark.skip(reason="create_mcp_tools() and .clients were removed — now uses MultiServerMCPClient")
class TestMCPMiddlewareCreateMCPTools:
    """Test create_mcp_tools method."""

    def test_create_mcp_tools_empty_cache(self, tmp_path: Path):
        """Test create_mcp_tools returns empty list when no tools cached."""
        middleware = MCPMiddleware(config_path=tmp_path / "mcp.json")
        tools = middleware.create_mcp_tools()
        assert tools == []

    def test_create_mcp_tools_creates_structured_tools(self, tmp_path: Path):
        """Test create_mcp_tools creates StructuredTool instances."""
        middleware = MCPMiddleware(config_path=tmp_path / "mcp.json")

        # Simulate cached tools
        middleware._tools_cache = [
            {
                "name": "search",
                "description": "Search for documents",
                "server": "docs-server",
                "inputSchema": {"type": "object"},
            },
            {
                "name": "fetch",
                "description": "Fetch a URL",
                "server": "web-server",
                "inputSchema": {},
            },
        ]

        # Add mock clients
        middleware.clients["docs-server"] = MagicMock()
        middleware.clients["web-server"] = MagicMock()

        tools = middleware.create_mcp_tools()

        assert len(tools) == 2
        # Check tool names are namespaced
        tool_names = [t.name for t in tools]
        assert "docs-server__search" in tool_names
        assert "web-server__fetch" in tool_names

    def test_create_mcp_tools_closure_fix(self, tmp_path: Path):
        """Test that the closure bug fix works correctly.

        Each tool should call the correct server and tool name,
        not the last one in the loop.
        """
        middleware = MCPMiddleware(config_path=tmp_path / "mcp.json")

        # Simulate multiple tools
        middleware._tools_cache = [
            {"name": "tool1", "description": "First tool", "server": "server1"},
            {"name": "tool2", "description": "Second tool", "server": "server2"},
            {"name": "tool3", "description": "Third tool", "server": "server3"},
        ]

        # Create mock clients
        for server in ["server1", "server2", "server3"]:
            middleware.clients[server] = MagicMock()

        tools = middleware.create_mcp_tools()

        # Verify each tool has the correct name binding
        assert tools[0].name == "server1__tool1"
        assert tools[1].name == "server2__tool2"
        assert tools[2].name == "server3__tool3"

        # The actual function calls would need to be tested async,
        # but we've verified the tool metadata is correctly bound


@pytest.mark.skip(reason=".clients was removed — tool calling now uses MultiServerMCPClient")
class TestMCPMiddlewareToolCaller:
    """Test _create_mcp_tool_caller method."""

    @pytest.mark.asyncio
    async def test_tool_caller_success(self, tmp_path: Path):
        """Test tool caller invokes correct client and tool."""
        middleware = MCPMiddleware(config_path=tmp_path / "mcp.json")

        # Create mock client
        mock_client = AsyncMock()
        mock_client.call_tool = AsyncMock(return_value={"result": "success"})
        middleware.clients["test-server"] = mock_client

        # Create tool caller
        caller = middleware._create_mcp_tool_caller("test-server", "search")

        # Call the tool
        result = await caller(query="test query")

        # Verify correct client and tool were called
        mock_client.call_tool.assert_called_once_with("search", arguments={"query": "test query"})
        assert result == {"result": "success"}

    @pytest.mark.asyncio
    async def test_tool_caller_server_not_found(self, tmp_path: Path):
        """Test tool caller raises error when server not found."""
        middleware = MCPMiddleware(config_path=tmp_path / "mcp.json")
        # No clients registered

        caller = middleware._create_mcp_tool_caller("nonexistent", "tool")

        with pytest.raises(ValueError, match="MCP server 'nonexistent' not found"):
            await caller()

    @pytest.mark.asyncio
    async def test_tool_caller_preserves_closure(self, tmp_path: Path):
        """Test that tool caller properly captures server and tool names.

        This is the key test for the closure bug fix.
        """
        middleware = MCPMiddleware(config_path=tmp_path / "mcp.json")

        # Create multiple mock clients
        mock_client1 = AsyncMock()
        mock_client1.call_tool = AsyncMock(return_value={"from": "server1"})
        mock_client2 = AsyncMock()
        mock_client2.call_tool = AsyncMock(return_value={"from": "server2"})

        middleware.clients["server1"] = mock_client1
        middleware.clients["server2"] = mock_client2

        # Create multiple tool callers
        caller1 = middleware._create_mcp_tool_caller("server1", "tool_a")
        caller2 = middleware._create_mcp_tool_caller("server2", "tool_b")

        # Call both tools
        result1 = await caller1(arg="value1")
        result2 = await caller2(arg="value2")

        # Verify each caller used the correct server and tool
        mock_client1.call_tool.assert_called_once_with("tool_a", arguments={"arg": "value1"})
        mock_client2.call_tool.assert_called_once_with("tool_b", arguments={"arg": "value2"})

        assert result1 == {"from": "server1"}
        assert result2 == {"from": "server2"}

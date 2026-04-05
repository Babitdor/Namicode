"""Unit tests for MCP client functionality."""

# MCPClient wrapper was removed; the MCP layer now uses MultiServerMCPClient
# directly from langchain_mcp_adapters. These tests need rewriting.
import pytest

pytest.skip("MCPClient class was removed — tests need rewriting", allow_module_level=True)

from unittest.mock import AsyncMock, MagicMock, patch  # noqa: E402

from novacode_cli.mcp.client import MCPClient, check_server_connection  # noqa: E402
from novacode_cli.mcp.config import MCPServerConfig


class TestMCPClientInit:
    """Test MCPClient initialization."""

    def test_init_with_http_config(self):
        """Test initialization with HTTP transport config."""
        config = MCPServerConfig(transport="http", url="https://example.com/mcp")
        client = MCPClient("test-server", config)

        assert client.name == "test-server"
        assert client.config == config
        assert client._session is None

    def test_init_with_stdio_config(self):
        """Test initialization with stdio transport config."""
        config = MCPServerConfig(
            transport="stdio",
            command="python",
            args=["-m", "server"],
        )
        client = MCPClient("local-server", config)

        assert client.name == "local-server"
        assert client.config.command == "python"


class TestMCPClientConnect:
    """Test MCPClient connect method."""

    @pytest.mark.asyncio
    async def test_connect_stdio_missing_command(self):
        """Test stdio connect raises error when command is missing."""
        # Create config without validation (simulating edge case)
        config = MCPServerConfig(transport="http", url="https://example.com")
        config.transport = "stdio"  # type: ignore[assignment]
        config.command = None

        client = MCPClient("test", config)

        with pytest.raises(ValueError, match="stdio transport requires a command"):
            async with client.connect():
                pass

    @pytest.mark.asyncio
    async def test_connect_http_missing_url(self):
        """Test HTTP connect raises error when URL is missing."""
        # Create config without validation (simulating edge case)
        config = MCPServerConfig(transport="stdio", command="python")
        config.transport = "http"  # type: ignore[assignment]
        config.url = None

        client = MCPClient("test", config)

        with pytest.raises(ValueError, match="HTTP transport requires a URL"):
            async with client.connect():
                pass

    @pytest.mark.asyncio
    async def test_connect_unsupported_transport(self):
        """Test connect raises error for unsupported transport."""
        config = MCPServerConfig(transport="http", url="https://example.com")
        config.transport = "websocket"  # type: ignore[assignment]

        client = MCPClient("test", config)

        with pytest.raises(ValueError, match="Unsupported transport type"):
            async with client.connect():
                pass

    @pytest.mark.asyncio
    async def test_connect_stdio_success(self):
        """Test successful stdio connection with mocked subprocess."""
        config = MCPServerConfig(
            transport="stdio",
            command="python",
            args=["-m", "test_server"],
        )
        client = MCPClient("test", config)

        # Mock the stdio_client and ClientSession
        mock_session = AsyncMock()
        mock_session.initialize = AsyncMock()

        with patch("NovaCode_cli.mcp.client.stdio_client") as mock_stdio:
            with patch("NovaCode_cli.mcp.client.ClientSession") as mock_session_class:
                # Setup mock context managers
                mock_read = MagicMock()
                mock_write = MagicMock()

                mock_stdio.return_value.__aenter__ = AsyncMock(return_value=(mock_read, mock_write))
                mock_stdio.return_value.__aexit__ = AsyncMock(return_value=None)

                mock_session_class.return_value.__aenter__ = AsyncMock(return_value=mock_session)
                mock_session_class.return_value.__aexit__ = AsyncMock(return_value=None)

                async with client.connect() as session:
                    assert session == mock_session
                    mock_session.initialize.assert_called_once()

    @pytest.mark.asyncio
    async def test_connect_http_success(self):
        """Test successful HTTP/SSE connection with mocked client."""
        config = MCPServerConfig(
            transport="http",
            url="https://example.com/sse",
        )
        client = MCPClient("test", config)

        # Mock the sse_client and ClientSession
        mock_session = AsyncMock()
        mock_session.initialize = AsyncMock()

        with patch("NovaCode_cli.mcp.client.sse_client") as mock_sse:
            with patch("NovaCode_cli.mcp.client.ClientSession") as mock_session_class:
                # Setup mock context managers
                mock_read = MagicMock()
                mock_write = MagicMock()

                mock_sse.return_value.__aenter__ = AsyncMock(return_value=(mock_read, mock_write))
                mock_sse.return_value.__aexit__ = AsyncMock(return_value=None)

                mock_session_class.return_value.__aenter__ = AsyncMock(return_value=mock_session)
                mock_session_class.return_value.__aexit__ = AsyncMock(return_value=None)

                async with client.connect() as session:
                    assert session == mock_session
                    mock_session.initialize.assert_called_once()

                # Verify sse_client was called with correct URL
                mock_sse.assert_called_once()
                call_kwargs = mock_sse.call_args[1]
                assert call_kwargs["url"] == "https://example.com/sse"

    @pytest.mark.asyncio
    async def test_connect_http_with_headers(self):
        """Test HTTP connection passes headers from env config."""
        config = MCPServerConfig(
            transport="http",
            url="https://example.com/sse",
            env={
                "HTTP_HEADER_X_API_KEY": "secret-key",
                "HTTP_HEADER_AUTHORIZATION": "Bearer token",
                "OTHER_VAR": "ignored",  # Should not become a header
            },
        )
        client = MCPClient("test", config)

        mock_session = AsyncMock()
        mock_session.initialize = AsyncMock()

        with patch("NovaCode_cli.mcp.client.sse_client") as mock_sse:
            with patch("NovaCode_cli.mcp.client.ClientSession") as mock_session_class:
                mock_read = MagicMock()
                mock_write = MagicMock()

                mock_sse.return_value.__aenter__ = AsyncMock(return_value=(mock_read, mock_write))
                mock_sse.return_value.__aexit__ = AsyncMock(return_value=None)

                mock_session_class.return_value.__aenter__ = AsyncMock(return_value=mock_session)
                mock_session_class.return_value.__aexit__ = AsyncMock(return_value=None)

                async with client.connect():
                    pass

                # Verify headers were passed correctly
                call_kwargs = mock_sse.call_args[1]
                headers = call_kwargs.get("headers", {})
                assert "X-API-KEY" in headers or "X-Api-Key" in headers
                assert (
                    headers.get("X-API-KEY") == "secret-key"
                    or headers.get("X-Api-Key") == "secret-key"
                )


class TestMCPClientListTools:
    """Test MCPClient list_tools method."""

    @pytest.mark.asyncio
    async def test_list_tools_success(self):
        """Test listing tools from MCP server."""
        config = MCPServerConfig(transport="http", url="https://example.com/mcp")
        client = MCPClient("test", config)

        # Create mock tool objects
        mock_tool1 = MagicMock()
        mock_tool1.name = "search"
        mock_tool1.description = "Search documents"
        mock_tool1.inputSchema = {"type": "object", "properties": {"query": {"type": "string"}}}

        mock_tool2 = MagicMock()
        mock_tool2.name = "fetch"
        mock_tool2.description = None  # Test None description
        mock_tool2.inputSchema = {}

        mock_result = MagicMock()
        mock_result.tools = [mock_tool1, mock_tool2]

        mock_session = AsyncMock()
        mock_session.list_tools = AsyncMock(return_value=mock_result)

        with patch.object(client, "connect") as mock_connect:
            mock_connect.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_connect.return_value.__aexit__ = AsyncMock(return_value=None)

            tools = await client.list_tools()

        assert len(tools) == 2
        assert tools[0]["name"] == "search"
        assert tools[0]["description"] == "Search documents"
        assert tools[1]["name"] == "fetch"
        assert tools[1]["description"] == ""  # None converted to empty string

    @pytest.mark.asyncio
    async def test_list_tools_error(self):
        """Test list_tools raises RuntimeError on failure."""
        config = MCPServerConfig(transport="http", url="https://example.com/mcp")
        client = MCPClient("test-server", config)

        mock_session = AsyncMock()
        mock_session.list_tools = AsyncMock(side_effect=Exception("Network error"))

        with patch.object(client, "connect") as mock_connect:
            mock_connect.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_connect.return_value.__aexit__ = AsyncMock(return_value=None)

            with pytest.raises(RuntimeError) as exc_info:
                await client.list_tools()

            assert "Failed to list tools from server 'test-server'" in str(exc_info.value)


class TestMCPClientCallTool:
    """Test MCPClient call_tool method."""

    @pytest.mark.asyncio
    async def test_call_tool_success(self):
        """Test calling a tool successfully."""
        config = MCPServerConfig(transport="http", url="https://example.com/mcp")
        client = MCPClient("test", config)

        mock_result = {"output": "Search results here"}
        mock_session = AsyncMock()
        mock_session.call_tool = AsyncMock(return_value=mock_result)

        with patch.object(client, "connect") as mock_connect:
            mock_connect.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_connect.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await client.call_tool("search", arguments={"query": "test"})

        assert result == mock_result
        mock_session.call_tool.assert_called_once_with(
            "search",
            arguments={"query": "test"},
        )

    @pytest.mark.asyncio
    async def test_call_tool_no_arguments(self):
        """Test calling a tool without arguments."""
        config = MCPServerConfig(transport="http", url="https://example.com/mcp")
        client = MCPClient("test", config)

        mock_result = {"status": "ok"}
        mock_session = AsyncMock()
        mock_session.call_tool = AsyncMock(return_value=mock_result)

        with patch.object(client, "connect") as mock_connect:
            mock_connect.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_connect.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await client.call_tool("ping")

        mock_session.call_tool.assert_called_once_with("ping", arguments={})
        assert result == mock_result

    @pytest.mark.asyncio
    async def test_call_tool_error(self):
        """Test call_tool raises RuntimeError on failure."""
        config = MCPServerConfig(transport="http", url="https://example.com/mcp")
        client = MCPClient("test-server", config)

        mock_session = AsyncMock()
        mock_session.call_tool = AsyncMock(side_effect=Exception("Tool error"))

        with patch.object(client, "connect") as mock_connect:
            mock_connect.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_connect.return_value.__aexit__ = AsyncMock(return_value=None)

            with pytest.raises(RuntimeError) as exc_info:
                await client.call_tool("broken-tool")

            assert "Failed to call tool 'broken-tool'" in str(exc_info.value)
            assert "test-server" in str(exc_info.value)


class TestCheckServerConnection:
    """Test the check_server_connection helper function."""

    @pytest.mark.asyncio
    async def test_connection_success(self):
        """Test successful connection check."""
        config = MCPServerConfig(transport="http", url="https://example.com/mcp")

        with patch("NovaCode_cli.mcp.client.MCPClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.list_tools = AsyncMock(
                return_value=[
                    {"name": "tool1"},
                    {"name": "tool2"},
                ]
            )
            mock_client_class.return_value = mock_client

            success, message = await check_server_connection("test-server", config)

        assert success is True
        assert "Connected successfully" in message
        assert "2 tools" in message

    @pytest.mark.asyncio
    async def test_connection_failure(self):
        """Test failed connection check."""
        config = MCPServerConfig(transport="http", url="https://example.com/mcp")

        with patch("NovaCode_cli.mcp.client.MCPClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_client.list_tools = AsyncMock(side_effect=RuntimeError("Connection refused"))
            mock_client_class.return_value = mock_client

            success, message = await check_server_connection("test-server", config)

        assert success is False
        assert "Connection failed" in message
        assert "Connection refused" in message

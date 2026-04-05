"""Unit tests for MCP configuration management."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from novacode_cli.mcp.config import MCPConfig, MCPServerConfig


class TestMCPServerConfig:
    """Test MCPServerConfig validation."""

    def test_valid_http_config(self):
        """Test valid HTTP transport configuration."""
        config = MCPServerConfig(
            transport="http",
            url="https://example.com/mcp",
            description="Test server",
        )
        assert config.transport == "http"
        assert config.url == "https://example.com/mcp"
        assert config.description == "Test server"

    def test_valid_stdio_config(self):
        """Test valid stdio transport configuration."""
        config = MCPServerConfig(
            transport="stdio",
            command="python",
            args=["-m", "mcp_server"],
            env={"SOME_VAR": "value"},
            description="Local server",
        )
        assert config.transport == "stdio"
        assert config.command == "python"
        assert config.args == ["-m", "mcp_server"]
        assert config.env == {"SOME_VAR": "value"}

    def test_http_requires_url(self):
        """Test that HTTP transport requires a URL."""
        with pytest.raises(ValidationError) as exc_info:
            MCPServerConfig(transport="http")
        assert "HTTP transport requires a URL" in str(exc_info.value)

    def test_stdio_requires_command(self):
        """Test that stdio transport requires a command."""
        with pytest.raises(ValidationError) as exc_info:
            MCPServerConfig(transport="stdio")
        assert "stdio transport requires a command" in str(exc_info.value)

    def test_http_with_command_ignored(self):
        """Test that command is ignored for HTTP transport."""
        config = MCPServerConfig(
            transport="http",
            url="https://example.com/mcp",
            command="should-be-ignored",
        )
        assert config.url == "https://example.com/mcp"
        assert config.command == "should-be-ignored"  # Not rejected, just ignored

    def test_stdio_with_url_ignored(self):
        """Test that URL is ignored for stdio transport."""
        config = MCPServerConfig(
            transport="stdio",
            command="python",
            url="https://should-be-ignored.com",
        )
        assert config.command == "python"
        assert config.url == "https://should-be-ignored.com"  # Not rejected

    def test_default_empty_args_and_env(self):
        """Test that args and env default to empty."""
        config = MCPServerConfig(transport="stdio", command="python")
        assert config.args == []
        assert config.env == {}

    def test_invalid_transport(self):
        """Test that invalid transport types are rejected."""
        with pytest.raises(ValidationError):
            MCPServerConfig(transport="websocket", url="ws://example.com")


class TestMCPConfig:
    """Test MCPConfig file operations."""

    def test_init_creates_config_dir(self, tmp_path: Path) -> None:
        """Test that initialization creates the config directory."""
        config_path = tmp_path / "subdir" / "mcp.json"
        MCPConfig(config_path)
        assert config_path.parent.exists()

    def test_load_empty_when_no_file(self, tmp_path: Path) -> None:
        """Test loading returns empty dict when file doesn't exist."""
        config_path = tmp_path / "mcp.json"
        config = MCPConfig(config_path)
        servers = config.load()
        assert servers == {}

    def test_save_and_load(self, tmp_path: Path) -> None:
        """Test saving and loading server configurations."""
        config_path = tmp_path / "mcp.json"
        config = MCPConfig(config_path)

        # Create test servers
        servers = {
            "test-http": MCPServerConfig(
                transport="http",
                url="https://example.com/mcp",
                description="HTTP server",
            ),
            "test-stdio": MCPServerConfig(
                transport="stdio",
                command="python",
                args=["-m", "server"],
            ),
        }

        # Save and reload
        config.save(servers)
        loaded = config.load()

        assert len(loaded) == 2
        assert "test-http" in loaded
        assert "test-stdio" in loaded
        assert loaded["test-http"].transport == "http"
        assert loaded["test-http"].url == "https://example.com/mcp"
        assert loaded["test-stdio"].command == "python"

    def test_add_server(self, tmp_path: Path) -> None:
        """Test adding a server configuration."""
        config_path = tmp_path / "mcp.json"
        config = MCPConfig(config_path)

        server_config = MCPServerConfig(
            transport="http",
            url="https://example.com/mcp",
        )
        config.add_server("new-server", server_config)

        loaded = config.load()
        assert "new-server" in loaded
        assert loaded["new-server"].url == "https://example.com/mcp"

    def test_add_server_updates_existing(self, tmp_path: Path) -> None:
        """Test that add_server updates existing server."""
        config_path = tmp_path / "mcp.json"
        config = MCPConfig(config_path)

        # Add initial server
        config.add_server(
            "server",
            MCPServerConfig(transport="http", url="https://old.com"),
        )

        # Update server
        config.add_server(
            "server",
            MCPServerConfig(transport="http", url="https://new.com"),
        )

        loaded = config.load()
        assert loaded["server"].url == "https://new.com"

    def test_remove_server_existing(self, tmp_path: Path) -> None:
        """Test removing an existing server."""
        config_path = tmp_path / "mcp.json"
        config = MCPConfig(config_path)

        config.add_server(
            "to-remove",
            MCPServerConfig(transport="http", url="https://example.com"),
        )

        result = config.remove_server("to-remove")
        assert result is True

        loaded = config.load()
        assert "to-remove" not in loaded

    def test_remove_server_nonexistent(self, tmp_path: Path) -> None:
        """Test removing a non-existent server returns False."""
        config_path = tmp_path / "mcp.json"
        config = MCPConfig(config_path)

        result = config.remove_server("does-not-exist")
        assert result is False

    def test_get_server_existing(self, tmp_path: Path) -> None:
        """Test getting an existing server configuration."""
        config_path = tmp_path / "mcp.json"
        config = MCPConfig(config_path)

        config.add_server(
            "my-server",
            MCPServerConfig(transport="http", url="https://example.com"),
        )

        server = config.get_server("my-server")
        assert server is not None
        assert server.url == "https://example.com"

    def test_get_server_nonexistent(self, tmp_path: Path) -> None:
        """Test getting a non-existent server returns None."""
        config_path = tmp_path / "mcp.json"
        config = MCPConfig(config_path)

        server = config.get_server("does-not-exist")
        assert server is None

    def test_list_servers(self, tmp_path: Path) -> None:
        """Test listing all server configurations."""
        config_path = tmp_path / "mcp.json"
        config = MCPConfig(config_path)

        config.add_server(
            "server1",
            MCPServerConfig(transport="http", url="https://one.com"),
        )
        config.add_server(
            "server2",
            MCPServerConfig(transport="stdio", command="python"),
        )

        servers = config.list_servers()
        assert len(servers) == 2
        assert "server1" in servers
        assert "server2" in servers

    def test_load_malformed_json(self, tmp_path: Path) -> None:
        """Test loading malformed JSON raises RuntimeError."""
        config_path = tmp_path / "mcp.json"
        config_path.write_text("not valid json {{{")

        config = MCPConfig(config_path)
        with pytest.raises(RuntimeError) as exc_info:
            config.load()
        assert "Failed to load MCP config" in str(exc_info.value)

    def test_load_invalid_config_structure(self, tmp_path: Path) -> None:
        """Test loading invalid config structure raises RuntimeError."""
        config_path = tmp_path / "mcp.json"
        # Valid JSON but invalid config (missing required fields)
        config_path.write_text(
            json.dumps(
                {
                    "mcpServers": {
                        "bad-server": {"transport": "http"}  # Missing URL
                    }
                }
            )
        )

        config = MCPConfig(config_path)
        with pytest.raises(RuntimeError) as exc_info:
            config.load()
        assert "Failed to load MCP config" in str(exc_info.value)

    def test_json_file_format(self, tmp_path: Path) -> None:
        """Test that saved JSON file has correct format."""
        config_path = tmp_path / "mcp.json"
        config = MCPConfig(config_path)

        config.add_server(
            "test-server",
            MCPServerConfig(
                transport="http",
                url="https://example.com/mcp",
                description="Test",
            ),
        )

        # Read raw JSON
        with config_path.open() as f:
            data = json.load(f)

        assert "mcpServers" in data
        assert "test-server" in data["mcpServers"]
        assert data["mcpServers"]["test-server"]["transport"] == "http"
        assert data["mcpServers"]["test-server"]["url"] == "https://example.com/mcp"

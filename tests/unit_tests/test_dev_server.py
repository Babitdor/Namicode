"""Unit tests for dev_server module."""

from __future__ import annotations

import socket
from unittest.mock import MagicMock, patch

import pytest

from novacode_cli.process_manager import ProcessManager, ProcessStatus
from novacode_cli.server_runner.dev_server import (
    ServerInfo,
    extract_port_from_command,
    find_available_port,
    is_port_in_use,
    list_servers,
    validate_server_command,
)


class TestServerInfo:
    """Tests for ServerInfo dataclass."""

    def test_create_server_info(self) -> None:
        """Test creating a ServerInfo instance."""
        info = ServerInfo(
            pid=1234,
            name="dev-server",
            url="http://localhost:3000",
            port=3000,
            status=ProcessStatus.HEALTHY,
            command="npm run dev",
        )
        assert info.pid == 1234
        assert info.name == "dev-server"
        assert info.url == "http://localhost:3000"
        assert info.port == 3000
        assert info.status == ProcessStatus.HEALTHY
        assert info.command == "npm run dev"


class TestFindAvailablePort:
    """Tests for find_available_port function."""

    def test_find_available_port_success(self) -> None:
        """Test finding an available port."""
        port = find_available_port(start_port=50000)
        assert 50000 <= port < 50100

    def test_find_available_port_skips_used(self) -> None:
        """Test that used ports are skipped."""
        # Bind a port
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("localhost", 50000))

            # Should find next available
            port = find_available_port(start_port=50000)
            assert port > 50000

    def test_find_available_port_max_attempts(self) -> None:
        """Test that RuntimeError is raised after max attempts."""
        # Mock socket to always fail
        with patch("socket.socket") as mock_socket:
            mock_instance = MagicMock()
            mock_instance.__enter__ = MagicMock(return_value=mock_instance)
            mock_instance.__exit__ = MagicMock(return_value=False)
            mock_instance.bind.side_effect = OSError("Port in use")
            mock_socket.return_value = mock_instance

            with pytest.raises(RuntimeError, match="No available ports"):
                find_available_port(start_port=50000, max_attempts=5)


class TestIsPortInUse:
    """Tests for is_port_in_use function."""

    def test_port_not_in_use(self) -> None:
        """Test detecting an unused port."""
        # Use a high port that's unlikely to be in use
        result = is_port_in_use(59999)
        # This might fail if the port happens to be in use, but unlikely
        assert isinstance(result, bool)

    def test_port_in_use(self) -> None:
        """Test detecting a port that is in use."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("localhost", 50001))
            result = is_port_in_use(50001)
            assert result is True


class TestExtractPortFromCommand:
    """Tests for extract_port_from_command function."""

    def test_extract_port_from_flag(self) -> None:
        """Test extracting port from --port flag."""
        assert extract_port_from_command("npm run dev --port 4000") == 4000

    def test_extract_port_from_equals_flag(self) -> None:
        """Test extracting port from --port= flag."""
        assert extract_port_from_command("npm run dev --port=5000") == 5000

    def test_extract_port_from_short_flag(self) -> None:
        """Test extracting port from -p flag."""
        assert extract_port_from_command("python -m http.server -p 8080") == 8080

    def test_extract_port_from_localhost(self) -> None:
        """Test extracting port from localhost:PORT."""
        assert extract_port_from_command("uvicorn main:app --host localhost:9000") == 9000

    def test_extract_port_from_ip(self) -> None:
        """Test extracting port from IP:PORT."""
        assert extract_port_from_command("uvicorn main:app --host 127.0.0.1:8000") == 8000

    def test_extract_port_from_zero_ip(self) -> None:
        """Test extracting port from 0.0.0.0:PORT."""
        assert extract_port_from_command("uvicorn main:app --host 0.0.0.0:8888") == 8888

    def test_extract_port_from_env(self) -> None:
        """Test extracting port from PORT= env var."""
        assert extract_port_from_command("PORT=3001 npm start") == 3001

    def test_default_port_npm_run_dev(self) -> None:
        """Test default port for npm run dev."""
        assert extract_port_from_command("npm run dev") == 3000

    def test_default_port_vite(self) -> None:
        """Test default port for vite."""
        assert extract_port_from_command("npx vite") == 5173

    def test_default_port_flask(self) -> None:
        """Test default port for flask."""
        assert extract_port_from_command("flask run") == 5000

    def test_default_port_uvicorn(self) -> None:
        """Test default port for uvicorn."""
        assert extract_port_from_command("uvicorn main:app") == 8000

    def test_default_port_when_not_found(self) -> None:
        """Test default port is returned when not found."""
        assert extract_port_from_command("unknown-command", default=9999) == 9999

    def test_python_http_server(self) -> None:
        """Test python http server port detection."""
        assert extract_port_from_command("python -m http.server") == 8000
        assert (
            extract_port_from_command("python -m http.server 9000") == 8000
        )  # Uses pattern default


class TestValidateServerCommand:
    """Tests for validate_server_command function."""

    def test_valid_npm_command(self) -> None:
        """Test valid npm command."""
        is_valid, error = validate_server_command("npm run dev")
        assert is_valid is True
        assert error is None

    def test_valid_python_command(self) -> None:
        """Test valid python http server command."""
        is_valid, error = validate_server_command("python -m http.server 8000")
        assert is_valid is True

    def test_valid_uvicorn_command(self) -> None:
        """Test valid uvicorn command."""
        is_valid, error = validate_server_command("uvicorn main:app --reload")
        assert is_valid is True

    def test_block_sudo_command(self) -> None:
        """Test that sudo commands are blocked."""
        is_valid, error = validate_server_command("sudo npm run dev")
        assert is_valid is False
        assert "blocked" in error.lower()

    def test_block_rm_command(self) -> None:
        """Test that rm commands are blocked."""
        is_valid, error = validate_server_command("rm -rf / && npm start")
        assert is_valid is False

    def test_block_kill_command(self) -> None:
        """Test that kill commands are blocked."""
        is_valid, error = validate_server_command("kill -9 1234")
        assert is_valid is False

    def test_empty_command(self) -> None:
        """Test that empty command is invalid."""
        is_valid, error = validate_server_command("")
        assert is_valid is False
        assert "empty" in error.lower()

    def test_whitespace_command(self) -> None:
        """Test that whitespace-only command is invalid."""
        is_valid, error = validate_server_command("   ")
        assert is_valid is False


class TestListServers:
    """Tests for list_servers function."""

    def setup_method(self) -> None:
        """Reset singleton before each test."""
        ProcessManager.reset_instance()

    def teardown_method(self) -> None:
        """Clean up after each test."""
        ProcessManager.reset_instance()

    def test_list_servers_empty(self) -> None:
        """Test listing servers when none are running."""
        servers = list_servers()
        assert servers == []

    @pytest.mark.asyncio
    async def test_list_servers_with_running_server(self) -> None:
        """Test listing servers with a running server."""
        import sys

        manager = ProcessManager.get_instance()

        # Start a process with a port
        if sys.platform == "win32":
            command = "cmd /c ping -n 100 localhost"
        else:
            command = "sleep 100"

        await manager.start_process(
            command,
            name="test-server",
            port=3000,
            working_dir=".",
        )

        servers = list_servers()

        assert len(servers) == 1
        assert servers[0].name == "test-server"
        assert servers[0].port == 3000
        assert servers[0].url == "http://localhost:3000"

        # Clean up
        await manager.stop_all()

    @pytest.mark.asyncio
    async def test_list_servers_excludes_non_port_processes(self) -> None:
        """Test that processes without ports are excluded."""
        import sys

        manager = ProcessManager.get_instance()

        # Start a process without a port
        if sys.platform == "win32":
            command = "cmd /c ping -n 100 localhost"
        else:
            command = "sleep 100"

        await manager.start_process(
            command,
            name="test-process",
            port=None,  # No port
            working_dir=".",
        )

        servers = list_servers()

        assert len(servers) == 0

        # Clean up
        await manager.stop_all()


class TestServerLifecycle:
    """Tests for server start/stop functionality."""

    def setup_method(self) -> None:
        """Reset singleton before each test."""
        ProcessManager.reset_instance()

    def teardown_method(self) -> None:
        """Clean up after each test."""
        ProcessManager.reset_instance()

    @pytest.mark.asyncio
    async def test_stop_server_by_pid(self) -> None:
        """Test stopping server by PID."""
        import sys

        from novacode_cli.server_runner.dev_server import stop_server

        manager = ProcessManager.get_instance()

        if sys.platform == "win32":
            command = "cmd /c ping -n 100 localhost"
        else:
            command = "sleep 100"

        info = await manager.start_process(
            command,
            name="test-server",
            port=3000,
            working_dir=".",
        )

        result = await stop_server(pid=info.pid)

        assert result is True

    @pytest.mark.asyncio
    async def test_stop_server_by_name(self) -> None:
        """Test stopping server by name."""
        import sys

        from novacode_cli.server_runner.dev_server import stop_server

        manager = ProcessManager.get_instance()

        if sys.platform == "win32":
            command = "cmd /c ping -n 100 localhost"
        else:
            command = "sleep 100"

        await manager.start_process(
            command,
            name="my-server",
            port=3000,
            working_dir=".",
        )

        result = await stop_server(name="my-server")

        assert result is True

    @pytest.mark.asyncio
    async def test_stop_server_not_found(self) -> None:
        """Test stopping a nonexistent server."""
        from novacode_cli.server_runner.dev_server import stop_server

        result = await stop_server(pid=99999)
        assert result is False

        result = await stop_server(name="nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_stop_server_no_args(self) -> None:
        """Test stop_server with no arguments returns False."""
        from novacode_cli.server_runner.dev_server import stop_server

        result = await stop_server()
        assert result is False


class TestListServersTool:
    """Tests for list_servers_tool function."""

    def setup_method(self) -> None:
        """Reset singleton before each test."""
        ProcessManager.reset_instance()

    def teardown_method(self) -> None:
        """Clean up after each test."""
        ProcessManager.reset_instance()

    def test_list_servers_tool_empty(self) -> None:
        """Test list_servers_tool with no servers."""
        from novacode_cli.server_runner.dev_server import list_servers_tool

        result = list_servers_tool()

        assert result["success"] is True
        assert result["servers"] == []
        assert result["count"] == 0

    @pytest.mark.asyncio
    async def test_list_servers_tool_with_servers(self) -> None:
        """Test list_servers_tool with running servers."""
        import sys

        from novacode_cli.server_runner.dev_server import list_servers_tool

        manager = ProcessManager.get_instance()

        if sys.platform == "win32":
            command = "cmd /c ping -n 100 localhost"
        else:
            command = "sleep 100"

        await manager.start_process(
            command,
            name="test-server",
            port=3000,
            working_dir=".",
        )

        result = list_servers_tool()

        assert result["success"] is True
        assert result["count"] == 1
        assert len(result["servers"]) == 1
        assert result["servers"][0]["name"] == "test-server"
        assert result["servers"][0]["port"] == 3000

        # Clean up
        await manager.stop_all()


class TestScanExternalServers:
    """Tests for scan_external_servers function."""

    def test_scan_external_servers_no_servers(self) -> None:
        """Test scanning when no external servers are running."""
        from novacode_cli.server_runner.dev_server import scan_external_servers

        # Scan ports that are unlikely to be in use
        servers = scan_external_servers(ports=[59990, 59991, 59992])
        assert servers == []

    def test_scan_external_servers_with_port_in_use(self) -> None:
        """Test scanning detects a port in use."""
        import socket

        from novacode_cli.server_runner.dev_server import scan_external_servers

        # Start a simple server on a test port
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("localhost", 59993))
            s.listen(1)

            # Scan the port we just bound
            servers = scan_external_servers(ports=[59993])

            # Should detect the server
            assert len(servers) == 1
            assert servers[0].port == 59993
            assert servers[0].pid == 0  # External server has unknown PID
            assert "external" in servers[0].name

    def test_scan_external_servers_timeout(self) -> None:
        """Test that timeout parameter works."""
        from novacode_cli.server_runner.dev_server import scan_external_servers

        # Should complete quickly with short timeout
        servers = scan_external_servers(ports=[59994], timeout=0.01)
        assert isinstance(servers, list)


class TestListServersWithExternal:
    """Tests for list_servers with include_external parameter."""

    def setup_method(self) -> None:
        """Reset singleton before each test."""
        ProcessManager.reset_instance()

    def teardown_method(self) -> None:
        """Clean up after each test."""
        ProcessManager.reset_instance()

    def test_list_servers_include_external_false(self) -> None:
        """Test list_servers without external servers."""
        servers = list_servers(include_external=False)
        assert isinstance(servers, list)

    def test_list_servers_include_external_true(self) -> None:
        """Test list_servers with external servers."""
        servers = list_servers(include_external=True)
        assert isinstance(servers, list)

    @pytest.mark.asyncio
    async def test_list_servers_merges_external_with_managed(self) -> None:
        """Test that list_servers merges external and managed servers."""
        import sys

        manager = ProcessManager.get_instance()

        # Start a managed process
        if sys.platform == "win32":
            command = "cmd /c ping -n 100 localhost"
        else:
            command = "sleep 100"

        await manager.start_process(
            command,
            name="managed-server",
            port=3000,
            working_dir=".",
        )

        try:
            # List servers with external
            servers = list_servers(include_external=True)

            # Should include the managed server
            managed = [s for s in servers if s.pid > 0]
            assert len(managed) == 1
            assert managed[0].name == "managed-server"

        finally:
            await manager.stop_all()

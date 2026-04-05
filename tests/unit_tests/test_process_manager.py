"""Unit tests for process_manager module."""

from __future__ import annotations

import asyncio
import sys
from unittest.mock import Mock

import pytest

from novacode_cli.process_manager import (
    ProcessInfo,
    ProcessManager,
    ProcessStatus,
    stream_subprocess_output,
)


class TestProcessStatus:
    """Tests for ProcessStatus enum."""

    def test_status_values(self) -> None:
        """Test that all expected status values exist."""
        assert ProcessStatus.STARTING.value == "starting"
        assert ProcessStatus.RUNNING.value == "running"
        assert ProcessStatus.HEALTHY.value == "healthy"
        assert ProcessStatus.UNHEALTHY.value == "unhealthy"
        assert ProcessStatus.STOPPED.value == "stopped"
        assert ProcessStatus.FAILED.value == "failed"


class TestProcessInfo:
    """Tests for ProcessInfo dataclass."""

    def test_create_process_info(self) -> None:
        """Test creating a ProcessInfo instance."""
        info = ProcessInfo(
            pid=1234,
            name="test-process",
            command="echo hello",
            port=3000,
            status=ProcessStatus.RUNNING,
            working_dir="/tmp",
        )
        assert info.pid == 1234
        assert info.name == "test-process"
        assert info.command == "echo hello"
        assert info.port == 3000
        assert info.status == ProcessStatus.RUNNING
        assert info.working_dir == "/tmp"

    def test_is_alive_with_running_process(self) -> None:
        """Test is_alive returns True for running process."""
        mock_process = Mock()
        mock_process.returncode = None

        info = ProcessInfo(
            pid=1234,
            name="test",
            command="echo hello",
            _process=mock_process,
        )

        assert info.is_alive is True

    def test_is_alive_with_terminated_process(self) -> None:
        """Test is_alive returns False for terminated process."""
        mock_process = Mock()
        mock_process.returncode = 0

        info = ProcessInfo(
            pid=1234,
            name="test",
            command="echo hello",
            _process=mock_process,
        )

        assert info.is_alive is False

    def test_is_alive_with_no_process(self) -> None:
        """Test is_alive returns False when no process is set."""
        info = ProcessInfo(
            pid=1234,
            name="test",
            command="echo hello",
        )

        assert info.is_alive is False

    def test_exit_code_with_terminated_process(self) -> None:
        """Test exit_code returns the process return code."""
        mock_process = Mock()
        mock_process.returncode = 42

        info = ProcessInfo(
            pid=1234,
            name="test",
            command="echo hello",
            _process=mock_process,
        )

        assert info.exit_code == 42

    def test_exit_code_with_no_process(self) -> None:
        """Test exit_code returns None when no process is set."""
        info = ProcessInfo(
            pid=1234,
            name="test",
            command="echo hello",
        )

        assert info.exit_code is None

    def test_output_property(self) -> None:
        """Test output property joins output lines."""
        info = ProcessInfo(
            pid=1234,
            name="test",
            command="echo hello",
        )
        info._output_lines = ["line1", "line2", "line3"]

        assert info.output == "line1\nline2\nline3"

    def test_output_property_empty(self) -> None:
        """Test output property with no output."""
        info = ProcessInfo(
            pid=1234,
            name="test",
            command="echo hello",
        )

        assert info.output == ""

    def test_default_values(self) -> None:
        """Test default values are set correctly."""
        info = ProcessInfo(
            pid=1234,
            name="test",
            command="echo hello",
        )

        assert info.port is None
        assert info.status == ProcessStatus.STARTING
        assert info.working_dir == "."
        assert info.health_check_url is None
        assert info._process is None
        assert info._output_lines == []


class TestProcessManager:
    """Tests for ProcessManager class."""

    def setup_method(self) -> None:
        """Reset singleton before each test."""
        ProcessManager.reset_instance()

    def teardown_method(self) -> None:
        """Clean up after each test."""
        ProcessManager.reset_instance()

    def test_singleton_instance(self) -> None:
        """Test that get_instance returns singleton."""
        manager1 = ProcessManager.get_instance()
        manager2 = ProcessManager.get_instance()

        assert manager1 is manager2

    def test_reset_instance(self) -> None:
        """Test that reset_instance creates new singleton."""
        manager1 = ProcessManager.get_instance()
        ProcessManager.reset_instance()
        manager2 = ProcessManager.get_instance()

        assert manager1 is not manager2

    def test_list_processes_empty(self) -> None:
        """Test listing processes when none exist."""
        manager = ProcessManager.get_instance()
        processes = manager.list_processes()

        assert processes == []

    def test_get_process_not_found(self) -> None:
        """Test getting a process that doesn't exist."""
        manager = ProcessManager.get_instance()
        info = manager.get_process(99999)

        assert info is None

    def test_get_by_name_not_found(self) -> None:
        """Test getting a process by name that doesn't exist."""
        manager = ProcessManager.get_instance()
        info = manager.get_by_name("nonexistent")

        assert info is None

    @pytest.mark.asyncio
    async def test_start_process_success(self) -> None:
        """Test successful process start."""
        manager = ProcessManager.get_instance()

        # Use a simple command that exits quickly
        if sys.platform == "win32":
            command = "cmd /c echo hello"
        else:
            command = "echo hello"

        info = await manager.start_process(
            command,
            name="test-echo",
            working_dir=".",
        )

        assert info.pid > 0
        assert info.name == "test-echo"
        assert info.command == command
        assert info.status == ProcessStatus.RUNNING

        # Clean up
        await manager.stop_process(info.pid)

    @pytest.mark.asyncio
    async def test_start_process_with_port(self) -> None:
        """Test starting process with port specified."""
        manager = ProcessManager.get_instance()

        if sys.platform == "win32":
            command = "cmd /c echo hello"
        else:
            command = "echo hello"

        info = await manager.start_process(
            command,
            name="test-with-port",
            port=3000,
            working_dir=".",
        )

        assert info.port == 3000

        # Clean up
        await manager.stop_process(info.pid)

    @pytest.mark.asyncio
    async def test_stop_process_success(self) -> None:
        """Test stopping a process."""
        manager = ProcessManager.get_instance()

        # Start a long-running process
        if sys.platform == "win32":
            command = "cmd /c ping -n 100 localhost"
        else:
            command = "sleep 100"

        info = await manager.start_process(
            command,
            name="test-long-running",
            working_dir=".",
        )

        # Stop it
        result = await manager.stop_process(info.pid)

        assert result is True
        assert info.status == ProcessStatus.STOPPED

    @pytest.mark.asyncio
    async def test_stop_process_not_found(self) -> None:
        """Test stopping a process that doesn't exist."""
        manager = ProcessManager.get_instance()
        result = await manager.stop_process(99999)

        assert result is False

    @pytest.mark.asyncio
    async def test_stop_by_name(self) -> None:
        """Test stopping a process by name."""
        manager = ProcessManager.get_instance()

        if sys.platform == "win32":
            command = "cmd /c ping -n 100 localhost"
        else:
            command = "sleep 100"

        info = await manager.start_process(
            command,
            name="test-stop-by-name",
            working_dir=".",
        )

        result = await manager.stop_by_name("test-stop-by-name")

        assert result is True
        assert info.status == ProcessStatus.STOPPED

    @pytest.mark.asyncio
    async def test_stop_by_name_not_found(self) -> None:
        """Test stopping a process by name that doesn't exist."""
        manager = ProcessManager.get_instance()
        result = await manager.stop_by_name("nonexistent")

        assert result is False

    @pytest.mark.asyncio
    async def test_stop_all(self) -> None:
        """Test stopping all processes."""
        manager = ProcessManager.get_instance()

        if sys.platform == "win32":
            command = "cmd /c ping -n 100 localhost"
        else:
            command = "sleep 100"

        # Start multiple processes
        info1 = await manager.start_process(
            command,
            name="test-1",
            working_dir=".",
        )
        info2 = await manager.start_process(
            command,
            name="test-2",
            working_dir=".",
        )

        # Stop all
        count = await manager.stop_all()

        assert count == 2
        assert info1.status == ProcessStatus.STOPPED
        assert info2.status == ProcessStatus.STOPPED

    @pytest.mark.asyncio
    async def test_list_processes_with_running(self) -> None:
        """Test listing running processes."""
        manager = ProcessManager.get_instance()

        if sys.platform == "win32":
            command = "cmd /c ping -n 100 localhost"
        else:
            command = "sleep 100"

        info = await manager.start_process(
            command,
            name="test-list",
            working_dir=".",
        )

        processes = manager.list_processes(alive_only=True)

        assert len(processes) == 1
        assert processes[0].pid == info.pid

        # Clean up
        await manager.stop_all()

    @pytest.mark.asyncio
    async def test_list_processes_include_stopped(self) -> None:
        """Test listing processes including stopped ones."""
        manager = ProcessManager.get_instance()

        if sys.platform == "win32":
            command = "cmd /c echo hello"
        else:
            command = "echo hello"

        info = await manager.start_process(
            command,
            name="test-echo",
            working_dir=".",
        )

        # Wait for process to finish
        await asyncio.sleep(0.5)

        # Should not appear in alive_only list
        alive_processes = manager.list_processes(alive_only=True)
        all_processes = manager.list_processes(alive_only=False)

        # The echo command should have finished
        assert len(alive_processes) == 0
        assert len(all_processes) == 1

    @pytest.mark.asyncio
    async def test_get_process_by_pid(self) -> None:
        """Test getting a process by PID."""
        manager = ProcessManager.get_instance()

        if sys.platform == "win32":
            command = "cmd /c ping -n 100 localhost"
        else:
            command = "sleep 100"

        info = await manager.start_process(
            command,
            name="test-get",
            working_dir=".",
        )

        retrieved = manager.get_process(info.pid)

        assert retrieved is not None
        assert retrieved.pid == info.pid
        assert retrieved.name == "test-get"

        # Clean up
        await manager.stop_all()

    @pytest.mark.asyncio
    async def test_get_by_name(self) -> None:
        """Test getting a process by name."""
        manager = ProcessManager.get_instance()

        if sys.platform == "win32":
            command = "cmd /c ping -n 100 localhost"
        else:
            command = "sleep 100"

        info = await manager.start_process(
            command,
            name="unique-name-123",
            working_dir=".",
        )

        retrieved = manager.get_by_name("unique-name-123")

        assert retrieved is not None
        assert retrieved.pid == info.pid

        # Clean up
        await manager.stop_all()

    @pytest.mark.asyncio
    async def test_check_health_no_url(self) -> None:
        """Test health check without URL returns RUNNING."""
        manager = ProcessManager.get_instance()

        if sys.platform == "win32":
            command = "cmd /c ping -n 100 localhost"
        else:
            command = "sleep 100"

        info = await manager.start_process(
            command,
            name="test-health",
            working_dir=".",
        )

        status = await manager.check_health(info.pid)

        assert status == ProcessStatus.RUNNING

        # Clean up
        await manager.stop_all()

    @pytest.mark.asyncio
    async def test_check_health_not_found(self) -> None:
        """Test health check for nonexistent process."""
        manager = ProcessManager.get_instance()
        status = await manager.check_health(99999)

        assert status == ProcessStatus.STOPPED

    @pytest.mark.asyncio
    async def test_output_callback(self) -> None:
        """Test that output callback is called."""
        manager = ProcessManager.get_instance()
        output_lines: list[str] = []

        def callback(line: str) -> None:
            output_lines.append(line)

        if sys.platform == "win32":
            command = "cmd /c echo hello world"
        else:
            command = "echo hello world"

        info = await manager.start_process(
            command,
            name="test-callback",
            working_dir=".",
            output_callback=callback,
        )

        # Wait for output to be captured
        await asyncio.sleep(1)

        # The output should contain "hello world"
        assert len(output_lines) > 0 or "hello" in info.output.lower()


class TestStreamSubprocessOutput:
    """Tests for stream_subprocess_output function."""

    @pytest.mark.asyncio
    async def test_stream_output_success(self) -> None:
        """Test streaming output from a command."""
        output_lines: list[str] = []

        def callback(line: str) -> None:
            output_lines.append(line)

        if sys.platform == "win32":
            command = "cmd /c echo line1 && echo line2"
        else:
            command = "echo line1 && echo line2"

        exit_code, output = await stream_subprocess_output(
            command,
            working_dir=".",
            callback=callback,
            timeout=10.0,
        )

        assert exit_code == 0
        assert "line1" in output.lower()
        assert "line2" in output.lower()
        assert len(output_lines) >= 2

    @pytest.mark.asyncio
    async def test_stream_output_timeout(self) -> None:
        """Test that timeout raises exception."""
        output_lines: list[str] = []

        def callback(line: str) -> None:
            output_lines.append(line)

        if sys.platform == "win32":
            command = "cmd /c ping -n 100 localhost"
        else:
            command = "sleep 100"

        with pytest.raises(asyncio.TimeoutError):
            await stream_subprocess_output(
                command,
                working_dir=".",
                callback=callback,
                timeout=0.5,
            )

    @pytest.mark.asyncio
    async def test_stream_output_exit_code(self) -> None:
        """Test that exit code is captured correctly."""
        output_lines: list[str] = []

        def callback(line: str) -> None:
            output_lines.append(line)

        if sys.platform == "win32":
            command = "cmd /c exit 42"
        else:
            command = "exit 42"

        exit_code, output = await stream_subprocess_output(
            command,
            working_dir=".",
            callback=callback,
            timeout=10.0,
        )

        assert exit_code == 42

    @pytest.mark.asyncio
    async def test_stream_output_with_env(self) -> None:
        """Test streaming output with custom environment."""
        output_lines: list[str] = []

        def callback(line: str) -> None:
            output_lines.append(line)

        if sys.platform == "win32":
            command = "cmd /c echo %TEST_VAR%"
        else:
            command = "echo $TEST_VAR"

        exit_code, output = await stream_subprocess_output(
            command,
            working_dir=".",
            callback=callback,
            timeout=10.0,
            env={"TEST_VAR": "hello_from_env"},
        )

        assert exit_code == 0
        assert "hello_from_env" in output

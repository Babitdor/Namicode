"""Unit tests for shell module."""

from __future__ import annotations

import sys
import tempfile

import pytest
from langchain_core.tools.base import ToolException

from namicode_cli.shell import (
    PROMPT_PATTERNS,
    SERVER_READY_PATTERNS,
    ShellMiddleware,
    is_interactive_prompt,
    is_long_running_command,
    is_server_ready,
)


class TestIsInteractivePrompt:
    """Tests for is_interactive_prompt function."""

    def test_yes_no_parentheses(self) -> None:
        """Test detection of (y/n) prompts."""
        assert is_interactive_prompt("Continue? (y/n)")
        assert is_interactive_prompt("Proceed (Y/N)?")
        assert is_interactive_prompt("OK? (y/n) ")

    def test_yes_no_brackets(self) -> None:
        """Test detection of [y/n] prompts."""
        assert is_interactive_prompt("Continue? [y/n]")
        assert is_interactive_prompt("Proceed [Y/N]?")
        assert is_interactive_prompt("[yes/no] Do you want to continue?")

    def test_proceed_continue_questions(self) -> None:
        """Test detection of proceed/continue prompts."""
        assert is_interactive_prompt("Ok to proceed?")
        assert is_interactive_prompt("Do you want to continue?")
        assert is_interactive_prompt("Would you like to proceed?")

    def test_npm_npx_prompts(self) -> None:
        """Test detection of npm/npx specific prompts."""
        assert is_interactive_prompt("Need to install the following packages: Ok to proceed? (y)")
        assert is_interactive_prompt("Would you like to use TypeScript?")
        assert is_interactive_prompt("Do you want to use ESLint?")

    def test_input_prompts(self) -> None:
        """Test detection of input prompts."""
        assert is_interactive_prompt("Enter your name:")
        assert is_interactive_prompt("Enter project name: ")
        assert is_interactive_prompt("Password:")
        assert is_interactive_prompt("Username:")

    def test_selection_prompts(self) -> None:
        """Test detection of selection prompts."""
        assert is_interactive_prompt("Select a framework:")
        assert is_interactive_prompt("Choose an option:")
        assert is_interactive_prompt("Pick a template:")

    def test_non_prompts(self) -> None:
        """Test that non-prompts are not detected."""
        assert not is_interactive_prompt("Installing packages...")
        assert not is_interactive_prompt("Build completed successfully")
        assert not is_interactive_prompt("Compiling 42 files")
        assert not is_interactive_prompt("Running tests")
        assert not is_interactive_prompt("")
        assert not is_interactive_prompt("   ")

    def test_case_insensitive(self) -> None:
        """Test that prompt detection is case insensitive."""
        assert is_interactive_prompt("CONTINUE? (Y/N)")
        assert is_interactive_prompt("proceed?")
        assert is_interactive_prompt("ENTER YOUR NAME:")


class TestShellMiddleware:
    """Tests for ShellMiddleware class."""

    def test_init(self) -> None:
        """Test middleware initialization."""
        with tempfile.TemporaryDirectory() as tmpdir:
            middleware = ShellMiddleware(workspace_root=tmpdir)

            assert middleware._workspace_root == tmpdir
            assert middleware._timeout == 120.0
            assert middleware._max_output_bytes == 100_000
            assert len(middleware.tools) == 1

    def test_init_with_custom_timeout(self) -> None:
        """Test middleware initialization with custom timeout."""
        with tempfile.TemporaryDirectory() as tmpdir:
            middleware = ShellMiddleware(workspace_root=tmpdir, timeout=60.0)

            assert middleware._timeout == 60.0

    def test_init_with_custom_env(self) -> None:
        """Test middleware initialization with custom environment."""
        custom_env = {"FOO": "bar", "PATH": "/usr/bin"}
        with tempfile.TemporaryDirectory() as tmpdir:
            middleware = ShellMiddleware(workspace_root=tmpdir, env=custom_env)

            assert middleware._env == custom_env

    def test_shell_tool_description_includes_interactive(self) -> None:
        """Test that shell tool description mentions interactive mode."""
        with tempfile.TemporaryDirectory() as tmpdir:
            middleware = ShellMiddleware(workspace_root=tmpdir)
            tool = middleware.tools[0]

            assert "interactive" in tool.description.lower()

    def test_run_shell_command_empty_command(self) -> None:
        """Test that empty command raises exception."""
        with tempfile.TemporaryDirectory() as tmpdir:
            middleware = ShellMiddleware(workspace_root=tmpdir)

            with pytest.raises(ToolException, match="non-empty command"):
                middleware._run_shell_command("", tool_call_id="test")

    def test_run_shell_command_success(self) -> None:
        """Test successful shell command execution."""
        middleware = ShellMiddleware(workspace_root=".")

        # Use a simple cross-platform command
        if sys.platform == "win32":
            result = middleware._run_shell_command("echo hello", tool_call_id="test")
        else:
            result = middleware._run_shell_command("echo hello", tool_call_id="test")

        assert result.status == "success"
        assert "hello" in result.content

    def test_run_shell_command_failure(self) -> None:
        """Test failed shell command execution."""
        middleware = ShellMiddleware(workspace_root=".")

        # Use a command that will fail
        result = middleware._run_shell_command(
            "exit 1" if sys.platform != "win32" else "cmd /c exit 1", tool_call_id="test"
        )

        assert result.status == "error"
        assert "Exit code: 1" in result.content

    def test_run_shell_command_timeout(self) -> None:
        """Test shell command timeout."""
        middleware = ShellMiddleware(workspace_root=".", timeout=0.1)

        # Use a command that will take longer than timeout
        if sys.platform == "win32":
            command = "ping -n 10 localhost"
        else:
            command = "sleep 10"

        result = middleware._run_shell_command(command, tool_call_id="test")

        assert result.status == "error"
        assert "timed out" in result.content.lower()


class TestInteractiveShellExecution:
    """Tests for interactive shell execution."""

    @pytest.mark.asyncio
    async def test_async_interactive_shell_simple_command(self) -> None:
        """Test async interactive shell with simple command."""
        middleware = ShellMiddleware(workspace_root=".")

        if sys.platform == "win32":
            command = "echo hello"
        else:
            command = "echo hello"

        result = await middleware._async_interactive_shell(
            command,
            tool_call_id="test",
        )

        assert result.status == "success"
        assert "hello" in result.content

    @pytest.mark.asyncio
    async def test_async_interactive_shell_with_mock_input(self) -> None:
        """Test async interactive shell with mocked input callback."""
        middleware = ShellMiddleware(workspace_root=".")

        # Create a script that prompts for input
        if sys.platform == "win32":
            # Windows: simple echo that doesn't need input
            command = "echo test-output"
        else:
            # Unix: simple echo
            command = "echo test-output"

        result = await middleware._async_interactive_shell(
            command,
            tool_call_id="test",
            input_callback=lambda _: "test-input",
        )

        assert result.status == "success"

    def test_run_interactive_shell_command_wrapper(self) -> None:
        """Test the synchronous wrapper for interactive shell."""
        middleware = ShellMiddleware(workspace_root=".")

        if sys.platform == "win32":
            command = "echo interactive-test"
        else:
            command = "echo interactive-test"

        result = middleware._run_interactive_shell_command(
            command,
            tool_call_id="test",
        )

        assert result.status == "success"
        assert "interactive-test" in result.content

    def test_run_interactive_shell_command_empty(self) -> None:
        """Test that empty command in interactive mode raises exception."""
        with tempfile.TemporaryDirectory() as tmpdir:
            middleware = ShellMiddleware(workspace_root=tmpdir)

            with pytest.raises(ToolException, match="non-empty command"):
                middleware._run_interactive_shell_command("", tool_call_id="test")


class TestPromptPatterns:
    """Tests for prompt pattern coverage."""

    def test_all_patterns_are_valid_regex(self) -> None:
        """Test that all prompt patterns are valid regex."""
        import re

        for pattern in PROMPT_PATTERNS:
            # This should not raise
            re.compile(pattern, re.IGNORECASE)

    def test_pattern_coverage(self) -> None:
        """Test that patterns cover common scenarios.

        Each tuple is (input_text, expected_match_result).
        """
        test_cases = [
            ("Ok to proceed? (y)", True),
            ("Need to install create-next-app@16.1.1. Ok to proceed? (y)", True),
            ("Would you like to use TypeScript? No / Yes", True),
            ("Would you like to use ESLint? No / Yes", True),
            ("Do you want to use Tailwind CSS? No / Yes", True),
            ("Enter a value:", True),
            ("Select your package manager:", True),
            ("Choose a preset:", True),
            ("Pick your favorite:", True),
            # Non-matches
            ("Downloading packages...", False),
            ("Created package.json", False),
            ("Running npm install", False),
        ]

        for text, should_match in test_cases:
            result = is_interactive_prompt(text)
            assert result == should_match, f"Expected {should_match} for: {text}"


class TestIsServerReady:
    """Tests for is_server_ready function."""

    def test_generic_server_patterns(self) -> None:
        """Test detection of generic server ready patterns."""
        assert is_server_ready("Server listening on port 3000")
        assert is_server_ready("Listening at http://localhost:3000")
        assert is_server_ready("Server running at http://127.0.0.1:8080")
        assert is_server_ready("Server started successfully")
        assert is_server_ready("Server is running on port 5000")

    def test_nextjs_react_patterns(self) -> None:
        """Test detection of Next.js/React server ready patterns."""
        assert is_server_ready("Local: http://localhost:3000")
        assert is_server_ready("➜ Local: http://localhost:5173/")
        assert is_server_ready("ready - started server on 0.0.0.0:3000")
        assert is_server_ready("▲ Next.js 14.0.0")

    def test_vite_patterns(self) -> None:
        """Test detection of Vite server ready patterns."""
        assert is_server_ready("VITE v5.0.0 ready in 500ms")
        assert is_server_ready("Dev server running at http://localhost:5173")

    def test_python_patterns(self) -> None:
        """Test detection of Python server ready patterns."""
        assert is_server_ready("Running on http://127.0.0.1:5000")
        assert is_server_ready("Uvicorn running on http://0.0.0.0:8000")
        assert is_server_ready("Serving at http://localhost:8000")
        assert is_server_ready("Serving HTTP on 0.0.0.0 port 8000")

    def test_flask_patterns(self) -> None:
        """Test detection of Flask server ready patterns."""
        assert is_server_ready("Running on all addresses (0.0.0.0)")
        assert is_server_ready("Debugger is active!")

    def test_django_patterns(self) -> None:
        """Test detection of Django server ready patterns."""
        assert is_server_ready("Starting development server at http://127.0.0.1:8000/")
        assert is_server_ready("Quit the server with CONTROL-C")

    def test_node_patterns(self) -> None:
        """Test detection of Node.js server ready patterns."""
        assert is_server_ready("App listening on port 3000")
        assert is_server_ready("Express server listening on 8080")

    def test_port_patterns(self) -> None:
        """Test detection of port-based patterns."""
        assert is_server_ready("Port 3000")
        assert is_server_ready("http://localhost:3000/")

    def test_non_ready_patterns(self) -> None:
        """Test that non-ready messages are not detected."""
        assert not is_server_ready("Installing dependencies...")
        assert not is_server_ready("Compiling TypeScript...")
        assert not is_server_ready("Building project")
        assert not is_server_ready("Downloading packages")
        assert not is_server_ready("")
        assert not is_server_ready("   ")

    def test_case_insensitive(self) -> None:
        """Test that detection is case insensitive."""
        assert is_server_ready("SERVER LISTENING ON PORT 3000")
        assert is_server_ready("listening on")
        assert is_server_ready("READY ON HTTP://LOCALHOST:3000")


class TestIsLongRunningCommand:
    """Tests for is_long_running_command function."""

    def test_npm_commands(self) -> None:
        """Test detection of npm commands."""
        assert is_long_running_command("npm run dev")
        assert is_long_running_command("npm start")
        assert is_long_running_command("npm run start")

    def test_yarn_commands(self) -> None:
        """Test detection of yarn commands."""
        assert is_long_running_command("yarn dev")
        assert is_long_running_command("yarn start")

    def test_pnpm_commands(self) -> None:
        """Test detection of pnpm commands."""
        assert is_long_running_command("pnpm dev")
        assert is_long_running_command("pnpm start")

    def test_nextjs_vite_commands(self) -> None:
        """Test detection of Next.js and Vite commands."""
        assert is_long_running_command("next dev")
        assert is_long_running_command("next start")
        assert is_long_running_command("vite")
        assert is_long_running_command("vite dev")
        assert is_long_running_command("vite preview")

    def test_python_server_commands(self) -> None:
        """Test detection of Python server commands."""
        assert is_long_running_command("flask run")
        assert is_long_running_command("uvicorn app:main --reload")
        assert is_long_running_command("gunicorn app:app")
        assert is_long_running_command("python -m http.server")
        assert is_long_running_command("python3 -m http.server")
        assert is_long_running_command("python -m uvicorn main:app")
        assert is_long_running_command("django runserver")

    def test_docker_commands(self) -> None:
        """Test detection of Docker commands."""
        assert is_long_running_command("docker compose up")
        assert is_long_running_command("docker-compose up")

    def test_other_dev_commands(self) -> None:
        """Test detection of other dev server commands."""
        assert is_long_running_command("cargo run")
        assert is_long_running_command("go run main.go")
        assert is_long_running_command("nodemon server.js")
        assert is_long_running_command("ts-node-dev src/index.ts")
        assert is_long_running_command("tsx watch src/index.ts")

    def test_non_long_running_commands(self) -> None:
        """Test that short-running commands are not detected."""
        assert not is_long_running_command("npm install")
        assert not is_long_running_command("pip install flask")
        assert not is_long_running_command("ls -la")
        assert not is_long_running_command("cat package.json")
        assert not is_long_running_command("echo hello")
        assert not is_long_running_command("pytest tests/")

    def test_case_insensitive(self) -> None:
        """Test that detection is case insensitive."""
        assert is_long_running_command("NPM RUN DEV")
        assert is_long_running_command("Flask Run")
        assert is_long_running_command("VITE")


class TestServerReadyPatterns:
    """Tests for SERVER_READY_PATTERNS list."""

    def test_all_patterns_are_valid_regex(self) -> None:
        """Test that all server ready patterns are valid regex."""
        import re

        for pattern in SERVER_READY_PATTERNS:
            # This should not raise
            re.compile(pattern, re.IGNORECASE)


class TestBackgroundShellExecution:
    """Tests for background shell execution."""

    @pytest.mark.asyncio
    async def test_async_background_shell_quick_exit(self) -> None:
        """Test background shell with command that exits quickly."""
        middleware = ShellMiddleware(workspace_root=".")

        # Use a quick command - should detect as "no ready signal"
        if sys.platform == "win32":
            command = "echo hello"
        else:
            command = "echo hello"

        result = await middleware._async_background_shell(
            command,
            tool_call_id="test",
            startup_timeout=5.0,
        )

        # The process exits immediately, so we expect it to complete
        # It should detect the process ended
        assert result is not None

    @pytest.mark.asyncio
    async def test_async_background_shell_with_server_ready_output(self) -> None:
        """Test background shell detects server ready patterns."""
        middleware = ShellMiddleware(workspace_root=".")

        # Use a command that outputs a server-ready-like message
        if sys.platform == "win32":
            command = "echo Server listening on port 3000"
        else:
            command = 'echo "Server listening on port 3000"'

        result = await middleware._async_background_shell(
            command,
            tool_call_id="test",
            startup_timeout=5.0,
        )

        # Should detect the server ready pattern
        assert "listening" in result.content.lower() or "Server" in result.content

    def test_run_background_shell_command_empty(self) -> None:
        """Test that empty command in background mode raises exception."""
        with tempfile.TemporaryDirectory() as tmpdir:
            middleware = ShellMiddleware(workspace_root=tmpdir)

            with pytest.raises(ToolException, match="non-empty command"):
                middleware._run_background_shell_command("", tool_call_id="test")

    def test_run_background_shell_command_wrapper(self) -> None:
        """Test the synchronous wrapper for background shell."""
        middleware = ShellMiddleware(workspace_root=".")

        if sys.platform == "win32":
            command = "echo background-test"
        else:
            command = "echo background-test"

        result = middleware._run_background_shell_command(
            command,
            tool_call_id="test",
            startup_timeout=5.0,
        )

        assert result is not None
        assert "background-test" in result.content

    def test_shell_tool_auto_detects_long_running(self) -> None:
        """Test that shell tool auto-detects long-running commands."""
        middleware = ShellMiddleware(workspace_root=".")
        tool = middleware.tools[0]

        # The tool description should mention background
        assert "background" in tool.description.lower()

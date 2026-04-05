"""Simplified middleware that exposes a basic shell tool to agents.

This module provides ShellMiddleware, which integrates shell command execution
into the deep agent with intelligent prompt detection and server management:

Key Features:
- Shell tool for executing commands in the local environment
- Interactive prompt detection to prevent hanging on user input
- Server startup pattern recognition for long-running processes
- Background process management for dev servers
- Cross-platform support (Windows, Linux, macOS)

ShellMiddleware provides:
- Automatic shell tool registration with the agent
- Detection of interactive prompts (y/n, password, etc.)
- Recognition of server startup patterns (listening, ready, etc.)
- Support for background processes and server management
- Error handling and timeout management

Detection Patterns:
- PROMPT_PATTERNS: Regex patterns for interactive prompts requiring user input
- SERVER_READY_PATTERNS: Regex patterns for successful server startup

This middleware ensures safe and reliable shell command execution by:
1. Blocking interactive commands that would hang waiting for input
2. Recognizing when dev servers start successfully
3. Managing background processes for long-running services
"""

from __future__ import annotations

import asyncio
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

from langchain.agents.middleware.types import AgentMiddleware, AgentState
from langchain.tools import ToolRuntime, tool
from langchain_core.messages import ToolMessage
from langchain_core.tools.base import ToolException


def _convert_unix_command_to_windows(command: str) -> str:
    """Convert Unix-style commands to Windows-compatible commands.
    
    This function transforms common Unix commands to work on Windows:
    - mkdir -p -> mkdir (Windows creates parent dirs automatically)
    - rm -rf -> rmdir /s /q or del /s /q
    - rm -r -> rmdir /s /q or del /s /q
    - cp -r -> xcopy /e /i /y
    - touch -> type nul >
    
    Args:
        command: The Unix-style command to convert
        
    Returns:
        Windows-compatible command string
    """
    if sys.platform != "win32":
        return command
    
    # Convert mkdir -p to Windows mkdir (Windows creates parent dirs automatically)
    # Pattern: mkdir -p "path" or mkdir -p path
    command = re.sub(
        r'\bmkdir\s+-p\s+',
        'mkdir ',
        command,
        flags=re.IGNORECASE
    )
    
    # Convert rm -rf to Windows rmdir /s /q
    # Pattern: rm -rf path or rm -rf "path"
    command = re.sub(
        r'\brm\s+-rf\s+',
        'rmdir /s /q ',
        command,
        flags=re.IGNORECASE
    )
    
    # Convert rm -r to Windows rmdir /s /q
    command = re.sub(
        r'\brm\s+-r\s+',
        'rmdir /s /q ',
        command,
        flags=re.IGNORECASE
    )
    
    # Convert cp -r to Windows xcopy
    # Pattern: cp -r source dest
    command = re.sub(
        r'\bcp\s+-r\s+',
        'xcopy /e /i /y ',
        command,
        flags=re.IGNORECASE
    )
    
    # Convert touch to Windows type nul >
    # Pattern: touch filename
    command = re.sub(
        r'\btouch\s+',
        'type nul > ',
        command,
        flags=re.IGNORECASE
    )
    
    return command

# Patterns that indicate a line is an interactive prompt requiring user input
PROMPT_PATTERNS = [
    r"\(y/n\)",  # Yes/No prompts
    r"\(yes/no\)",  # Full yes/no
    r"\[y/n\]",  # Bracketed yes/no
    r"\[yes/no\]",  # Bracketed full yes/no
    r"proceed\?",  # "Ok to proceed?"
    r"continue\?",  # "Do you want to continue?"
    r"overwrite\?",  # "Overwrite existing file?"
    r"ok to proceed",  # npm's "Ok to proceed? (y)"
    r"would you like to",  # "Would you like to use..."
    r"do you want to",  # "Do you want to..."
    r"enter .*:",  # "Enter your name:"
    r"password:",  # Password prompts
    r"username:",  # Username prompts
    r"select.*:",  # "Select a framework:"
    r"choose.*:",  # "Choose an option:"
    r"pick.*:",  # "Pick a template:"
]

# Patterns that indicate a long-running server has successfully started
# When any of these patterns are found, we consider the command "successful"
# and can return control to the agent (leaving the process running in background)
SERVER_READY_PATTERNS = [
    # Generic server patterns
    r"listening on",
    r"listening at",
    r"server running",
    r"server started",
    r"server is running",
    r"ready on",
    r"ready in",
    r"started server",
    r"started at",
    r"started on",
    # Next.js / React patterns
    r"local:\s*http",
    r"➜\s*local:",
    r"ready -",
    r"▲ next",
    # Vite patterns
    r"vite.*ready",
    r"dev server running",
    # Python patterns
    r"running on http",
    r"uvicorn running",
    r"starting.*server",
    r"serving at",
    r"serving on",
    r"serving http",
    # Flask patterns
    r"running on all addresses",
    r"debugger is active",
    # Django patterns
    r"starting development server",
    r"quit the server",
    # Node patterns
    r"app listening",
    r"express.*listening",
    # Generic port listening
    r"port \d+",
    r":\d{4,5}/?$",  # URLs ending with port
]

# Commands that are known to be long-running dev servers
LONG_RUNNING_COMMANDS = [
    "npm run dev",
    "npm start",
    "npm run start",
    "yarn dev",
    "yarn start",
    "pnpm dev",
    "pnpm start",
    "next dev",
    "next start",
    "vite",
    "vite dev",
    "vite preview",
    "nuxt dev",
    "flask run",
    "uvicorn",
    "gunicorn",
    "python -m http.server",
    "python3 -m http.server",
    "python -m uvicorn",
    "django runserver",
    "manage.py runserver",
    "cargo run",
    "go run",
    "nodemon",
    "ts-node-dev",
    "tsx watch",
    "docker compose up",
    "docker-compose up",
]

# Commands that are known to be interactive and require user input.
# These will automatically use interactive mode to handle prompts.
INTERACTIVE_COMMANDS = [
    # Project scaffolding tools
    "create-next-app",
    "create-react-app",
    "create-vite",
    "npm init",
    "yarn init",
    "pnpm init",
    "npx create-next-app",
    "npx create-react-app",
    "npx create-vite",
    "npm create vite",
    "yarn create vite",
    "pnpm create vite",
    # Framework CLIs
    "ng new",  # Angular CLI
    "vue create",  # Vue CLI
    "nuxt init",  # Nuxt
    "remix create",  # Remix
    "astro create",  # Astro
    "svelte-create",  # Svelte
    # Package managers with prompts
    "npm install -g",  # May prompt for permissions
    "yarn global add",
    # Git commands that can be interactive
    "git rebase -i",
    "git add -p",  # Interactive staging
    "git stash -p",  # Interactive stash
    # Other interactive tools
    "django-admin startproject",
    "rails new",
    "cargo new",
    "go mod init",
    # Configuration tools
    "tsconfig.json",  # TypeScript init
    "eslint --init",
    "prettier --init",
    "husky install",
]

# Commands that are destructive, irreversible, or enable remote code execution.
# These are hard-blocked before any subprocess is spawned.
DANGEROUS_PATTERNS = [
    # Recursive/forced deletion of root, home, or all files in cwd
    r"rm\s+(-\w*r\w*f|-\w*f\w*r)\s+[/~]",
    r"rm\s+(-\w*r\w*f|-\w*f\w*r)\s+\*",
    # Raw disk writes (data destruction)
    r"dd\s+.*of\s*=\s*/dev/",
    r">\s*/dev/(sd|hd|nvme|vd)",
    r"mkfs\.",
    r"fdisk\s+/dev/",
    # Fork bomb
    r":\(\)\s*\{.*\|",
    # System control on host machine
    r"\b(shutdown|reboot|halt|poweroff)\b",
    # Piped remote-code execution
    r"(curl|wget)\s+.*\|\s*(bash|sh|python|python3|node|ruby|perl)",
    # Recursive world-writable permission on /
    r"chmod\s+(-\w*R|-R\w*)\s+[0-7]*7+\s+/",
]

_COMPILED_PATTERNS = [re.compile(p, re.IGNORECASE) for p in PROMPT_PATTERNS]
_COMPILED_SERVER_READY = [re.compile(p, re.IGNORECASE) for p in SERVER_READY_PATTERNS]
_COMPILED_DANGEROUS = [re.compile(p, re.IGNORECASE) for p in DANGEROUS_PATTERNS]

# Environment variables that can redirect interpreter loading or import resolution.
# Stripped from the subprocess environment before execution.
_DANGEROUS_ENV_VARS: frozenset[str] = frozenset(
    {
        "PYTHONPATH",
        "PYTHONSTARTUP",
        "PYTHONEXECUTABLE",
        "PYTHONHOME",
        "COMSPEC",  # Windows command interpreter
        "LD_PRELOAD",  # Linux dyNovac linker injection
        "LD_LIBRARY_PATH",
        "DYLD_INSERT_LIBRARIES",  # macOS equivalent of LD_PRELOAD
        "DYLD_LIBRARY_PATH",
    }
)


def is_dangerous_command(command: str) -> tuple[bool, str]:
    """Return (True, pattern) if the command matches a destructive pattern.

    Args:
        command: The shell command string to inspect.

    Returns:
        A tuple of (is_dangerous, matched_pattern_string).
    """
    for pattern in _COMPILED_DANGEROUS:
        if pattern.search(command):
            return True, pattern.pattern
    return False, ""


def is_interactive_prompt(line: str) -> bool:
    """Detect if a line is an interactive prompt requiring user input.

    Args:
        line: The output line to check.

    Returns:
        True if the line appears to be a prompt requiring input.
    """
    stripped = line.strip()
    if not stripped:
        return False

    # Check against known prompt patterns
    return any(pattern.search(stripped) for pattern in _COMPILED_PATTERNS)


def is_server_ready(line: str) -> bool:
    """Detect if a line indicates a server has successfully started.

    Args:
        line: The output line to check.

    Returns:
        True if the line indicates the server is ready.
    """
    stripped = line.strip()
    if not stripped:
        return False

    # Check against server ready patterns
    return any(pattern.search(stripped) for pattern in _COMPILED_SERVER_READY)


def is_long_running_command(command: str) -> bool:
    """Detect if a command is a known long-running server command.

    Args:
        command: The command to check.

    Returns:
        True if this is a known long-running command.
    """
    command_lower = command.lower()
    return any(pattern in command_lower for pattern in LONG_RUNNING_COMMANDS)


def is_interactive_command(command: str) -> bool:
    """Detect if a command is known to be interactive and requires user input.

    These commands typically prompt the user for configuration options,
    project names, framework selections, etc.

    Args:
        command: The command to check.

    Returns:
        True if this is a known interactive command.
    """
    command_lower = command.lower()
    return any(pattern in command_lower for pattern in INTERACTIVE_COMMANDS)


class ShellMiddleware(AgentMiddleware[AgentState, Any]):
    """Give basic shell access to agents via the shell.

    This shell will execute on the local machine and has NO safeguards except
    for the human in the loop safeguard provided by the CLI itself.
    """

    def __init__(
        self,
        *,
        workspace_root: str,
        timeout: float = 120.0,
        max_output_bytes: int = 100_000,
        env: dict[str, str] | None = None,
    ) -> None:
        """Initialize an instance of `ShellMiddleware`.

        Args:
            workspace_root: Working directory for shell commands.
            timeout: Maximum time in seconds to wait for command completion.
                Defaults to 120 seconds.
            max_output_bytes: Maximum number of bytes to capture from command output.
                Defaults to 100,000 bytes.
            env: Environment variables to pass to the subprocess. If None,
                uses the current process's environment. Defaults to None.
        """
        super().__init__()
        self._timeout = timeout
        self._max_output_bytes = max_output_bytes
        self._tool_name = "shell"
        self._env = ShellMiddleware._sanitize_env(env if env is not None else os.environ.copy())
        self._workspace_root = workspace_root
        
        # Track background processes for cleanup
        self._background_processes: list[asyncio.subprocess.Process] = []
        
        # Register cleanup on exit
        import atexit
        atexit.register(self._cleanup_background_processes)

        # Build description with working directory information
        description = (
            f"Execute a shell command directly on the host. Commands will run in "
            f"the working directory: {self._workspace_root}. Each command runs in a fresh shell "
            f"environment with the current process's environment variables. Commands may "
            f"be truncated if they exceed the configured timeout or output limits. "
            f"Use interactive=True for commands that may prompt for user input "
            f"(e.g., npx create-next-app, npm init, git rebase -i). "
            f"Use background=True for long-running commands like dev servers "
            f"(e.g., npm run dev, vite, flask run) - returns when server is ready."
        )

        @tool(self._tool_name, description=description)
        def shell_tool(
            command: str,
            runtime: ToolRuntime[None, AgentState],
            interactive: bool = False,  # noqa: FBT001, FBT002
            background: bool = False,  # noqa: FBT001, FBT002
        ) -> ToolMessage | str:
            """Execute a shell command.

            Args:
                command: The shell command to execute.
                interactive: If True, run in interactive mode allowing user to
                    respond to prompts. Use for commands like npx create-next-app,
                    npm init, or any command that may ask for user input.
                    Note: Many interactive commands are auto-detected and will
                    automatically use interactive mode.
                background: If True, run as a background process and return when
                    server is ready (for long-running commands like npm run dev,
                    vite, flask run). The process continues running in background.
            """
            # Auto-detect interactive commands
            if not interactive and is_interactive_command(command):
                interactive = True

            if background or is_long_running_command(command):
                return self._run_background_shell_command(
                    command, tool_call_id=runtime.tool_call_id
                )
            if interactive:
                return self._run_interactive_shell_command(
                    command, tool_call_id=runtime.tool_call_id
                )
            return self._run_shell_command(command, tool_call_id=runtime.tool_call_id)

        self._shell_tool = shell_tool
        self.tools = [self._shell_tool]

    def _cleanup_background_processes(self) -> None:
        """Clean up background processes before exit to prevent asyncio errors."""
        for process in self._background_processes:
            try:
                if process.returncode is None:
                    # Process is still running, terminate it
                    process.terminate()
                    # Try to wait for it to finish (with timeout)
                    try:
                        import time
                        start = time.time()
                        while process.returncode is None and time.time() - start < 1.0:
                            time.sleep(0.1)
                    except Exception:
                        pass
            except Exception:
                # Ignore errors during cleanup
                pass
        self._background_processes.clear()
    
    def _remove_completed_process(self, process: asyncio.subprocess.Process) -> None:
        """Remove a completed process from tracking.
        
        Args:
            process: The process to remove from tracking
        """
        try:
            if process in self._background_processes:
                self._background_processes.remove(process)
        except Exception:
            pass

    @staticmethod
    def _sanitize_env(env: dict[str, str]) -> dict[str, str]:
        """Remove env vars that can redirect interpreter or import resolution.

        Args:
            env: The environment dict to sanitize.

        Returns:
            A new dict with dangerous variables removed.
        """
        return {k: v for k, v in env.items() if k not in _DANGEROUS_ENV_VARS}

    def _run_shell_command(
        self,
        command: str,
        *,
        tool_call_id: str | None,
    ) -> ToolMessage | str:
        """Execute a shell command and return the result.

        This method uses dyNovac prompt detection:
        1. Run the command with a short initial timeout
        2. If output contains a prompt pattern, automatically switch to interactive mode
        3. Otherwise, continue with normal execution

        Args:
            command: The shell command to execute.
            tool_call_id: The tool call ID for creating a ToolMessage.

        Returns:
            A ToolMessage with the command output or an error message.
        """
        if not command or not isinstance(command, str):
            msg = "Shell tool expects a non-empty command string."
            raise ToolException(msg)

        # Convert Unix commands to Windows-compatible commands
        command = _convert_unix_command_to_windows(command)

        dangerous, reason = is_dangerous_command(command)
        if dangerous:
            blocked_msg = (
                f"Command blocked: matches dangerous pattern `{reason}`. "
                "If intentional, run it manually in your terminal."
            )
            return ToolMessage(
                content=blocked_msg,
                tool_call_id=tool_call_id,
                name=self._tool_name,
                status="error",
            )

        # Snapshot files targeted by rm before they are deleted
        if re.search(r"\brm\b", command):
            try:
                from novacode_cli.recovery import extract_rm_targets, get_recovery_manager

                mgr = get_recovery_manager()
                if mgr:
                    for target in extract_rm_targets(command, Path(self._workspace_root)):
                        mgr.snapshot(target, reason="rm-command", command=command)
            except Exception:
                pass  # never block execution due to snapshot failure

        # Phase 1: Try running with a short timeout to detect prompts
        prompt_detection_timeout = 5.0  # Short timeout to detect prompts
        try:
            result = subprocess.run(  # noqa: S602
                command,
                check=False,
                shell=True,
                capture_output=True,
                timeout=prompt_detection_timeout,
                env=self._env,
                cwd=self._workspace_root,
            )

            # Command completed quickly - return result
            stdout = (result.stdout or b"").decode("utf-8", errors="replace")
            stderr = (result.stderr or b"").decode("utf-8", errors="replace")

            output_parts = []
            if stdout.strip():
                output_parts.append(stdout)
            if stderr.strip():
                stderr_lines = stderr.strip().split("\n")
                output_parts.extend(f"[stderr] {line}" for line in stderr_lines)

            output = "\n".join(output_parts) if output_parts else "<no output>"

            if len(output) > self._max_output_bytes:
                output = output[: self._max_output_bytes]
                output += f"\n\n... Output truncated at {self._max_output_bytes} bytes."

            if result.returncode != 0:
                output = f"{output.rstrip()}\n\nExit code: {result.returncode}"
                status = "error"
            else:
                status = "success"

            return ToolMessage(
                content=output,
                tool_call_id=tool_call_id,
                name=self._tool_name,
                status=status,
            )

        except subprocess.TimeoutExpired as e:
            # Command timed out - check if it's waiting for input
            partial_output = ""
            if e.stdout:
                partial_output = e.stdout.decode("utf-8", errors="replace")
            if e.stderr:
                stderr = e.stderr.decode("utf-8", errors="replace")
                if stderr.strip():
                    partial_output += "\n" + "\n".join(f"[stderr] {line}" for line in stderr.strip().split("\n"))

            # Check if the partial output contains a prompt pattern
            if partial_output and is_interactive_prompt(partial_output):
                # Prompt detected - switch to interactive mode
                sys.stdout.write("\n\033[1;33m⚠ Interactive prompt detected. Switching to interactive mode...\033[0m\n")
                sys.stdout.write(partial_output)
                sys.stdout.flush()
                return self._run_interactive_shell_command(
                    command,
                    tool_call_id=tool_call_id,
                    initial_output=partial_output,
                )

            # No prompt detected - it's just a slow command, let it continue
            # Run again with full timeout
            try:
                result = subprocess.run(  # noqa: S602
                    command,
                    check=False,
                    shell=True,
                    capture_output=True,
                    timeout=self._timeout,
                    env=self._env,
                    cwd=self._workspace_root,
                )

                stdout = (result.stdout or b"").decode("utf-8", errors="replace")
                stderr = (result.stderr or b"").decode("utf-8", errors="replace")

                output_parts = []
                if stdout.strip():
                    output_parts.append(stdout)
                if stderr.strip():
                    stderr_lines = stderr.strip().split("\n")
                    output_parts.extend(f"[stderr] {line}" for line in stderr_lines)

                output = "\n".join(output_parts) if output_parts else "<no output>"

                if len(output) > self._max_output_bytes:
                    output = output[: self._max_output_bytes]
                    output += f"\n\n... Output truncated at {self._max_output_bytes} bytes."

                if result.returncode != 0:
                    output = f"{output.rstrip()}\n\nExit code: {result.returncode}"
                    status = "error"
                else:
                    status = "success"

                return ToolMessage(
                    content=output,
                    tool_call_id=tool_call_id,
                    name=self._tool_name,
                    status=status,
                )

            except subprocess.TimeoutExpired:
                output = f"Error: Command timed out after {self._timeout:.1f} seconds."
                return ToolMessage(
                    content=output,
                    tool_call_id=tool_call_id,
                    name=self._tool_name,
                    status="error",
                )

    def _run_interactive_shell_command(
        self,
        command: str,
        *,
        tool_call_id: str | None,
        input_callback: Callable[[str], str] | None = None,
        initial_output: str | None = None,
    ) -> ToolMessage | str:
        """Execute a shell command in interactive mode with real-time I/O.

        This method streams output in real-time and prompts the user for input
        when it detects interactive prompts from the subprocess.

        Args:
            command: The shell command to execute.
            tool_call_id: The tool call ID for creating a ToolMessage.
            input_callback: Optional callback to get user input. If None, uses
                the default console input. The callback receives the prompt text
                and should return the user's response.
            initial_output: Optional output already captured from a previous
                execution attempt (used when switching to interactive mode).

        Returns:
            A ToolMessage with the command output or an error message.
        """
        if not command or not isinstance(command, str):
            msg = "Shell tool expects a non-empty command string."
            raise ToolException(msg)

        # Convert Unix commands to Windows-compatible commands
        command = _convert_unix_command_to_windows(command)

        dangerous, reason = is_dangerous_command(command)
        if dangerous:
            blocked_msg = (
                f"Command blocked: matches dangerous pattern `{reason}`. "
                "If intentional, run it manually in your terminal."
            )
            return ToolMessage(
                content=blocked_msg,
                tool_call_id=tool_call_id,
                name=self._tool_name,
                status="error",
            )

        # Run the async implementation in an event loop
        try:
            # Try to get the running loop, or create a new one
            try:
                asyncio.get_running_loop()
                # If we're already in an async context, we need to use a thread
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(
                        asyncio.run,
                        self._async_interactive_shell(
                            command,
                            tool_call_id=tool_call_id,
                            input_callback=input_callback,
                            initial_output=initial_output,
                        ),
                    )
                    return future.result(timeout=self._timeout)
            except RuntimeError:
                # No running loop, we can use asyncio.run directly
                return asyncio.run(
                    self._async_interactive_shell(
                        command,
                        tool_call_id=tool_call_id,
                        input_callback=input_callback,
                        initial_output=initial_output,
                    )
                )
        except TimeoutError:
            return ToolMessage(
                content=f"Error: Command timed out after {self._timeout:.1f} seconds.",
                tool_call_id=tool_call_id,
                name=self._tool_name,
                status="error",
            )
        except OSError as e:
            return ToolMessage(
                content=f"Error running interactive command: {e}",
                tool_call_id=tool_call_id,
                name=self._tool_name,
                status="error",
            )

    async def _async_interactive_shell(  # noqa: PLR0912, PLR0915
        self,
        command: str,
        *,
        tool_call_id: str | None,
        input_callback: Callable[[str], str] | None = None,
        initial_output: str | None = None,
    ) -> ToolMessage:
        """Async implementation of interactive shell execution.

        Args:
            command: The shell command to execute.
            tool_call_id: The tool call ID for creating a ToolMessage.
            input_callback: Optional callback to get user input.
            initial_output: Optional output already captured from a previous
                execution attempt (used when switching to interactive mode).

        Returns:
            A ToolMessage with the command output.
        """
        output_lines: list[str] = []
        status = "success"

        # Include any initial output from previous execution
        if initial_output:
            output_lines.append(initial_output)
            # Check if initial output contains a prompt that needs response
            if is_interactive_prompt(initial_output):
                sys.stdout.write(initial_output)
                sys.stdout.flush()
                if input_callback:
                    user_input = input_callback(initial_output)
                else:
                    user_input = self._get_user_input(initial_output)
                output_lines.append(f"> {user_input}")

        # Use cmd.exe on Windows, bash/sh on Unix
        if sys.platform == "win32":
            shell_cmd = command
            process = await asyncio.create_subprocess_shell(
                shell_cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=self._workspace_root,
                env=self._env,
            )
        else:
            process = await asyncio.create_subprocess_shell(
                command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=self._workspace_root,
                env=self._env,
            )

        # Buffer for accumulating partial lines (prompts often don't end with newline)
        buffer = ""
        last_prompt_check = ""

        try:
            while True:
                # Read available data (with timeout to check for prompts)
                try:
                    chunk = await asyncio.wait_for(
                        process.stdout.read(1024),  # type: ignore[union-attr]
                        timeout=0.5,
                    )
                except TimeoutError:
                    # No data available, check if buffer looks like a prompt
                    if buffer and buffer != last_prompt_check:
                        last_prompt_check = buffer
                        if is_interactive_prompt(buffer):
                            # Display the prompt and get user input
                            sys.stdout.write(buffer)
                            sys.stdout.flush()

                            if input_callback:
                                user_input = input_callback(buffer)
                            else:
                                user_input = self._get_user_input(buffer)

                            output_lines.append(buffer)
                            output_lines.append(f"> {user_input}")
                            buffer = ""

                            # Send input to process
                            if process.stdin:
                                process.stdin.write((user_input + "\n").encode())
                                await process.stdin.drain()
                    continue

                if not chunk:
                    # Process ended
                    break

                # Decode and process the chunk
                decoded = chunk.decode("utf-8", errors="replace")
                buffer += decoded

                # Process complete lines
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    # Display and record the line
                    sys.stdout.write(line + "\n")
                    sys.stdout.flush()
                    output_lines.append(line)

                # Check if remaining buffer is a prompt (even without newline)
                if buffer and is_interactive_prompt(buffer):
                    # Display the prompt and get user input
                    sys.stdout.write(buffer)
                    sys.stdout.flush()

                    if input_callback:
                        user_input = input_callback(buffer)
                    else:
                        user_input = self._get_user_input(buffer)

                    output_lines.append(buffer)
                    output_lines.append(f"> {user_input}")
                    buffer = ""
                    last_prompt_check = ""

                    # Send input to process
                    if process.stdin:
                        process.stdin.write((user_input + "\n").encode())
                        await process.stdin.drain()

            # Flush any remaining buffer
            if buffer:
                sys.stdout.write(buffer + "\n")
                sys.stdout.flush()
                output_lines.append(buffer)

            # Wait for process to complete
            await process.wait()

            if process.returncode != 0:
                status = "error"

        except OSError as e:
            output_lines.append(f"\nError during execution: {e}")
            status = "error"
            # Try to terminate the process
            try:
                process.terminate()
                await process.wait()
            except OSError:
                pass  # Process may already be terminated
        except KeyboardInterrupt:
            # User interrupted - terminate the process immediately
            output_lines.append("\n[yellow]Interrupted by user[/yellow]")
            status = "error"
            try:
                # Try graceful termination first
                process.terminate()
                # Wait briefly for graceful shutdown
                try:
                    await asyncio.wait_for(process.wait(), timeout=2.0)
                except asyncio.TimeoutError:
                    # Force kill if process doesn't terminate
                    try:
                        process.kill()
                        await process.wait()
                    except OSError:
                        pass  # Process already terminated
            except OSError:
                pass  # Process already terminated
            finally:
                # Ensure stdin is closed
                try:
                    if process.stdin:
                        process.stdin.close()
                except Exception:
                    pass
        finally:
            # Close stdin (StreamWriter) to prevent ResourceWarning on Windows
            # Note: stdout/stderr are StreamReader and don't need explicit closing
            try:
                if process.stdin:
                    process.stdin.close()
            except Exception:
                pass

        # Build output
        output = "\n".join(output_lines) if output_lines else "<no output>"

        # Truncate if needed
        if len(output) > self._max_output_bytes:
            output = output[: self._max_output_bytes]
            output += f"\n\n... Output truncated at {self._max_output_bytes} bytes."

        # Add exit code if non-zero
        if process.returncode and process.returncode != 0:
            output = f"{output.rstrip()}\n\nExit code: {process.returncode}"

        return ToolMessage(
            content=output,
            tool_call_id=tool_call_id,
            name=self._tool_name,
            status=status,
        )

    def _get_user_input(self, _prompt: str) -> str:
        """Get user input for an interactive prompt.

        Args:
            _prompt: The prompt text (for context, already displayed to user).

        Returns:
            The user's input string.
        """
        # Print a visual indicator that input is needed
        sys.stdout.write("\n")
        sys.stdout.write("\033[1;33m")  # Yellow bold
        sys.stdout.write("⚠ Shell is waiting for input")
        sys.stdout.write("\033[0m")  # Reset
        sys.stdout.write("\n")
        sys.stdout.flush()

        try:
            return input("> ")
        except EOFError:
            # User pressed Ctrl+D - treat as empty input
            return ""
        except KeyboardInterrupt:
            # User pressed Ctrl+C - return empty and let caller handle it
            # Re-raise to ensure proper cleanup in the calling context
            raise

    def _run_background_shell_command(
        self,
        command: str,
        *,
        tool_call_id: str | None,
        startup_timeout: float = 60.0,
    ) -> ToolMessage | str:
        """Execute a long-running shell command in the background.

        This method starts the command, watches output for "server ready" signals,
        and returns success once the server is up. The process continues running
        in the background.

        Args:
            command: The shell command to execute.
            tool_call_id: The tool call ID for creating a ToolMessage.
            startup_timeout: Maximum time to wait for server to be ready.

        Returns:
            A ToolMessage with the startup output or an error message.
        """
        if not command or not isinstance(command, str):
            msg = "Shell tool expects a non-empty command string."
            raise ToolException(msg)

        # Convert Unix commands to Windows-compatible commands
        command = _convert_unix_command_to_windows(command)

        dangerous, reason = is_dangerous_command(command)
        if dangerous:
            blocked_msg = (
                f"Command blocked: matches dangerous pattern `{reason}`. "
                "If intentional, run it manually in your terminal."
            )
            return ToolMessage(
                content=blocked_msg,
                tool_call_id=tool_call_id,
                name=self._tool_name,
                status="error",
            )

        # Run the async implementation in an event loop
        try:
            try:
                asyncio.get_running_loop()
                # If we're already in an async context, we need to use a thread
                import concurrent.futures

                with concurrent.futures.ThreadPoolExecutor() as executor:
                    future = executor.submit(
                        asyncio.run,
                        self._async_background_shell(
                            command,
                            tool_call_id=tool_call_id,
                            startup_timeout=startup_timeout,
                        ),
                    )
                    return future.result(timeout=startup_timeout + 10)
            except RuntimeError:
                # No running loop, we can use asyncio.run directly
                return asyncio.run(
                    self._async_background_shell(
                        command,
                        tool_call_id=tool_call_id,
                        startup_timeout=startup_timeout,
                    )
                )
        except TimeoutError:
            return ToolMessage(
                content=f"Error: Server did not start within {startup_timeout:.1f} seconds.",
                tool_call_id=tool_call_id,
                name=self._tool_name,
                status="error",
            )
        except OSError as e:
            return ToolMessage(
                content=f"Error running background command: {e}",
                tool_call_id=tool_call_id,
                name=self._tool_name,
                status="error",
            )

    async def _async_background_shell(  # noqa: PLR0912, PLR0915
        self,
        command: str,
        *,
        tool_call_id: str | None,
        startup_timeout: float = 60.0,
    ) -> ToolMessage:
        """Async implementation of background shell execution.

        Starts the command and waits for a "server ready" signal in the output.
        Returns when the server is ready, leaving the process running.

        Args:
            command: The shell command to execute.
            tool_call_id: The tool call ID for creating a ToolMessage.
            startup_timeout: Maximum time to wait for server to be ready.

        Returns:
            A ToolMessage with the startup output.
        """
        import time

        from novacode_cli.process_manager import ProcessManager, ProcessStatus

        output_lines: list[str] = []
        status = "success"
        server_ready = False
        start_time = time.time()

        # Start the subprocess.
        # stdin=DEVNULL is critical: prevents the background process from
        # inheriting the terminal's stdin handle. On Windows, a subprocess
        # that holds the console handle locks the terminal entirely —
        # the user cannot type or Ctrl+C until the process exits.
        process = await asyncio.create_subprocess_shell(
            command,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=self._workspace_root,
            env=self._env,
        )
        
        # Track background process for cleanup
        self._background_processes.append(process)

        # Register with ProcessManager for proper cleanup on exit
        manager = ProcessManager.get_instance()
        from novacode_cli.process_manager import ProcessInfo

        process_info = ProcessInfo(
            pid=process.pid,
            name=f"bg-{process.pid}",
            command=command,
            status=ProcessStatus.RUNNING,
            working_dir=self._workspace_root,
            _process=process,
        )
        manager._processes[process.pid] = process_info
        manager._name_to_pid[process_info.name] = process.pid

        # Print a header to indicate we're starting a background process
        sys.stdout.write(f"\n\033[1;36m▶ Starting background process: {command}\033[0m\n")
        sys.stdout.flush()

        try:
            while time.time() - start_time < startup_timeout:
                # Check if process has ended unexpectedly
                if process.returncode is not None:
                    # Process ended - this is usually a failure for long-running commands
                    status = "error"
                    break

                # Read available data with timeout
                try:
                    chunk = await asyncio.wait_for(
                        process.stdout.read(1024),  # type: ignore[union-attr]
                        timeout=1.0,
                    )
                except TimeoutError:
                    continue

                if not chunk:
                    # Process ended
                    break

                # Decode and process the chunk
                decoded = chunk.decode("utf-8", errors="replace")

                # Process each line
                for line in decoded.split("\n"):
                    if line:
                        sys.stdout.write(line + "\n")
                        sys.stdout.flush()
                        output_lines.append(line)

                        # Check if this line indicates server is ready
                        if is_server_ready(line):
                            server_ready = True
                            sys.stdout.write("\n\033[1;32m✓ Server is ready!\033[0m\n")
                            sys.stdout.flush()
                            break

                if server_ready:
                    break

            # Wait a brief moment to capture any additional startup output
            if server_ready:
                await asyncio.sleep(0.5)
                # Read any remaining output
                try:
                    remaining = await asyncio.wait_for(
                        process.stdout.read(4096),  # type: ignore[union-attr]
                        timeout=0.5,
                    )
                    if remaining:
                        decoded = remaining.decode("utf-8", errors="replace")
                        for line in decoded.split("\n"):
                            if line:
                                sys.stdout.write(line + "\n")
                                output_lines.append(line)
                        sys.stdout.flush()
                except TimeoutError:
                    pass

        except OSError as e:
            output_lines.append(f"\nError during startup: {e}")
            status = "error"

        # If process failed (exited), clean up stdin (StreamWriter) to prevent
        # ResourceWarning on Windows. stdout/stderr are StreamReader and don't need closing.
        # For running background processes, stdin stays open for potential input.
        if process.returncode is not None:
            try:
                if process.stdin:
                    process.stdin.close()
                # Remove from tracking since it's completed
                self._remove_completed_process(process)
            except Exception:
                pass

        # If the server is still running, drain its stdout pipe in a background
        # daemon thread. Without this, the pipe buffer (~64 KB) fills up as the
        # server keeps logging, causing the server process to block on write and
        # appear frozen. The daemon thread exits automatically when the process ends.
        if process.returncode is None and process.stdout is not None:
            import threading

            def _drain_stdout(proc_stdout: asyncio.StreamReader) -> None:
                """Read and discard server output to keep the pipe from filling."""
                import asyncio as _asyncio

                loop = _asyncio.new_event_loop()
                try:
                    async def _drain() -> None:
                        while True:
                            try:
                                chunk = await _asyncio.wait_for(proc_stdout.read(4096), timeout=1.0)
                                if not chunk:
                                    break
                            except (_asyncio.TimeoutError, Exception):
                                if proc_stdout.at_eof():
                                    break

                    loop.run_until_complete(_drain())
                finally:
                    loop.close()

            drain_thread = threading.Thread(
                target=_drain_stdout,
                args=(process.stdout,),
                daemon=True,
                name=f"stdout-drain-{process.pid}",
            )
            drain_thread.start()

        # Build output message
        output = "\n".join(output_lines) if output_lines else "<no output>"

        # Truncate if needed
        if len(output) > self._max_output_bytes:
            output = output[: self._max_output_bytes]
            output += f"\n\n... Output truncated at {self._max_output_bytes} bytes."

        # Determine final status and message
        if server_ready:
            output = (
                f"{output}\n\n"
                f"✓ Server started successfully (PID: {process.pid})\n"
                f"The server is running in the background."
            )
            status = "success"
        elif process.returncode is not None:
            output = f"{output}\n\n✗ Process exited with code {process.returncode}"
            status = "error"
        else:
            # Timeout without server ready signal
            output = (
                f"{output}\n\n"
                f"⚠ Server may be running (PID: {process.pid}) but no ready signal detected.\n"
                f"The process is still running in the background."
            )
            # Consider it success since the process is still running
            status = "success"

        return ToolMessage(
            content=output,
            tool_call_id=tool_call_id,
            name=self._tool_name,
            status=status,
        )


__all__ = [
    "DANGEROUS_PATTERNS",
    "ShellMiddleware",
    "is_dangerous_command",
    "is_interactive_prompt",
    "is_long_running_command",
    "is_server_ready",
]

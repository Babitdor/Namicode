"""Shell module: ShellMiddleware class.

Provides ShellMiddleware, the LangGraph agent middleware that integrates
shell command execution with intelligent prompt detection, server management,
background process tracking, and sandbox execution support.
"""

from __future__ import annotations

import asyncio
import os
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

from novacode_cli.shell.patterns import _NPX_YES_RE
from novacode_cli.shell.utils import (
    _convert_unix_command_to_windows,
    _sanitize_env,
    get_auto_answer,
    is_dangerous_command,
    is_interactive_command,
    is_interactive_prompt,
    is_long_running_command,
    is_server_ready,
)


class ShellMiddleware(AgentMiddleware[AgentState, Any]):
    """Give basic shell access to agents via the shell.

    This shell will execute on the local machine and has NO safeguards except
    for the human in the loop safeguard provided by the CLI itself.

    When a sandbox backend is provided, commands will be executed in the sandbox
    instead of locally, enabling remote execution in isolated environments.
    """

    def __init__(
        self,
        *,
        workspace_root: str,
        timeout: float = 120.0,
        max_output_bytes: int = 100_000,
        env: dict[str, str] | None = None,
        backend: Any = None,
        sandbox_working_dir: str | None = None,
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
            backend: Optional sandbox backend for remote execution. When provided,
                commands will be executed in the sandbox instead of locally.
                Must implement SandboxBackendProtocol with an execute() method.
            sandbox_working_dir: Working directory inside the sandbox (e.g.
                "/workspace"), used only for the tool description shown to the
                model when running in a sandbox. Falls back to workspace_root.
        """
        super().__init__()
        self._timeout = timeout
        self._max_output_bytes = max_output_bytes
        self._tool_name = "shell"
        self._env = _sanitize_env(
            env if env is not None else os.environ.copy()
        )
        self._workspace_root = workspace_root
        self._backend = backend

        # Track background processes for cleanup
        self._background_processes: list[asyncio.subprocess.Process] = []

        # Register cleanup on exit
        import atexit

        atexit.register(self._cleanup_background_processes)

        # Whether commands actually execute in a sandbox. A CompositeBackend is
        # always passed (for /skills/ etc. routing), so "backend is not None" is
        # not a reliable signal — check whether the *default* backend supports
        # remote execution.
        _is_sandbox = self._supports_sandbox_execution()
        # Directory shown to the model in the tool description.
        _display_dir = (
            (sandbox_working_dir or self._workspace_root)
            if _is_sandbox
            else self._workspace_root
        )

        # Determine shell and platform for this environment
        if _is_sandbox:
            # Sandboxes are always Linux/bash
            _shell_name = "bash"
            _platform_note = "You are operating in an **isolated Linux sandbox** — always use bash syntax."
        elif sys.platform == "win32":
            _shell_name = "PowerShell"
            _platform_note = (
                "The host is **Windows** — always use PowerShell syntax. "
                "NEVER use bash commands (rm -rf, chmod, sudo, export, etc.). "
                "Use `;` to chain commands, `$env:VAR` for env vars, "
                "`Remove-Item -Recurse -Force` instead of `rm -rf`."
            )
        elif sys.platform == "darwin":
            _shell_name = "zsh"
            _platform_note = "The host is **macOS** — use zsh/bash syntax."
        else:
            _shell_name = "bash"
            _platform_note = "The host is **Linux** — use bash syntax."

        # Determine execution context for description
        if _is_sandbox:
            execution_context = (
                f"You are operating in an **isolated sandbox environment** at {_display_dir}. "
                f"All commands execute inside the sandbox, not on the local machine. "
            )
        else:
            execution_context = f"Commands run in **{_shell_name}** in the working directory: {_display_dir}. "

        # Build description with working directory and platform information
        description = (
            f"Execute a {_shell_name} command. {_platform_note} {execution_context}"
            f"Each command runs in a fresh shell environment. Commands may "
            f"be truncated if they exceed the configured timeout or output limits. "
            f"Use interactive=True for commands that may prompt for user input "
            f"(e.g., npx create-next-app, npm init, git rebase -i). "
            f"Use background=True for long-running commands like dev servers "
            f"(e.g., npm run dev, vite, flask run) - returns when server is ready. "
            f"For scaffolding commands (create-next-app, ng new, npm init, etc.) "
            f"always pass non-interactive flags (--yes, --defaults, --no-interaction, "
            f"or explicit option flags) so arrow-key TUI menus never appear — "
            f"piped stdin cannot support TUI navigation."
        )

        def _shell_impl(
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

        self._shell_tool = tool(self._tool_name, description=description)(_shell_impl)

        # Alias: Claude-family models habitually call `bash` (a reflex from
        # Claude Code's Bash tool), which otherwise errors with "bash is not a
        # valid tool". Register a same-behavior `bash` alias so those calls
        # resolve. (We intentionally do NOT alias `execute` — deepagents already
        # registers an `execute` tool and a duplicate name would break the build.)
        self.tools = [self._shell_tool]
        if self._tool_name != "bash":
            self._bash_alias = tool(
                "bash", description=f"Alias for `{self._tool_name}`. {description}"
            )(_shell_impl)
            self.tools.append(self._bash_alias)

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
    def _preprocess_command(command: str) -> str:
        """Inject --yes into npx commands to skip package-install prompts."""
        return _NPX_YES_RE.sub(r"\1 --yes ", command)

    def _run_command_with_stdin(
        self,
        command: str,
        stdin_input: str,
        *,
        tool_call_id: str | None,
    ) -> ToolMessage:
        """Re-run a command feeding stdin_input to its stdin (for auto-answered prompts).

        Args:
            command: The shell command to execute.
            stdin_input: The text to pipe into the command's stdin.
            tool_call_id: The tool call ID for creating a ToolMessage.

        Returns:
            A ToolMessage with the command output.
        """
        try:
            result = subprocess.run(  # noqa: S602
                command,
                check=False,
                shell=True,
                capture_output=True,
                input=stdin_input.encode(),
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
                output_parts.extend(
                    f"[stderr] {line}" for line in stderr.strip().split("\n")
                )

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
            return ToolMessage(
                content=f"Error: Command timed out after {self._timeout:.1f} seconds.",
                tool_call_id=tool_call_id,
                name=self._tool_name,
                status="error",
            )

    def _supports_sandbox_execution(self) -> bool:
        """Check whether the backend can actually execute shell commands.

        This must use the *exact same* test that ``CompositeBackend.execute``
        uses internally — ``isinstance(default, SandboxBackendProtocol)`` —
        otherwise the two disagree: the old duck-typed check (``hasattr
        execute``) returned True for any non-Filesystem default with an
        ``execute`` attr (including ``CompositeBackend`` itself, whose
        ``execute`` always exists but raises ``NotImplementedError`` when the
        default isn't a real sandbox). That mismatch produced the
        "Sandbox execution not available" error. By checking the protocol
        directly we guarantee that whenever this returns True, ``execute``
        succeeds — and when it returns False we fall back to local execution.

        Returns:
            True only if the (default) backend implements SandboxBackendProtocol.
        """
        if self._backend is None:
            return False

        from deepagents.backends.protocol import SandboxBackendProtocol

        # CompositeBackend: execution always delegates to the *default* backend,
        # so the sandbox question is really "is the default a sandbox?".
        try:
            from deepagents.backends import CompositeBackend

            if isinstance(self._backend, CompositeBackend):
                return isinstance(self._backend.default, SandboxBackendProtocol)
        except ImportError:
            pass

        # Direct backend: it supports execution iff it is a sandbox backend.
        return isinstance(self._backend, SandboxBackendProtocol)

    def _run_shell_command(
        self,
        command: str,
        *,
        tool_call_id: str | None,
    ) -> ToolMessage | str:
        """Execute a shell command and return the result.

        This method uses dynamic prompt detection:
        1. Run the command with a short initial timeout
        2. If output contains a prompt pattern, automatically switch to interactive mode
        3. Otherwise, continue with normal execution

        When a sandbox backend is configured, commands are executed in the sandbox
        instead of locally.

        Args:
            command: The shell command to execute.
            tool_call_id: The tool call ID for creating a ToolMessage.

        Returns:
            A ToolMessage with the command output or an error message.
        """
        if not command or not isinstance(command, str):
            msg = "Shell tool expects a non-empty command string."
            raise ToolException(msg)

        # Convert Unix commands to Windows-compatible commands (for local execution)
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

        # Snapshot files targeted by rm before they are deleted (local only)
        if self._backend is None and re.search(r"\brm\b", command):
            try:
                from novacode_cli.recovery import (
                    extract_rm_targets,
                    get_recovery_manager,
                )

                mgr = get_recovery_manager()
                if mgr:
                    for target in extract_rm_targets(
                        command, Path(self._workspace_root)
                    ):
                        mgr.snapshot(target, reason="rm-command", command=command)
            except Exception:
                pass  # never block execution due to snapshot failure

        # If sandbox backend is available, execute in sandbox
        if self._supports_sandbox_execution():
            return self._run_sandbox_command(command, tool_call_id=tool_call_id)

        # Local execution (original behavior)
        return self._run_local_command(command, tool_call_id=tool_call_id)

    def _run_sandbox_command(
        self,
        command: str,
        *,
        tool_call_id: str | None,
    ) -> ToolMessage:
        """Execute a shell command in the sandbox backend.

        Args:
            command: The shell command to execute.
            tool_call_id: The tool call ID for creating a ToolMessage.

        Returns:
            A ToolMessage with the command output or an error message.
        """
        try:
            # Call the sandbox backend's execute method
            result = self._backend.execute(command)

            # Format output for LLM consumption
            output = result.output or "<no output>"

            if len(output) > self._max_output_bytes:
                output = output[: self._max_output_bytes]
                output += f"\n\n... Output truncated at {self._max_output_bytes} bytes."

            if result.exit_code is not None and result.exit_code != 0:
                output = f"{output.rstrip()}\n\nExit code: {result.exit_code}"
                status = "error"
            else:
                status = "success"

            if result.truncated:
                output += "\n[Output was truncated due to size limits]"

            return ToolMessage(
                content=output,
                tool_call_id=tool_call_id,
                name=self._tool_name,
                status=status,
            )
        except NotImplementedError as e:
            return ToolMessage(
                content=f"Error: Sandbox execution not available. {e}",
                tool_call_id=tool_call_id,
                name=self._tool_name,
                status="error",
            )
        except Exception as e:
            return ToolMessage(
                content=f"Error executing command in sandbox: {e}",
                tool_call_id=tool_call_id,
                name=self._tool_name,
                status="error",
            )

    def _run_local_command(
        self,
        command: str,
        *,
        tool_call_id: str | None,
    ) -> ToolMessage:
        """Execute a shell command locally (original behavior).

        This method uses dynamic prompt detection:
        1. Run the command with a short initial timeout
        2. If output contains a prompt pattern, automatically switch to interactive mode
        3. Otherwise, continue with normal execution

        Args:
            command: The shell command to execute.
            tool_call_id: The tool call ID for creating a ToolMessage.

        Returns:
            A ToolMessage with the command output or an error message.
        """
        command = self._preprocess_command(command)

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
                    partial_output += "\n" + "\n".join(
                        f"[stderr] {line}" for line in stderr.strip().split("\n")
                    )

            # Check if the partial output contains a prompt pattern
            if partial_output and is_interactive_prompt(partial_output):
                auto = get_auto_answer(partial_output)
                if auto is not None:
                    # Safe to answer automatically — pipe the response and re-run
                    return self._run_command_with_stdin(
                        command, auto, tool_call_id=tool_call_id
                    )
                # Not auto-answerable → switch to interactive mode
                sys.stdout.write(
                    "\n\033[1;33m⚠ Interactive prompt detected. Switching to interactive mode...\033[0m\n"
                )
                sys.stdout.write(partial_output)
                sys.stdout.flush()
                return self._run_interactive_shell_command(
                    command,
                    tool_call_id=tool_call_id,
                    initial_output=partial_output,
                )  # type: ignore

            # No prompt detected — return partial output from the first attempt
            # instead of re-running. This avoids double-execution of side-effectful
            # commands (INSERT, git push, etc.) and wasteful re-execution.
            partial_output = (partial_output.strip() or "<no output before timeout>")
            return ToolMessage(
                content=partial_output
                + f"\n\n[Command timed out after {prompt_detection_timeout:.1f}s. "
                f"No interactive prompt detected — partial output shown above.]",
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
        command = self._preprocess_command(command)

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
                            auto = get_auto_answer(buffer)
                            if auto is not None:
                                user_input = auto
                            else:
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
                    auto = get_auto_answer(buffer)
                    if auto is not None:
                        user_input = auto
                    else:
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

        except asyncio.CancelledError:
            # Task was cancelled — terminate the subprocess and re-raise
            output_lines.append("\n[yellow]Task cancelled[/yellow]")
            status = "error"
            try:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), timeout=2.0)
                except TimeoutError:
                    process.kill()
                    await process.wait()
            except OSError:
                pass
            finally:
                try:
                    if process.stdin:
                        process.stdin.close()
                except Exception:
                    pass
            raise
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
                except TimeoutError:
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

        Note: In sandbox mode, background commands are executed synchronously
        since the sandbox doesn't support persistent background processes.

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
        command = self._preprocess_command(command)

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

        # If sandbox backend is available, execute synchronously
        # (sandbox doesn't support persistent background processes)
        if self._supports_sandbox_execution():
            return self._run_sandbox_command(command, tool_call_id=tool_call_id)

        # Run the async implementation in an event loop (local execution)
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
        sys.stdout.write(
            f"\n\033[1;36m▶ Starting background process: {command}\033[0m\n"
        )
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
                            sys.stdout.write("\n\033[1;32m✓ Server started successfully!\033[0m\n")
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

        except asyncio.CancelledError:
            output_lines.append("\n[yellow]Background task cancelled[/yellow]")
            status = "error"
            try:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), timeout=2.0)
                except TimeoutError:
                    process.kill()
                    await process.wait()
            except OSError:
                pass
            finally:
                try:
                    if process.stdin:
                        process.stdin.close()
                except Exception:
                    pass
            raise
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
                                chunk = await _asyncio.wait_for(
                                    proc_stdout.read(4096), timeout=1.0
                                )
                                if not chunk:
                                    break
                            except (TimeoutError, Exception):
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
    "ShellMiddleware",
]
"""Shell module: ShellMiddleware class.

Provides ShellMiddleware, the LangGraph agent middleware that integrates
shell command execution with intelligent prompt detection, server management,
background process tracking, and sandbox execution support.
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

from langchain.agents.middleware.types import AgentMiddleware, AgentState
from langchain.tools import ToolRuntime, tool
from langchain_core.messages import ToolMessage
from langchain_core.tools.base import ToolException

from novacode_cli.shell.os_sandbox import OSSandboxPolicy, detect_backend, wrap_command
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
        exec_sandbox: bool = False,
        allow_network: bool = True,
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
            exec_sandbox: When True (Pattern A), wrap locally-executed commands in
                an OS kernel sandbox (bwrap/sandbox-exec) that confines filesystem
                writes to ``workspace_root``. Ignored for sandbox-backend
                execution. Degrades to no-op when no backend is available.
            allow_network: Whether the OS sandbox permits network egress. Defaults
                to True so dependency installs keep working.
        """
        super().__init__()
        self._timeout = timeout
        self._max_output_bytes = max_output_bytes
        self._tool_name = "shell"
        self._env = _sanitize_env(env if env is not None else os.environ.copy())
        self._workspace_root = workspace_root
        self._backend = backend

        # OS-level shell confinement (Pattern A). Sets self._os_confined and
        # self._os_policy; probes the backend once, at build time.
        self._init_os_sandbox(exec_sandbox, allow_network)

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
            (sandbox_working_dir or self._workspace_root) if _is_sandbox else self._workspace_root
        )

        # Determine shell and platform for this environment
        if _is_sandbox:
            # Sandboxes are always Linux/bash
            _shell_name = "bash"
            _platform_note = (
                "You are operating in an **isolated Linux sandbox** — always use bash syntax."
            )
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
        elif self._os_confined:
            _net = "Network is available" if self._os_policy.allow_network else "Network is blocked"
            execution_context = (
                f"Commands run in **{_shell_name}** in the working directory: {_display_dir}. "
                f"The shell is **confined by an OS sandbox**: filesystem writes are "
                f"restricted to the workspace ({_display_dir}) — writes elsewhere "
                f"(e.g. /etc, $HOME) will fail. {_net}. "
            )
        else:
            execution_context = (
                f"Commands run in **{_shell_name}** in the working directory: {_display_dir}. "
            )

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

        # ── Resolve the program each tool ACTUALLY executes locally ──────
        # `shell` → the host's native interactive shell: **PowerShell on Windows**
        # (matching the description above), instead of cmd.exe — which is what
        # asyncio's create_subprocess_shell would otherwise use, silently
        # contradicting "use PowerShell syntax". `bash` → the **real bash** binary
        # (Git Bash / WSL on Windows). ``None`` ⇒ fall back to
        # create_subprocess_shell (POSIX sh on Unix, cmd.exe on Windows).
        import shutil

        self._native_prog: list[str] | None = None
        if sys.platform == "win32":
            _pwsh = shutil.which("pwsh") or shutil.which("powershell")
            if _pwsh:
                self._native_prog = [_pwsh, "-NoProfile", "-Command"]
        _bash_exe = shutil.which("bash")
        self._bash_prog: list[str] | None = [_bash_exe, "-c"] if _bash_exe else None

        bash_description = (
            "Execute a command in the **bash** shell — use POSIX/bash syntax "
            "(`rm -rf`, `chmod`, `export`, `&&`, `$VAR`, `ls`, `cat`, …). Use this "
            "when you specifically want bash; for the host's native shell "
            f"(**{_shell_name}**) use `shell`. Same interactive=/background= options "
            "as `shell`."
        )

        def _make_impl(prog: list[str] | None, *, is_bash: bool = False) -> Callable[..., ToolMessage | str]:
            """Build a tool body bound to the program it should execute."""

            def _impl(
                command: str,
                runtime: ToolRuntime[None, AgentState],
                interactive: bool = False,  # noqa: FBT001, FBT002
                background: bool = False,  # noqa: FBT001, FBT002
            ) -> ToolMessage | str:
                """Execute a command (see the tool description for which shell + syntax)."""
                # `bash` with no bash on the host (and no sandbox to run it in) —
                # fail clearly instead of silently running it in another shell.
                if is_bash and prog is None and not self._supports_sandbox_execution():
                    return ToolMessage(
                        content=(
                            "bash is not available on this host. Install Git Bash or "
                            "WSL, or use the `shell` tool (PowerShell on Windows)."
                        ),
                        tool_call_id=runtime.tool_call_id,
                        name="bash",
                        status="error",
                    )
                if not interactive and is_interactive_command(command):
                    interactive = True
                if background or is_long_running_command(command):
                    return self._run_background_shell_command(
                        command, tool_call_id=runtime.tool_call_id, prog=prog
                    )
                if interactive:
                    return self._run_interactive_shell_command(
                        command, tool_call_id=runtime.tool_call_id, prog=prog
                    )
                return self._run_shell_command(
                    command, tool_call_id=runtime.tool_call_id, prog=prog
                )

            return _impl

        self._shell_tool = tool(self._tool_name, description=description)(
            _make_impl(self._native_prog)
        )
        self.tools = [self._shell_tool]
        # `bash` is a real, separate tool (not a same-behavior alias) so Claude's
        # reflexive bash calls run actual bash. We intentionally do NOT register
        # `execute` — deepagents already provides one and a duplicate breaks build.
        if self._tool_name != "bash":
            self._bash_alias = tool("bash", description=bash_description)(
                _make_impl(self._bash_prog, is_bash=True)
            )
            self.tools.append(self._bash_alias)

    def _init_os_sandbox(self, exec_sandbox: bool, allow_network: bool) -> None:  # noqa: FBT001
        """Probe and configure the OS-level shell sandbox (Pattern A).

        Done once at build time so the per-command path stays cheap and never
        ``console.print``s (which would corrupt the TUI). If confinement was
        requested but no backend is available, it is disabled with a one-line
        warning — execution still runs, guarded by the dangerous-command
        blocklist + HITL.
        """
        self._os_confined = False
        self._os_policy = OSSandboxPolicy(
            workspace_root=self._workspace_root,
            allow_network=allow_network,
            enabled=False,
        )
        if not exec_sandbox:
            return

        from novacode_cli.config.config import boot_status

        detected = detect_backend()
        if detected is None:
            boot_status(
                "sandbox: no OS sandbox backend available — shell runs "
                "unconfined (blocklist + approval still apply)",
                "warn",
            )
            return

        self._os_policy = OSSandboxPolicy(
            workspace_root=self._workspace_root,
            allow_network=allow_network,
            enabled=True,
            backend=detected,
        )
        self._os_confined = True
        net = "network on" if allow_network else "network blocked"
        boot_status(f"sandbox: shell confined to workspace via {detected} ({net})", "ok")

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
        """Inject helpers into commands before execution.

        - npx: add --yes to skip package-install prompts.
        - grep -r / --recursive: add --exclude-dir for .git and other noise dirs.
          A bare recursive grep walks .git/objects/pack files (100 MB+ binary) and
          node_modules, which can add hundreds of seconds per call. Skip injection
          when the caller already set any --exclude-dir flag.
        """
        command = _NPX_YES_RE.sub(r"\1 --yes ", command)

        if "--exclude-dir" not in command and re.search(
            r"\bgrep\b.*(-[a-zA-Z]*r[a-zA-Z]*|--recursive\b)",
            command,
            re.IGNORECASE,
        ):
            command = re.sub(
                r"\bgrep\b",
                (
                    "grep"
                    " --exclude-dir=.git"
                    " --exclude-dir=node_modules"
                    " --exclude-dir=__pycache__"
                    " --exclude-dir=.venv"
                    " --exclude-dir=venv"
                    " --exclude-dir=.next"
                    " --exclude-dir=dist"
                    " --exclude-dir=build"
                ),
                command,
                count=1,
                flags=re.IGNORECASE,
            )

        return command

    def _run_async(
        self,
        make_coro: Callable[[], Awaitable[ToolMessage]],
        *,
        timeout: float,
        detach_future: Any = None,
    ) -> ToolMessage:
        """Run a coroutine to completion from this (synchronous) tool body.

        The agent runs async, so a sync tool needing asyncio must bridge: if an
        event loop is already running, execute in a worker thread with its own
        loop; otherwise run it directly. ``make_coro`` is a thunk so the coroutine
        is created exactly once, on whichever path is taken. Exceptions (including
        the worker's ``TimeoutError``) propagate to the caller.

        ``detach_future`` (a ``concurrent.futures.Future``) supports Ctrl+B
        backgrounding: when the coroutine sets it, we return that "backgrounded"
        result to the agent *immediately* while leaving the worker thread running
        so it keeps draining the process to completion. Only used on the in-loop
        (TUI) path — the direct path has no separate thread to keep alive.
        """
        import concurrent.futures

        # Detach-capable commands run on the shared background loop so a Ctrl+B
        # detach can return to the agent while the coroutine keeps draining the
        # process here. We just wait on it from this (worker) thread.
        if detach_future is not None:
            from novacode_cli.shell.jobs import get_background_loop

            main = asyncio.run_coroutine_threadsafe(make_coro(), get_background_loop())
            done, _ = concurrent.futures.wait(
                {main, detach_future},
                timeout=timeout,
                return_when=concurrent.futures.FIRST_COMPLETED,
            )
            if detach_future in done:
                # Backgrounded: hand the "job started" message to the agent now;
                # `main` keeps running on the background loop to completion.
                return detach_future.result()
            if main in done:
                return main.result()
            # Timed out waiting. The coroutine has its own self._timeout guard
            # and terminates the subprocess on its own; surface a TimeoutError.
            raise TimeoutError

        try:
            asyncio.get_running_loop()
            in_loop = True
        except RuntimeError:
            in_loop = False

        if in_loop:
            # Don't use `with ThreadPoolExecutor()` — its __exit__ calls
            # shutdown(wait=True), which blocks until the submitted thread
            # finishes even when result() already raised TimeoutError. That
            # adds up to self._timeout extra seconds after the outer deadline.
            executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
            try:
                return executor.submit(asyncio.run, make_coro()).result(timeout=timeout)
            except concurrent.futures.TimeoutError:
                raise TimeoutError from None
            finally:
                executor.shutdown(wait=False)
        return asyncio.run(make_coro())

    def _supports_sandbox_execution(self) -> bool:
        """Check whether the backend can actually execute shell commands.

        This must use the same routing rule as ``CompositeBackend.execute``
        — it delegates to the *default* backend — but we intentionally restrict
        the check to real sandbox backends (subclasses of ``BaseSandbox``). Nova's
        local-mode backend, ``LocalShellBackend``, implements
        ``SandboxBackendProtocol`` but is **not** a sandbox; we want the
        ``ShellMiddleware`` to handle local execution itself so dangerous-command
        blocklists, OS confinement, and background-process management keep
        working. Remote sandbox wrappers such as ``WorkdirSandboxBackend`` extend
        ``BaseSandbox`` and are therefore treated as sandboxes.

        Returns:
            True only if the (default) backend is a real sandbox backend.
        """
        if self._backend is None:
            return False

        from deepagents.backends.sandbox import BaseSandbox

        # CompositeBackend: execution always delegates to the *default* backend,
        # so the sandbox question is really "is the default a real sandbox?".
        try:
            from deepagents.backends import CompositeBackend

            if isinstance(self._backend, CompositeBackend):
                return isinstance(self._backend.default, BaseSandbox)
        except ImportError:
            pass

        # Direct backend: it supports execution iff it is a real sandbox backend.
        return isinstance(self._backend, BaseSandbox)

    def _run_shell_command(
        self,
        command: str,
        *,
        tool_call_id: str | None,
        prog: list[str] | None = None,
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
            prog: argv prefix used to exec the command (e.g. PowerShell / bash); ``None`` runs it in the platform default shell.

        Returns:
            A ToolMessage with the command output or an error message.
        """
        if not command or not isinstance(command, str):
            msg = "Shell tool expects a non-empty command string."
            raise ToolException(msg)

        # Convert Unix→cmd.exe ONLY for the native fallback path (prog is None on
        # Windows ⇒ cmd.exe). PowerShell/bash (prog set) run the syntax as-is.
        if prog is None:
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
                    for target in extract_rm_targets(command, Path(self._workspace_root)):
                        mgr.snapshot(target, reason="rm-command", command=command)
            except Exception:
                pass  # never block execution due to snapshot failure

        # If sandbox backend is available, execute in sandbox
        if self._supports_sandbox_execution():
            return self._run_sandbox_command(command, tool_call_id=tool_call_id)

        # Local execution (original behavior)
        return self._run_local_command(command, tool_call_id=tool_call_id, prog=prog)

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

    def _run_sandbox_background_command(
        self,
        command: str,
        *,
        tool_call_id: str | None,
        settle_secs: float = 2.0,
    ) -> ToolMessage:
        """Launch a long-running command detached inside the sandbox.

        Sandbox ``execute`` waits for the command to exit, so a server that never
        exits hangs the call until the outer timeout. We instead ``nohup`` the
        command into the background (output redirected to a log, stdin closed) so
        ``execute`` returns immediately, wait a couple of seconds, then report
        whether it is still running — capturing the startup banner (e.g.
        ``Serving HTTP on ...``) or, if it died early (port in use, crash), the
        error output. The server keeps running for the rest of the task.

        Args:
            command: The shell command to launch (Linux/bash — sandboxes are Linux).
            tool_call_id: Tool call ID for the resulting ToolMessage.
            settle_secs: How long to wait before checking liveness.

        Returns:
            A ToolMessage describing the launch (status=error if it exited early).
        """
        import shlex
        import uuid

        cid = (tool_call_id or "").replace("/", "_")[:12] or uuid.uuid4().hex[:8]
        # /tmp inside the (Linux) sandbox container, namespaced per tool call.
        log_path = f"/tmp/nova-bg-{cid}.log"  # noqa: S108 — sandbox container path
        cmd_q = shlex.quote(command)
        log_q = shlex.quote(log_path)
        settle = max(1, int(settle_secs))

        # nohup … & detaches; redirecting std{out,err}→log and stdin←/dev/null
        # ensures the child doesn't hold the exec pipe open (which would re-hang).
        script = (
            f"nohup sh -c {cmd_q} > {log_q} 2>&1 < /dev/null & "
            f"NOVA_BG_PID=$!; "
            f"sleep {settle}; "
            f'if kill -0 "$NOVA_BG_PID" 2>/dev/null; then '
            f'echo "[background] started (pid $NOVA_BG_PID), still running after {settle}s"; '
            f'echo "[background] logs: {log_path}"; '
            f"echo '--- startup output ---'; tail -n 30 {log_q} 2>/dev/null; "
            f"else "
            f'echo "[background] process exited within {settle}s — it did not stay up:"; '
            f"cat {log_q} 2>/dev/null; "
            f"exit 1; "
            f"fi"
        )
        return self._run_sandbox_command(script, tool_call_id=tool_call_id)

    def _run_local_command(
        self,
        command: str,
        *,
        tool_call_id: str | None,
        prog: list[str] | None = None,
    ) -> ToolMessage:
        """Execute a shell command locally, streaming to completion.

        The command runs (on a single process — never re-executed) until it exits
        or the full ``self._timeout`` elapses. The first few seconds double as
        interactive-prompt detection: a known prompt is auto-answered on the
        process's stdin; an unanswerable prompt aborts with guidance instead of
        blocking. Output is returned in the ToolMessage — nothing is written to
        stdout (that corrupts the Textual TUI; see ``iterate_agent_events``).

        Args:
            command: The shell command to execute.
            tool_call_id: The tool call ID for creating a ToolMessage.
            prog: argv prefix used to exec the command (e.g. PowerShell / bash); ``None`` runs it in the platform default shell.

        Returns:
            A ToolMessage with the command output or an error message.
        """
        command = self._preprocess_command(command)
        import concurrent.futures

        detach_future: concurrent.futures.Future = concurrent.futures.Future()
        try:
            return self._run_async(
                lambda: self._async_local_shell(
                    command, tool_call_id=tool_call_id, prog=prog, detach_future=detach_future
                ),
                timeout=self._timeout + 15,
                detach_future=detach_future,
            )
        except TimeoutError:
            return ToolMessage(
                content=f"Error: Command timed out after {self._timeout:.0f} seconds.",
                tool_call_id=tool_call_id,
                name=self._tool_name,
                status="error",
            )
        except OSError as e:
            return ToolMessage(
                content=f"Error running command: {e}",
                tool_call_id=tool_call_id,
                name=self._tool_name,
                status="error",
            )

    async def _spawn(
        self,
        command: str,
        prog: list[str] | None,
        *,
        stdin: int,
        stdout: int,
        stderr: int,
    ) -> asyncio.subprocess.Process:
        """Create the subprocess in the correct shell.

        When *prog* is set (e.g. ``[pwsh, "-NoProfile", "-Command"]`` or
        ``[bash, "-c"]``) the command runs in that exact shell via
        ``create_subprocess_exec`` — no cmd.exe wrapper, no quoting surprises.
        When *prog* is ``None`` it falls back to the platform default shell
        (POSIX ``sh`` on Unix, ``cmd.exe`` on Windows).
        """
        kwargs = {
            "stdin": stdin,
            "stdout": stdout,
            "stderr": stderr,
            "cwd": self._workspace_root,
            "env": self._env,
        }
        if prog is not None:
            return await asyncio.create_subprocess_exec(*prog, command, **kwargs)
        return await asyncio.create_subprocess_shell(command, **kwargs)

    async def _async_local_shell(  # noqa: PLR0912, PLR0915
        self,
        command: str,
        *,
        tool_call_id: str | None,
        prompt_window: float = 5.0,
        prog: list[str] | None = None,
        detach_future: Any = None,
    ) -> ToolMessage:
        """Stream a local command to completion (up to ``self._timeout``).

        Reads output on one long-lived process. During the first ``prompt_window``
        seconds, a stall with prompt-like output is treated as an interactive
        prompt — auto-answered if known, otherwise aborted with guidance (the agent
        can re-run with non-interactive flags) rather than hanging on console input.
        """
        import time

        # Confine the command to the workspace via the OS sandbox (no-op when
        # confinement is disabled or unavailable). Done here, at the single local
        # launch point, so interactive + non-interactive paths are both covered.
        command = wrap_command(command, self._os_policy)

        proc = await self._spawn(
            command,
            prog,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

        # Publish a control handle so the TUI can reach this subprocess (it runs
        # in a detached thread+loop that Textual task-cancellation can't touch).
        # Esc sets ``kill`` → we terminate promptly instead of freezing for the
        # full timeout. Cleared in ``finally``.
        from novacode_cli.shell import jobs as _jobs

        _ctl = _jobs.set_current(command)

        out_parts: list[str] = []
        tail = ""  # rolling last-4KB window, for prompt detection only
        last_prompt = ""
        start = time.time()
        status = "success"
        note = ""
        detached = False
        _job = None

        try:
            while True:
                if _ctl.kill.is_set():
                    proc.kill()
                    status = "error"
                    note = "\n\n[Command killed by user (Esc).]"
                    break
                if not detached and _ctl.detach.is_set():
                    # Ctrl+B: hand this command to a background job and return a
                    # "backgrounded" result to the agent NOW. We keep looping to
                    # drain the process to completion (no timeout for a bg job).
                    detached = True
                    _job = _jobs.get_registry().add(command, self._tool_name)
                    if detach_future is not None and not detach_future.done():
                        detach_future.set_result(
                            ToolMessage(
                                content=(
                                    f"[backgrounded: job {_job.id}] `{command}` is still running. "
                                    f"Continue with other work — you'll be notified when it finishes. "
                                    f"Call wait_for_job({_job.id}) to get its output, or "
                                    f"list_jobs() to see all jobs."
                                ),
                                tool_call_id=tool_call_id,
                                name=self._tool_name,
                                status="success",
                            )
                        )
                if not detached and time.time() - start > self._timeout:
                    proc.kill()
                    status = "error"
                    note = f"\n\n[Command exceeded {self._timeout:.0f}s and was terminated.]"
                    break
                try:
                    chunk = await asyncio.wait_for(proc.stdout.read(1024), timeout=0.5)  # type: ignore[union-attr]
                except TimeoutError:
                    # No output right now. Within the prompt window, check whether the
                    # process is blocked waiting on an interactive prompt.
                    if (
                        not detached
                        and tail
                        and tail != last_prompt
                        and (time.time() - start) <= prompt_window
                        and proc.returncode is None
                        and is_interactive_prompt(tail)
                    ):
                        last_prompt = tail
                        auto = get_auto_answer(tail)
                        if auto is not None and proc.stdin is not None:
                            proc.stdin.write((auto + "\n").encode())
                            try:
                                await proc.stdin.drain()
                            except (OSError, ConnectionResetError):
                                pass
                        else:
                            proc.kill()
                            status = "error"
                            note = (
                                "\n\n[This command is waiting for interactive input, which "
                                "can't be provided here. Re-run it non-interactively — pass "
                                "flags like --yes / --defaults / -y, or pipe the input via stdin.]"
                            )
                            break
                    continue
                if not chunk:
                    break  # stdout closed → process is exiting
                text = chunk.decode("utf-8", errors="replace")
                out_parts.append(text)
                tail = (tail + text)[-4096:]
                # Once detached the tool widget is gone (the agent moved on), so
                # stop streaming to it — the output is delivered via the job.
                if tool_call_id and not detached:
                    from novacode_cli.events import emit_tool_output
                    emit_tool_output(tool_call_id, text)
        except asyncio.CancelledError:
            proc.kill()
            raise
        finally:
            _jobs.clear_current(_ctl)
            if proc.returncode is None:
                try:
                    await asyncio.wait_for(proc.wait(), timeout=2.0)
                except TimeoutError:
                    proc.kill()
            try:
                if proc.stdin:
                    proc.stdin.close()
            except Exception:  # noqa: BLE001
                pass

        output = "".join(out_parts).strip() or "<no output>"
        if len(output) > self._max_output_bytes:
            output = (
                output[: self._max_output_bytes]
                + f"\n\n... Output truncated at {self._max_output_bytes} bytes."
            )
        rc = proc.returncode
        if status == "success" and rc not in (0, None):
            status = "error"
            output = f"{output}\n\nExit code: {rc}"

        if detached and _job is not None:
            # The agent already got the "backgrounded" message; deliver the final
            # output to the job (fires the TUI notify/note callback). The return
            # value below is discarded by _run_async on the detach path.
            _jobs.get_registry().complete(_job.id, output + note, rc)

        return ToolMessage(
            content=output + note,
            tool_call_id=tool_call_id,
            name=self._tool_name,
            status=status,
        )

    def _run_interactive_shell_command(
        self,
        command: str,
        *,
        tool_call_id: str | None,
        prog: list[str] | None = None,
    ) -> ToolMessage:
        """Run a command that may prompt for input, handling prompts non-blockingly.

        Shares the streaming path with ``_run_local_command`` — the only difference
        is that prompt detection stays active for the *whole* command (not just the
        first few seconds). Known prompts (npm/npx "ok to proceed?", …) are
        auto-answered on the process's stdin; an unanswerable prompt aborts with
        guidance rather than blocking on console input (there is no console to read
        from under the Textual TUI). Nothing is written to stdout.

        Args:
            command: The shell command to execute.
            tool_call_id: The tool call ID for creating a ToolMessage.
            prog: argv prefix used to exec the command (e.g. PowerShell / bash); ``None`` runs it in the platform default shell.

        Returns:
            A ToolMessage with the command output or an error message.
        """
        if not command or not isinstance(command, str):
            msg = "Shell tool expects a non-empty command string."
            raise ToolException(msg)

        if prog is None:
            command = _convert_unix_command_to_windows(command)
        command = self._preprocess_command(command)

        dangerous, reason = is_dangerous_command(command)
        if dangerous:
            return ToolMessage(
                content=(
                    f"Command blocked: matches dangerous pattern `{reason}`. "
                    "If intentional, run it manually in your terminal."
                ),
                tool_call_id=tool_call_id,
                name=self._tool_name,
                status="error",
            )

        import concurrent.futures

        detach_future: concurrent.futures.Future = concurrent.futures.Future()
        try:
            return self._run_async(
                lambda: self._async_local_shell(
                    command,
                    tool_call_id=tool_call_id,
                    prompt_window=self._timeout,
                    prog=prog,
                    detach_future=detach_future,
                ),
                timeout=self._timeout + 15,
                detach_future=detach_future,
            )
        except TimeoutError:
            return ToolMessage(
                content=f"Error: Command timed out after {self._timeout:.0f} seconds.",
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

    def _run_background_shell_command(
        self,
        command: str,
        *,
        tool_call_id: str | None,
        startup_timeout: float = 60.0,
        prog: list[str] | None = None,
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
            prog: argv prefix used to exec the command (e.g. PowerShell / bash); ``None`` runs it in the platform default shell.
            startup_timeout: Maximum time to wait for server to be ready.

        Returns:
            A ToolMessage with the startup output or an error message.
        """
        if not command or not isinstance(command, str):
            msg = "Shell tool expects a non-empty command string."
            raise ToolException(msg)

        # Convert Unix→cmd.exe only for the native fallback (prog is None).
        if prog is None:
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

        # In a sandbox, launch the process DETACHED inside the container so the
        # call returns immediately. Running it synchronously (the old behavior)
        # blocked forever on never-exiting servers (e.g. `python -m http.server`),
        # which looked like the agent hanging until the outer timeout fired.
        if self._supports_sandbox_execution():
            return self._run_sandbox_background_command(command, tool_call_id=tool_call_id)

        # Local execution: stream the server's startup in its own loop.
        try:
            return self._run_async(
                lambda: self._async_background_shell(
                    command, tool_call_id=tool_call_id, startup_timeout=startup_timeout, prog=prog
                ),
                timeout=startup_timeout + 10,
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
        prog: list[str] | None = None,
    ) -> ToolMessage:
        """Async implementation of background shell execution.

        Starts the command and waits for a "server ready" signal in the output.
        Returns when the server is ready, leaving the process running.

        Args:
            command: The shell command to execute.
            tool_call_id: The tool call ID for creating a ToolMessage.
            prog: argv prefix used to exec the command (e.g. PowerShell / bash); ``None`` runs it in the platform default shell.
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
        # Confine the background command to the workspace via the OS sandbox
        # (no-op when disabled/unavailable). --die-with-parent in the bwrap recipe
        # ties the server's sandbox to Nova so it isn't orphaned on exit.
        command = wrap_command(command, self._os_policy)

        process = await self._spawn(
            command,
            prog,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
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
        manager.register_process(process_info)

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
                if tool_call_id:
                    from novacode_cli.events import emit_tool_output
                    emit_tool_output(tool_call_id, decoded)

                # Collect each line into output_lines — do NOT stream to stdout
                # (that corrupts the Textual TUI; the agent loop renders the
                # returned ToolMessage instead).
                for line in decoded.split("\n"):
                    if line:
                        output_lines.append(line)
                        if is_server_ready(line):
                            server_ready = True
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
                                output_lines.append(line)
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
                                chunk = await _asyncio.wait_for(proc_stdout.read(4096), timeout=1.0)
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

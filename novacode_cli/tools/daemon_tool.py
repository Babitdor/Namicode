"""Detached daemon tool — launch long-lived background processes that survive the CLI.

The ``daemon`` tool starts a process that keeps running after the CLI exits (a
detached daemon), tracks it in a JSON registry under ``~/.nova/daemons/``, and lets
the agent check status, tail logs, and stop it. This is distinct from the
in-session :class:`~novacode_cli.shell.jobs.BackgroundJob`, which dies with the CLI.

Windows-first (per NOVA.md): the child is spawned with ``DETACHED_PROCESS |
CREATE_NEW_PROCESS_GROUP`` so it survives the console. On POSIX it uses
``start_new_session=True``. stdout/stderr are redirected to a per-daemon log file.

This module must NEVER ``console.print`` — it runs inside the live agent loop / TUI.
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

from langchain.tools import tool

from novacode_cli.daemons.registry import (
    DaemonInfo,
    get,
    is_alive,
    list_daemons,
    log_path_for,
    register,
    unregister,
)

#: Windows creation flags that run the child without a console window and in its
#: own process group. ``CREATE_NO_WINDOW`` (not ``DETACHED_PROCESS``) is used so
#: the child's stdout/stderr can still be captured to the log file — a
#: ``DETACHED_PROCESS`` has no console and console apps (e.g. ``python``) can't
#: write to stdout when detached, so their output is lost.
_CREATE_FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(
    subprocess, "CREATE_NEW_PROCESS_GROUP", 0
)


def _spawn(command: str, cwd: str, log_path: Path) -> int:
    """Spawn *command* detached, redirecting output to *log_path*. Returns the pid."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("ab") as log:
        if os.name == "nt":
            proc = subprocess.Popen(  # noqa: S602 — the tool's whole job is running shell commands
                command,
                shell=True,
                cwd=cwd,
                stdout=log,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                creationflags=_CREATE_FLAGS,
                close_fds=True,
            )
        else:
            proc = subprocess.Popen(  # noqa: S602 — the tool's whole job is running shell commands
                command,
                shell=True,
                cwd=cwd,
                stdout=log,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
                close_fds=True,
            )
    return proc.pid


def _tail(path: Path, lines: int = 30) -> str:
    """Return the last *lines* of a log file, or a friendly placeholder."""
    if not path.exists():
        return "(no log file yet)"
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "(log unreadable)"
    if not text.strip():
        return "(log is empty)"
    tail = text.splitlines()[-max(1, lines) :]
    return "\n".join(tail)


@tool
def daemon(
    action: str,
    name: str = "",
    command: str = "",
    cwd: str = "",
    tail_lines: int = 30,
) -> str:
    """Manage a detached background daemon that survives the CLI session.

    Use this to launch a long-lived process (a server, watcher, or worker) that
    keeps running after Nova exits, then check/stop it later.

    Args:
        action: "start", "status", "logs", "stop", or "list".
        name: Unique daemon name (required for start/status/logs/stop).
        command: Shell command to run (required for start).
        cwd: Working directory for the daemon (default: current directory).
        tail_lines: How many trailing log lines to show for "logs" (default 30).

    Returns:
        A human-readable result describing what happened.
    """
    action = (action or "").strip().lower()
    name = (name or "").strip()

    if action == "list":
        return _list_daemons()
    if not name:
        return "Error: name is required for start/status/logs/stop."
    handlers = {
        "start": lambda: _start_daemon(name, command, cwd),
        "status": lambda: _status_daemon(name),
        "logs": lambda: _logs_daemon(name, tail_lines),
        "stop": lambda: _stop_daemon(name),
    }
    handler = handlers.get(action)
    if handler is None:
        return f"Error: unknown action '{action}'. Supported: start, status, logs, stop, list."
    return handler()


def _list_daemons() -> str:
    """Render the list of registered daemons."""
    daemons = list_daemons()
    if not daemons:
        return "No daemons registered."
    lines = [f"{len(daemons)} daemon(s):"]
    for d in daemons:
        state = "running" if is_alive(d.pid) else "stopped"
        lines.append(f"  {d.name}  {state}  pid {d.pid}  - {d.command[:60]}")
    return "\n".join(lines)


def _start_daemon(name: str, command: str, cwd: str) -> str:
    """Start a daemon and register it."""
    if not command.strip():
        return "Error: command is required for start."
    existing = get(name)
    if existing is not None and is_alive(existing.pid):
        return f"Error: daemon '{name}' is already running (pid {existing.pid})."
    log_path = log_path_for(name)
    try:
        pid = _spawn(command, cwd or str(Path.cwd()), log_path)
    except OSError as exc:
        return f"Error: failed to start daemon: {exc}"
    register(
        DaemonInfo(
            name=name,
            pid=pid,
            command=command,
            log_path=str(log_path),
            started_at=time.time(),
            cwd=cwd or str(Path.cwd()),
        )
    )
    return f"Started daemon '{name}' (pid {pid}). Log: {log_path}"


def _status_daemon(name: str) -> str:
    """Report a daemon's running/stopped state."""
    info = get(name)
    if info is None:
        return f"Daemon '{name}' is not registered."
    state = "running" if is_alive(info.pid) else "stopped"
    return f"Daemon '{name}': {state} (pid {info.pid}, started {info.started_at:.0f})."


def _logs_daemon(name: str, tail_lines: int) -> str:
    """Tail a daemon's log file."""
    info = get(name)
    if info is None:
        return f"Daemon '{name}' is not registered."
    return _tail(Path(info.log_path), tail_lines)


def _stop_daemon(name: str) -> str:
    """Stop a daemon and unregister it."""
    info = get(name)
    if info is None:
        return f"Daemon '{name}' is not registered."
    if is_alive(info.pid):
        try:
            if os.name == "nt":
                subprocess.run(  # noqa: S603 — terminating a daemon we started
                    ["taskkill", "/PID", str(info.pid), "/T", "/F"],  # noqa: S607
                    capture_output=True,
                    timeout=10,
                    check=False,
                )
            else:
                os.kill(info.pid, 15)  # SIGTERM
        except (OSError, subprocess.TimeoutExpired) as exc:
            return f"Error: failed to stop daemon '{name}': {exc}"
    unregister(name)
    return f"Stopped daemon '{name}'."

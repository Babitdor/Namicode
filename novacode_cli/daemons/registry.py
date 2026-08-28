"""Detached-daemon registry — a JSON file-backed pid store that survives restarts.

A *daemon* is a long-lived background process launched by the ``daemon`` tool that
outlives the CLI session (unlike an in-session :class:`~novacode_cli.shell.jobs.BackgroundJob`,
which dies with the CLI). This module tracks those daemons by name in a small JSON
file under ``~/.nova/daemons/registry.json`` so the agent can list, check, and stop
them across CLI restarts.

The registry is thread-safe (a lock guards every read-modify-write) and writes
atomically (temp file + rename) so a crash can't corrupt it.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: Directory holding daemon logs + the registry.
DAEMONS_DIR = Path.home() / ".nova" / "daemons"
#: Registry file path.
REGISTRY_PATH = DAEMONS_DIR / "registry.json"

_lock = threading.RLock()


@dataclass
class DaemonInfo:
    """A registered daemon's metadata."""

    name: str
    pid: int
    command: str
    log_path: str
    started_at: float
    cwd: str = "."

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-able dict."""
        return {
            "name": self.name,
            "pid": self.pid,
            "command": self.command,
            "log_path": self.log_path,
            "started_at": self.started_at,
            "cwd": self.cwd,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DaemonInfo:
        """Deserialize from a dict (as written by :meth:`to_dict`)."""
        return cls(
            name=str(data.get("name", "")),
            pid=int(data.get("pid", 0)),
            command=str(data.get("command", "")),
            log_path=str(data.get("log_path", "")),
            started_at=float(data.get("started_at", 0.0)),
            cwd=str(data.get("cwd", ".")),
        )


def _read() -> dict[str, dict[str, Any]]:
    if not REGISTRY_PATH.exists():
        return {}
    try:
        data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, OSError):
        return {}
    return {}


def _write(data: dict[str, dict[str, Any]]) -> None:
    DAEMONS_DIR.mkdir(parents=True, exist_ok=True)
    tmp = REGISTRY_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(REGISTRY_PATH)


def register(info: DaemonInfo) -> None:
    """Add or update a daemon in the registry."""
    with _lock:
        data = _read()
        data[info.name] = info.to_dict()
        _write(data)


def unregister(name: str) -> bool:
    """Remove a daemon by name. Returns True if it was present."""
    with _lock:
        data = _read()
        if name not in data:
            return False
        del data[name]
        _write(data)
        return True


def get(name: str) -> DaemonInfo | None:
    """Look up a daemon by name, or None."""
    with _lock:
        data = _read()
        raw = data.get(name)
        if raw is None:
            return None
        return DaemonInfo.from_dict(raw)


def list_daemons() -> list[DaemonInfo]:
    """Return all registered daemons, sorted by name."""
    with _lock:
        data = _read()
        return sorted(
            (DaemonInfo.from_dict(raw) for raw in data.values()),
            key=lambda d: d.name,
        )


def is_alive(pid: int) -> bool:
    """Return True if a process with *pid* is currently running.

    Uses ``os.kill(pid, 0)`` (a signal-0 probe) which works on both Windows and
    POSIX without sending a real signal. On Windows, ``os.kill(pid, 0)`` raises
    ``OSError`` for a dead pid and succeeds for a live one.
    """
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def log_path_for(name: str) -> Path:
    """Return the log file path for a daemon (without creating it)."""
    return DAEMONS_DIR / f"{name}.log"

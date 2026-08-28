"""Detached daemon tool: start/status/logs/stop/list + registry round-trip."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import pytest

import novacode_cli.daemons.registry as reg
from novacode_cli.tools import daemon_tool

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture(autouse=True)
def _isolate_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point the registry at a temp dir so tests never touch ~/.nova."""
    monkeypatch.setattr(reg, "DAEMONS_DIR", tmp_path)
    monkeypatch.setattr(reg, "REGISTRY_PATH", tmp_path / "registry.json")
    # The tool imported log_path_for by name; patch both the module and the tool.
    monkeypatch.setattr(daemon_tool, "log_path_for", reg.log_path_for)


def _start(name: str, command: str) -> str:
    return daemon_tool.daemon.invoke({"action": "start", "name": name, "command": command})


def _sleep_cmd(tmp_path: Path) -> str:
    """A long-running command (python script file, no nested quotes)."""
    script = tmp_path / "sleep.py"
    script.write_text("import time; time.sleep(30)")
    return f"python -u {script}"


class TestStartStatusStop:
    def test_start_status_stop_roundtrip(self, tmp_path: Path):
        out = _start("sleeper", _sleep_cmd(tmp_path))
        assert "Started daemon" in out
        assert "pid" in out

        info = reg.get("sleeper")
        assert info is not None
        assert reg.is_alive(info.pid)

        status = daemon_tool.daemon.invoke({"action": "status", "name": "sleeper"})
        assert "running" in status

        stopped = daemon_tool.daemon.invoke({"action": "stop", "name": "sleeper"})
        assert "Stopped" in stopped
        assert reg.get("sleeper") is None

    def test_start_requires_command(self):
        out = daemon_tool.daemon.invoke({"action": "start", "name": "x"})
        assert "command is required" in out

    def test_start_requires_name(self):
        out = daemon_tool.daemon.invoke({"action": "start", "command": "echo hi"})
        assert "name is required" in out

    def test_unknown_action(self):
        out = daemon_tool.daemon.invoke({"action": "bogus", "name": "x"})
        assert "unknown action" in out


class TestListAndRegistry:
    def test_list_shows_registered(self, tmp_path: Path):
        _start("a", _sleep_cmd(tmp_path))
        _start("b", _sleep_cmd(tmp_path))
        out = daemon_tool.daemon.invoke({"action": "list"})
        assert "2 daemon(s)" in out
        assert "a" in out
        assert "b" in out

    def test_registry_roundtrip(self, tmp_path: Path):
        _start("persist", _sleep_cmd(tmp_path))
        # Simulate a restart: re-read from disk.
        reloaded = reg.list_daemons()
        names = [d.name for d in reloaded]
        assert "persist" in names

    def test_unregister_missing_returns_false(self):
        assert reg.unregister("nope") is False


class TestLogs:
    def test_logs_tail(self, tmp_path: Path):
        # A script that prints two lines then exits (no nested quotes).
        script = tmp_path / "logger.py"
        script.write_text("print('daemon line 1'); print('daemon line 2')")
        _start("logger", f"python -u {script}")
        # Give the daemon a moment to write.
        time.sleep(0.5)
        out = daemon_tool.daemon.invoke({"action": "logs", "name": "logger"})
        assert "daemon line 1" in out
        assert "daemon line 2" in out

    def test_logs_missing_daemon(self):
        out = daemon_tool.daemon.invoke({"action": "logs", "name": "ghost"})
        assert "not registered" in out

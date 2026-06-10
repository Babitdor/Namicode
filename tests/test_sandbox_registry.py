"""Tests for the sandbox registry — ownership/liveness store + reclaim dispatch."""

from __future__ import annotations

import os
import time

import pytest

from novacode_cli.integrations import sandbox_registry as reg


@pytest.fixture
def reg_dir(tmp_path, monkeypatch):
    """Point the registry at a temp dir so tests never touch real ~/.nova."""
    d = tmp_path / "sandboxes"
    d.mkdir()
    monkeypatch.setattr(reg, "_registry_dir", lambda: d)
    return d


# ── pid liveness ─────────────────────────────────────────────────────────────


class TestPidAlive:
    def test_self_is_alive(self):
        assert reg._pid_alive(os.getpid()) is True

    def test_bogus_pid_is_dead(self):
        assert reg._pid_alive(2_000_000_111) is False

    def test_zero_is_dead(self):
        assert reg._pid_alive(0) is False


# ── store round-trips ────────────────────────────────────────────────────────


class TestStore:
    def test_register_read_list(self, reg_dir):
        reg.register("box1", provider="docker", session_id="sessA", persist=True)
        rec = reg.read_record("box1")
        assert rec is not None
        assert rec["provider"] == "docker"
        assert rec["session_id"] == "sessA"
        assert rec["persist"] is True
        assert rec["pid"] == os.getpid()
        assert [r["sandbox_id"] for r in reg.list_records()] == ["box1"]

    def test_heartbeat_advances(self, reg_dir):
        reg.register("box1", provider="docker", session_id="sessA")
        rec = reg.read_record("box1")
        rec["heartbeat_ts"] = 0.0
        reg._write_record("box1", rec)
        reg.heartbeat("box1")
        assert reg.read_record("box1")["heartbeat_ts"] > 0.0

    def test_retie_changes_only_session(self, reg_dir):
        reg.register("box1", provider="docker", session_id="sessA", persist=True)
        reg.retie("box1", "sessB")
        rec = reg.read_record("box1")
        assert rec["session_id"] == "sessB"
        assert rec["provider"] == "docker"
        assert rec["persist"] is True

    def test_deregister(self, reg_dir):
        reg.register("box1", provider="docker", session_id="sessA")
        reg.deregister("box1")
        assert reg.read_record("box1") is None
        assert reg.list_records() == []


# ── dead detection ───────────────────────────────────────────────────────────


def _make_record(reg_dir, sandbox_id, *, pid, heartbeat_age, **extra):
    reg.register(sandbox_id, provider="docker", session_id="s", **extra)
    rec = reg.read_record(sandbox_id)
    rec["pid"] = pid
    rec["heartbeat_ts"] = time.time() - heartbeat_age
    reg._write_record(sandbox_id, rec)


class TestDeadRecords:
    def test_live_owner_not_dead(self, reg_dir):
        _make_record(reg_dir, "live", pid=os.getpid(), heartbeat_age=0)
        assert reg.dead_records() == []

    def test_dead_pid_and_stale_is_dead(self, reg_dir):
        _make_record(reg_dir, "crashed", pid=2_000_000_111, heartbeat_age=999)
        dead = reg.dead_records()
        assert [r["sandbox_id"] for r in dead] == ["crashed"]

    def test_dead_pid_but_fresh_heartbeat_not_dead(self, reg_dir):
        # Heartbeat fresh ⇒ a very-recently-departed owner isn't reclaimed yet.
        _make_record(reg_dir, "recent", pid=2_000_000_111, heartbeat_age=1)
        assert reg.dead_records() == []

    def test_hard_stale_is_dead_regardless_of_pid(self, reg_dir):
        # Even if the pid probe says alive (current pid), a very old record is gone.
        _make_record(reg_dir, "ancient", pid=os.getpid(), heartbeat_age=10_000)
        assert [r["sandbox_id"] for r in reg.dead_records()] == ["ancient"]

    def test_exclude_pid_skips_current(self, reg_dir):
        _make_record(reg_dir, "mine", pid=os.getpid(), heartbeat_age=10_000)
        assert reg.dead_records(exclude_pid=os.getpid()) == []


# ── reclaim dispatch ─────────────────────────────────────────────────────────


class TestReclaim:
    def test_reclaims_dead_and_deregisters(self, reg_dir, monkeypatch):
        terminated: list[str] = []
        monkeypatch.setattr(
            reg,
            "_terminate_record",
            lambda rec: terminated.append(rec["sandbox_id"]) or True,
        )
        _make_record(reg_dir, "dead", pid=2_000_000_111, heartbeat_age=999)
        _make_record(reg_dir, "live", pid=os.getpid(), heartbeat_age=0)

        reclaimed = reg.reclaim_dead_sandboxes(exclude_pid=os.getpid())

        assert reclaimed == ["dead"]
        assert terminated == ["dead"]
        assert reg.read_record("dead") is None  # deregistered
        assert reg.read_record("live") is not None  # untouched

    def test_failed_terminate_keeps_record(self, reg_dir, monkeypatch):
        monkeypatch.setattr(reg, "_terminate_record", lambda rec: False)
        _make_record(reg_dir, "stuck", pid=2_000_000_111, heartbeat_age=999)
        assert reg.reclaim_dead_sandboxes(exclude_pid=os.getpid()) == []
        assert reg.read_record("stuck") is not None  # not dropped on failure

    def test_terminate_owned(self, reg_dir, monkeypatch):
        terminated: list[str] = []
        monkeypatch.setattr(
            reg,
            "_terminate_record",
            lambda rec: terminated.append(rec["sandbox_id"]) or True,
        )
        reg.register("mine", provider="docker", session_id="s")  # current pid
        _make_record(reg_dir, "other", pid=2_000_000_111, heartbeat_age=1)

        reg.terminate_owned()

        assert terminated == ["mine"]
        assert reg.read_record("mine") is None
        assert reg.read_record("other") is not None  # different owner, untouched

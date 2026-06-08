"""Tests for not orphaning sandboxes when a session saves nothing.

A fresh Docker sandbox is created with persist=True so a later resume can
reconnect. But if the user exits immediately (no turns → nothing saved), the
persisted container would be orphaned forever. The caller vetoes persistence by
setting ``_nova_discard_on_exit`` so create_docker_sandbox removes it on exit.
"""

from __future__ import annotations

from datetime import UTC, datetime

from novacode_cli.integrations import sandbox_factory
from novacode_cli.integrations.sandbox_factory import (
    _cleanup_stale_docker_containers,
    _keep_sandbox_on_exit,
)


class _FakeContainer:
    def __init__(self, cid, session, status, *, created=None):
        self.id = cid
        self.status = status
        self.labels = {"nova.managed": "1", "nova.session": session}
        self.attrs = {"Created": (created or datetime.now(UTC).isoformat())}
        self.removed = False

    def remove(self, force=False):  # noqa: FBT002, ARG002
        self.removed = True


class _FakeClient:
    def __init__(self, conts):
        self._conts = conts
        self.containers = self

    def list(self, all=False, filters=None):  # noqa: A002, ARG002, FBT002
        return self._conts


class _Backend:
    pass


def test_persist_kept_by_default():
    assert _keep_sandbox_on_exit(persist=True, backend=_Backend()) is True


def test_persist_vetoed_by_discard_flag():
    b = _Backend()
    b._nova_discard_on_exit = True  # caller saw an empty session
    assert _keep_sandbox_on_exit(persist=True, backend=b) is False


def test_non_persist_never_kept():
    assert _keep_sandbox_on_exit(persist=False, backend=_Backend()) is False
    b = _Backend()
    b._nova_discard_on_exit = True
    assert _keep_sandbox_on_exit(persist=False, backend=b) is False


def test_cleanup_removes_stopped_orphans_only(monkeypatch):
    monkeypatch.setattr(sandbox_factory, "_saved_session_ids", lambda: {"valid"})

    orphan_stopped = _FakeContainer("c1", "gone", "exited")      # remove
    orphan_running = _FakeContainer("c2", "gone", "running")     # keep (live)
    valid_stopped = _FakeContainer("c3", "valid", "exited")      # keep (saved)
    conts = [orphan_stopped, orphan_running, valid_stopped]

    _cleanup_stale_docker_containers(_FakeClient(conts))

    assert orphan_stopped.removed is True
    assert orphan_running.removed is False
    assert valid_stopped.removed is False


def test_cleanup_removes_stale_by_age(monkeypatch):
    monkeypatch.setattr(sandbox_factory, "_saved_session_ids", lambda: {"valid"})
    old = _FakeContainer("c4", "valid", "exited", created="2000-01-01T00:00:00.000000Z")
    _cleanup_stale_docker_containers(_FakeClient([old]), max_age_days=30)
    assert old.removed is True


def test_cleanup_never_removes_keep_id(monkeypatch):
    monkeypatch.setattr(sandbox_factory, "_saved_session_ids", lambda: set())
    keep = _FakeContainer("keepme", "gone", "exited")
    _cleanup_stale_docker_containers(_FakeClient([keep]), keep_id="keepme")
    assert keep.removed is False

"""Session leases — durable, TTL-based cross-process turn ownership.

Covers the ``SessionLease`` primitive (acquire/renew/release/get/stale), the
``lease_session`` async context manager (acquire on entry, release on exit, even
on exception), and the holder identity format.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from novacode_cli.sessions import lease as lease_mod


class FakeStore:
    """Minimal async store stand-in (same shape as other Hermes tests)."""

    def __init__(self) -> None:
        self.data: dict[tuple, dict] = {}

    async def aget(self, namespace: tuple, key: str) -> SimpleNamespace | None:
        ns = self.data.get(tuple(namespace), {})
        return SimpleNamespace(value=dict(ns[key])) if key in ns else None

    async def aput(self, namespace: tuple, key: str, value: dict) -> None:
        self.data.setdefault(tuple(namespace), {})[key] = dict(value)

    async def adelete(self, namespace: tuple, key: str) -> None:
        self.data.get(tuple(namespace), {}).pop(key, None)


def _lease(store: FakeStore | None = None) -> lease_mod.SessionLease:
    return lease_mod.SessionLease(store or FakeStore())


# ── holder identity ─────────────────────────────────────────────────────────


class TestLeaseHolder:
    def test_format(self) -> None:
        h = lease_mod.lease_holder("worker")
        assert h.startswith("pid:")
        assert h.endswith(":worker")


# ── SessionLease primitive ─────────────────────────────────────────────────


class TestSessionLease:
    async def test_acquire_then_get(self) -> None:
        store = FakeStore()
        lease = _lease(store)
        info = await lease.acquire("t1", "pid:1:worker", ttl=300.0)
        assert info.thread_id == "t1"
        assert info.holder == "pid:1:worker"
        assert info.expires_at > info.acquired_at

        got = await lease.get("t1")
        assert got is not None
        assert got.holder == "pid:1:worker"

    async def test_acquire_while_held_by_other_raises(self) -> None:
        lease = _lease()
        await lease.acquire("t1", "pid:1:worker", ttl=300.0)
        with pytest.raises(lease_mod.LeaseHeldError):
            await lease.acquire("t1", "pid:2:worker", ttl=300.0)

    async def test_acquire_after_expiry_takes_over(self, monkeypatch: pytest.MonkeyPatch) -> None:
        now = 1_000.0
        monkeypatch.setattr(lease_mod.time, "time", lambda: now)
        lease = _lease()
        await lease.acquire("t1", "pid:1:worker", ttl=10.0)  # expires at 1010

        monkeypatch.setattr(lease_mod.time, "time", lambda: now + 20.0)  # now 1020 > 1010
        info = await lease.acquire("t1", "pid:2:worker", ttl=10.0)
        assert info.holder == "pid:2:worker"  # stale lease taken over

    async def test_renew_by_holder_extends(self, monkeypatch: pytest.MonkeyPatch) -> None:
        now = 1_000.0
        monkeypatch.setattr(lease_mod.time, "time", lambda: now)
        lease = _lease()
        await lease.acquire("t1", "pid:1:worker", ttl=10.0)
        before = (await lease.get("t1")).expires_at

        monkeypatch.setattr(lease_mod.time, "time", lambda: now + 5.0)
        assert await lease.renew("t1", "pid:1:worker") is True
        after = (await lease.get("t1")).expires_at
        assert after > before  # extended

    async def test_renew_by_non_holder_returns_false(self) -> None:
        lease = _lease()
        await lease.acquire("t1", "pid:1:worker", ttl=300.0)
        assert await lease.renew("t1", "pid:2:worker") is False

    async def test_release_by_holder_deletes(self) -> None:
        lease = _lease()
        await lease.acquire("t1", "pid:1:worker", ttl=300.0)
        assert await lease.release("t1", "pid:1:worker") is True
        assert await lease.get("t1") is None

    async def test_release_by_non_holder_returns_false(self) -> None:
        lease = _lease()
        await lease.acquire("t1", "pid:1:worker", ttl=300.0)
        assert await lease.release("t1", "pid:2:worker") is False
        assert (await lease.get("t1")).holder == "pid:1:worker"  # untouched

    async def test_is_stale(self) -> None:
        info = lease_mod.LeaseInfo("t1", "pid:1:worker", 0.0, expires_at=100.0, ttl=10.0)
        assert lease_mod.SessionLease.is_stale(info, now=101.0)
        assert not lease_mod.SessionLease.is_stale(info, now=99.0)


# ── lease_session context manager ───────────────────────────────────────────


class TestLeaseSession:
    async def test_acquires_and_releases(self) -> None:
        store = FakeStore()
        lease = lease_mod.SessionLease(store)
        async with lease_mod.lease_session("t1", "pid:1:tui", store=store):
            assert (await lease.get("t1")).holder == "pid:1:tui"
        assert await lease.get("t1") is None  # released on exit

    async def test_releases_on_exception(self) -> None:
        store = FakeStore()
        lease = lease_mod.SessionLease(store)
        boom = RuntimeError("boom")
        with pytest.raises(RuntimeError):
            async with lease_mod.lease_session("t1", "pid:1:tui", store=store):
                raise boom
        assert await lease.get("t1") is None  # released despite the exception

    async def test_conflict_runs_unleased(self) -> None:
        store = FakeStore()
        lease = lease_mod.SessionLease(store)
        await lease.acquire("t1", "pid:9:other", ttl=300.0)
        # A held lease must not block the turn — the block still runs.
        async with lease_mod.lease_session("t1", "pid:1:tui", store=store) as info:
            assert info is None  # unleased
        assert (await lease.get("t1")).holder == "pid:9:other"  # other's lease intact

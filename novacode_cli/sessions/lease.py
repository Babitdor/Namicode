"""Durable, TTL-based session leases — cross-process turn ownership.

A lease grants one holder (a process + entry point) exclusive, time-bounded
ownership of a session thread. It lives in the durable store
(``~/.nova/store.db`` via :func:`novacode_cli.memory.store.get_durable_store`),
so it is visible across processes: the TUI, the REPL, the remote bridge, the
FastAPI server, and spawned session workers all see the same lease state.

Why: Nova has several entry points that can drive the same session. In-process
locks (``_remote_message_lock``) serialize turns within one process, but nothing
guards against two *processes* running turns on the same thread concurrently
(checkpointer corruption), and nothing marks a session whose owning process
crashed mid-turn. A lease with a TTL + holder PID solves both: a live lease
rejects concurrent acquisition; an expired lease (holder died) can be taken
over.

The lease is an *ownership marker*, not a hard lock: the turn entry points
acquire it best-effort and proceed unleased on conflict, so a lease can never
block a turn. The state is authoritative for inspection, crash recovery, and
the session supervisor's cleanup.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import time
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

logger = logging.getLogger(__name__)

#: Store namespace for all session leases.
_NS = ("nova", "session_leases")

#: Default lease duration (seconds). A turn outliving this is kept alive by the
#: heartbeat; a dead process's heartbeat dies with it, so the lease expires and
#: the session becomes takeable.
DEFAULT_TTL = 300.0

#: How often the heartbeat renews the lease during a turn.
DEFAULT_RENEW_INTERVAL = 60.0


@dataclass
class LeaseInfo:
    """A session lease as stored/returned.

    Attributes:
        thread_id: The session thread the lease guards.
        holder: ``"pid:<pid>:<entry>"`` — who owns the lease.
        acquired_at: Epoch seconds when the lease was acquired.
        expires_at: Epoch seconds when the lease lapses (stale).
        ttl: Lease duration in seconds.
    """

    thread_id: str
    holder: str
    acquired_at: float
    expires_at: float
    ttl: float


class LeaseHeldError(Exception):
    """The session is currently leased by another live holder."""


def lease_holder(entry: str) -> str:
    """Build the holder identity for this process and entry point.

    Args:
        entry: One of ``"tui"``, ``"repl"``, ``"worker"``, ``"server"``.

    Returns:
        ``"pid:<pid>:<entry>"`` — unique per process + entry point.
    """
    return f"pid:{os.getpid()}:{entry}"


def _info_from_item(item: Any) -> LeaseInfo:  # noqa: ANN401
    """Rehydrate a :class:`LeaseInfo` from a store item (``item.value`` dict)."""
    return LeaseInfo(**dict(item.value))


class SessionLease:
    """Durable lease operations over the shared store.

    All methods are async (the store's async API runs the sync SQLite store in
    a worker thread). The check-then-set ``acquire`` has a tiny cross-process
    race window (two processes reading "no lease" simultaneously); the
    consequence is the same as having no lease at all, so it is strictly
    better than nothing, and the TTL + holder PID make stale takeover safe.
    """

    def __init__(self, store: Any = None) -> None:  # noqa: ANN401
        """Initialize with the durable store (defaults to the shared one)."""
        if store is None:
            from novacode_cli.memory.store import get_durable_store

            store = get_durable_store()
        self._store = store

    async def acquire(self, thread_id: str, holder: str, ttl: float = DEFAULT_TTL) -> LeaseInfo:
        """Claim the session for ``holder`` for ``ttl`` seconds.

        Raises:
            LeaseHeldError: A live lease (not expired) is held by another holder.
        """
        now = time.time()
        item = await self._store.aget(_NS, thread_id)
        if item is not None:
            info = _info_from_item(item)
            if info.expires_at > now and info.holder != holder:
                msg = f"session {thread_id} leased by {info.holder}"
                raise LeaseHeldError(msg)
        info = LeaseInfo(
            thread_id=thread_id,
            holder=holder,
            acquired_at=now,
            expires_at=now + ttl,
            ttl=ttl,
        )
        await self._store.aput(_NS, thread_id, asdict(info))
        return info

    async def renew(self, thread_id: str, holder: str, ttl: float | None = None) -> bool:
        """Extend the lease's expiry. Only the current holder may renew."""
        item = await self._store.aget(_NS, thread_id)
        if item is None:
            return False
        info = _info_from_item(item)
        if info.holder != holder:
            return False
        info.ttl = ttl if ttl is not None else info.ttl
        info.expires_at = time.time() + info.ttl
        await self._store.aput(_NS, thread_id, asdict(info))
        return True

    async def release(self, thread_id: str, holder: str) -> bool:
        """Drop the lease. Only the current holder may release."""
        item = await self._store.aget(_NS, thread_id)
        if item is None:
            return False
        info = _info_from_item(item)
        if info.holder != holder:
            return False
        await self._store.adelete(_NS, thread_id)
        return True

    async def get(self, thread_id: str) -> LeaseInfo | None:
        """Return the current lease for the session, or ``None``."""
        item = await self._store.aget(_NS, thread_id)
        if item is None:
            return None
        return _info_from_item(item)

    @staticmethod
    def is_stale(info: LeaseInfo, now: float | None = None) -> bool:
        """True when the lease has lapsed (holder may be dead)."""
        return info.expires_at < (now if now is not None else time.time())


@asynccontextmanager
async def lease_session(
    thread_id: str,
    holder: str,
    *,
    ttl: float = DEFAULT_TTL,
    renew_interval: float = DEFAULT_RENEW_INTERVAL,
    store: Any = None,  # noqa: ANN401 — injectable for tests; defaults to the shared store
) -> AsyncIterator[LeaseInfo | None]:
    """Acquire a session lease for the duration of an ``async with`` block.

    A background heartbeat renews the lease every ``renew_interval`` seconds so
    long turns stay owned; the heartbeat stops and the lease is released in a
    ``finally`` (even on exception). On ``LeaseHeldError`` the block still runs
    unleased (best-effort — a lease must never block a turn); the conflict is
    logged.
    """
    lease = SessionLease(store)
    try:
        info = await lease.acquire(thread_id, holder, ttl)
    except LeaseHeldError:
        logger.warning("session %s already leased — running turn unleased", thread_id)
        yield None
        return

    stop = asyncio.Event()

    async def _heartbeat() -> None:
        while not stop.is_set():
            await asyncio.sleep(renew_interval)
            try:
                await lease.renew(thread_id, holder, ttl)
            except Exception:  # noqa: BLE001 — a failed renewal must not kill the turn
                logger.debug("lease renewal failed for %s", thread_id, exc_info=True)

    hb = asyncio.create_task(_heartbeat())
    try:
        yield info
    finally:
        stop.set()
        hb.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await hb
        with contextlib.suppress(Exception):
            await lease.release(thread_id, holder)

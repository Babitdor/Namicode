"""Durable, process-lifetime LangGraph store for cross-session agent memory.

Nova's filesystem ``/memories/`` route already persists markdown memory on disk.
This module adds the *other* half the deep-agents memory model expects: a durable
LangGraph ``BaseStore`` for **structured, key/value, cross-session** memory
(``store.put`` / ``store.get`` / ``store.search``).

Previously Nova passed an :class:`~langgraph.store.memory.InMemoryStore` to
``create_deep_agent`` — non-durable, lost on every restart (the deep-agents
``fix-production-store`` anti-pattern). Here we back the store with
:class:`~langgraph.store.sqlite.SqliteStore` at ``~/.nova/store.db`` so anything
the agent (or its subagents) writes via the store survives restarts.

The store is opened once and kept alive for the whole process — ``from_conn_string``
is a context manager that would close the connection on exit, so we construct the
store directly from a long-lived ``sqlite3`` connection (mirroring how
``main.py`` builds the SQLite checkpointer) and close it at interpreter exit.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from novacode_cli.config.config import HOME_DIR, console

if TYPE_CHECKING:
    from langgraph.store.base import BaseStore

# Process-lifetime singleton. Built lazily on first request and reused so the
# agent and all its subagents share one durable store.
_store: "BaseStore | None" = None


def get_durable_store() -> "BaseStore":
    """Return the shared, durable LangGraph store (creating it on first call).

    Falls back to an in-memory store if SQLite-backed storage can't be
    initialised, so a packaging/permissions problem degrades memory to
    ephemeral rather than crashing startup.
    """
    global _store
    if _store is not None:
        return _store

    try:
        import sqlite3

        from langgraph.store.sqlite import SqliteStore

        db_path = HOME_DIR / "store.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db_path), check_same_thread=False, isolation_level=None)
        store = SqliteStore(conn)
        store.setup()
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        _store = store
    except Exception:  # noqa: BLE001
        from langgraph.store.memory import InMemoryStore

        console.print("[yellow]⚠ Durable memory store unavailable; falling back to in-memory.[/yellow]")
        _store = InMemoryStore()

    return _store


__all__ = ["get_durable_store"]

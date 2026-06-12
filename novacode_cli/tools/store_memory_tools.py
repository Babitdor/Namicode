"""Structured, cross-session memory tools backed by the durable LangGraph store.

These complement the markdown file memory (``write_memory`` / ``read_memory``,
which inject whole files into the system prompt). Where those are good for prose
the model should always see, these tools provide **structured key/value recall**
the model fetches on demand:

    remember(key, content, tags=...)   → store a fact under a key
    recall(key)                        → fetch one fact by key
    list_memories(query=..., tag=...)  → browse / search stored facts
    forget(key)                        → delete a fact

Entries live in the process-wide durable store (SQLite at ``~/.nova/store.db`` —
see :mod:`novacode_cli.memory.store`), so they persist across sessions AND are
shared across the main agent and every subagent in the run (with author
attribution), which is exactly what the subagent prompts already assume.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from langchain.tools import ToolRuntime, tool

# Single shared namespace so memories are visible across agents, subagents, and
# sessions. Scope (project vs global) is recorded as metadata, not baked into the
# namespace, so the model can recall everything and filter when it wants to.
_NAMESPACE: tuple[str, ...] = ("nova_memory",)


def _author() -> str:
    """Best-effort identifier of the agent writing the memory (for attribution)."""
    try:
        from novacode_cli.config.config import MAIN_AGENT_ID

        return MAIN_AGENT_ID or "nova"
    except Exception:  # noqa: BLE001
        return "nova"


def _project_key() -> str | None:
    """Current project root (so memories can note where they were learned)."""
    try:
        from novacode_cli.config.config import settings

        return str(settings.project_root) if settings.project_root else None
    except Exception:  # noqa: BLE001
        return None


def _item_to_dict(item: Any) -> dict[str, Any]:
    """Flatten a store Item into a JSON-friendly dict for the model."""
    value = getattr(item, "value", {}) or {}
    return {
        "key": getattr(item, "key", None),
        "content": value.get("content", ""),
        "tags": value.get("tags", []),
        "category": value.get("category", "general"),
        "author": value.get("author"),
        "project": value.get("project"),
        "updated_at": value.get("updated_at_iso"),
    }


@tool
def remember(
    key: str,
    content: str,
    runtime: ToolRuntime,
    tags: list[str] | None = None,
    category: str = "general",
) -> dict[str, Any]:
    """Save a structured fact to durable, cross-session memory under a key.

    Use this for discrete, reusable facts the agent should be able to look up
    later by key or tag — e.g. an architecture decision, a build command, a
    user's name, an API quirk. Persists across sessions and is shared with
    subagents. For long prose that should always be in context, prefer
    ``write_memory`` (markdown files) instead.

    Args:
        key: Short, stable identifier for the fact (e.g. "build-command",
            "db-schema-notes"). Re-using a key overwrites the prior value.
        content: The fact to remember (plain text or markdown).
        tags: Optional labels for later filtering (e.g. ["ci", "deploy"]).
        category: Optional grouping (default "general").

    Returns:
        Dict with success flag, the stored key, and a short message.
    """
    store = getattr(runtime, "store", None)
    if store is None:
        return {"success": False, "error": "No memory store available in this run."}

    now = time.time()
    value = {
        "content": content,
        "tags": list(tags or []),
        "category": category,
        "author": _author(),
        "project": _project_key(),
        "updated_at": now,
        "updated_at_iso": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    try:
        store.put(_NAMESPACE, key, value)
    except Exception as e:  # noqa: BLE001
        return {"success": False, "error": f"Failed to store memory: {e}", "key": key}

    return {
        "success": True,
        "key": key,
        "category": category,
        "message": f"Remembered '{key}' (category: {category}).",
    }


@tool
def recall(key: str, runtime: ToolRuntime) -> dict[str, Any]:
    """Fetch a single fact from durable memory by its exact key.

    Args:
        key: The key the fact was stored under via ``remember``.

    Returns:
        Dict with the fact (content, tags, category, author, when it was
        updated) or ``found: False`` if no such key exists.
    """
    store = getattr(runtime, "store", None)
    if store is None:
        return {"success": False, "error": "No memory store available in this run."}

    try:
        item = store.get(_NAMESPACE, key)
    except Exception as e:  # noqa: BLE001
        return {"success": False, "error": f"Failed to read memory: {e}", "key": key}

    if item is None:
        return {"success": True, "found": False, "key": key, "message": "No memory under that key."}

    return {"success": True, "found": True, **_item_to_dict(item)}


@tool
def list_memories(
    runtime: ToolRuntime,
    query: str | None = None,
    tag: str | None = None,
    category: str | None = None,
    limit: int = 25,
) -> dict[str, Any]:
    """List or search stored facts in durable memory.

    Call this to recall what you've learned in previous sessions before asking
    the user or re-deriving something. With no arguments it returns the most
    recent memories; pass ``query``/``tag``/``category`` to narrow down.

    Args:
        query: Case-insensitive substring matched against key, content, and tags.
        tag: Only return memories carrying this exact tag.
        category: Only return memories in this category.
        limit: Max number of memories to return (default 25).

    Returns:
        Dict with a ``memories`` list (each: key, content, tags, category,
        author, updated_at) and a ``count``.
    """
    store = getattr(runtime, "store", None)
    if store is None:
        return {"success": False, "error": "No memory store available in this run."}

    try:
        # Over-fetch so post-filtering can still fill up to `limit`.
        items = store.search(_NAMESPACE, limit=max(limit * 4, limit))
    except Exception as e:  # noqa: BLE001
        return {"success": False, "error": f"Failed to search memory: {e}"}

    q = query.lower().strip() if query else None
    results: list[dict[str, Any]] = []
    for item in items:
        rec = _item_to_dict(item)
        if category and rec.get("category") != category:
            continue
        if tag and tag not in (rec.get("tags") or []):
            continue
        if q:
            haystack = " ".join(
                [
                    str(rec.get("key") or ""),
                    str(rec.get("content") or ""),
                    " ".join(rec.get("tags") or []),
                ]
            ).lower()
            if q not in haystack:
                continue
        results.append(rec)
        if len(results) >= limit:
            break

    return {"success": True, "count": len(results), "memories": results}


@tool
def forget(key: str, runtime: ToolRuntime) -> dict[str, Any]:
    """Delete a fact from durable memory by key.

    Args:
        key: The key to remove. Safe to call even if the key doesn't exist.

    Returns:
        Dict with a success flag and a short message.
    """
    store = getattr(runtime, "store", None)
    if store is None:
        return {"success": False, "error": "No memory store available in this run."}

    try:
        store.delete(_NAMESPACE, key)
    except Exception as e:  # noqa: BLE001
        return {"success": False, "error": f"Failed to delete memory: {e}", "key": key}

    return {"success": True, "key": key, "message": f"Forgot '{key}'."}


__all__ = ["remember", "recall", "list_memories", "forget"]

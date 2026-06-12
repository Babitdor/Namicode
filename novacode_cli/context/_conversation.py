"""Recent-conversation digest from agent state.

Private to the ``context`` package. Used by long-running commands (/research,
/ralph) so the task they kick off is grounded in what was already discussed with
the core agent — including for the subagents they spawn, which otherwise run on
fresh threads with no history. Surfaced through ``ContextManager.digest``.
"""

from __future__ import annotations

from typing import Any


def _message_text(msg: Any) -> str:
    """Extract plain text from a LangChain message's content (str or blocks)."""
    content = getattr(msg, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    parts.append(block.get("text", ""))
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(parts)
    return str(content)


async def get_recent_conversation_digest(
    agent: Any,
    thread_id: str,
    *,
    max_turns: int = 10,
    max_chars: int = 4000,
) -> str:
    """Return a compact transcript of the most recent user/assistant turns.

    Reads the agent's checkpointed state for ``thread_id`` and formats the last
    ``max_turns`` Human/AI turns (tool noise skipped) into a bounded text block.
    Returns an empty string if there's no history or the state can't be read.
    """
    config = {"configurable": {"thread_id": thread_id}}
    try:
        state = await agent.aget_state(config)
    except Exception:  # noqa: BLE001
        return ""

    values = getattr(state, "values", None) or {}
    messages = values.get("messages", []) or []
    if not messages:
        return ""

    turns: list[str] = []
    for msg in messages:
        role = getattr(msg, "type", "") or ""
        if role not in ("human", "ai"):
            continue
        text = _message_text(msg).strip()
        if not text:
            continue
        speaker = "User" if role == "human" else "Assistant"
        turns.append(f"{speaker}: {text}")

    if not turns:
        return ""

    turns = turns[-max_turns:]
    digest = "\n\n".join(turns)
    if len(digest) > max_chars:
        digest = "…(earlier turns trimmed)…\n\n" + digest[-max_chars:]
    return digest

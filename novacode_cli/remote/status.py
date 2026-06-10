"""Remote status line — a single compact, throttled 'agent is working' message.

The answer to a remote turn flows as a normal chat message (sent via
``reply_fn``). This module owns a *separate*, tiny status message that edits in
place to show the agent is actively working — condensed to category counts so
it never floods or scrolls:

    ⚙️ working…
    ⚙️ read×4, edit×2, 🤖 subagent×1
    ✅ 9 tools · read×4, edit×3, run×2     (finalized)

Only the status line edits; the answer is always a fresh message. Edits are
coalesced to ~1.3s so a burst of tool calls is one Discord-safe edit. Needs only
an async ``edit_fn(text, final=False)`` — which the Discord/Telegram bridges
provide — so both platforms behave identically.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from novacode_cli.remote.bridge import categorize_tools

logger = logging.getLogger(__name__)

EditFn = Callable[..., Awaitable[None]]  # edit_fn(text, final=False)

_PUMP_INTERVAL = 1.3
_WORKING = "⚙️ working…"
# Todo status -> glyph for the live plan checklist.
_TODO_GLYPH: dict[str, str] = {
    "completed": "✅",
    "in_progress": "▶️",
    "pending": "☐",
}
_TODO_MAX = 8


class RemoteStatusLine:
    """One edit-in-place status message showing condensed live tool activity."""

    def __init__(self, edit_fn: EditFn, *, interval: float = _PUMP_INTERVAL) -> None:
        self._edit = edit_fn
        self._names: list[str] = []
        self._todos: list[tuple[str, str]] = []  # (content, status)
        self._dirty = False
        self._interval = interval
        self._task: asyncio.Task | None = None
        self._closed = False

    def note(self, name: str) -> None:
        """Record a tool/subagent name (``task`` → 🤖 subagent). No network call."""
        if name:
            self._names.append(str(name))
            self._dirty = True

    def note_todos(self, todos: list) -> None:
        """Set the current plan/checklist (TodoWrite). Shown live, in place."""
        parsed: list[tuple[str, str]] = []
        for td in todos or []:
            if isinstance(td, dict):
                content = str(td.get("content", "")).strip()
                if content:
                    parsed.append((content, td.get("status", "pending")))
        self._todos = parsed
        self._dirty = True

    def _summary(self) -> str:
        return categorize_tools(self._names)

    def _todo_lines(self) -> list[str]:
        shown = self._todos[:_TODO_MAX]
        lines = [f"{_TODO_GLYPH.get(status, '☐')} {content}" for content, status in shown]
        extra = len(self._todos) - len(shown)
        if extra > 0:
            lines.append(f"… +{extra} more")
        return lines

    def _content(self) -> str:
        # The plan (when present) on top, the condensed tool activity beneath.
        lines = self._todo_lines() if self._todos else []
        summary = self._summary()
        if summary:
            lines.append(f"⚙️ {summary}")
        return "\n".join(lines) if lines else _WORKING

    def start(self) -> None:
        """Begin the coalescing pump (idempotent)."""
        if self._task is None:
            self._task = asyncio.create_task(self._pump())

    async def _pump(self) -> None:
        last: str | None = None
        try:
            first = self._content()
            await self._edit(first, False)  # immediate first paint
            last = first
        except Exception:  # noqa: BLE001
            logger.debug("status first paint failed", exc_info=True)
        self._dirty = False
        try:
            while not self._closed:
                await asyncio.sleep(self._interval)
                if not self._dirty:
                    continue
                self._dirty = False
                content = self._content()
                if content != last:
                    last = content
                    try:
                        await self._edit(content, False)
                    except Exception:  # noqa: BLE001 — a dropped edit is non-fatal
                        logger.debug("status edit failed", exc_info=True)
        except asyncio.CancelledError:
            return

    async def finalize(self) -> None:
        """Stop the pump and settle the status to a compact done-summary."""
        self._closed = True
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._task = None

        summary = self._summary()
        total = len([n for n in self._names if n])
        plural = "s" if total != 1 else ""
        done = f"✅ {total} tool{plural} · {summary}" if summary else "✅ done"
        # Keep the (now-complete) plan visible above the done-summary so the final
        # status reflects what got accomplished.
        lines = self._todo_lines() if self._todos else []
        text = "\n".join([*lines, done]) if lines else done
        try:
            await self._edit(text, True)
        except Exception:  # noqa: BLE001
            logger.debug("status finalize failed", exc_info=True)

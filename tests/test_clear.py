"""/clear must fully reset conversation context — including attached images and
pending background-task notes — not just the message history."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace


class _FakeAgent:
    async def aget_state(self, config):
        return SimpleNamespace(values={"messages": []})


async def _drive() -> None:
    from novacode_cli.input_utils import ImageTracker
    from novacode_cli.states.Session import SessionState
    from novacode_cli.tui.app import NovaApp
    from novacode_cli.ui.ui_elements import TokenTracker

    ss = SessionState()
    tracker = ImageTracker()
    app = NovaApp(
        agent=_FakeAgent(),
        assistant_id="nova-agent",
        session_state=ss,
        backend=None,
        token_tracker=TokenTracker(),
        image_tracker=tracker,
        model_name="m",
        session_manager=None,
    )

    async with app.run_test():
        # Simulate leftover conversation context.
        tracker._images["img1"] = object()  # a tracked image
        app._pending_job_notes.append("Background task_41 finished (exit 0).")
        old_thread = ss.thread_id

        await app._run_clear()

        # New conversation identity (fresh checkpointer state).
        assert ss.thread_id != old_thread
        # Leaks fixed: images and pending notes gone.
        assert tracker.get_images() == []
        assert app._pending_job_notes == []
        # Carried-over context cleared by reset_conversation.
        assert ss.todos is None
        assert not ss.steering_instructions


def test_clear_resets_images_and_pending_notes() -> None:
    try:
        import textual  # noqa: F401
    except ImportError:
        return
    asyncio.run(_drive())

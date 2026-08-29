"""The compaction summary must never replay as a user turn.

``compact_conversation`` rewrites the whole conversation into ONE synthetic
HumanMessage carrying the summary. It has to be a HumanMessage for provider
turn-ordering, but the user never typed it — so replaying history verbatim
showed the entire summarized context in the transcript as though they had.
"""

from __future__ import annotations

import asyncio

from langchain_core.messages import AIMessage, HumanMessage

from novacode_cli.compaction import COMPACTION_SUMMARY_MARKER, is_compaction_summary

NL = chr(10)

try:
    import textual  # noqa: F401

    _HAS_TEXTUAL = True
except ImportError:  # pragma: no cover
    _HAS_TEXTUAL = False


def test_marker_is_recognized():
    body = COMPACTION_SUMMARY_MARKER + NL * 2 + "We fixed the glob bug."
    assert is_compaction_summary(body)
    assert is_compaction_summary("   " + body), "leading whitespace should not defeat it"


def test_ordinary_messages_are_not_mistaken_for_it():
    for text in (
        "Can you summarize the previous session?",
        "The conversation context was getting long.",
        "[note] previous session was about globbing",
    ):
        assert not is_compaction_summary(text), text


async def _drive_replay_skips_the_summary():
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).parent))
    from test_tui_app import _FakeAgent, _SS

    from novacode_cli.tui.app import NovaApp
    from novacode_cli.ui.ui_elements import TokenTracker

    app = NovaApp(
        agent=_FakeAgent(), assistant_id="nova-agent", session_state=_SS(),
        backend=None, token_tracker=TokenTracker(), image_tracker=None,
        model_name="m",
    )
    async with app.run_test(size=(100, 30)) as pilot:
        seen: list[str] = []
        original = app._add_message

        async def spy(label, kind, body):
            seen.append(getattr(body, "markup", None) or str(body))
            return await original(label, kind, body)

        app._add_message = spy
        app._restored_messages = [
            HumanMessage(content=COMPACTION_SUMMARY_MARKER + NL * 2 + "summarized context"),
            HumanMessage(content="a real question"),
            AIMessage(content="a real answer"),
        ]
        app._replay_history()
        await app.workers.wait_for_complete()
        for _ in range(3):
            await pilot.pause()

        joined = " | ".join(seen)
        assert "Conversation context" not in joined, "compaction summary replayed as a user turn"
        assert "a real question" in joined, "a genuine user message was dropped"
        assert "a real answer" in joined, "a genuine assistant message was dropped"


def test_replay_skips_the_compaction_summary():
    if not _HAS_TEXTUAL:
        return
    asyncio.run(_drive_replay_skips_the_summary())

"""Tests for TextRepetitionGuard — breaking a model stuck repeating its own prose.

Pins the reported bug: the CLI streams the same paragraphs over and over, no
tool call in sight, and the turn never ends. Also pins the false-positive side —
genuinely repetitive *content* (boilerplate, table rows) must stream through.
"""

from __future__ import annotations

import asyncio
import types

import novacode_cli.ui_events as ev
from novacode_cli.core.agent_loop import iterate_agent_events
from novacode_cli.tracking.loop_guard import TextRepetitionGuard

# The reported cycle, trimmed to its shape.
_CYCLE = (
    "Let me also check the `#upload-status` element. In the original code, it was "
    "`<span id=\"upload-status\" class=\"muted\">`.\n"
    "In the new HTML, it's `<span id=\"upload-status\" class=\"status-line\">` and the "
    "JS sets its textContent.\n"
    "The CSS has `.status-line` styling. Good.\n"
    "Now let me also verify the `#delete-session-btn` element, which the JS only "
    "references by ID. Good.\n"
)


def test_trips_on_repeated_block():
    g = TextRepetitionGuard()
    tripped_at = None
    for i in range(1, 21):
        if g.feed(_CYCLE):
            tripped_at = i
            break
    assert tripped_at is not None, "never detected the cycle"
    assert tripped_at <= 6, f"took {tripped_at} repeats to notice"


def test_survives_token_sized_deltas():
    """Real streaming arrives a few characters at a time, splitting lines."""
    g = TextRepetitionGuard()
    text = _CYCLE * 10
    tripped = False
    for i in range(0, len(text), 7):
        if g.feed(text[i : i + 7]):
            tripped = True
            break
    assert tripped


def test_long_unique_prose_does_not_trip():
    g = TextRepetitionGuard()
    for i in range(2000):
        assert not g.feed(
            f"Paragraph {i}: this is a substantial line of unique explanatory "
            f"prose about item number {i} in the list.\n"
        )


def test_repetitive_content_does_not_trip():
    """Boilerplate with repeated *lines* is not a repeated *block*."""
    g = TextRepetitionGuard()
    row = '                    <td class="cell"><span class="value">—</span></td>\n'
    for i in range(200):
        # Same long line every time, but each block is anchored by a unique line.
        assert not g.feed(f"<tr data-row-index=\"{i}\" class=\"data-row striped\">\n{row}")


def test_short_lines_are_ignored():
    g = TextRepetitionGuard()
    for _ in range(500):
        assert not g.feed("Good.\nOk.\nDone.\n")


# ── end-to-end through the agent loop ────────────────────────────────────────


class _Chunk:
    def __init__(self, mid, blocks):
        self.id = mid
        self._blocks = blocks
        self.usage_metadata = None

    @property
    def content_blocks(self):
        return self._blocks


class _State:
    def __init__(self, msgs):
        self.values = {"messages": msgs}


class _SS:
    thread_id = "t1"


def test_agent_loop_aborts_a_repeating_turn():
    """The endless stream is cut short with an Error instead of running forever."""

    class LoopingAgent:
        def __init__(self):
            self.deltas = 0

        async def aget_state(self, config):
            return _State([])

        async def astream(self, inp, **kw):
            while True:  # a model that never stops talking
                self.deltas += 1
                assert self.deltas < 500, "guard never fired"
                yield ((), "messages", (_Chunk("m1", [{"type": "text", "text": _CYCLE}]), {}))

        async def aupdate_state(self, **kw):
            pass

    agent = LoopingAgent()

    async def _run():
        out = []
        async for e in iterate_agent_events("hi", agent, "nova-agent", _SS()):
            out.append(e)
        return out

    evts = asyncio.run(_run())
    kinds = [type(e).__name__ for e in evts]
    assert any(
        isinstance(e, ev.Error) and "repeating itself" in e.message for e in evts
    ), kinds
    # The repeated blob is discarded, not committed as an assistant message.
    assert not any(isinstance(e, ev.AssistantMessage) for e in evts), kinds
    assert any(isinstance(e, ev.TextDiscard) for e in evts), kinds


def test_agent_loop_aborts_on_repeating_reasoning():
    """Same guard covers the reasoning stream — that loops too."""

    class LoopingAgent:
        def __init__(self):
            self.deltas = 0

        async def aget_state(self, config):
            return _State([])

        async def astream(self, inp, **kw):
            while True:
                self.deltas += 1
                assert self.deltas < 500, "guard never fired"
                yield (
                    (),
                    "messages",
                    (_Chunk("m1", [{"type": "reasoning", "text": _CYCLE}]), {}),
                )

        async def aupdate_state(self, **kw):
            pass

    evts = []

    async def _run():
        async for e in iterate_agent_events("hi", LoopingAgent(), "nova-agent", _SS()):
            evts.append(e)

    asyncio.run(_run())
    assert any(isinstance(e, ev.Error) and "repeating itself" in e.message for e in evts)


def test_normal_turn_still_completes():
    """Regression net: an ordinary answer is untouched by the guard."""

    class Agent:
        async def aget_state(self, config):
            return _State([])

        async def astream(self, inp, **kw):
            yield ((), "messages", (_Chunk("m1", [{"type": "text", "text": "Hello "}]), {}))
            yield ((), "messages", (_Chunk("m1", [{"type": "text", "text": "world"}]), {}))

        async def aupdate_state(self, **kw):
            pass

    evts = []

    async def _run():
        async for e in iterate_agent_events("hi", Agent(), "nova-agent", _SS()):
            evts.append(e)

    asyncio.run(_run())
    assert any(isinstance(e, ev.Done) for e in evts)
    assert not any(isinstance(e, ev.Error) for e in evts)


if __name__ == "__main__":
    test_trips_on_repeated_block()
    test_survives_token_sized_deltas()
    test_long_unique_prose_does_not_trip()
    test_repetitive_content_does_not_trip()
    test_short_lines_are_ignored()
    test_agent_loop_aborts_a_repeating_turn()
    test_agent_loop_aborts_on_repeating_reasoning()
    test_normal_turn_still_completes()
    print("ALL TESTS PASSED")

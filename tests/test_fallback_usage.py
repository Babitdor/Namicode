"""Fallback token capture from the persisted final AIMessage.

Some providers (notably Ollama) don't surface ``usage_metadata`` on the final
streamed chunk, so ``execute_task``'s primary capture path stays at zero.  The
``_capture_fallback_usage`` helper reads the aggregated AIMessage from the
persisted graph state instead.  These tests pin that behaviour and its
best-effort error handling.
"""

from __future__ import annotations

from types import SimpleNamespace

from novacode_cli.ui.execution import _capture_fallback_usage
from novacode_cli.ui.ui_elements import TokenTracker


class _FakeAgent:
    """Minimal agent exposing ``aget_state`` over a fixed message list."""

    def __init__(self, messages: list[object], *, raise_exc: Exception | None = None) -> None:
        self._messages = messages
        self._raise_exc = raise_exc

    async def aget_state(self, _config: object) -> SimpleNamespace:
        if self._raise_exc is not None:
            raise self._raise_exc
        return SimpleNamespace(values={"messages": self._messages})


def _msg(usage: dict | None) -> SimpleNamespace:
    return SimpleNamespace(usage_metadata=usage)


async def test_fallback_captures_usage_from_final_message():
    tracker = TokenTracker()
    agent = _FakeAgent([_msg({"input_tokens": 1234, "output_tokens": 56})])

    await _capture_fallback_usage(agent, {}, tracker)

    assert tracker.current_context == 1234
    assert tracker.last_output == 56
    assert tracker.has_api_data is True


async def test_fallback_uses_most_recent_message_with_usage():
    tracker = TokenTracker()
    # Newest message (last in list) carries usage; an earlier one differs.
    agent = _FakeAgent(
        [
            _msg({"input_tokens": 10, "output_tokens": 1}),
            _msg(None),  # e.g. a tool message with no usage
            _msg({"input_tokens": 999, "output_tokens": 42}),
        ]
    )

    await _capture_fallback_usage(agent, {}, tracker)

    assert tracker.current_context == 999
    assert tracker.last_output == 42


async def test_fallback_skips_zero_usage_but_stops_scanning():
    tracker = TokenTracker()
    agent = _FakeAgent([_msg({"input_tokens": 0, "output_tokens": 0})])

    await _capture_fallback_usage(agent, {}, tracker)

    # Zero usage must not flip has_api_data — nothing real was captured.
    assert tracker.has_api_data is False
    assert tracker.current_context == 0


async def test_fallback_no_message_with_usage_is_noop():
    tracker = TokenTracker()
    agent = _FakeAgent([_msg(None), _msg(None)])

    await _capture_fallback_usage(agent, {}, tracker)

    assert tracker.has_api_data is False


async def test_fallback_swallows_aget_state_errors():
    tracker = TokenTracker()
    agent = _FakeAgent([], raise_exc=RuntimeError("graph exploded"))

    # Must not raise — a learning/telemetry failure can't break the turn.
    await _capture_fallback_usage(agent, {}, tracker)

    assert tracker.has_api_data is False

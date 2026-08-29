"""Context-window overflow is recoverable by compacting, not by retrying.

``agent_loop`` imported ``is_context_overflow`` from ``novacode_cli.errors`` and
yielded ``ev.ContextOverflow``, but neither existed — every turn that hit the
funnel died with ``ImportError: cannot import name 'is_context_overflow'``.
"""

from __future__ import annotations

import asyncio

import novacode_cli.ui_events as ev
from novacode_cli.errors import is_context_overflow

try:
    import textual  # noqa: F401

    _HAS_TEXTUAL = True
except ImportError:  # pragma: no cover
    _HAS_TEXTUAL = False


def test_the_symbol_agent_loop_imports_exists():
    """The regression itself: the import in agent_loop must resolve."""
    from novacode_cli.errors import is_context_overflow as fn  # noqa: F401

    assert callable(fn)
    assert hasattr(ev, "ContextOverflow")


def test_real_provider_overflow_messages_are_detected():
    """Wording varies by provider; these are the shapes seen in the wild."""
    overflows = (
        "This model's maximum context length is 200000 tokens, however you "
        "requested 210000 tokens.",
        "prompt is too long: 205000 tokens > 200000 maximum",
        "Request too large for model, reduce the length of the messages.",
        "context_length_exceeded: input is too long for the context window",
    )
    for msg in overflows:
        assert is_context_overflow(RuntimeError(msg)), msg


def test_unrelated_errors_are_not_treated_as_overflow():
    """A false positive silently compacts the user's conversation."""
    others = (
        "Rate limit reached. Please try again later.",
        "invalid api key provided",
        "connection refused",
        "max_tokens must be a positive integer",   # mentions max_tokens, not a limit
        "the file is too long to display",         # 'too long', but not context
        None,
    )
    for msg in others:
        exc = RuntimeError(msg) if msg is not None else None
        assert not is_context_overflow(exc), msg


async def _drive(second_overflow: bool):
    """Render a ContextOverflow (optionally twice) and capture the log."""
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
        logged: list[str] = []
        app._log = lambda t: logged.append(str(getattr(t, "plain", t)))  # type: ignore[assignment]

        compacted: list[str] = []

        async def fake_compact(arg):
            compacted.append(arg)

        app._run_compact = fake_compact  # type: ignore[assignment]

        streamed: list[str] = []

        async def fake_stream(text, assistant_id=None):
            streamed.append(text)
            if second_overflow:
                await app._render(ev.ContextOverflow("still too long"))

        app._stream_prompt = fake_stream  # type: ignore[assignment]
        app._last_user_prompt = "do the thing"

        await app._render(ev.ContextOverflow("prompt is too long"))
        for _ in range(2):
            await pilot.pause()
        return logged, compacted, streamed


def test_overflow_compacts_and_retries_once():
    if not _HAS_TEXTUAL:
        return
    logged, compacted, streamed = asyncio.run(_drive(second_overflow=False))
    assert compacted == [""], "should have compacted exactly once"
    assert streamed == ["do the thing"], "should re-send the user's prompt"
    assert any("compacting and retrying" in line for line in logged)


def test_a_second_overflow_gives_up_instead_of_looping():
    """Compacting twice would spin; tell the user how to recover instead."""
    if not _HAS_TEXTUAL:
        return
    logged, compacted, _ = asyncio.run(_drive(second_overflow=True))
    assert len(compacted) == 1, f"compacted {len(compacted)} times — retry looped"
    assert any("can't be shrunk further" in line for line in logged), logged

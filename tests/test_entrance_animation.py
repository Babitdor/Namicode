"""Entrance animations are skipped under load, never at the cost of visibility.

``_add_message`` animates EVERY chat message, and each animation repaints its
widget every frame for its duration. A fast stream stacked them — measured at 40
concurrent — turning the polish into jank: mounting cost 4.8 ms without the
animation and 10.0 ms with it.

The animation is now skipped once several are already in flight. The risk that
introduces is the serious one: a widget left at opacity 0 is invisible, which is
far worse than a slow fade. These pin both halves.
"""

from __future__ import annotations

import asyncio

try:
    import textual  # noqa: F401

    _HAS_TEXTUAL = True
except ImportError:  # pragma: no cover
    _HAS_TEXTUAL = False


def test_threshold_is_a_sane_size():
    """Small enough to protect a burst, large enough for an ordinary exchange."""
    from novacode_cli.tui.animations import _MAX_CONCURRENT_ENTRANCES

    assert 2 <= _MAX_CONCURRENT_ENTRANCES <= 20


def test_in_flight_counter_never_raises():
    """It reads a private Textual attribute; it must degrade, not explode."""
    from novacode_cli.tui.animations import _entrances_in_flight

    class _NoApp:
        @property
        def app(self):
            raise RuntimeError("no app")

    assert _entrances_in_flight(_NoApp()) == 0


async def _drive():
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).parent))
    from test_tui_app import _FakeAgent, _SS
    from textual.widgets import Static

    from novacode_cli.tui.animations import animate_entrance
    from novacode_cli.tui.app import NovaApp
    from novacode_cli.ui.ui_elements import TokenTracker

    out: dict = {}
    app = NovaApp(
        agent=_FakeAgent(), assistant_id="nova-agent", session_state=_SS(),
        backend=None, token_tracker=TokenTracker(), image_tracker=None,
        model_name="m",
    )
    async with app.run_test(size=(120, 40)) as pilot:
        for _ in range(6):
            await pilot.pause()
        await asyncio.sleep(0.5)  # let startup animations drain
        for _ in range(4):
            await pilot.pause()
        tr = app.query_one("#transcript")

        # Quiet UI: the polish is preserved (starts transparent, fades in).
        w = Static("quiet")
        await tr.mount(w)
        animate_entrance(w, "slide")
        out["idle_animates"] = float(w.styles.opacity) < 1.0
        await asyncio.sleep(0.45)
        for _ in range(3):
            await pilot.pause()
        out["idle_ends_visible"] = float(w.styles.opacity) == 1.0

        # Burst: past the threshold the animation is skipped — but NOTHING may
        # be left invisible, now or after every animation has settled.
        widgets = []
        for i in range(20):
            x = Static(f"burst {i}")
            await tr.mount(x)
            animate_entrance(x, "slide")
            widgets.append(x)
        # How many were shown WITHOUT waiting for any animation. Not asserted as
        # zero: the first few widgets are below the threshold and do animate, so
        # sampling here can legitimately catch one mid-fade at opacity 0 — under
        # full-suite load the animator drains slower and that is exactly what
        # happened. "Mid-fade" and "stuck invisible" are different things, and
        # only the second is a bug; `_MAX_CONCURRENT_ENTRANCES` bounds how many
        # can ever be mid-fade at once.
        out["shown_immediately"] = sum(
            1 for x in widgets if float(x.styles.opacity) > 0.0
        )
        out["mid_fade"] = len(widgets) - out["shown_immediately"]

        # The real property: once every animation has settled, nothing is
        # invisible. A broken skip leaves widgets at 0 here forever.
        await asyncio.sleep(0.8)
        for _ in range(6):
            await pilot.pause()
        out["invisible_after_settle"] = sum(
            1 for x in widgets if float(x.styles.opacity) == 0.0
        )
        out["all_visible"] = all(float(x.styles.opacity) == 1.0 for x in widgets)
    return out


def test_animation_is_skipped_under_load_but_nothing_stays_invisible():
    if not _HAS_TEXTUAL:
        return
    out = asyncio.run(_drive())
    assert out["idle_animates"], "a quiet UI should still animate (polish preserved)"
    assert out["idle_ends_visible"], "the idle fade must complete"
    # The skip must actually engage: most of a 20-widget burst appears at once
    # rather than every one queueing an animation. Bounded by the threshold, so
    # this stays true regardless of how slowly the animator drains.
    from novacode_cli.tui.animations import _MAX_CONCURRENT_ENTRANCES

    assert out["mid_fade"] <= _MAX_CONCURRENT_ENTRANCES + 2, (
        f"{out['mid_fade']} widgets were animating — the skip did not engage"
    )
    # The one that matters: nothing may stay invisible once animations settle.
    assert out["invisible_after_settle"] == 0, (
        "a skipped animation left a widget at opacity 0 — invisible content"
    )
    assert out["all_visible"], "every burst widget must end fully opaque"

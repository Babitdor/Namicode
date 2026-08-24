"""Regression tests for the auto-compaction loop guard in ``NovaApp._check_context``.

The reported bug: a mis-sized context window kept ctx% "critical" every turn, so
the TUI auto-compacted every turn and spammed the degraded "SESSION INTENT /
read conversation_history to recover" summary forever. The guard stops that:

  * if we auto-compacted last turn and are STILL critical, disable auto-compact
    and hand control back (don't compact again this turn);
  * if a single compaction can't get us back under critical (window too small),
    disable auto-compact with a recovery hint;
  * a compaction that DOES free space re-arms the guard.

``_check_context`` only touches a handful of ``self`` attributes, so it's driven
here on a lightweight stub via the unbound method — no Textual App boot needed.

Runnable directly (``python tests/test_context_compaction_guard.py``) or pytest.
"""

from __future__ import annotations

import asyncio

try:
    import textual  # noqa: F401

    _HAS_TEXTUAL = True
except ImportError:  # pragma: no cover
    _HAS_TEXTUAL = False

import pytest

pytestmark = pytest.mark.skipif(not _HAS_TEXTUAL, reason="textual not installed")


class _BD:
    """Minimal ContextBreakdown stand-in with the thresholds the guard reads."""

    def __init__(self, pct: float) -> None:
        self.usage_percentage = pct

    @property
    def is_critical(self) -> bool:
        return self.usage_percentage >= 90

    @property
    def is_warning(self) -> bool:
        return self.usage_percentage >= 75


class _StubApp:
    """Stands in for NovaApp: exposes only what ``_check_context`` uses."""

    def __init__(
        self,
        pct: float,
        after_compact_pct: float | None = None,
        *,
        auto: bool = True,
        compacted_last: bool = False,
    ) -> None:
        self._pct = pct
        self._after = pct if after_compact_pct is None else after_compact_pct
        self._auto_compact = auto
        self._compacted_last_turn = compacted_last
        self._ctx_warned = False
        self.compact_calls = 0
        self.logs: list[str] = []
        self.token_tracker = self  # get_breakdown() lives here

    def get_breakdown(self) -> _BD:
        return _BD(self._pct)

    def _log(self, msg: object) -> None:
        self.logs.append(str(msg))

    async def _run_compact(self, _arg: str) -> None:
        self.compact_calls += 1
        self._pct = self._after  # compaction updates measured usage


def _check(app: _StubApp) -> None:
    from novacode_cli.tui.app import NovaApp

    asyncio.run(NovaApp._check_context(app))


def _joined(app: _StubApp) -> str:
    return " ".join(app.logs).lower()


# ── the loop break ───────────────────────────────────────────────────────────


def test_consecutive_critical_disables_autocompact_without_recompacting():
    # Already compacted last turn and still critical → the loop guard fires
    # BEFORE compacting again.
    app = _StubApp(pct=95, compacted_last=True)
    _check(app)
    assert app.compact_calls == 0  # did not compact a second time
    assert app._auto_compact is False
    assert app._compacted_last_turn is False
    assert "loop" in _joined(app) and "/clear" in _joined(app)


def test_compaction_that_frees_space_rearms_guard():
    # First critical turn; compaction drops us to 40% → healthy. Guard stays
    # armed for next time, auto-compact stays on.
    app = _StubApp(pct=95, after_compact_pct=40)
    _check(app)
    assert app.compact_calls == 1
    assert app._auto_compact is True
    assert app._compacted_last_turn is True


def test_compaction_that_cannot_free_space_disables_autocompact():
    # Window too small: still critical after compacting → give up, tell the user.
    app = _StubApp(pct=95, after_compact_pct=92)
    _check(app)
    assert app.compact_calls == 1
    assert app._auto_compact is False
    assert "too small" in _joined(app)


def test_below_critical_warning_resets_the_guard():
    # Dropped to the warning band (e.g. right after a compaction). No compaction,
    # and the consecutive-compaction flag is cleared so a later critical turn
    # gets a fresh compaction attempt rather than being treated as a loop.
    app = _StubApp(pct=80, compacted_last=True)
    _check(app)
    assert app.compact_calls == 0
    assert app._compacted_last_turn is False


def test_no_autocompact_only_warns():
    # Auto-compact off: critical only nudges the user, never compacts.
    app = _StubApp(pct=95, auto=False)
    _check(app)
    assert app.compact_calls == 0
    assert app._auto_compact is False
    assert "/compact" in _joined(app)


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-v", "--assert=plain"]))

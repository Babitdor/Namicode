"""Tests for standalone pre-TUI Textual pickers (e.g. --resume)."""

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

try:
    import textual  # noqa: F401

    _HAS_TEXTUAL = True
except ImportError:  # pragma: no cover
    _HAS_TEXTUAL = False


def _sessions():
    now = datetime.now(UTC).isoformat()
    return [
        SimpleNamespace(
            session_id="abcd1234ef",
            project_root="b:/proj/nova",
            model_name="deepseek-v4",
            message_count=63,
            last_active=now,
            current_task="wire steering",
            task_status="active",
        ),
        SimpleNamespace(
            session_id="99887766aa",
            project_root=None,
            model_name="gpt",
            message_count=4,
            last_active=now,
            current_task=None,
            task_status="complete",
        ),
    ]


async def _drive_pick(select_index, key):
    from novacode_cli.tui.pickers import SessionPickerApp

    sessions = _sessions()
    app = SessionPickerApp(sessions)
    async with app.run_test() as pilot:
        ol = app.query_one("#sessions")
        assert ol.option_count == len(sessions), ol.option_count
        ol.focus()
        ol.highlighted = select_index
        await pilot.press(key)
    return app.return_value


def test_picker_returns_selected_session():
    if not _HAS_TEXTUAL:
        return
    res = asyncio.run(_drive_pick(1, "enter"))
    assert res == "99887766aa", res


def test_picker_cancel_returns_none():
    if not _HAS_TEXTUAL:
        return
    res = asyncio.run(_drive_pick(0, "escape"))
    assert res is None, res


async def _drive_onboarding():
    from textual.widgets import Input, Select

    from novacode_cli.tui.pickers import OnboardingApp

    captured = {}

    app = OnboardingApp()
    # Don't touch the real keyring/config — capture what would be persisted.
    app._persist = staticmethod(
        lambda provider, key, opt: captured.update(
            provider=provider, key=key, opt=opt
        )
    )
    async with app.run_test() as pilot:
        prov = app.query_one("#provider", Select)
        key = app.query_one("#provider-key", Input)
        assert str(prov.value) == "ollama"
        assert key.password is False  # host field, not secret

        # Cloud provider -> password + required validation.
        prov.value = "anthropic"
        await pilot.pause()
        assert key.password is True
        app.query_one("#finish").press()
        await pilot.pause()
        assert "required" in str(app.query_one("#status").render()).lower()

        # Provide a key and finish -> persists + exits True.
        key.value = "sk-test-123"
        app.query_one("#finish").press()
        await pilot.pause()
    return app.return_value, captured


def test_onboarding_validates_and_persists():
    if not _HAS_TEXTUAL:
        return
    result, captured = asyncio.run(_drive_onboarding())
    assert result is True, result
    assert captured.get("provider") == "anthropic"
    assert captured.get("key") == "sk-test-123"

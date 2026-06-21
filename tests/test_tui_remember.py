"""Tests for TUI session/always-allow wiring in the tool interrupt handler."""

from __future__ import annotations

import asyncio
import types
from typing import TYPE_CHECKING

from novacode_cli.security.session_allow import get_session_allow, reset_session_allow

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    import pytest


def _interrupt(name: str, args: dict) -> types.SimpleNamespace:
    fut: asyncio.Future = asyncio.get_event_loop().create_future()
    return types.SimpleNamespace(
        kind="tool",
        payload={"action_requests": [{"name": name, "args": args}]},
        future=fut,
    )


def _async_return(value: object) -> Callable[..., Awaitable[object]]:
    async def _fn(*_args: object, **_kwargs: object) -> object:
        return value

    return _fn


async def test_tui_session_choice_remembers_and_approves(monkeypatch: pytest.MonkeyPatch) -> None:
    from novacode_cli.tui.app import NovaApp

    reset_session_allow()
    app = NovaApp.__new__(NovaApp)  # bypass __init__; only exercise the handler
    app.session_state = types.SimpleNamespace(plan_mode_enabled=False, auto_approve=False)
    monkeypatch.setattr(app, "push_screen_wait", _async_return("session"), raising=False)
    monkeypatch.setattr(app, "_log", lambda *_a, **_k: None, raising=False)

    e = _interrupt("shell", {"command": "npm run build"})
    await app._handle_interrupt_inner(e)

    result = e.future.result()
    assert result["decisions"][0]["type"] == "approve"
    assert get_session_allow().matches("shell", {"command": "npm run build --prod"}) is True
    reset_session_allow()

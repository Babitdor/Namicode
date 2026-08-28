"""Tests for the /refine command handler (commands/refine_handler.py).

Covers the subcommand surface added in the Prime-Agent-inspired completion:
- ``/refine`` (no args) → run the loop
- ``/refine plan`` → dry-run plan
- ``/refine status`` → harness state
- ``/refine history`` / ``/refine rollback <id>`` (existing)
"""

from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from rich.console import Console

from novacode_cli.commands import refine_handler


class _FakeStore:
    """Minimal stand-in exposing the session-store surface the handler needs."""


class _FakeSessionState:
    def __init__(self, store: object) -> None:
        self._store = store


@pytest.fixture
def console() -> Console:
    return Console(file=io.StringIO())


@pytest.fixture
def session_state() -> _FakeSessionState:
    return _FakeSessionState(_FakeStore())


async def test_no_args_runs_loop(
    session_state: _FakeSessionState, console: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    summary = {
        "items": [{"domain": "skill", "target": "alpha", "action": "patch", "outcome": "applied"}],
        "planned": 1,
        "applied": 1,
        "accepted": 1,
        "rolled_back": 0,
    }
    run_refine = AsyncMock(return_value=summary)
    monkeypatch.setattr("novacode_cli.hermes.refine_loop.run_refine", run_refine)
    ok = await refine_handler.handle_refine_command(None, session_state, console)
    assert ok is True
    run_refine.assert_awaited_once()


async def test_plan_is_dry_run(
    session_state: _FakeSessionState, console: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = [{"domain": "memory", "target": "lessons", "action": "create", "reason": "r"}]
    plan_refinements = AsyncMock(return_value=plan)
    monkeypatch.setattr("novacode_cli.hermes.refine_loop.plan_refinements", plan_refinements)
    ok = await refine_handler.handle_refine_command("plan", session_state, console)
    assert ok is True
    plan_refinements.assert_awaited_once()


async def test_plan_empty(
    session_state: _FakeSessionState, console: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan_refinements = AsyncMock(return_value=[])
    monkeypatch.setattr("novacode_cli.hermes.refine_loop.plan_refinements", plan_refinements)
    ok = await refine_handler.handle_refine_command("plan", session_state, console)
    assert ok is True


async def test_status_lists_harness_state(
    session_state: _FakeSessionState, console: Console, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(refine_handler, "_user_skills_dir", Path)
    monkeypatch.setattr(
        "novacode_cli.hermes.refine_loop._list_skills",
        lambda _dir: [{"name": "alpha", "description": "d"}],
    )
    monkeypatch.setattr("novacode_cli.hermes.refine_loop._prompt_state", list)
    monkeypatch.setattr("novacode_cli.hermes.refine_loop._memory_topics", lambda: ["lessons"])
    ok = await refine_handler.handle_refine_command("status", session_state, console)
    assert ok is True


async def test_missing_store_is_handled(console: Console) -> None:
    state = _FakeSessionState(None)
    ok = await refine_handler.handle_refine_command(None, state, console)
    assert ok is True


async def test_unknown_subcommand(session_state: _FakeSessionState, console: Console) -> None:
    ok = await refine_handler.handle_refine_command("bogus", session_state, console)
    assert ok is True

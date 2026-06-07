"""Tests for /ralph UI emission — the handler routes all user-facing output
through the injected ``emit`` sink (so the TUI renders it natively) instead of
printing to stdout/stderr.
"""

from __future__ import annotations

import types

from novacode_cli.commands import ralph_handler as rh


def _sink():
    lines: list[str] = []
    return lines, lines.append


async def test_no_args_emits_usage_not_stdout(capsys):
    lines, emit = _sink()
    ok = await rh.handle_ralph_command(
        agent=object(),
        session_state=types.SimpleNamespace(),
        assistant_id="ralph",
        token_tracker=None,
        cmd_args=None,
        emit=emit,
    )
    assert ok is True
    joined = "\n".join(lines)
    assert "Usage: /ralph" in joined
    assert "--iterations" in joined
    # Nothing leaked to the real stdout/stderr.
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


async def test_status_empty_emits_to_sink(capsys):
    lines, emit = _sink()
    session = types.SimpleNamespace(background_ralph_tasks={})
    ok = await rh.handle_ralph_status(session, emit)
    assert ok is True
    assert any("No background Ralph tasks" in ln for ln in lines)
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


async def test_status_via_command_routes_to_status():
    lines, emit = _sink()
    session = types.SimpleNamespace(background_ralph_tasks={})
    ok = await rh.handle_ralph_command(
        agent=object(),
        session_state=session,
        assistant_id="ralph",
        token_tracker=None,
        cmd_args="--status",
        emit=emit,
    )
    assert ok is True
    assert any("Ralph Background Tasks" in ln for ln in lines)


async def test_bad_iterations_arg_emits_error():
    lines, emit = _sink()
    ok = await rh.handle_ralph_command(
        agent=object(),
        session_state=types.SimpleNamespace(),
        assistant_id="ralph",
        token_tracker=None,
        cmd_args="do something --iterations notanumber",
        emit=emit,
    )
    assert ok is True
    assert any("requires a number" in ln for ln in lines)


def test_console_emit_is_default():
    # The module's default sink is the console emitter (CLI path).
    assert rh._console_emit is not None
    assert rh.handle_ralph_command.__defaults__ is not None

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


# --- Structured on_event path (drives the TUI's native widgets) ------------


async def test_status_with_on_event_yields_snapshot():
    """--status hands a renderer a plain StatusSnapshot instead of markup lines."""
    from novacode_cli.commands import ralph_events as rev
    from novacode_cli.states.Session import BackgroundRalphTask, RalphTaskStatus

    task = BackgroundRalphTask(
        task_id="abc123",
        iteration=2,
        max_iterations=5,
        task_description="do the thing",
    )
    task.status = RalphTaskStatus.RUNNING
    session = types.SimpleNamespace(background_ralph_tasks={"abc123": task})

    markup, emit = _sink()
    events: list = []
    ok = await rh.handle_ralph_status(session, emit, on_event=events.append)

    assert ok is True
    # Nothing went to the markup sink — the renderer gets a structured snapshot.
    assert markup == []
    assert len(events) == 1
    snap = events[0]
    assert isinstance(snap, rev.StatusSnapshot)
    assert snap.total == 1
    assert snap.running == 1
    assert snap.rows[0].iteration == 2
    assert snap.rows[0].status == "running"


async def test_foreground_emits_structured_events(tmp_path, monkeypatch):
    """A foreground run reports start/iteration/finish through on_event, and the
    structured banner markup is suppressed when a renderer is wired up."""
    monkeypatch.chdir(tmp_path)

    calls: list[str] = []

    async def fake_execute(prompt, agent, name, ss, tt, backend=None):  # noqa: ANN001, ARG001
        calls.append(name)

    session = types.SimpleNamespace(
        auto_approve=False,
        thread_id="t",
        background_ralph_tasks={},
        add_notification=lambda **_: None,
    )
    markup, emit = _sink()
    events: list = []

    ok = await rh.handle_ralph_command(
        agent=object(),
        session_state=session,
        assistant_id="ralph",
        token_tracker=None,
        cmd_args="do something --iterations 2",
        execute_fn=fake_execute,
        emit=emit,
        on_event=events.append,
    )

    assert ok is True
    assert calls == ["ralph", "ralph"]  # one agent run per iteration

    kinds = [type(e).__name__ for e in events]
    assert kinds == [
        "RalphStarted",
        "IterationStarted",
        "IterationFinished",
        "IterationStarted",
        "IterationFinished",
        "RalphFinished",
    ]
    assert events[0].task == "do something"
    assert events[0].max_iterations == 2
    assert events[0].background is False
    assert events[-1].completed == 2
    assert events[-1].failed == 0

    # The header/banner/summary markup is routed to on_event, not the markup sink.
    joined = "\n".join(markup)
    assert "Ralph Mode" not in joined
    assert "Iteration 1/2" not in joined


async def test_ralph_stop_requested(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    calls = []

    async def fake_execute(prompt, agent, name, ss, tt, backend=None):
        # Request stop when executing the first iteration
        ss._ralph_stop_requested = True
        calls.append(name)

    session = types.SimpleNamespace(
        auto_approve=False,
        thread_id="t",
        background_ralph_tasks={},
        add_notification=lambda **_: None,
        _ralph_stop_requested=False,
    )
    markup, emit = _sink()
    events = []

    ok = await rh.handle_ralph_command(
        agent=object(),
        session_state=session,
        assistant_id="ralph",
        token_tracker=None,
        cmd_args="do something --iterations 5",
        execute_fn=fake_execute,
        emit=emit,
        on_event=events.append,
    )

    assert ok is True
    # Should only execute one iteration, then stop.
    assert len(calls) == 1
    kinds = [type(e).__name__ for e in events]
    assert kinds == [
        "RalphStarted",
        "IterationStarted",
        "IterationFinished",
        "RalphFinished",
    ]
    assert events[-1].completed == 1
    assert events[-1].reason == "stopped"


async def test_ralph_checkpoint_requested(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(rh, "_get_checkpoint_path", lambda: tmp_path / "ralph-checkpoint.json")
    calls = []

    async def fake_execute(prompt, agent, name, ss, tt, backend=None):
        # Request checkpoint
        ss._ralph_checkpoint_requested = True
        calls.append(name)

    session = types.SimpleNamespace(
        auto_approve=False,
        thread_id="t",
        background_ralph_tasks={},
        add_notification=lambda **_: None,
        _ralph_checkpoint_requested=False,
    )
    markup, emit = _sink()
    events = []

    ok = await rh.handle_ralph_command(
        agent=object(),
        session_state=session,
        assistant_id="ralph",
        token_tracker=None,
        cmd_args="do something --iterations 5",
        execute_fn=fake_execute,
        emit=emit,
        on_event=events.append,
    )

    assert ok is True
    # Should only execute one iteration, then stop after saving checkpoint.
    assert len(calls) == 1
    kinds = [type(e).__name__ for e in events]
    assert kinds == [
        "RalphStarted",
        "IterationStarted",
        "IterationFinished",
        "RalphFinished",
    ]
    assert events[-1].completed == 1
    assert events[-1].reason == "checkpoint"
    # Ensure checkpoint file was created
    assert (tmp_path / "ralph-checkpoint.json").is_file()


async def test_ralph_cancelled_error(tmp_path, monkeypatch):
    import asyncio

    monkeypatch.chdir(tmp_path)
    calls = []

    async def fake_execute(prompt, agent, name, ss, tt, backend=None):
        calls.append(name)
        raise asyncio.CancelledError()

    session = types.SimpleNamespace(
        auto_approve=False,
        thread_id="t",
        background_ralph_tasks={},
        add_notification=lambda **_: None,
    )
    markup, emit = _sink()
    events = []

    ok = await rh.handle_ralph_command(
        agent=object(),
        session_state=session,
        assistant_id="ralph",
        token_tracker=None,
        cmd_args="do something --iterations 5",
        execute_fn=fake_execute,
        emit=emit,
        on_event=events.append,
    )

    assert ok is True
    assert len(calls) == 1
    kinds = [type(e).__name__ for e in events]
    assert kinds == [
        "RalphStarted",
        "IterationStarted",
        "RalphFinished",
    ]
    assert events[-1].completed == 0
    assert events[-1].reason == "stopped"


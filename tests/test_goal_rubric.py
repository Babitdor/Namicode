"""`/goal rubric ...` — pair an acceptance rubric with the active goal.

The rubric is threaded into the run as the `rubric` state key (agent_loop), which
deepagents' RubricMiddleware grades against. These tests pin the command surface.
"""

from __future__ import annotations

import types

from novacode_cli.commands.side_commands import handle_goal_command


def _session() -> types.SimpleNamespace:
    return types.SimpleNamespace(active_goal=None, active_rubric=None)


def test_set_goal_then_rubric() -> None:
    ss = _session()
    r1 = handle_goal_command(ss, "build a CSV parser")
    assert r1.action == "set"
    assert ss.active_goal == "build a CSV parser"
    assert ss.active_rubric is None  # setting a goal doesn't touch the rubric

    r2 = handle_goal_command(ss, "rubric - all tests pass\n- handles empty input")
    assert r2.action == "rubric-set"
    assert ss.active_rubric == "- all tests pass\n- handles empty input"
    assert r2.rubric == ss.active_rubric


def test_status_shows_goal_and_rubric() -> None:
    ss = _session()
    handle_goal_command(ss, "do the thing")
    handle_goal_command(ss, "rubric must lint clean")
    r = handle_goal_command(ss, "status")
    assert "Active goal" in r.message
    assert "Rubric" in r.message


def test_rubric_clear_keeps_goal() -> None:
    ss = _session()
    handle_goal_command(ss, "ship feature")
    handle_goal_command(ss, "rubric green CI")
    handle_goal_command(ss, "rubric clear")
    assert ss.active_rubric is None
    assert ss.active_goal == "ship feature"  # only the rubric was cleared


def test_clear_drops_both_goal_and_rubric() -> None:
    ss = _session()
    handle_goal_command(ss, "ship feature")
    handle_goal_command(ss, "rubric green CI")
    handle_goal_command(ss, "clear")
    assert ss.active_goal is None
    assert ss.active_rubric is None


def test_empty_rubric_arg_clears() -> None:
    ss = _session()
    handle_goal_command(ss, "rubric something")
    assert ss.active_rubric == "something"
    handle_goal_command(ss, "rubric")  # bare `rubric` with no criteria clears it
    assert ss.active_rubric is None

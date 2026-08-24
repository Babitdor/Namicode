"""FileOpTracker isolation: the main TUI agent and the cowork server agent run
concurrently in one process with different backends/workspace roots. They must
NOT share a single global tracker (that clobber surfaced as "Agent run failed"
under simultaneous TUI + Cowork use)."""

from __future__ import annotations

from novacode_cli.file_ops import (
    get_session_file_op_tracker,
    reset_session_file_op_tracker,
)


def test_distinct_agents_get_distinct_trackers():
    reset_session_file_op_tracker()
    tui = get_session_file_op_tracker(assistant_id="nova-agent", backend=None)
    cowork = get_session_file_op_tracker(assistant_id="nova-server", backend=None)
    assert tui is not cowork  # concurrent agents isolated


def test_same_agent_reuses_tracker():
    reset_session_file_op_tracker()
    a = get_session_file_op_tracker(assistant_id="nova-agent", backend=None)
    b = get_session_file_op_tracker(assistant_id="nova-agent", backend=None)
    assert a is b  # main agent + subagents still share


def test_scoped_reset_drops_only_that_agent():
    reset_session_file_op_tracker()
    tui = get_session_file_op_tracker(assistant_id="nova-agent", backend=None)
    cowork = get_session_file_op_tracker(assistant_id="nova-server", backend=None)
    reset_session_file_op_tracker("nova-server")
    assert get_session_file_op_tracker(assistant_id="nova-agent") is tui  # untouched
    assert get_session_file_op_tracker(assistant_id="nova-server") is not cowork  # rebuilt

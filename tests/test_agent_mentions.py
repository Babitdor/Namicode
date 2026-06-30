"""Tests for multi-@agent mention parsing (sequential subagent orchestration)."""

from __future__ import annotations

from novacode_cli.agents.default_subagents.subagents import retrieve_core_subagents
from novacode_cli.input_utils import parse_agent_mentions, parse_agent_mentions_multi

_CORE = [s["name"] for s in retrieve_core_subagents()]
_A, _B = _CORE[0], _CORE[1]


def test_multi_orders_and_dedups():
    text = f"@{_A} fix @app.py then hand to @{_B} and back to @{_A}"
    assert parse_agent_mentions_multi(text) == [_A, _B]


def test_multi_ignores_unknown_and_files():
    assert parse_agent_mentions_multi("@nope-xyz edit @thing.py and @style.css") == []


def test_multi_ignores_emails_and_midword():
    # Mid-word / email '@' must not match a known agent name.
    assert parse_agent_mentions_multi(f"reach me at foo@{_A}") == []


def test_multi_empty_when_no_mentions():
    assert parse_agent_mentions_multi("just a normal request") == []


def test_single_start_mention_still_parses():
    name, query = parse_agent_mentions(f"@{_A} do the thing")
    assert name == _A
    assert query == "do the thing"

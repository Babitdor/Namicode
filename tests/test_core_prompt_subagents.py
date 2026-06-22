"""The core system prompt tells the agent the task tool is synchronous."""

from __future__ import annotations

from novacode_cli.prompts import render_template


def _core_prompt() -> str:
    # Lenient Jinja Undefined => no kwargs needed for this static-block assertion.
    return render_template("core_agent_system.jinja")


def test_core_prompt_has_subagents_block():
    out = _core_prompt()
    assert "<subagents>" in out
    assert "</subagents>" in out


def test_core_prompt_states_task_is_synchronous_and_no_wait():
    out = _core_prompt()
    assert "synchronous" in out
    assert "Never end your turn" in out


def test_subagents_block_follows_todo_management():
    out = _core_prompt()
    assert "<todo_management>" in out
    assert "<subagents>" in out
    assert out.index("<subagents>") > out.index("</todo_management>")

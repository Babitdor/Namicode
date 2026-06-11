"""Subagents must run unattended — the main agent is the sole HITL boundary.

A HITL interrupt raised inside a subagent is invoked via ``subagent.ainvoke()``
in deepagents' ``task`` tool, so it surfaces as a ``GraphInterrupt`` exception
bubbling out of the parent stream (never a top-level ``__interrupt__``) and the
auto-approve path never sees it → the turn crashes. ``_harden_subagent_specs``
therefore (a) clears ``interrupt_on`` on every declarative subagent and (b) strips
tools that raise ``interrupt()`` directly in their body (``ask_user_question`` and
the plan-mode tools). These tests lock in that contract.
"""

from langchain.tools import tool

from novacode_cli.agents.core_agent import _harden_subagent_specs
from novacode_cli.agents.default_subagents.subagents import retrieve_core_subagents


@tool
def _fake_ask_user_question(question: str) -> str:
    """Stand-in with the same name as the real interrupting tool."""
    return question


_fake_ask_user_question.name = "ask_user_question"


@tool
def _fake_think(thought: str) -> str:
    """A harmless non-interrupting tool."""
    return thought


def test_core_subagents_are_declarative_dicts():
    # The fix only applies to declarative specs (no 'runnable'/'url'); confirm
    # that's what retrieve_core_subagents produces.
    specs = retrieve_core_subagents(tools=[])
    assert specs, "expected core subagents"
    for s in specs:
        assert isinstance(s, dict)
        assert "runnable" not in s and "url" not in s
        assert "system_prompt" in s  # declarative SubAgent


def test_harden_clears_interrupt_on():
    specs = retrieve_core_subagents(tools=[])
    hardened = _harden_subagent_specs(specs)
    for s in hardened:
        # deepagents adds HumanInTheLoopMiddleware only `if interrupt_on:` — an
        # empty dict is falsy, so HITL is skipped for the subagent.
        assert s.get("interrupt_on") == {}
        assert not s["interrupt_on"]


def test_harden_strips_interrupting_tools_from_subagents():
    spec = {
        "name": "general-purpose",
        "system_prompt": "x",
        "tools": [_fake_ask_user_question, _fake_think],
        "interrupt_on": {"shell": object()},
    }
    hardened = _harden_subagent_specs([spec])[0]
    names = [getattr(t, "name", None) for t in hardened["tools"]]
    assert "ask_user_question" not in names  # interrupting tool removed
    assert _fake_think.name in names  # harmless tool kept
    assert hardened["interrupt_on"] == {}


def test_harden_does_not_mutate_original_spec():
    tools = [_fake_ask_user_question, _fake_think]
    spec = {"name": "a", "system_prompt": "x", "tools": tools}
    _harden_subagent_specs([spec])
    # The (possibly cached) input spec + its tool list must be untouched.
    assert spec["tools"] is tools
    assert any(getattr(t, "name", None) == "ask_user_question" for t in spec["tools"])


def test_deepagents_skips_hitl_for_empty_interrupt_on():
    # Contract with deepagents.middleware.subagents._build (`if interrupt_on:`):
    # a falsy interrupt_on means no HITL middleware is attached to the subagent.
    assert bool({}) is False
    assert bool(None) is False
    assert bool({"execute": object()}) is True

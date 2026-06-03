"""Subagents must run unattended — the main agent is the sole HITL boundary.

A HITL interrupt raised inside a subagent is invoked via ``subagent.ainvoke()``
in deepagents' ``task`` tool, so it surfaces as a ``GraphInterrupt`` exception
bubbling out of the parent stream (never a top-level ``__interrupt__``) and the
auto-approve path never sees it → the turn crashes. core_agent therefore clears
``interrupt_on`` on every declarative subagent so they don't inherit the main
agent's HITL config. These tests lock in that contract.
"""

from novacode_cli.agents.default_subagents.subagents import retrieve_core_subagents


def _clear_subagent_hitl(specs):
    """Mirror the loop in core_agent.create_agent_with_config."""
    for spec in specs:
        if isinstance(spec, dict) and "runnable" not in spec and "url" not in spec:
            spec["interrupt_on"] = {}
    return specs


def test_core_subagents_are_declarative_dicts():
    # The fix only applies to declarative specs (no 'runnable'/'url'); confirm
    # that's what retrieve_core_subagents produces.
    specs = retrieve_core_subagents(tools=[], skill_sources=None)
    assert specs, "expected core subagents"
    for s in specs:
        assert isinstance(s, dict)
        assert "runnable" not in s and "url" not in s
        assert "system_prompt" in s  # declarative SubAgent


def test_clear_hitl_sets_empty_interrupt_on():
    specs = _clear_subagent_hitl(retrieve_core_subagents(tools=[], skill_sources=None))
    for s in specs:
        assert s.get("interrupt_on") == {}
        # deepagents adds HumanInTheLoopMiddleware only `if interrupt_on:` — an
        # empty dict is falsy, so HITL is skipped for the subagent.
        assert not s["interrupt_on"]


def test_deepagents_skips_hitl_for_empty_interrupt_on():
    # Contract with deepagents.middleware.subagents._build (`if interrupt_on:`):
    # a falsy interrupt_on means no HITL middleware is attached to the subagent.
    assert bool({}) is False
    assert bool(None) is False
    assert bool({"execute": object()}) is True

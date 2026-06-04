"""Tests for conversation-context grounding of /research and /ralph."""

import asyncio

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from novacode_cli.prompts import render_template
from novacode_cli.context import ContextManager


class _State:
    def __init__(self, msgs):
        self.values = {"messages": msgs}


class _Agent:
    def __init__(self, msgs):
        self._m = msgs

    async def aget_state(self, config):
        return _State(self._m)


def test_digest_extracts_user_and_assistant_skips_tools():
    msgs = [
        HumanMessage(content="build a parser for CSV"),
        AIMessage(content="done, added parser.py"),
        ToolMessage(content="tool noise", tool_call_id="x"),
        HumanMessage(content="now add tests"),
    ]
    d = asyncio.run(ContextManager().digest(_Agent(msgs), "t1"))
    assert "build a parser for CSV" in d
    assert "now add tests" in d
    assert "tool noise" not in d
    assert d.startswith("User:")


def test_digest_empty_when_no_history():
    assert asyncio.run(ContextManager().digest(_Agent([]), "t1")) == ""


def test_digest_handles_unreadable_state():
    class _BadAgent:
        async def aget_state(self, config):
            raise RuntimeError("no state")

    assert asyncio.run(ContextManager().digest(_BadAgent(), "t1")) == ""


def test_research_template_includes_context_when_present():
    d = "User: build a parser\n\nAssistant: ok"
    r = render_template(
        "research_swarm.jinja",
        mode="general",
        research_query="q",
        base_dir=".nova/research",
        agents=["web-researcher"],
        fast_mode=False,
        mode_description="x",
        agent_count=1,
        conversation_context=d,
    )
    assert "Prior Conversation" in r and "build a parser" in r
    # Absent context -> no section.
    r0 = render_template(
        "research_swarm.jinja",
        mode="general",
        research_query="q",
        base_dir=".nova/research",
        agents=["web-researcher"],
        fast_mode=False,
        mode_description="x",
        agent_count=1,
        conversation_context="",
    )
    assert "Prior Conversation" not in r0


def test_ralph_template_includes_context_when_present():
    d = "User: now add tests\n\nAssistant: sure"
    rl = render_template(
        "ralph_iteration.jinja",
        iteration_display="1",
        task="do it",
        conversation_context=d,
    )
    assert "Prior Conversation" in rl and "now add tests" in rl
    r0 = render_template(
        "ralph_iteration.jinja",
        iteration_display="1",
        task="do it",
        conversation_context="",
    )
    assert "Prior Conversation" not in r0

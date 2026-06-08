"""Tests for live steering injection.

Steering must (a) land in the system prompt as a standing instruction AND (b)
surface a newly-added steer as a one-time live user message so the agent —
mid-tool-loop — actually reads and acts on it instead of ignoring a passive
system-prompt line.
"""

from __future__ import annotations

from langchain_core.messages import HumanMessage

from novacode_cli.bootstrap.steering import SteeringInstruction, SteeringMiddleware


class _Req:
    """Minimal stand-in for langchain's ModelRequest (only what _inject uses)."""

    def __init__(self, system_prompt="BASE", messages=None):
        self.system_prompt = system_prompt
        self.messages = messages if messages is not None else []
        self.applied: dict = {}

    def override(self, **kw):
        out = _Req(self.system_prompt, kw.get("messages", self.messages))
        out.applied = kw
        return out


def _content(m):
    return str(getattr(m, "content", m))


def test_steer_in_system_prompt_and_delivered_as_message_once():
    instrs = [SteeringInstruction("steer", "focus on performance")]
    mw = SteeringMiddleware(instructions=instrs)

    out1 = mw._inject(_Req("BASE", [HumanMessage("hi")]))
    sm = out1.applied["system_message"]
    assert "User Steering" in sm.content
    assert "focus on performance" in sm.content
    # Newly added -> surfaced as a live user message.
    assert "messages" in out1.applied
    last = out1.applied["messages"][-1]
    assert "incorporate it into your current task" in _content(last)
    assert "focus on performance" in _content(last)

    # Next call: nothing new -> still in system prompt, but NOT re-delivered.
    out2 = mw._inject(_Req("BASE", [HumanMessage("hi")]))
    assert "focus on performance" in out2.applied["system_message"].content
    assert "messages" not in out2.applied


def test_new_steer_added_later_is_delivered():
    instrs = [SteeringInstruction("steer", "first")]
    mw = SteeringMiddleware(instructions=instrs)
    mw._inject(_Req())  # delivers "first"

    instrs.append(SteeringInstruction("steer", "second — added mid-run"))
    out = mw._inject(_Req("BASE", [HumanMessage("x")]))
    last = _content(out.applied["messages"][-1])
    assert "second — added mid-run" in last
    assert "first" not in last  # already delivered, not repeated as a message
    # both still persist in the system prompt
    assert "first" in out.applied["system_message"].content
    assert "second — added mid-run" in out.applied["system_message"].content


def test_noop_when_no_instructions():
    mw = SteeringMiddleware(instructions=[])
    req = _Req("BASE", [])
    assert mw._inject(req) is req  # unchanged passthrough


def test_disabled_is_passthrough():
    mw = SteeringMiddleware(instructions=[SteeringInstruction("s", "x")], enabled=False)
    req = _Req("BASE", [])
    assert mw._inject(req) is req


def test_reset_conversation_preserves_list_identity():
    """The agent middleware holds the same list; reset must mutate it in place."""
    from novacode_cli.states.Session import SessionState

    ss = SessionState()
    shared = ss.steering_instructions  # the object the middleware would hold
    shared.append(SteeringInstruction("steer", "keep me out after clear"))
    ss.reset_conversation()
    assert ss.steering_instructions is shared  # same object (not reassigned)
    assert ss.steering_instructions == []  # cleared in place

"""Tests for the UI-agnostic agent event stream (Phase 0 of the Textual migration).

These exercise ``run_agent_stream`` against a mocked ``agent.astream`` and assert
the emitted :mod:`novacode_cli.ui_events` sequence — the contract both the legacy
renderer and the new Textual UI rely on.

Runnable directly (``python tests/test_agent_stream.py``) or via pytest.
"""

from __future__ import annotations

import asyncio
import types

import novacode_cli.ui_events as ev
from novacode_cli.core.agent_loop import iterate_agent_events


class _Chunk:
    """A fake AIMessageChunk. Name must NOT be 'AIMessage' (that marks a completed,
    non-streamed message whose text is intentionally not re-accumulated)."""

    def __init__(self, mid, blocks, *, usage=None):
        self.id = mid
        self._blocks = blocks
        self.usage_metadata = usage or {"input_tokens": 12, "output_tokens": 4}

    @property
    def content_blocks(self):
        return self._blocks


class _State:
    def __init__(self, msgs):
        self.values = {"messages": msgs}


class _SessionState:
    thread_id = "t1"


def _collect(agent, user_input="hi", on_interrupt=None):
    """Drive iterate_agent_events to completion, resolving interrupts via on_interrupt."""

    async def _run():
        out = []
        async for e in iterate_agent_events(user_input, agent, "nova-agent", _SessionState()):
            out.append(e)
            if isinstance(e, ev.InterruptRequest):
                resp = on_interrupt(e) if on_interrupt else None
                e.future.set_result(resp)
        return out

    return asyncio.run(_run())


def test_happy_path_text_tool_todo():
    class Agent:
        async def aget_state(self, config):
            return _State([])

        async def astream(self, inp, **kw):
            yield ((), "messages", (_Chunk("m1", [{"type": "text", "text": "Hello "}]), {}))
            yield ((), "messages", (_Chunk("m1", [{"type": "text", "text": "world"}]), {}))
            yield (
                (),
                "messages",
                (
                    _Chunk(
                        "m2",
                        [
                            {
                                "type": "tool_call_chunk",
                                "name": "shell",
                                "id": "tc1",
                                "args": {"command": "ls"},
                                "index": 0,
                            }
                        ],
                    ),
                    {},
                ),
            )
            yield ((), "updates", {"model": {"todos": [{"content": "x", "status": "pending"}]}})

        async def aupdate_state(self, **kw):
            pass

    evts = _collect(Agent())
    kinds = [type(e).__name__ for e in evts]

    assert any(isinstance(e, ev.AssistantMessage) and e.text == "Hello world" for e in evts), kinds
    assert any(isinstance(e, ev.ToolCall) and e.name == "shell" for e in evts), kinds
    assert any(isinstance(e, ev.TodoUpdate) for e in evts), kinds
    assert any(isinstance(e, ev.UsageUpdate) for e in evts), kinds
    assert isinstance(evts[0], ev.StatusUpdate)
    assert isinstance(evts[-1], ev.Done) and evts[-1].had_response


def test_question_interrupt_resumes():
    class Agent:
        def __init__(self):
            self.calls = 0

        async def aget_state(self, config):
            return _State([])

        async def astream(self, inp, **kw):
            self.calls += 1
            if self.calls == 1:
                # Pause with a question interrupt.
                yield (
                    (),
                    "updates",
                    {
                        "__interrupt__": [
                            types.SimpleNamespace(
                                value={"type": "question", "request": {"prompt": "pick"}},
                                id="i1",
                            )
                        ]
                    },
                )
            else:
                # Resumed: emit the final answer.
                yield (
                    (),
                    "messages",
                    (_Chunk("m9", [{"type": "text", "text": "done"}]), {}),
                )

        async def aupdate_state(self, **kw):
            pass

    seen = {}

    def on_interrupt(req: ev.InterruptRequest):
        seen["kind"] = req.kind
        seen["payload"] = req.payload
        return {"answer": "A"}  # question response object

    evts = _collect(Agent(), on_interrupt=on_interrupt)

    assert seen["kind"] == "question"
    assert seen["payload"] == {"prompt": "pick"}
    assert any(isinstance(e, ev.AssistantMessage) and e.text == "done" for e in evts), [
        type(e).__name__ for e in evts
    ]
    assert isinstance(evts[-1], ev.Done)


def test_approval_interrupt_fires_and_clears_notification():
    """An interrupt raises an 'approval' notification BEFORE it's surfaced (so the
    badge/hook fire the moment permission is needed) and clears it once resolved."""

    class _RecordingSS:
        thread_id = "t1"

        def __init__(self):
            self.added: list = []
            self.registered: list = []
            self.dismissed: list = []
            self._n = 0

        def add_notification(
            self, level, title, message, source, *, action_id=None, action_type=None
        ):
            self._n += 1
            nid = f"n{self._n}"
            self.added.append((level, action_id, action_type, nid))
            return nid

        def register_pending_approval(self, action_id, future):
            self.registered.append(action_id)

        def dismiss_notification(self, nid):
            self.dismissed.append(nid)
            return True

    class Agent:
        def __init__(self):
            self.calls = 0

        async def aget_state(self, config):
            return _State([])

        async def astream(self, inp, **kw):
            self.calls += 1
            if self.calls == 1:
                yield (
                    (),
                    "updates",
                    {
                        "__interrupt__": [
                            types.SimpleNamespace(
                                value={"type": "question", "request": {"prompt": "pick"}},
                                id="i1",
                            )
                        ]
                    },
                )
            else:
                yield ((), "messages", (_Chunk("m9", [{"type": "text", "text": "done"}]), {}))

        async def aupdate_state(self, **kw):
            pass

    ss = _RecordingSS()

    async def _run():
        async for e in iterate_agent_events("hi", Agent(), "nova-agent", ss):
            if isinstance(e, ev.InterruptRequest):
                # Raised BEFORE the interrupt surfaced (the ordering fix).
                assert ss.added, "notification must precede the interrupt"
                e.future.set_result({"answer": "A"})

    asyncio.run(_run())

    assert ss.added, ss.added
    level, action_id, action_type, nid = ss.added[0]
    assert level == "approval"
    assert action_id == "i1"
    assert action_type == "select"
    assert "i1" in ss.registered
    assert nid in ss.dismissed  # cleared once resolved


def test_approval_notification_suppressed_when_auto_approving():
    """A /remote turn auto-approves (auto_approve=True) — no permission is asked of
    the user, so the approval notification must NOT fire (it would just be noise)."""

    class _RecordingSS:
        thread_id = "t1"
        auto_approve = True  # e.g. a /remote turn

        def __init__(self):
            self.added: list = []
            self.registered: list = []

        def add_notification(self, *a, **kw):
            self.added.append((a, kw))
            return "n1"

        def register_pending_approval(self, action_id, future):
            self.registered.append(action_id)

        def dismiss_notification(self, nid):
            return True

    class Agent:
        def __init__(self):
            self.calls = 0

        async def aget_state(self, config):
            return _State([])

        async def astream(self, inp, **kw):
            self.calls += 1
            if self.calls == 1:
                yield (
                    (),
                    "updates",
                    {
                        "__interrupt__": [
                            types.SimpleNamespace(
                                value={"type": "question", "request": {"prompt": "pick"}},
                                id="i1",
                            )
                        ]
                    },
                )
            else:
                yield ((), "messages", (_Chunk("m9", [{"type": "text", "text": "done"}]), {}))

        async def aupdate_state(self, **kw):
            pass

    ss = _RecordingSS()

    async def _run():
        async for e in iterate_agent_events("hi", Agent(), "nova-agent", ss):
            if isinstance(e, ev.InterruptRequest):
                e.future.set_result({"answer": "A"})

    asyncio.run(_run())

    # The interrupt was still surfaced + resolved, but no notification was raised.
    assert ss.added == [], ss.added
    assert ss.registered == [], ss.registered


class _PolicyRecordingSS:
    """Session state that records notifications and never auto-approves."""

    thread_id = "t1"
    auto_approve = False
    plan_mode_enabled = False

    def __init__(self):
        self.added: list = []
        self.registered: list = []

    def add_notification(self, *a, **kw):
        self.added.append((a, kw))
        return "n1"

    def register_pending_approval(self, action_id, future):
        self.registered.append(action_id)

    def dismiss_notification(self, nid):
        return True


def _tool_interrupt_agent(command):
    """Agent that raises a tool HITL interrupt for ``command`` then answers."""

    class Agent:
        def __init__(self):
            self.calls = 0

        async def aget_state(self, config):
            return _State([])

        async def astream(self, inp, **kw):
            self.calls += 1
            if self.calls == 1:
                yield (
                    (),
                    "updates",
                    {
                        "__interrupt__": [
                            types.SimpleNamespace(
                                value={
                                    "action_requests": [
                                        {
                                            "name": "shell",
                                            "args": {"command": command},
                                            "description": "run",
                                        }
                                    ],
                                    "review_configs": [],
                                },
                                id="i1",
                            )
                        ]
                    },
                )
            else:
                yield ((), "messages", (_Chunk("m9", [{"type": "text", "text": "done"}]), {}))

        async def aupdate_state(self, **kw):
            pass

    return Agent()


def _drive(agent, ss, on_interrupt=None):
    seen = {"interrupts": 0}

    async def _run():
        async for e in iterate_agent_events("hi", agent, "nova-agent", ss):
            if isinstance(e, ev.InterruptRequest):
                seen["interrupts"] += 1
                e.future.set_result(
                    on_interrupt(e)
                    if on_interrupt
                    else {"decisions": [{"type": "approve"}], "any_rejected": False}
                )

    asyncio.run(_run())
    return seen


def test_policy_allow_tool_resolves_without_interrupt():
    """A policy-allowed command (``git status``) is auto-approved in the loop:
    no InterruptRequest is surfaced and no approval notification is raised."""
    from novacode_cli.security.policy import reset_policy_cache

    reset_policy_cache()
    ss = _PolicyRecordingSS()
    seen = _drive(_tool_interrupt_agent("git status"), ss)
    assert seen["interrupts"] == 0
    assert ss.added == []


def test_policy_deny_tool_rejected_without_prompt():
    """A policy-denied command (``rm -rf /``) is rejected without a prompt."""
    from novacode_cli.security.policy import reset_policy_cache

    reset_policy_cache()
    ss = _PolicyRecordingSS()
    seen = _drive(_tool_interrupt_agent("rm -rf /"), ss)
    assert seen["interrupts"] == 0
    assert ss.added == []


def test_policy_ask_tool_still_interrupts():
    """An ambiguous command still surfaces the InterruptRequest + notification."""
    from novacode_cli.security.policy import reset_policy_cache

    reset_policy_cache()
    ss = _PolicyRecordingSS()
    seen = _drive(_tool_interrupt_agent("frobnicate --now"), ss)
    assert seen["interrupts"] == 1
    assert ss.added, "ask path must raise an approval notification"


def test_enter_plan_mode_engages_read_only_enforcement():
    """When the core agent calls enter_plan_mode, the loop flips the session's
    plan_mode_enabled flag so the pre-HITL gate starts blocking writes/shell."""

    class _SS:
        thread_id = "t1"
        plan_mode_enabled = False

    ss = _SS()

    class Agent:
        async def aget_state(self, config):
            return _State([])

        async def astream(self, inp, **kw):
            yield (
                (),
                "messages",
                (
                    _Chunk(
                        "m1",
                        [
                            {
                                "type": "tool_call_chunk",
                                "name": "enter_plan_mode",
                                "id": "tc1",
                                "args": {"reason": "complex refactor"},
                                "index": 0,
                            }
                        ],
                    ),
                    {},
                ),
            )

        async def aupdate_state(self, **kw):
            pass

    async def _run():
        async for _e in iterate_agent_events("hi", Agent(), "nova-agent", ss):
            pass

    asyncio.run(_run())
    assert ss.plan_mode_enabled is True


def test_out_of_band_hermes_messages_are_dropped():
    """Hermes review/refine model calls run out-of-band but inherit the graph's
    message-stream callback, so their output (e.g. a regenerated SKILL.md) shows
    up in the 'messages' stream tagged nova_oob. It must never render as a Nova
    assistant message — only the real agent text does."""

    class Agent:
        async def aget_state(self, config):
            return _State([])

        async def astream(self, inp, **kw):
            # Real agent token.
            yield ((), "messages", (_Chunk("m1", [{"type": "text", "text": "real answer"}]), {}))
            # Out-of-band refine leak (explicit marker).
            yield (
                (),
                "messages",
                (
                    _Chunk("m2", [{"type": "text", "text": "--- name: leaked-skill ---"}]),
                    {"nova_oob": True},
                ),
            )
            # Out-of-band review leak (tag-based).
            yield (
                (),
                "messages",
                (
                    _Chunk("m3", [{"type": "text", "text": "LEAKED LESSON"}]),
                    {"tags": ["nova", "hermes", "oob-review"]},
                ),
            )

        async def aupdate_state(self, **kw):
            pass

    evts = _collect(Agent())
    deltas = [e.text for e in evts if isinstance(e, ev.TextDelta)]
    assert "real answer" in deltas
    assert all("leaked-skill" not in t for t in deltas), deltas
    assert all("LEAKED" not in t for t in deltas), deltas
    msgs = [e.text for e in evts if isinstance(e, ev.AssistantMessage)]
    assert all("leaked-skill" not in m and "LEAKED" not in m for m in msgs), msgs


def test_text_streams_as_deltas_then_commits():
    class Agent:
        async def aget_state(self, config):
            return _State([])

        async def astream(self, inp, **kw):
            yield ((), "messages", (_Chunk("m1", [{"type": "text", "text": "Hel"}]), {}))
            yield ((), "messages", (_Chunk("m1", [{"type": "text", "text": "lo"}]), {}))

        async def aupdate_state(self, **kw):
            pass

    evts = _collect(Agent())
    kinds = [type(e).__name__ for e in evts]
    # Two streamed deltas, then a committed message — deltas before the commit.
    assert kinds.count("TextDelta") == 2, kinds
    assert "AssistantMessage" in kinds, kinds
    assert kinds.index("TextDelta") < kinds.index("AssistantMessage"), kinds
    msg = next(e for e in evts if isinstance(e, ev.AssistantMessage))
    assert msg.text == "Hello"


def test_usage_captured_from_empty_final_chunk():
    """Providers attach usage_metadata to a final chunk with NO content blocks.

    Regression: the usage capture used to run after an empty-blocks early-continue,
    so those token counts were dropped and /context always showed 0.
    """

    class Agent:
        async def aget_state(self, config):
            return _State([])

        async def astream(self, inp, **kw):
            # Real text, but no usage on the content chunks...
            yield ((), "messages", (_Chunk("m1", [{"type": "text", "text": "Hi"}], usage={}), {}))
            # ...then a final, content-less chunk that carries the usage.
            yield (
                (),
                "messages",
                (_Chunk("m1", [], usage={"input_tokens": 4321, "output_tokens": 99}), {}),
            )

        async def aupdate_state(self, **kw):
            pass

    evts = _collect(Agent())
    usage = next((e for e in evts if isinstance(e, ev.UsageUpdate)), None)
    assert usage is not None, [type(e).__name__ for e in evts]
    assert usage.input_tokens == 4321
    assert usage.output_tokens == 99


def test_cancellation_emits_cancelled():
    class Agent:
        async def aget_state(self, config):
            return _State([])

        async def astream(self, inp, **kw):
            raise asyncio.CancelledError
            yield  # pragma: no cover (makes this an async generator)

        async def aupdate_state(self, **kw):
            pass

    evts = _collect(Agent())
    assert any(isinstance(e, ev.Cancelled) for e in evts), [type(e).__name__ for e in evts]


if __name__ == "__main__":
    test_happy_path_text_tool_todo()
    test_question_interrupt_resumes()
    test_cancellation_emits_cancelled()
    print("ALL TESTS PASSED")

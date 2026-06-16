"""Shared LangGraph agent iteration loop.

``iterate_agent_events`` is the single canonical async generator for driving a
LangGraph agent stream. It yields :mod:`novacode_cli.ui_events` dataclass
instances that describe what happened — text, tool calls, interrupts, etc. —
without coupling to any particular rendering strategy.

Two consumers wrap it:

* :func:`novacode_cli.agent_stream.run_agent_stream` — forwards events directly
  (for the Textual TUI and test code).
* :func:`novacode_cli.ui.execution.execute_task` — consumes events and renders
  each to the ``rich`` console.

Bug fixes and feature additions belong *here* so both UIs benefit immediately.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from typing import Any

from langchain.agents.middleware.human_in_the_loop import HITLRequest
from langchain_core.messages import HumanMessage, ToolMessage
from langgraph.errors import GraphInterrupt
from langgraph.types import Command, Interrupt
from pydantic import TypeAdapter, ValidationError


from novacode_cli.config.config import COLORS, get_agent_color
from novacode_cli.file_ops import get_session_file_op_tracker
from novacode_cli.ui.input_preparation import (
    build_agent_config,
    get_agent_display_name,
    prepare_input_content,
)
from novacode_cli.ui.streaming import (
    TOOL_CATEGORIES,
    TOOL_ICONS,
    format_condensed_activity,
    is_internal_context_text,
)
from novacode_cli.ui.subagent_tracking import (
    SubagentTracker,
    format_duration,
    get_status_icon,
)
from novacode_cli.ui.ui_elements import (
    format_tool_display,
    format_tool_message_content,
    format_tool_result_preview,
)
from novacode_cli import ui_events as ev

_HITL_REQUEST_ADAPTER = TypeAdapter(HITLRequest)


def default_interrupt_response(kind: str) -> Any:
    """Safe fallback for an unresolved :class:`~novacode_cli.ui_events.InterruptRequest`.

    Consumers resolve the request's future in their own coroutines; if that
    handler raises before calling ``set_result``, the agent loop would await the
    future forever. Consumers should resolve with this value in a ``finally`` so
    the turn fails closed (reject) instead of hanging.
    """
    if kind == "tool":
        return {"decisions": [], "any_rejected": True}
    if kind == "plan":
        return {
            "response": {"approved": False, "action": "reject", "feedback": ""},
            "state_update": {},
        }
    # "question" and anything else: an empty response is benign.
    return {}


async def _safe_stream(stream_gen: AsyncIterator[Any]) -> AsyncIterator[Any]:
    """Wraps an async generator and swallows GraphInterrupt.

    This ensures that when the graph execution is suspended due to an interrupt,
    the resulting GraphInterrupt exception is caught and the stream completes
    normally instead of crashing the iteration loop.
    """
    try:
        async for chunk in stream_gen:
            yield chunk
    except GraphInterrupt:
        pass



async def iterate_agent_events(  # noqa: C901, PLR0912, PLR0915
    user_input: str,
    agent,
    assistant_id: str | None,
    session_state,
    *,
    backend=None,
    image_tracker=None,
    seen_message_ids: set[str] | None = None,
    skip_file_mentions: bool = False,
) -> AsyncIterator[Any]:
    """Run the agent and yield UI events.

    Yields instances from :mod:`novacode_cli.ui_events`. Terminates with a
    :class:`~novacode_cli.ui_events.Done`, :class:`~novacode_cli.ui_events.Cancelled`,
    or :class:`~novacode_cli.ui_events.Error` event.
    """
    loop = asyncio.get_running_loop()

    if getattr(session_state, "plan_mode_enabled", False):
        directive = (
            "[System Directive: You are entering a new planning phase. "
            "Any previous plan approvals have expired. You are currently restricted to "
            "read-only tools. Design a new plan for the request below, and call `exit_plan_mode(plan=...)` "
            "to request user approval. Do NOT call write_todos or attempt to implement yet.]\n\n"
        )
        if not user_input.startswith("[System Directive:"):
            user_input = directive + user_input

    message_content = await prepare_input_content(
        user_input, image_tracker, skip_file_mentions=skip_file_mentions
    )

    thread_id = session_state.thread_id
    config = build_agent_config(thread_id, assistant_id)

    agent_display_name = get_agent_display_name(assistant_id)
    agent_colors = (
        get_agent_color(assistant_id)
        if assistant_id and assistant_id != "nova-agent"
        else (COLORS["success"] if assistant_id == "nova-agent" else COLORS["agent"])
    )

    if seen_message_ids is None:
        seen_message_ids = set()

    file_op_tracker = get_session_file_op_tracker(assistant_id=assistant_id, backend=backend)
    subagent_tracker = SubagentTracker()

    displayed_tool_ids: set[str] = set()
    tool_call_buffers: dict[str | int, dict] = {}
    tool_call_to_name: dict[str, str] = {}
    pending_text = ""
    current_ai_message_id: str | None = None
    _post_summarization = False
    has_responded = False
    _streamed_pending = False  # whether TextDelta(s) were emitted for the buffer

    captured = ev.UsageUpdate()

    # Drain any Nova events queued by the middleware (review cycles, skill
    # activity) into proper ContextMessage events for both UIs.
    def _drain_nova_events() -> list[ev.ContextMessage]:
        try:
            from novacode_cli.events import nova_event_log

            events: list[ev.ContextMessage] = []
            while nova_event_log:
                etype, icon, color, msg = nova_event_log.pop(0)
                events.append(
                    ev.ContextMessage(message=msg, event_type=etype, icon=icon, color=color)
                )
            return events
        except Exception:
            return []

    yield ev.StatusUpdate(f"{agent_display_name} is thinking...")
    for _ctx in _drain_nova_events():
        yield _ctx

    def _flush_events() -> list:
        """Finalize buffered prose into events.

        Returns ``[AssistantMessage]`` to commit, ``[TextDiscard]`` to drop a
        live preview that was suppressed (internal context / dedup), or ``[]``.
        """
        nonlocal pending_text, current_ai_message_id, _post_summarization
        nonlocal has_responded, _streamed_pending

        def _discard() -> list:
            nonlocal pending_text, current_ai_message_id, _streamed_pending
            pending_text = ""
            current_ai_message_id = None
            had = _streamed_pending
            _streamed_pending = False
            return [ev.TextDiscard()] if had else []

        if not pending_text.strip():
            return _discard()

        if _post_summarization:
            _post_summarization = False
            if is_internal_context_text(pending_text):
                return _discard()

        if is_internal_context_text(pending_text):
            # Internal context echo — never shown to the user.
            return _discard()

        if current_ai_message_id and current_ai_message_id in seen_message_ids:
            return _discard()

        text = pending_text.rstrip()
        msg = ev.AssistantMessage(
            text=text, agent_name=agent_display_name, agent_color=agent_colors
        )
        if current_ai_message_id:
            seen_message_ids.add(current_ai_message_id)
        current_ai_message_id = None
        pending_text = ""
        has_responded = True
        _streamed_pending = False
        return [msg]

    # Seed dedup set with pre-existing messages.
    pre_stream_msg_count: int | None = None
    try:
        _pre_state = await agent.aget_state(config)
        _pre_msgs = _pre_state.values.get("messages", [])
        pre_stream_msg_count = len(_pre_msgs)
        for _m in _pre_msgs:
            _mid = getattr(_m, "id", None)
            if _mid:
                seen_message_ids.add(_mid)
    except Exception:
        pass

    stream_input: Any = {"messages": [{"role": "user", "content": message_content}]}
    _current_stream_gen: Any = None

    from novacode_cli.tools.plan_mode_tools import _auto_approve_var
    auto_approve_val = bool(getattr(session_state, "auto_approve", False))
    token = _auto_approve_var.set(auto_approve_val)

    try:
        while True:
            interrupt_occurred = False
            hitl_response: dict[str, Any] = {}
            command_state_update: dict = {}
            # Collected interrupts to resolve after the stream pauses:
            # list of (interrupt_id, kind, payload)
            pending_interrupts: list[tuple[str, str, Any]] = []
            subagent_tracker.clear()
            current_ai_message_id = None

            _current_stream_gen = agent.astream(
                stream_input,
                stream_mode=["updates", "messages"],
                subgraphs=True,
                config=config,
                durability="exit",
            )

            async for chunk in _safe_stream(_current_stream_gen):
                # Surface any Nova learning events (review cycles) as they happen
                # so the UI's live indicator updates mid-turn rather than only at
                # turn boundaries.
                for _ctx in _drain_nova_events():
                    yield _ctx

                if not isinstance(chunk, tuple) or len(chunk) != 3:
                    continue
                _namespace, current_stream_mode, data = chunk

                if current_stream_mode == "updates":
                    if not isinstance(data, dict):
                        continue

                    chunk_data = None
                    for _node_state in data.values():
                        if isinstance(_node_state, dict):
                            if chunk_data is None:
                                chunk_data = _node_state
                            if "todos" in _node_state:
                                _new_todos = _node_state["todos"]
                                yield ev.TodoUpdate(
                                    todos=_new_todos,
                                    agent_name=_node_state.get("agent_name"),
                                )
                                break

                    if "__interrupt__" in data:
                        interrupts: list[Interrupt] = data["__interrupt__"]
                        for interrupt_obj in interrupts:
                            interrupt_value = interrupt_obj.value
                            # ask_question interrupt
                            if isinstance(interrupt_value, dict) and (
                                interrupt_value.get("type") == "question"
                                or (
                                    interrupt_value.get("type") == "tool"
                                    and interrupt_value.get("name")
                                    in ("ask_question", "ask_user_question")
                                )
                            ):
                                pending_interrupts.append(
                                    (
                                        interrupt_obj.id,
                                        "question",
                                        interrupt_value.get("request", {}),
                                    )
                                )
                                interrupt_occurred = True
                                continue
                            # plan approval interrupt
                            if (
                                isinstance(interrupt_value, dict)
                                and interrupt_value.get("type") == "plan_approval"
                            ):
                                pending_interrupts.append(
                                    (interrupt_obj.id, "plan", interrupt_value)
                                )
                                interrupt_occurred = True
                                continue
                            # generic tool HITL interrupt
                            try:
                                validated = _HITL_REQUEST_ADAPTER.validate_python(interrupt_value)
                                pending_interrupts.append((interrupt_obj.id, "tool", validated))
                                interrupt_occurred = True
                            except ValidationError as e:
                                yield ev.Error(f"Invalid HITL request data: {e}")
                                raise

                    # summarization detection
                    if chunk_data and isinstance(chunk_data, dict):
                        _msgs = chunk_data.get("messages")
                        if _msgs is not None:
                            if hasattr(_msgs, "value"):
                                _msgs = _msgs.value
                            if not isinstance(_msgs, list):
                                try:
                                    _msgs = list(_msgs)
                                except TypeError:
                                    _msgs = []
                            for _msg in _msgs:
                                if (
                                    getattr(_msg, "additional_kwargs", {}).get("lc_source")
                                    == "summarization"
                                ):
                                    _post_summarization = True
                                    break

                elif current_stream_mode == "messages":
                    is_main_agent = _namespace == ()
                    is_subagent = _namespace != ()
                    subagent_type_for_ns = _namespace[0] if is_subagent and _namespace else None

                    if not isinstance(data, tuple) or len(data) != 2:
                        continue
                    message, _metadata = data

                    # Hermes runs its review/skill-refine model calls out-of-band
                    # as fire-and-forget asyncio tasks spawned from inside the
                    # agent's model call. Those tasks inherit LangGraph's message
                    # streaming callback via contextvars, so their full output
                    # (e.g. a regenerated SKILL.md) would otherwise surface here as
                    # a "Nova" assistant message. They're tagged nova_oob — drop
                    # them; their user-facing notices come via nova_event_log.
                    if isinstance(_metadata, dict) and (
                        _metadata.get("nova_oob") or "hermes" in (_metadata.get("tags") or [])
                    ):
                        continue

                    _ckpt_ns = (
                        _metadata.get("langgraph_checkpoint_ns", "")
                        if isinstance(_metadata, dict)
                        else ""
                    )
                    if _ckpt_ns and "before_model" in _ckpt_ns:
                        continue

                    if hasattr(message, "id") and message.id in seen_message_ids:
                        continue
                    if isinstance(message, HumanMessage):
                        continue

                    if isinstance(message, ToolMessage):
                        async for _e in _handle_tool_message(
                            message,
                            namespace=_namespace,
                            is_main_agent=is_main_agent,
                            is_subagent=is_subagent,
                            tool_call_to_name=tool_call_to_name,
                            displayed_tool_ids=displayed_tool_ids,
                            seen_message_ids=seen_message_ids,
                            file_op_tracker=file_op_tracker,
                            subagent_tracker=subagent_tracker,
                            agent_display_name=agent_display_name,
                            flush_text=_flush_events,
                        ):
                            yield _e
                        continue

                    # Build content blocks
                    if hasattr(message, "content_blocks"):
                        blocks: list[dict] = message.content_blocks
                    else:
                        blocks = []
                        raw = getattr(message, "content", "")
                        if isinstance(raw, str) and raw:
                            blocks.append({"type": "text", "text": raw})
                        elif isinstance(raw, list):
                            for item in raw:
                                if isinstance(item, dict):
                                    blocks.append(item)
                                elif isinstance(item, str) and item:
                                    blocks.append({"type": "text", "text": item})
                        for tc in getattr(message, "tool_call_chunks", []) or []:
                            if isinstance(tc, dict):
                                blocks.append({"type": "tool_call_chunk", **tc})

                    # Usage capture (main agent). MUST run before the empty-blocks
                    # early-continue below: providers (Ollama, OpenAI, Anthropic)
                    # attach usage_metadata to a *final chunk with empty content*,
                    # which has no blocks — skipping it here lost all token counts.
                    if is_main_agent:
                        usage = getattr(message, "usage_metadata", None)
                        if usage:
                            cache_read = usage.get("cache_read_input_tokens", 0)
                            cache_create = usage.get("cache_creation_input_tokens", 0)
                            actual = usage.get("input_tokens", 0) + cache_read + cache_create
                            out = usage.get("output_tokens", 0)
                            if actual or out:
                                captured.input_tokens = max(captured.input_tokens, actual)
                                captured.output_tokens = max(captured.output_tokens, out)
                                captured.cache_read_tokens = max(
                                    captured.cache_read_tokens, cache_read
                                )
                                captured.cache_creation_tokens = max(
                                    captured.cache_creation_tokens, cache_create
                                )

                    if not blocks:
                        continue

                    _is_completed_msg = type(message).__name__ == "AIMessage"

                    for block in blocks:
                        btype = block.get("type")
                        if btype == "text":
                            text = block.get("text", "")
                            if text and is_main_agent and not _is_completed_msg:
                                current_ai_message_id = getattr(message, "id", None)
                                pending_text += text
                                _streamed_pending = True
                                yield ev.TextDelta(text)
                        elif btype in ("reasoning", "thinking"):
                            if is_main_agent and not _is_completed_msg:
                                rtext = (
                                    block.get("text")
                                    or block.get("reasoning")
                                    or block.get("thinking")
                                    or ""
                                )
                                if rtext:
                                    yield ev.ReasoningDelta(rtext)
                        elif btype in ("tool_call_chunk", "tool_call"):
                            async for _e in _handle_tool_call_chunk(
                                block,
                                is_main_agent=is_main_agent,
                                namespace=_namespace,
                                subagent_type_for_ns=subagent_type_for_ns,
                                tool_call_buffers=tool_call_buffers,
                                displayed_tool_ids=displayed_tool_ids,
                                tool_call_to_name=tool_call_to_name,
                                file_op_tracker=file_op_tracker,
                                subagent_tracker=subagent_tracker,
                                flush_text=_flush_events,
                            ):
                                # The agent can self-engage plan mode: when it calls
                                # enter_plan_mode, flip the session flag so the
                                # pre-HITL gate (check_plan_mode_blocked) starts
                                # blocking writes/shell for the rest of the turn —
                                # making the agent read-only until exit_plan_mode is
                                # approved. exit_plan_mode's approval clears it.
                                if (
                                    isinstance(_e, ev.ToolCall)
                                    and _e.name == "enter_plan_mode"
                                    and is_main_agent
                                ):
                                    try:
                                        session_state.plan_mode_enabled = True
                                    except Exception:  # noqa: BLE001
                                        pass
                                yield _e

                    if getattr(message, "chunk_position", None) == "last":
                        if hasattr(message, "id"):
                            seen_message_ids.add(message.id)
                        for _e in _flush_events():
                            yield _e

            _current_stream_gen = None

            # Flush any trailing prose.
            for _e in _flush_events():
                yield _e

            # Resolve interrupts (graph is paused).
            if interrupt_occurred:
                any_rejected = False
                plan_approved = False
                # When the turn auto-approves (e.g. a /remote turn sets
                # auto_approve=True), no permission is actually being asked of the
                # user — the interrupt is resolved automatically — so a badge /
                # desktop notification would just be noise. Skip it there; local,
                # interactive turns (auto_approve off) still notify.
                _auto_approve = bool(getattr(session_state, "auto_approve", False))
                from novacode_cli.ui.hitl_approval import evaluate_tool_actions

                for interrupt_id, kind, payload in pending_interrupts:
                    # Pre-HITL policy gate: auto-resolve the actions that don't need
                    # a prompt (policy-allow → approve, policy-deny → reject, plus
                    # plan-mode/auto_approve) so the safe majority never interrupts
                    # and hard-denies block without asking. Only a genuine "ask"
                    # falls through to surface an InterruptRequest + notification.
                    _policy_resolutions: list[dict | None] | None = None
                    if kind == "plan" and _auto_approve:
                        # Auto-approve plan without prompting
                        hitl_response[interrupt_id] = {"approved": True, "mode": "auto"}
                        command_state_update.update({"plan_mode_enabled": False})
                        plan_approved = True

                        # Set plan_mode_enabled=False on session_state and clear plan agent
                        session_state.plan_mode_enabled = False
                        using_separate_plan_agent = (
                            hasattr(session_state, "plan_agent") and session_state.plan_agent is not None
                        )
                        if using_separate_plan_agent:
                            # Try to extract the plan content from the payload
                            inline_plan = (payload or {}).get("plan")
                            if inline_plan:
                                session_state.set_approved_plan(inline_plan)
                            session_state.clear_plan_agent()
                        session_state.plan_content = None

                        yield ev.ContextMessage(
                            "Plan Approved - switching to execution mode (auto-approved)",
                            icon="✓",
                            color="green",
                        )
                        continue

                    if kind == "tool":
                        try:
                            _policy_resolutions = evaluate_tool_actions(
                                payload,
                                session_state,
                                plan_mode_enabled=getattr(
                                    session_state, "plan_mode_enabled", False
                                ),
                            )
                        except Exception:  # noqa: BLE001 — never break the turn
                            _policy_resolutions = None
                        if _policy_resolutions is not None and all(
                            r is not None for r in _policy_resolutions
                        ):
                            _decided = [r for r in _policy_resolutions if r is not None]
                            hitl_response[interrupt_id] = {"decisions": _decided}
                            if any(d.get("type") == "reject" for d in _decided):
                                any_rejected = True
                            continue

                    fut: asyncio.Future = loop.create_future()

                    # Raise the notification BEFORE surfacing the interrupt, so the
                    # badge/notification hook fire the moment approval is needed —
                    # not after the modal is answered (the old order ran this only
                    # once the generator resumed past the yield). Skipped entirely
                    # when auto-approving (see above).
                    _notif_id: str | None = None
                    if kind in ("tool", "plan", "question") and not _auto_approve:
                        _notif_msg = (
                            "Plan requires approval"
                            if kind == "plan"
                            else (
                                "Tool action requires approval"
                                if kind == "tool"
                                else "Question requires response"
                            )
                        )
                        try:
                            _notif_id = session_state.add_notification(
                                level="approval",
                                title=_notif_msg,
                                message=str(payload)[:200],
                                source="system",
                                action_id=interrupt_id,
                                action_type=("approve" if kind in ("tool", "plan") else "select"),
                            )
                            session_state.register_pending_approval(interrupt_id, fut)
                        except Exception:  # noqa: BLE001 — never break the turn on a notification
                            pass

                    yield ev.InterruptRequest(kind=kind, payload=payload, future=fut)
                    response = await fut

                    # Resolved (via the modal or /notifications) — clear the badge
                    # so a settled approval doesn't linger as "pending".
                    if _notif_id is not None:
                        try:
                            session_state.dismiss_notification(_notif_id)
                        except Exception:  # noqa: BLE001
                            pass
                    if kind == "tool":
                        _user_decisions = list(response.get("decisions", []))
                        # Overlay policy verdicts onto the user's batch decision:
                        # policy-decided slots (allow/deny) win, only the "ask"
                        # slots take the user's choice — so a hard deny in a mixed
                        # batch is honored even if the user approved the prompt.
                        if _policy_resolutions is not None:
                            _final: list[dict] = []
                            for _i, _r in enumerate(_policy_resolutions):
                                if _r is not None:
                                    _final.append(_r)
                                elif _i < len(_user_decisions):
                                    _final.append(_user_decisions[_i])
                                else:
                                    _final.append({"type": "reject", "message": "No decision"})
                            _user_decisions = _final
                        hitl_response[interrupt_id] = {"decisions": _user_decisions}
                        if response.get("any_rejected") or any(
                            d.get("type") == "reject" for d in _user_decisions
                        ):
                            any_rejected = True
                    elif kind == "question":
                        hitl_response[interrupt_id] = response
                    elif kind == "plan":
                        resp_data = response.get("response", {})
                        hitl_response[interrupt_id] = resp_data
                        su = response.get("state_update")
                        if su:
                            command_state_update.update(su)
                        # When the plan is approved, don't resume the plan agent —
                        # the caller (TUI or CLI) handles the hand-off to the main
                        # execution agent. Resuming would let the model continue its
                        # turn and potentially re-enter plan mode.
                        if resp_data.get("approved"):
                            plan_approved = True

                if any_rejected:
                    yield ev.ErrorOutput("Command rejected. Tell the agent what to do differently.")



                stream_input = Command(
                    resume=hitl_response,
                    update=command_state_update or None,
                )
                continue

            break

        # Compaction detection
        try:
            if pre_stream_msg_count is not None:
                _post_state = await agent.aget_state(config)
                if _post_state is not None:
                    post_count = len(_post_state.values.get("messages", []))
                    if post_count < pre_stream_msg_count - 2:
                        yield ev.CompactionNotice()
        except Exception:
            pass

    except asyncio.CancelledError:
        _gen = _current_stream_gen
        _current_stream_gen = None
        if _gen is not None:
            try:
                await asyncio.wait_for(asyncio.shield(_gen.aclose()), timeout=2.0)
            except Exception:
                pass
        try:
            await asyncio.wait_for(
                asyncio.shield(
                    agent.aupdate_state(
                        config=config,
                        values={
                            "messages": [
                                HumanMessage(
                                    content="[The previous request was cancelled by the system]"
                                )
                            ]
                        },
                        as_node="model",
                    )
                ),
                timeout=3.0,
            )
        except Exception:
            pass
        yield ev.Cancelled()
        return

    except Exception as e:  # noqa: BLE001
        # Promptly release the underlying LangGraph stream rather than leaving it
        # for GC-time finalization.
        _gen = _current_stream_gen
        _current_stream_gen = None
        if _gen is not None:
            try:
                await asyncio.wait_for(asyncio.shield(_gen.aclose()), timeout=2.0)
            except Exception:  # noqa: BLE001
                pass
        # A GraphInterrupt that reaches here came from a NESTED graph (a `task`
        # subagent hitting a HITL-gated tool like shell/execute/write_file).
        # The parent stream only auto-resolves interrupts surfaced as the
        # top-level `__interrupt__` event, not exceptions bubbling out of a
        # subagent — so render a concise, actionable note instead of dumping the
        # raw interrupt value as a scary error.
        try:
            from langgraph.errors import GraphInterrupt
        except Exception:  # noqa: BLE001
            GraphInterrupt = ()  # type: ignore[assignment]
        if GraphInterrupt and isinstance(e, GraphInterrupt):
            yield ev.Error(
                "A subagent requested approval for a guarded tool "
                "(shell/execute/write) and the run could not auto-approve it. "
                "Re-run with auto-approve enabled, or avoid shell commands in "
                "automated flows.",
                exception=e,
            )
            return
        yield ev.Error(str(e), exception=e)
        return
    finally:
        _auto_approve_var.reset(token)

    if captured.input_tokens or captured.output_tokens:
        yield captured
    for _ctx in _drain_nova_events():
        yield _ctx
    yield ev.Done(had_response=has_responded)


async def _handle_tool_message(
    message,
    *,
    namespace,
    is_main_agent: bool,
    is_subagent: bool,
    tool_call_to_name: dict,
    displayed_tool_ids: set,
    seen_message_ids: set,
    file_op_tracker,
    subagent_tracker: SubagentTracker,
    agent_display_name: str,
    flush_text,
) -> AsyncIterator[Any]:
    """Translate a ToolMessage into events (results, file ops, subagent status)."""
    tool_id = getattr(message, "id", None) or getattr(message, "tool_call_id", None)
    if tool_id and tool_id in seen_message_ids:
        return
    if tool_id:
        seen_message_ids.add(tool_id)

    tool_call_id = getattr(message, "tool_call_id", None)
    tool_name = tool_call_to_name.get(tool_call_id, "") or getattr(message, "name", "")
    tool_status = getattr(message, "status", "success")
    tool_content = format_tool_message_content(message.content)
    record = file_op_tracker.complete_with_message(message)

    if is_subagent and namespace:
        if tool_status != "success" or (
            tool_content and str(tool_content).lower().startswith("error")
        ):
            subagent_tracker.record_error(namespace, tool_name)

        # Resolve subagent task's tool_call_id
        subagent_cid = None
        if namespace in subagent_tracker.lg_ns_to_tool_call_id:
            subagent_cid = subagent_tracker.lg_ns_to_tool_call_id[namespace]
        elif subagent_tracker.subagent_stack:
            subagent_cid = subagent_tracker.subagent_stack[-1][0]
            subagent_tracker.lg_ns_to_tool_call_id[namespace] = subagent_cid

        if subagent_cid and tool_call_id:
            subagent_type = None
            if subagent_cid in subagent_tracker.active_subagents:
                subagent_type = subagent_tracker.active_subagents[subagent_cid][0]
            elapsed = None
            start = subagent_tracker.tool_call_start_times.pop(tool_call_id, None)
            if start is not None:
                elapsed = time.time() - start
            preview = format_tool_result_preview(tool_name, tool_content, tool_status, elapsed)
            yield ev.SubagentActivity(
                kind="tool_result",
                subagent_type=subagent_type,
                message=preview or f"Completed {tool_name}",
                detail=tool_call_id,
                call_id=subagent_cid,
                color="#73daca" if tool_status == "success" else "#f7768e",
            )

    # Completed subagent (task tool)
    if tool_name == "task" and tool_call_id and tool_call_id in subagent_tracker.active_subagents:
        info = subagent_tracker.complete_subagent(tool_call_id)
        if info:
            subagent_type, _, start_time = info
        else:
            subagent_type, start_time = "unknown", time.time()
        activity = subagent_tracker.claim_namespace_for_tool_call(namespace, tool_call_id)
        yield ev.SubagentActivity(
            kind="completed",
            subagent_type=subagent_type,
            message=f"{get_status_icon(tool_status == 'success')} {subagent_type}",
            detail=(format_condensed_activity(activity) if activity else None),
            color=get_agent_color(subagent_type),
            call_id=tool_call_id,
        )
        yield ev.StatusUpdate(f"{agent_display_name} is synthesizing...")
        return

    if is_main_agent:
        # Surface shell / generic errors
        if tool_name == "shell" and tool_status != "success" and tool_content:
            for _e in flush_text():
                yield _e
            yield ev.ErrorOutput(tool_content)
        elif tool_content and isinstance(tool_content, str):
            if tool_content.lstrip().lower().startswith("error"):
                for _e in flush_text():
                    yield _e
                yield ev.ErrorOutput(tool_content)

        if record:
            for _e in flush_text():
                yield _e
            yield ev.FileOp(
                record=record,
                full_output=(tool_content if isinstance(tool_content, str) else ""),
                call_id=tool_call_id,
            )
        elif tool_call_id and tool_call_id in displayed_tool_ids:
            already_error = (tool_name == "shell" and tool_status != "success") or (
                tool_content
                and isinstance(tool_content, str)
                and tool_content.lstrip().lower().startswith("error")
            )
            if not already_error:
                elapsed = None
                start = subagent_tracker.tool_call_start_times.pop(tool_call_id, None)
                if start is not None:
                    elapsed = time.time() - start
                preview = format_tool_result_preview(tool_name, tool_content, tool_status, elapsed)
                if preview:
                    yield ev.ToolResult(
                        preview=preview,
                        is_error=preview.startswith("✗"),
                        full_output=(tool_content if isinstance(tool_content, str) else ""),
                        call_id=tool_call_id,
                    )


async def _handle_tool_call_chunk(
    block: dict,
    *,
    is_main_agent: bool,
    namespace,
    subagent_type_for_ns,
    tool_call_buffers: dict,
    displayed_tool_ids: set,
    tool_call_to_name: dict,
    file_op_tracker,
    subagent_tracker: SubagentTracker,
    flush_text,
) -> AsyncIterator[Any]:
    """Accumulate streamed tool-call args and emit a ToolCall when complete."""
    chunk_name = block.get("name")
    chunk_args = block.get("args")
    chunk_id = block.get("id")
    chunk_index = block.get("index")

    if chunk_index is not None:
        buffer_key: str | int = chunk_index
    elif chunk_id is not None:
        buffer_key = chunk_id
    else:
        buffer_key = f"unknown-{len(tool_call_buffers)}"

    buffer = tool_call_buffers.setdefault(
        buffer_key, {"name": None, "id": None, "args": None, "args_parts": []}
    )
    if chunk_name:
        buffer["name"] = chunk_name
    if chunk_id:
        buffer["id"] = chunk_id

    if isinstance(chunk_args, dict):
        buffer["args"] = chunk_args
        buffer["args_parts"] = []
    elif isinstance(chunk_args, str):
        if chunk_args:
            parts: list[str] = buffer.setdefault("args_parts", [])
            if not parts or chunk_args != parts[-1]:
                parts.append(chunk_args)
            buffer["args"] = "".join(parts)
    elif chunk_args is not None:
        buffer["args"] = chunk_args

    buffer_name = buffer.get("name")
    buffer_id = buffer.get("id")
    if buffer_name is None:
        return

    parsed_args = buffer.get("args")
    if isinstance(parsed_args, str):
        if not parsed_args:
            return
        try:
            parsed_args = json.loads(parsed_args)
        except json.JSONDecodeError:
            return
    elif parsed_args is None:
        return
    if not isinstance(parsed_args, dict):
        parsed_args = {"value": parsed_args}

    for _e in flush_text():
        yield _e

    display_needed = False
    if buffer_id is not None:
        if buffer_id not in displayed_tool_ids:
            displayed_tool_ids.add(buffer_id)
            tool_call_to_name[buffer_id] = buffer_name
            subagent_tracker.tool_call_start_times[buffer_id] = time.time()
            file_op_tracker.start_operation(buffer_name, parsed_args, buffer_id)
            display_needed = True
        else:
            file_op_tracker.update_args(buffer_id, parsed_args)
    else:
        display_needed = True
    tool_call_buffers.pop(buffer_key, None)

    # A `task` call spawns a subagent — it's rendered via the SubagentActivity
    # ("dispatched"/"completed") events below, so suppress the duplicate generic
    # ToolCall card that would otherwise show the raw subagent prompt.
    _is_subagent_dispatch = buffer_name == "task" and "subagent_type" in parsed_args

    # ask_question / ask_user_question are surfaced as a QuestionModal via their
    # "question" interrupt, so don't also render a generic tool card for them.
    _is_question = buffer_name in ("ask_question", "ask_user_question")

    if display_needed and not _is_question and not _is_subagent_dispatch:
        icon = TOOL_ICONS.get(buffer_name, "🔧")
        display_str = format_tool_display(buffer_name, parsed_args)
        if is_main_agent:
            yield ev.ToolCall(
                name=buffer_name,
                display_str=display_str,
                icon=icon,
                is_main_agent=True,
                args=parsed_args,
                call_id=buffer_id,
            )
        elif namespace:
            subagent_tracker.record_tool_call(
                namespace,
                subagent_type_for_ns,
                buffer_name,
                parsed_args,
                TOOL_CATEGORIES,
            )
            # Resolve subagent task's tool_call_id
            subagent_cid = None
            if namespace in subagent_tracker.lg_ns_to_tool_call_id:
                subagent_cid = subagent_tracker.lg_ns_to_tool_call_id[namespace]
            elif subagent_tracker.subagent_stack:
                subagent_cid = subagent_tracker.subagent_stack[-1][0]
                subagent_tracker.lg_ns_to_tool_call_id[namespace] = subagent_cid

            if subagent_cid and buffer_id:
                yield ev.SubagentActivity(
                    kind="tool_start",
                    subagent_type=subagent_type_for_ns,
                    message=f"{icon} {display_str}",
                    detail=buffer_id,
                    call_id=subagent_cid,
                )

    if buffer_name == "task" and "subagent_type" in parsed_args:
        subagent_type = parsed_args["subagent_type"]
        description = parsed_args.get("description", "")
        if subagent_tracker.dispatch_subagent(buffer_id, subagent_type, description):
            yield ev.SubagentActivity(
                kind="dispatched",
                subagent_type=subagent_type,
                message=f"{subagent_type} is thinking…",
                detail=description or None,
                color=get_agent_color(subagent_type),
                call_id=buffer_id,
            )

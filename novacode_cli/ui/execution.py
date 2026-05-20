"""Task execution and streaming logic for the CLI."""

import asyncio
import json
import time
import uuid
from pathlib import Path

from langchain.agents.middleware.human_in_the_loop import HITLRequest, HITLResponse
from langchain_core.messages import HumanMessage, ToolMessage
from langgraph.types import Command, Interrupt
from pydantic import TypeAdapter, ValidationError
from rich.markdown import Markdown
from rich.text import Text

from novacode_cli.vixie.server import (
    set_idle as vixie_set_idle,
    set_thinking as vixie_set_thinking,
    set_working as vixie_set_working,
)
from novacode_cli.config.config import COLORS, console, get_agent_color
from novacode_cli.file_ops import get_session_file_op_tracker
from novacode_cli.input import ImageTracker
from novacode_cli.ui.hitl_approval import process_hitl_approval
from novacode_cli.ui.input_preparation import (
    build_agent_config,
    get_agent_display_name,
    prepare_input_content,
)
from novacode_cli.ui.interrupt_handlers import (
    handle_plan_approval_interrupt,
    handle_question_interrupt,
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
    TokenTracker,
    format_tool_display,
    format_tool_message_content,
    format_tool_result_preview,
    render_file_operation,
    render_todo_list,
    render_tool_panel,
)

_HITL_REQUEST_ADAPTER = TypeAdapter(HITLRequest)


async def execute_task(  # type: ignore
    user_input: str,
    agent,
    assistant_id: str | None,
    session_state,
    token_tracker: TokenTracker | None = None,
    backend=None,
    is_subagent: bool = False,
    image_tracker: ImageTracker | None = None,
    seen_message_ids: set[str] | None = None,
    *,
    skip_file_mentions: bool = False,
) -> None:
    """Execute any task by passing it directly to the AI agent."""
    message_content = await prepare_input_content(
        user_input, image_tracker, skip_file_mentions=skip_file_mentions
    )

    thread_id = str(uuid.uuid4()) if is_subagent else session_state.thread_id
    config = build_agent_config(thread_id, assistant_id)

    agent_display_name = get_agent_display_name(assistant_id)
    agent_colors = (
        get_agent_color(assistant_id)
        if assistant_id and is_subagent
        else COLORS["agent"]
    )

    if token_tracker:
        token_tracker.increment_user_messages()

    has_responded = False
    captured_input_tokens = 0
    captured_output_tokens = 0
    captured_cache_read_tokens = 0
    captured_cache_creation_tokens = 0
    current_todos = None
    _prev_auto_approve: bool | None = None

    try:
        import logging as _vixie_logging

        _vixie_logging.getLogger("vixie").info("Setting Vixie state to THINKING")
        await vixie_set_thinking()
        _vixie_logging.getLogger("vixie").info("Vixie state set to THINKING complete")
    except Exception as e:
        import logging as _logging

        _logging.getLogger("vixie").warning(f"Failed to set Vixie state: {e}")

    status = console.status(
        f"[bold {agent_colors}]{agent_display_name} is thinking...",
        spinner="dots",
    )
    status.start()
    spinner_active = True

    # Use session-level tracker so subagent file ops are tracked
    file_op_tracker = get_session_file_op_tracker(
        assistant_id=assistant_id, backend=backend
    )

    displayed_tool_ids = set()
    tool_call_buffers: dict[str | int, dict] = {}
    pending_text = ""
    _post_summarization = False
    tool_call_to_name: dict[str, str] = {}
    current_ai_message_id: str | None = None
    _tool_preview_buffer: list[Text] = []  # batched "  ⎿  …" result lines

    import os as _os

    _DEBUG_ENABLED = _os.environ.get("Nova_DEBUG", "").lower() in ("1", "true", "yes")

    def _dbg(tag: str, msg: str) -> None:
        pass

    if _DEBUG_ENABLED:
        import datetime as _dt

        _DBG_PATH = Path("_Nova_debug.log")

        def _dbg(tag: str, msg: str) -> None:  # type: ignore
            with open(_DBG_PATH, "a", encoding="utf-8") as f:
                f.write(f"[{_dt.datetime.now():%H:%M:%S.%f}] [{tag}] {msg}\n")

    _dbg(
        "START",
        f"=== new execute_task ===  plan_mode={getattr(session_state, 'plan_mode_enabled', '?')}",
    )

    subagent_tracker = SubagentTracker()

    def flush_tool_previews() -> None:
        """Print all buffered tool-result preview lines in a single stop/start cycle."""
        nonlocal spinner_active
        if not _tool_preview_buffer:
            return
        if spinner_active:
            status.stop()
            spinner_active = False
        for _detail in _tool_preview_buffer:
            console.print(_detail)
        _tool_preview_buffer.clear()
        if not spinner_active:
            status.start()
            spinner_active = True

    def flush_text_buffer(*, final: bool = False) -> None:
        """Flush accumulated assistant text as rendered markdown when appropriate."""
        nonlocal pending_text, spinner_active, has_responded, current_ai_message_id, _post_summarization
        _dbg(
            "FLUSH-TEXT",
            f"final={final} pending_len={len(pending_text)} ai_msg_id={current_ai_message_id} has_responded={has_responded} post_summarization={_post_summarization}",
        )
        if not final or not pending_text.strip():
            return

        if _post_summarization:
            _post_summarization = False
            if is_internal_context_text(pending_text):
                _dbg(
                    "FLUSH-POST-SUMMARIZATION",
                    f"suppressing post-compaction echo ({len(pending_text)} chars)",
                )
                pending_text = ""
                current_ai_message_id = None
                return

        if is_internal_context_text(pending_text):
            _dbg(
                "FLUSH-INTERNAL",
                f"internal text ({len(pending_text)} chars), verbose={session_state.verbose}: {pending_text[:80]!r}",
            )
            if not session_state.verbose:
                try:
                    from novacode_cli.config.config import settings as _settings

                    _Nova_dir = _settings.ensure_project_deepagents_dir()
                    if _Nova_dir:
                        (_Nova_dir / "context.md").write_text(
                            pending_text, encoding="utf-8"
                        )
                except Exception:
                    pass
                pending_text = ""
                current_ai_message_id = None
                return

        if (
            current_ai_message_id
            and seen_message_ids
            and current_ai_message_id in seen_message_ids
        ):
            _dbg("FLUSH-SKIP", f"dedup: msg_id={current_ai_message_id} already seen")
            pending_text = ""
            current_ai_message_id = None
            return

        subagent_tracker.flush_completions(spinner_active, status)
        if spinner_active:
            status.stop()
            spinner_active = False
        if not has_responded:
            console.print()
            console.print("●", style=agent_colors, markup=False, end=" ")
            has_responded = True
        _dbg("FLUSH-PRINT", f"text[:120]={pending_text[:120]!r}")
        markdown = Markdown(pending_text.rstrip())
        console.print(agent_display_name, style=agent_colors)
        console.print(markdown, justify="full")
        # Fire agent.message hook
        try:
            from novacode_cli.hooks import dispatch_hook_fire_and_forget, HookEvent
            dispatch_hook_fire_and_forget(HookEvent.AGENT_MESSAGE, {
                "session_id": getattr(session_state, "session_id", ""),
                "thread_id": getattr(session_state, "thread_id", ""),
                "message": pending_text[:500],
            })
        except Exception:
            pass
        if current_ai_message_id and seen_message_ids:
            seen_message_ids.add(current_ai_message_id)
            current_ai_message_id = None
        pending_text = ""

    stream_input = {"messages": [{"role": "user", "content": message_content}]}
    if seen_message_ids is None:
        seen_message_ids = set()

    pre_stream_msg_count: int | None = None
    _last_known_state: object = (
        None  # reused by post-stream checks to avoid re-querying
    )
    try:
        _pre_state = await agent.aget_state(config)
        _last_known_state = _pre_state
        _pre_msgs = _pre_state.values.get("messages", [])
        pre_stream_msg_count = len(_pre_msgs)
        for _m in _pre_msgs:
            _mid = getattr(_m, "id", None)
            if _mid:
                seen_message_ids.add(_mid)
    except Exception:
        pass

    _current_stream_gen: object = None

    try:
        while True:
            _dbg(
                "LOOP-ITER",
                f"stream_input_type={type(stream_input).__name__} seen_ids_count={len(seen_message_ids)}",
            )
            interrupt_occurred = False
            hitl_response: dict[str, HITLResponse] = {}
            command_state_update: dict = (
                {}
            )  # State updates to apply atomically on resume
            suppress_resumed_output = False
            # Reset per-iteration tracking (in-progress state only)
            subagent_tracker.clear()
            current_ai_message_id = None
            _dbg("ITER-RESET", "clearing per-iteration state")
            # Track all pending interrupts: {interrupt_id: request_data}
            pending_interrupts: dict[str, HITLRequest] = {}

            # Store generator reference at outer scope so interrupt handlers can
            # close it before calling aupdate_state (releases checkpointer lock).
            _current_stream_gen = agent.astream(
                stream_input,
                stream_mode=["updates", "messages"],  # Dual-mode for HITL support
                subgraphs=True,
                config=config,
                durability="exit",
            )
            async for chunk in _current_stream_gen:
                # Unpack chunk - with subgraphs=True and dual-mode, it's (namespace, stream_mode, data)
                if not isinstance(chunk, tuple) or len(chunk) != 3:
                    continue

                _namespace, current_stream_mode, data = chunk

                # Handle UPDATES stream - for interrupts and todos
                if current_stream_mode == "updates":
                    if not isinstance(data, dict):
                        continue

                    # Extract chunk_data and update current_todos BEFORE interrupt
                    # handling — ensures current_todos is populated when the
                    # plan_approval handler checks `if current_todos:` below.
                    # Scan ALL node values (not just the first) to find "todos".
                    chunk_data = None
                    for _node_state in data.values():
                        if isinstance(_node_state, dict):
                            if chunk_data is None:
                                chunk_data = (
                                    _node_state  # first dict for summarization check
                                )
                            if "todos" in _node_state:
                                _new_todos = _node_state["todos"]
                                if _new_todos != current_todos:
                                    current_todos = _new_todos
                                    _dbg(
                                        "TODO-UPDATE",
                                        f"new_todos_count={len(_new_todos)}",
                                    )
                                    if spinner_active:
                                        status.stop()
                                        spinner_active = False
                                    console.print()
                                    # Get agent name from state if available
                                    _agent_name = _node_state.get("agent_name")
                                    render_todo_list(_new_todos, agent_name=_agent_name)
                                    console.print()
                                break

                    # Check for interrupts - collect ALL pending interrupts
                    if "__interrupt__" in data:
                        interrupts: list[Interrupt] = data["__interrupt__"]
                        _dbg(
                            "INTERRUPT",
                            f"count={len(interrupts)} types={[type(i.value).__name__ for i in interrupts]}",
                        )
                        if interrupts:
                            for interrupt_obj in interrupts:
                                interrupt_value = interrupt_obj.value

                                # Check if this is a question interrupt (from ask_question tool)
                                # Handle both "question" type (plan_agent) and "tool" type (deepagents)
                                if isinstance(interrupt_value, dict) and (
                                    interrupt_value.get("type") == "question"
                                    or (
                                        interrupt_value.get("type") == "tool"
                                        and interrupt_value.get("name")
                                        == "ask_question"
                                    )
                                ):
                                    # Handle question interrupt using the module
                                    question_request = interrupt_value.get(
                                        "request", {}
                                    )
                                    response, spinner_active = (
                                        await handle_question_interrupt(
                                            question_request=question_request,
                                            auto_approve=session_state.auto_approve,
                                            spinner_active=spinner_active,
                                            status=status,
                                        )
                                    )

                                    # Create a question response to resume with
                                    hitl_response[interrupt_obj.id] = response
                                    interrupt_occurred = True

                                    # Restart spinner
                                    if not spinner_active:
                                        status.start()
                                        spinner_active = True

                                    continue

                                # Check if this is a plan approval interrupt (from exit_plan_mode tool)
                                if (
                                    isinstance(interrupt_value, dict)
                                    and interrupt_value.get("type") == "plan_approval"
                                ):
                                    # Handle plan approval using the module
                                    (
                                        response,
                                        occurred,
                                        spinner_active,
                                        cmd_state_update,
                                    ) = await handle_plan_approval_interrupt(
                                        current_todos=current_todos,
                                        session_state=session_state,
                                        spinner_active=spinner_active,
                                        status=status,
                                        dbg_func=_dbg,
                                    )
                                    hitl_response[interrupt_obj.id] = response
                                    interrupt_occurred = occurred
                                    if cmd_state_update:
                                        command_state_update.update(cmd_state_update)
                                    continue

                                try:
                                    validated_request = (
                                        _HITL_REQUEST_ADAPTER.validate_python(
                                            interrupt_value
                                        )
                                    )
                                    pending_interrupts[interrupt_obj.id] = (
                                        validated_request
                                    )
                                    interrupt_occurred = True
                                except ValidationError as e:
                                    console.print(
                                        f"[yellow]Warning: Invalid HITL request data: {e}[/yellow]",
                                        style="dim",
                                    )
                                    raise

                    if chunk_data and isinstance(chunk_data, dict):
                        if "messages" in chunk_data:
                            _msgs = chunk_data["messages"]
                            if hasattr(_msgs, "value"):
                                _msgs = _msgs.value
                            if not isinstance(_msgs, list):
                                try:
                                    _msgs = list(_msgs)
                                except TypeError:
                                    _msgs = []
                            for _msg in _msgs:
                                _src = getattr(_msg, "additional_kwargs", {}).get(
                                    "lc_source"
                                )
                                if _src == "summarization":
                                    _post_summarization = True
                                    _dbg(
                                        "SUMMARIZATION",
                                        "detected summarization compaction — suppressing next AI text",
                                    )
                                    break

                elif current_stream_mode == "messages":
                    is_main_agent = _namespace == ()
                    is_subagent = _namespace != ()
                    subagent_type_for_ns = None
                    if is_subagent and len(_namespace) > 0:
                        subagent_type_for_ns = _namespace[0]

                    if not is_main_agent:
                        pass

                    if not isinstance(data, tuple) or len(data) != 2:
                        continue

                    message, _metadata = data

                    _ckpt_ns = (
                        _metadata.get("langgraph_checkpoint_ns", "")
                        if isinstance(_metadata, dict)
                        else ""
                    )
                    if _ckpt_ns and "before_model" in _ckpt_ns:
                        continue

                    if hasattr(message, "id"):
                        msg_id = message.id
                        if msg_id in seen_message_ids:
                            continue  # Skip entire message if already processed via updates

                    if isinstance(message, HumanMessage):
                        # Never re-display user messages or internal summaries.
                        # The user already typed their input; compaction summaries
                        # and continuation prompts are state-only.
                        continue

                    if isinstance(message, ToolMessage):
                        # Tool results are sent to the agent, not displayed to users
                        # Exception: show shell command errors to help with debugging
                        tool_id = getattr(message, "id", None) or getattr(
                            message, "tool_call_id", None
                        )

                        if tool_id and tool_id in seen_message_ids:
                            continue

                        if tool_id:
                            seen_message_ids.add(tool_id)

                        # Use tracked tool name for reliable lookup (ToolMessage.name is unreliable)
                        tool_call_id = getattr(message, "tool_call_id", None)
                        tool_name = tool_call_to_name.get(tool_call_id, "") or getattr(
                            message, "name", ""
                        )
                        tool_status = getattr(message, "status", "success")
                        tool_content = format_tool_message_content(message.content)
                        record = file_op_tracker.complete_with_message(message)

                        # Track subagent tool errors by LangGraph namespace
                        if is_subagent and _namespace:
                            if tool_status != "success" or (
                                tool_content
                                and str(tool_content).lower().startswith("error")
                            ):
                                subagent_tracker.record_error(_namespace, tool_name)

                        if (
                            tool_name == "task"
                            and tool_call_id
                            and tool_call_id in subagent_tracker.active_subagents
                        ):
                            subagent_info = subagent_tracker.complete_subagent(
                                tool_call_id
                            )
                            if subagent_info:
                                subagent_type, _, start_time = subagent_info
                            else:
                                subagent_type, start_time = "unknown", time.time()
                            subagent_color = get_agent_color(subagent_type)

                            activity = subagent_tracker.claim_namespace_for_tool_call(
                                _namespace, tool_call_id
                            )
                            status_icon = get_status_icon(tool_status == "success")
                            duration_str = format_duration(time.time() - start_time)

                            subagent_tracker.add_pending_completion(
                                status_icon=status_icon,
                                subagent_type=subagent_type,
                                duration_str=duration_str,
                                condensed=(
                                    format_condensed_activity(activity)
                                    if activity
                                    else None
                                ),
                                subagent_color=subagent_color,
                            )

                            remaining = subagent_tracker.get_remaining_count()
                            done_count = subagent_tracker.get_done_count()
                            total_count = done_count + remaining
                            if remaining > 0:
                                spinner_msg = (
                                    f"[bold {COLORS['thinking']}]"
                                    f"{done_count}/{total_count} subagents done, waiting for {remaining} more..."
                                )
                            else:
                                label = "subagent" if done_count == 1 else "subagents"
                                spinner_msg = f"[bold {COLORS['thinking']}]All {done_count} {label} done, synthesizing..."
                            if spinner_active:
                                status.update(spinner_msg)
                            else:
                                status.start()
                                spinner_active = True
                                status.update(spinner_msg)
                            continue

                        elif spinner_active:
                            pending_count = len(subagent_tracker.pending_completions)
                            if pending_count and subagent_tracker.get_remaining_count():
                                pass
                            elif pending_count:
                                label = (
                                    "subagent" if pending_count == 1 else "subagents"
                                )
                                status.update(
                                    f"[bold {COLORS['thinking']}]All {pending_count} {label} done, synthesizing..."
                                )
                            else:
                                status.update(
                                    f"[bold {COLORS['thinking']}]{agent_display_name} is thinking..."
                                )

                        if is_main_agent:
                            if tool_name == "shell" and tool_status != "success":
                                flush_text_buffer(final=True)
                                if tool_content:
                                    if spinner_active:
                                        status.stop()
                                        spinner_active = False
                                    console.print()
                                    console.print(
                                        tool_content, style="red", markup=False
                                    )
                                    console.print()
                            elif tool_content and isinstance(tool_content, str):
                                stripped = tool_content.lstrip()
                                if stripped.lower().startswith("error"):
                                    flush_text_buffer(final=True)
                                    if spinner_active:
                                        status.stop()
                                        spinner_active = False
                                    console.print()
                                    console.print(
                                        tool_content, style="red", markup=False
                                    )
                                    console.print()

                            if record:
                                flush_tool_previews()
                                flush_text_buffer(final=True)
                                if spinner_active:
                                    status.stop()
                                    spinner_active = False
                                console.print()
                                render_file_operation(record)
                                console.print()
                                if not spinner_active:
                                    status.start()
                                    spinner_active = True
                            elif tool_call_id and tool_call_id in displayed_tool_ids:
                                already_printed_error = (
                                    tool_name == "shell" and tool_status != "success"
                                ) or (
                                    tool_content
                                    and isinstance(tool_content, str)
                                    and tool_content.lstrip()
                                    .lower()
                                    .startswith("error")
                                )
                                if not already_printed_error:
                                    elapsed = None
                                    start = subagent_tracker.tool_call_start_times.pop(
                                        tool_call_id, None
                                    )
                                    if start is not None:
                                        elapsed = time.time() - start
                                    preview = format_tool_result_preview(
                                        tool_name, tool_content, tool_status, elapsed
                                    )
                                    if preview:
                                        is_err = preview.startswith("✗")
                                        sty = (
                                            "red" if is_err else f"dim {COLORS['tool']}"
                                        )
                                        detail = Text()
                                        detail.append("  ⎿  ", style=sty)
                                        detail.append(preview, style=sty)
                                        _tool_preview_buffer.append(detail)

                                        # Notify remote bridges of tool result
                                        _notify = getattr(session_state, "_remote_tool_notify", None)
                                        if _notify is not None:
                                            try:
                                                _notify(tool_name, preview, is_result=True)
                                            except Exception:
                                                pass

                                        # Fire tool.result hook
                                        try:
                                            from novacode_cli.hooks import dispatch_hook_fire_and_forget, HookEvent
                                            dispatch_hook_fire_and_forget(HookEvent.TOOL_RESULT, {
                                                "tool": tool_name,
                                                "status": tool_status,
                                                "preview": preview[:300],
                                                "session_id": getattr(session_state, "session_id", ""),
                                            })
                                        except Exception:
                                            pass

                        continue

                    if hasattr(message, "content_blocks"):
                        blocks: list[dict] = message.content_blocks
                    else:
                        blocks = []
                        raw_content = getattr(message, "content", "")
                        if isinstance(raw_content, str) and raw_content:
                            blocks.append({"type": "text", "text": raw_content})
                        elif isinstance(raw_content, list):
                            for item in raw_content:
                                if isinstance(item, dict):
                                    blocks.append(item)
                                elif isinstance(item, str) and item:
                                    blocks.append({"type": "text", "text": item})
                        for tc in getattr(message, "tool_call_chunks", []) or []:
                            if isinstance(tc, dict):
                                blocks.append({"type": "tool_call_chunk", **tc})

                    if not blocks:
                        continue

                    if (
                        token_tracker
                        and is_main_agent
                        and hasattr(message, "usage_metadata")
                    ):
                        usage = message.usage_metadata
                        if usage:
                            input_toks = usage.get("input_tokens", 0)
                            output_toks = usage.get("output_tokens", 0)
                            # Prompt-caching: cached tokens are NOT in input_tokens
                            # but still occupy the context window. Must add them back.
                            cache_read = usage.get("cache_read_input_tokens", 0)
                            cache_create = usage.get("cache_creation_input_tokens", 0)
                            # Actual context sent = fresh tokens + cached tokens
                            actual_context = input_toks + cache_read + cache_create
                            if actual_context or output_toks:
                                captured_input_tokens = max(
                                    captured_input_tokens, actual_context
                                )
                                captured_output_tokens = max(
                                    captured_output_tokens, output_toks
                                )
                                captured_cache_read_tokens = max(
                                    captured_cache_read_tokens, cache_read
                                )
                                captured_cache_creation_tokens = max(
                                    captured_cache_creation_tokens, cache_create
                                )

                    # LangGraph's messages stream emits individual
                    # AIMessageChunk objects during streaming, then a final
                    # completed AIMessage with the FULL accumulated content.
                    # We must only accumulate text from the incremental chunks;
                    # re-appending the completed AIMessage would double the output.
                    _msg_type_name = type(message).__name__
                    _is_completed_msg = _msg_type_name == "AIMessage"

                    # Process normalized content blocks
                    for block in blocks:
                        block_type = block.get("type")
                        # Handle text blocks - only accumulate from streaming chunks
                        if block_type == "text":
                            text = block.get("text", "")
                            if text and is_main_agent and not _is_completed_msg:
                                # Track which message owns the buffered text so
                                # flush_text_buffer can deduplicate against the updates stream
                                current_ai_message_id = getattr(message, "id", None)
                                pending_text += text
                                _dbg(
                                    "TEXT-ACCUM",
                                    f"chunk_len={len(text)} total={len(pending_text)} msg_type={_msg_type_name}",
                                )

                        # Handle reasoning/thinking blocks (extended thinking)
                        # Claude returns "thinking" blocks; other models may use "reasoning"
                        # These are internal deliberation — never shown to the user.
                        elif block_type in ("reasoning", "thinking"):
                            pass  # Silently skip — internal reasoning only

                        # Handle tool call chunks
                        # Some models (OpenAI, Anthropic) stream tool_call_chunks
                        # Others (Gemini) don't stream them and just return the full tool_call
                        elif block_type in ("tool_call_chunk", "tool_call"):
                            chunk_name = block.get("name")
                            chunk_args = block.get("args")
                            chunk_id = block.get("id")
                            chunk_index = block.get("index")

                            # Use index as stable buffer key; fall back to id if needed
                            buffer_key: str | int
                            if chunk_index is not None:
                                buffer_key = chunk_index
                            elif chunk_id is not None:
                                buffer_key = chunk_id
                            else:
                                buffer_key = f"unknown-{len(tool_call_buffers)}"

                            buffer = tool_call_buffers.setdefault(
                                buffer_key,
                                {
                                    "name": None,
                                    "id": None,
                                    "args": None,
                                    "args_parts": [],
                                },
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
                                    parts: list[str] = buffer.setdefault(
                                        "args_parts", []
                                    )
                                    if not parts or chunk_args != parts[-1]:
                                        parts.append(chunk_args)
                                    buffer["args"] = "".join(parts)
                            elif chunk_args is not None:
                                buffer["args"] = chunk_args

                            buffer_name = buffer.get("name")
                            buffer_id = buffer.get("id")
                            if buffer_name is None:
                                continue

                            parsed_args = buffer.get("args")
                            if isinstance(parsed_args, str):
                                if not parsed_args:
                                    continue
                                try:
                                    parsed_args = json.loads(parsed_args)
                                except json.JSONDecodeError:
                                    continue
                            elif parsed_args is None:
                                continue

                            if not isinstance(parsed_args, dict):
                                parsed_args = {"value": parsed_args}

                            _dbg(
                                "TOOL-FLUSH",
                                f"tool={buffer_name} pending_len={len(pending_text)} text[:80]={pending_text[:80]!r}",
                            )
                            flush_text_buffer(final=True)
                            display_needed = False
                            if buffer_id is not None:
                                if buffer_id not in displayed_tool_ids:
                                    displayed_tool_ids.add(buffer_id)
                                    tool_call_to_name[buffer_id] = buffer_name
                                    subagent_tracker.tool_call_start_times[
                                        buffer_id
                                    ] = time.time()
                                    file_op_tracker.start_operation(
                                        buffer_name, parsed_args, buffer_id
                                    )
                                    display_needed = True
                                else:
                                    file_op_tracker.update_args(buffer_id, parsed_args)
                            else:
                                display_needed = True
                            tool_call_buffers.pop(buffer_key, None)

                            if display_needed:
                                if buffer_name == "ask_question":
                                    continue

                                try:
                                    await vixie_set_working()
                                except Exception:
                                    pass

                                icon = TOOL_ICONS.get(buffer_name, "🔧")
                                display_str = format_tool_display(
                                    buffer_name, parsed_args
                                )

                                if is_main_agent:
                                    flush_tool_previews()
                                    if spinner_active:
                                        status.stop()
                                        spinner_active = False

                                    if has_responded:
                                        console.print()

                                    # Use bordered panel for tool display
                                    render_tool_panel(buffer_name, display_str, icon)

                                    # Fire tool.call hook
                                    try:
                                        from novacode_cli.hooks import dispatch_hook_fire_and_forget, HookEvent
                                        dispatch_hook_fire_and_forget(HookEvent.TOOL_CALL, {
                                            "tool": buffer_name,
                                            "args": str(parsed_args)[:500] if parsed_args else "",
                                            "session_id": getattr(session_state, "session_id", ""),
                                        })
                                    except Exception:
                                        pass

                                    # Notify remote bridges of tool usage
                                    _notify = getattr(session_state, "_remote_tool_notify", None)
                                    if _notify is not None:
                                        try:
                                            _notify(buffer_name, display_str)
                                        except Exception:
                                            pass

                                elif is_subagent and _namespace:
                                    subagent_tracker.record_tool_call(
                                        _namespace,
                                        subagent_type_for_ns,
                                        buffer_name,
                                        parsed_args,
                                        TOOL_CATEGORIES,
                                    )

                            if buffer_name == "task" and "subagent_type" in parsed_args:
                                subagent_type = parsed_args["subagent_type"]
                                description = parsed_args.get("description", "")

                                if subagent_tracker.dispatch_subagent(
                                    buffer_id, subagent_type, description
                                ):
                                    remaining = subagent_tracker.get_remaining_count()
                                    _subagent_color = get_agent_color(subagent_type)
                                    if remaining > 1:
                                        status.update(
                                            f"[bold {_subagent_color}]{remaining} agents thinking..."
                                        )
                                    else:
                                        status.update(
                                            f"[bold {_subagent_color}]{subagent_type} is thinking..."
                                        )
                                    status.start()
                                    spinner_active = True

                    if getattr(message, "chunk_position", None) == "last":
                        _dbg(
                            "LAST-FLUSH",
                            f"msg_id={getattr(message, 'id', '?')} pending_len={len(pending_text)}",
                        )
                        if hasattr(message, "id"):
                            seen_message_ids.add(message.id)
                        flush_text_buffer(final=True)

            _current_stream_gen = None

            _dbg(
                "STREAM-END",
                f"interrupt_occurred={interrupt_occurred} pending_len={len(pending_text)}",
            )
            flush_tool_previews()
            flush_text_buffer(final=True)
            subagent_tracker.flush_completions(spinner_active, status)

            _dbg(
                "HITL-PRECHECK",
                f"interrupt_occurred={interrupt_occurred} pending_count={len(pending_interrupts)} plan_mode={session_state.plan_mode_enabled}",
            )
            if interrupt_occurred:
                _dbg(
                    "HITL-RESUME",
                    f"pending_count={len(pending_interrupts)} auto_approve={session_state.auto_approve}",
                )
                any_rejected = False

                for interrupt_id, hitl_request in pending_interrupts.items():
                    decisions, any_rejected, spinner_active = (
                        await process_hitl_approval(
                            hitl_request=hitl_request,
                            session_state=session_state,
                            assistant_id=assistant_id,
                            backend=backend,
                            spinner_active=spinner_active,
                            status=status,
                            dbg_func=_dbg,
                        )
                    )
                    hitl_response[interrupt_id] = {"decisions": decisions}

                suppress_resumed_output = any_rejected

            if interrupt_occurred and hitl_response:
                if suppress_resumed_output:
                    if spinner_active:
                        status.stop()
                        spinner_active = False

                    console.print("[yellow]Command rejected.[/yellow]", style="bold")
                    console.print("Tell the agent what you'd like to do differently.")
                    console.print()

                    stream_input = Command(
                        resume=hitl_response,
                        update=command_state_update if command_state_update else None,
                    )
                    _dbg(
                        "HITL-REJECT",
                        f"resuming with rejection for {list(hitl_response.keys())}",
                    )
                    continue

                # Resume the agent with the human decision.
                # Include any state updates (e.g. plan_mode_enabled=False) atomically
                # so they are applied at the same checkpoint as the resume — not as a
                # separate aupdate_state call that Command(resume=...) would ignore.
                stream_input = Command(
                    resume=hitl_response,
                    update=command_state_update if command_state_update else None,
                )
                _dbg(
                    "HITL-INPUT",
                    f"resume keys={list(hitl_response.keys())} state_update={command_state_update} suppress={suppress_resumed_output}",
                )
                # Continue the while loop to restream
            else:
                # No interrupt, break out of while loop
                break

        # Detect if context was auto-compacted during this turn.
        # The SummarizationMiddleware modifies the model request's messages
        # but leaves state["messages"] intact (it uses private _summarization_event
        # state instead of RemoveMessage). So a message-count decrease only
        # happens when the user runs /compact manually or the agent calls the
        # compact_conversation tool. For the middleware path, we rely on the
        # post-turn token tracker warning in main.py instead.
        try:
            if not interrupt_occurred and pre_stream_msg_count is not None:
                _post_state = await agent.aget_state(config)
                _last_known_state = _post_state
                if _post_state is not None:
                    post_msg_count = len(_post_state.values.get("messages", []))
                    if post_msg_count < pre_stream_msg_count - 2:
                        console.print()
                        console.print(
                            "[dim]⟳ Context compacted — old messages replaced with summary[/dim]"
                        )
        except Exception:
            pass

    except asyncio.CancelledError:
        # Event loop cancelled the task (e.g. Ctrl+C during streaming) - clean up and return
        if spinner_active:
            status.stop()
        console.print("\n[yellow]Interrupted by user[/yellow]")

        try:
            await asyncio.shield(vixie_set_idle())
        except Exception:
            pass

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
        except asyncio.TimeoutError:
            pass
        except Exception:
            pass

        return

    except KeyboardInterrupt:
        if spinner_active:
            status.stop()
        console.print("\n[yellow]Interrupted[/yellow]")

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
                                    content="[User interrupted the previous request with Ctrl+C]"
                                )
                            ]
                        },
                        as_node="model",
                    )
                ),
                timeout=3.0,
            )
        except asyncio.TimeoutError:
            pass
        except Exception:
            pass

        # Don't re-raise — the caller (main.py while True loop) doesn't
        # catch KeyboardInterrupt.  Instead return cleanly so the loop
        # continues with a fresh prompt.  This also prevents the double-Ctrl+C
        # from exiting the CLI when the user just wanted to interrupt a task.
        return

    subagent_tracker.flush_completions(spinner_active, status)

    if spinner_active:
        status.stop()

    if current_todos:
        session_state.todos = current_todos

    if _prev_auto_approve is not None:
        session_state.auto_approve = _prev_auto_approve

    if has_responded:
        console.print()
        if token_tracker and (captured_input_tokens or captured_output_tokens):
            token_tracker.add(
                captured_input_tokens,
                captured_output_tokens,
                cache_read_tokens=captured_cache_read_tokens,
                cache_creation_tokens=captured_cache_creation_tokens,
            )
        if token_tracker:
            token_tracker.increment_assistant_messages()
            if displayed_tool_ids:
                token_tracker.increment_tool_calls(len(displayed_tool_ids))

            try:
                from novacode_cli.context.context_manager import build_context_breakdown

                # Reuse the state already fetched for compaction detection above;
                # only fall back to a fresh query if we never fetched it (interrupted turn
                # where _last_known_state is the pre-stream snapshot).
                _bd_state = _last_known_state
                if _bd_state is None:
                    _bd_state = await agent.aget_state(config)
                    _last_known_state = _bd_state
                _bd_msgs = _bd_state.values.get("messages", [])
                if _bd_msgs and token_tracker.model_name:
                    breakdown = build_context_breakdown(
                        _bd_msgs, token_tracker.model_name
                    )
                    token_tracker.set_breakdown(breakdown)
            except Exception:
                pass

        try:
            await vixie_set_idle()
        except Exception:
            pass

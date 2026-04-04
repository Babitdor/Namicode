"""Tool message processing and display.

This module handles processing of ToolMessage objects from the agent stream,
including error display, file operation rendering, and result previews.
"""

import time

from rich.text import Text

from namicode_cli.config.config import COLORS, console
from namicode_cli.ui.ui_elements import (
    format_tool_message_content,
    format_tool_result_preview,
    render_file_operation,
)


def display_tool_error(
    tool_name: str,
    tool_content: str,
    tool_status: str,
    spinner_active: bool,
    status,
    flush_text_buffer_func,
) -> bool:
    """Display tool errors to the console.

    Args:
        tool_name: Name of the tool
        tool_content: Tool result content
        tool_status: Tool execution status
        spinner_active: Whether spinner is active
        status: Status spinner object
        flush_text_buffer_func: Function to flush text buffer

    Returns:
        True if an error was displayed, False otherwise
    """
    # Shell command errors
    if tool_name == "shell" and tool_status != "success":
        flush_text_buffer_func(final=True)
        if tool_content:
            if spinner_active:
                status.stop()
                spinner_active = False
            console.print()
            console.print(tool_content, style="red", markup=False)
            console.print()
            return True

    # Generic error messages
    if tool_content and isinstance(tool_content, str):
        stripped = tool_content.lstrip()
        if stripped.lower().startswith("error"):
            flush_text_buffer_func(final=True)
            if spinner_active:
                status.stop()
                spinner_active = False
            console.print()
            console.print(tool_content, style="red", markup=False)
            console.print()
            return True

    return False


def display_file_operation(
    record,
    spinner_active: bool,
    status,
    flush_text_buffer_func,
) -> bool:
    """Display file operation record.

    Args:
        record: File operation record
        spinner_active: Whether spinner is active
        status: Status spinner object
        flush_text_buffer_func: Function to flush text buffer

    Returns:
        True if a file operation was displayed, False otherwise
    """
    if not record:
        return False

    flush_text_buffer_func(final=True)
    if spinner_active:
        status.stop()
        spinner_active = False
    console.print()
    render_file_operation(record)
    console.print()
    return True


def display_tool_result_preview(
    tool_name: str,
    tool_content: str,
    tool_status: str,
    tool_call_id: str,
    displayed_tool_ids: set,
    tool_call_start_times: dict,
    spinner_active: bool,
    status,
    flush_text_buffer_func,
) -> tuple[bool, bool]:
    """Display a one-line result preview for a tool call.

    Args:
        tool_name: Name of the tool
        tool_content: Tool result content
        tool_status: Tool execution status
        tool_call_id: Tool call ID
        displayed_tool_ids: Set of displayed tool call IDs
        tool_call_start_times: Dict of tool call start times
        spinner_active: Whether spinner is active
        status: Status spinner object
        flush_text_buffer_func: Function to flush text buffer

    Returns:
        Tuple of (preview_was_shown, new_spinner_active)
    """
    if tool_call_id not in displayed_tool_ids:
        return False, spinner_active

    # Calculate elapsed time
    elapsed = None
    start = tool_call_start_times.pop(tool_call_id, None)
    if start is not None:
        elapsed = time.time() - start

    # Format preview
    preview = format_tool_result_preview(tool_name, tool_content, tool_status, elapsed)
    if not preview:
        return False, spinner_active

    flush_text_buffer_func(final=True)
    if spinner_active:
        status.stop()
        spinner_active = False

    is_err = preview.startswith("✗")
    sty = "red" if is_err else f"dim {COLORS['tool']}"
    detail = Text()
    detail.append("  ⎿  ", style=sty)
    detail.append(preview, style=sty)
    console.print(detail)

    return True, spinner_active


def process_tool_message(
    message,
    tool_call_to_name: dict,
    displayed_tool_ids: set,
    tool_call_start_times: dict,
    seen_message_ids: set,
    spinner_active: bool,
    status,
    flush_text_buffer_func,
    is_main_agent: bool,
    is_subagent: bool,
    namespace: tuple,
    subagent_tracker,
) -> tuple[bool, bool]:
    """Process a ToolMessage from the stream.

    Args:
        message: The ToolMessage object
        tool_call_to_name: Dict mapping tool call IDs to names
        displayed_tool_ids: Set of displayed tool call IDs
        tool_call_start_times: Dict of tool call start times
        seen_message_ids: Set of seen message IDs
        spinner_active: Whether spinner is active
        status: Status spinner object
        flush_text_buffer_func: Function to flush text buffer
        is_main_agent: Whether this is the main agent
        is_subagent: Whether this is a subagent
        namespace: LangGraph namespace tuple
        subagent_tracker: SubagentTracker instance

    Returns:
        Tuple of (should_continue, new_spinner_active)
    """
    # Get tool ID
    tool_id = getattr(message, "id", None) or getattr(message, "tool_call_id", None)

    if tool_id and tool_id in seen_message_ids:
        return True, spinner_active

    if tool_id:
        seen_message_ids.add(tool_id)

    # Get tool info
    tool_call_id = getattr(message, "tool_call_id", None)
    tool_name = tool_call_to_name.get(tool_call_id, "") or getattr(message, "name", "")
    tool_status = getattr(message, "status", "success")
    tool_content = format_tool_message_content(message.content)

    # Track subagent errors
    if is_subagent and namespace:
        if tool_status != "success" or (
            tool_content and str(tool_content).lower().startswith("error")
        ):
            subagent_tracker.record_error(namespace, tool_name)

    # Handle task tool completion
    if tool_name == "task" and tool_call_id and tool_call_id in subagent_tracker.active_subagents:
        return _handle_task_completion(
            tool_call_id=tool_call_id,
            tool_status=tool_status,
            namespace=namespace,
            subagent_tracker=subagent_tracker,
            spinner_active=spinner_active,
            status=status,
        )

    # Reset spinner message after non-task tools
    if spinner_active:
        pending_count = len(subagent_tracker.pending_completions)
        if pending_count and subagent_tracker.get_remaining_count():
            pass  # Still aggregating
        elif pending_count:
            label = "subagent" if pending_count == 1 else "subagents"
            status.update(
                f"[bold {COLORS['thinking']}]"
                f"All {pending_count} {label} done, synthesizing..."
            )
        else:
            from namicode_cli.config.config import get_agent_color
            # This will be updated with agent_display_name in the main module
            pass

    # Main agent: display errors and file operations
    if is_main_agent:
        # Display errors
        error_shown = display_tool_error(
            tool_name=tool_name,
            tool_content=tool_content,
            tool_status=tool_status,
            spinner_active=spinner_active,
            status=status,
            flush_text_buffer_func=flush_text_buffer_func,
        )

        # Display file operations
        from namicode_cli.file_ops import get_session_file_op_tracker
        record = get_session_file_op_tracker().complete_with_message(message)

        if not error_shown and record:
            display_file_operation(
                record=record,
                spinner_active=spinner_active,
                status=status,
                flush_text_buffer_func=flush_text_buffer_func,
            )

        # Display result preview
        elif tool_call_id and tool_call_id in displayed_tool_ids and not error_shown:
            # Check if error was already printed
            already_printed_error = (
                tool_name == "shell" and tool_status != "success"
            ) or (
                tool_content
                and isinstance(tool_content, str)
                and tool_content.lstrip().lower().startswith("error")
            )

            if not already_printed_error and tool_call_id:
                _, spinner_active = display_tool_result_preview(
                    tool_name=tool_name,
                    tool_content=tool_content,
                    tool_status=tool_status,
                    tool_call_id=tool_call_id,
                    displayed_tool_ids=displayed_tool_ids,
                    tool_call_start_times=tool_call_start_times,
                    spinner_active=spinner_active,
                    status=status,
                    flush_text_buffer_func=flush_text_buffer_func,
                )

    return True, spinner_active


def _handle_task_completion(
    tool_call_id: str,
    tool_status: str,
    namespace: tuple,
    subagent_tracker,
    spinner_active: bool,
    status,
) -> tuple[bool, bool]:
    """Handle completion of a task tool (subagent).

    Args:
        tool_call_id: Tool call ID
        tool_status: Tool execution status
        namespace: LangGraph namespace tuple
        subagent_tracker: SubagentTracker instance
        spinner_active: Whether spinner is active
        status: Status spinner object

    Returns:
        Tuple of (should_continue, new_spinner_active)
    """
    from namicode_cli.config.config import get_agent_color
    from namicode_cli.ui.streaming import format_condensed_activity
    from namicode_cli.ui.subagent_tracking import format_duration, get_status_icon

    subagent_info = subagent_tracker.complete_subagent(tool_call_id)
    if subagent_info:
        subagent_type, _, start_time = subagent_info
    else:
        subagent_type, start_time = "unknown", time.time()

    subagent_color = get_agent_color(subagent_type)

    # Find activity by LangGraph namespace
    activity = subagent_tracker.claim_namespace_for_tool_call(namespace, tool_call_id)

    # Status icon
    status_icon = get_status_icon(tool_status == "success")

    # Calculate duration
    duration_str = format_duration(time.time() - start_time)

    # Add pending completion
    subagent_tracker.add_pending_completion(
        status_icon=status_icon,
        subagent_type=subagent_type,
        duration_str=duration_str,
        condensed=format_condensed_activity(activity) if activity else None,
        subagent_color=subagent_color,
    )

    # Update spinner
    remaining = subagent_tracker.get_remaining_count()
    done_count = subagent_tracker.get_done_count()
    total_count = done_count + remaining

    if remaining > 0:
        spinner_msg = (
            f"[bold {COLORS['thinking']}]"
            f"{done_count}/{total_count} subagents done, "
            f"waiting for {remaining} more..."
        )
    else:
        label = "subagent" if done_count == 1 else "subagents"
        spinner_msg = (
            f"[bold {COLORS['thinking']}]"
            f"All {done_count} {label} done, synthesizing..."
        )

    if spinner_active:
        status.update(spinner_msg)
    else:
        status.start()
        spinner_active = True
        status.update(spinner_msg)

    return False, spinner_active  # Skip generic tool result preview
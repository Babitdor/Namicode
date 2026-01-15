"""Task execution and streaming logic for the CLI.

This module handles the execution of deep agent tasks and streaming of results
to the terminal. It provides:

- Streaming execution of agent tasks with real-time output
- Human-in-the-loop approval for destructive operations
- Tool call visualization and diff previews
- Error handling and recovery
- Context window management and token tracking

Key Components:
- execute_task(): Main task execution with streaming
- prompt_for_tool_approval(): Interactive approval UI for tool calls
- process_streaming_response(): Handle streaming agent responses
- render_tool_message(): Display tool execution results

The execution flow:
1. Execute agent with streaming enabled
2. Process tool calls and request approval if needed
3. Render tool results and output to terminal
4. Track token usage and context window
5. Handle errors and provide recovery options
- UI rendering functions for formatted output
- Token usage tracking and context management
"""

import asyncio
import json
import sys

from langchain.agents.middleware.human_in_the_loop import (
    ActionRequest,
    ApproveDecision,
    Decision,
    HITLRequest,
    HITLResponse,
    RejectDecision,
)
from langchain_core.messages import HumanMessage, ToolMessage
from langgraph.types import Command, Interrupt
from pydantic import TypeAdapter, ValidationError
from rich import box
from rich.markdown import Markdown
from rich.panel import Panel
from namicode_cli.config.config import COLORS, console, get_agent_color
from namicode_cli.errors.handlers import ErrorHandler
from namicode_cli.file_ops import FileOpTracker, build_approval_preview
from namicode_cli.input import parse_file_mentions, ImageTracker
from namicode_cli.image_utils import create_multimodal_content
from namicode_cli.ui.ui_elements import (
    TokenTracker,
    format_tool_display,
    format_tool_message_content,
    render_diff_block,
    render_file_operation,
    render_todo_list,
)
from namicode_cli.ui.question_prompt import handle_agent_question

_HITL_REQUEST_ADAPTER = TypeAdapter(HITLRequest)


def prompt_for_tool_approval(
    action_request: ActionRequest,
    assistant_id: str | None,
) -> Decision | dict:
    """Prompt user to approve/reject a tool action with interactive menu.

    Uses a cross-platform prompt_toolkit-based menu with arrow key navigation
    that works consistently on Windows, Linux, and Mac.

    Args:
        action_request: The action request containing tool name, args, and description.
        assistant_id: Optional assistant ID for context.

    Returns:
        Decision (ApproveDecision or RejectDecision) OR
        dict with {"type": "auto_approve_all"} to switch to auto-approve mode
    """
    description = action_request.get("description", "No description available")
    name = action_request["name"]
    args = action_request["args"]
    preview = build_approval_preview(name, args, assistant_id) if name else None

    body_lines = []
    if preview:
        body_lines.append(f"[bold]{preview.title}[/bold]")
        body_lines.extend(preview.details)
        if preview.error:
            body_lines.append(f"[red]{preview.error}[/red]")
    else:
        body_lines.append(description)

    # Display action info first
    console.print(
        Panel(
            "[bold yellow]Tool Action Requires Approval[/bold yellow]\n\n"
            + "\n".join(body_lines),
            border_style="yellow",
            box=box.ROUNDED,
            padding=(0, 1),
        )
    )
    if preview and preview.diff and not preview.error:
        console.print()
        render_diff_block(preview.diff, preview.diff_title or preview.title)

    options = ["approve", "reject", "auto-accept all going forward"]
    selected = 0  # Start with approve selected

    try:
        # Import termios/tty only when needed (Unix-only modules)
        import termios
        import tty

        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)  # type: ignore

        try:
            tty.setraw(fd)  # type: ignore
            # Hide cursor during menu interaction
            sys.stdout.write("\033[?25l")
            sys.stdout.flush()

            # Initial render flag
            first_render = True

            while True:
                if not first_render:
                    # Move cursor back to start of menu (up 3 lines, then to start of line)
                    sys.stdout.write("\033[3A\r")

                first_render = False

                # Display options vertically with ANSI color codes
                for i, option in enumerate(options):
                    sys.stdout.write("\r\033[K")  # Clear line from cursor to end

                    if i == selected:
                        if option == "approve":
                            # Green bold with filled checkbox
                            sys.stdout.write("\033[1;32m☑ Approve\033[0m\n")
                        elif option == "reject":
                            # Red bold with filled checkbox
                            sys.stdout.write("\033[1;31m☑ Reject\033[0m\n")
                        else:
                            # Blue bold with filled checkbox for auto-accept
                            sys.stdout.write(
                                "\033[1;34m☑ Auto-accept all going forward\033[0m\n"
                            )
                    elif option == "approve":
                        # Dim with empty checkbox
                        sys.stdout.write("\033[2m☐ Approve\033[0m\n")
                    elif option == "reject":
                        # Dim with empty checkbox
                        sys.stdout.write("\033[2m☐ Reject\033[0m\n")
                    else:
                        # Dim with empty checkbox
                        sys.stdout.write(
                            "\033[2m☐ Auto-accept all going forward\033[0m\n"
                        )

                sys.stdout.flush()

                # Read key
                char = sys.stdin.read(1)

                if char == "\x1b":  # ESC sequence (arrow keys)
                    next1 = sys.stdin.read(1)
                    next2 = sys.stdin.read(1)
                    if next1 == "[":
                        if next2 == "B":  # Down arrow
                            selected = (selected + 1) % len(options)
                        elif next2 == "A":  # Up arrow
                            selected = (selected - 1) % len(options)
                elif char in {"\r", "\n"}:  # Enter
                    sys.stdout.write("\r\n")  # Move to start of line and add newline
                    break
                elif char == "\x03":  # Ctrl+C
                    sys.stdout.write("\r\n")  # Move to start of line and add newline
                    raise KeyboardInterrupt
                elif char.lower() == "a":
                    selected = 0
                    sys.stdout.write("\r\n")  # Move to start of line and add newline
                    break
                elif char.lower() == "r":
                    selected = 1
                    sys.stdout.write("\r\n")  # Move to start of line and add newline
                    break

        finally:
            # Show cursor again
            sys.stdout.write("\033[?25h")
            sys.stdout.flush()
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)  # type: ignore

    except (ImportError, AttributeError, Exception):
        # Fallback for non-Unix systems (ImportError when termios/tty not available)
        # or any other terminal-related errors
        console.print("  ☐ (A)pprove  (default)")
        console.print("  ☐ (R)eject")
        console.print("  ☐ (Auto)-accept all going forward")
        choice = input("\nChoice (A/R/Auto, default=Approve): ").strip().lower()
        if choice in {"r", "reject"}:
            selected = 1
        elif choice in {"auto", "auto-accept"}:
            selected = 2
        else:
            selected = 0

    # Return decision based on selection
    if selected == 0:
        return ApproveDecision(type="approve")
    if selected == 1:
        return RejectDecision(type="reject", message="User rejected the command")
    # Return special marker for auto-approve mode
    return {"type": "auto_approve_all"}


async def execute_task(  # type: ignore
    user_input: str,
    agent,
    assistant_id: str | None,
    session_state,
    token_tracker: TokenTracker | None = None,
    backend=None,
    is_subagent: bool = False,
    image_tracker: ImageTracker | None = None,
) -> None:
    """Execute any task by passing it directly to the AI agent."""
    # Initialize error handler for this execution
    error_handler = ErrorHandler()

    # Parse file mentions and inject content if any
    prompt_text, mentioned_files = parse_file_mentions(user_input)

    if mentioned_files:
        context_parts = [prompt_text, "\n\n## Referenced Files\n"]
        for file_path in mentioned_files:
            try:
                content = file_path.read_text()
                # Limit file content to reasonable size
                if len(content) > 50000:
                    content = content[:50000] + "\n... (file truncated)"
                context_parts.append(
                    f"\n### {file_path.name}\nPath: `{file_path}`\n```\n{content}\n```"
                )
            except Exception as e:
                # Use error handler for better error messages
                recovery = await error_handler.handle(
                    e,
                    context={"file_name": str(file_path), "file_path": str(file_path)},
                )
                error_msg = f"\n### {file_path.name}\n[{recovery.message}]"
                if recovery.suggestion:
                    error_msg += f"\n{recovery.suggestion}"
                context_parts.append(error_msg)

        final_input = "\n".join(context_parts)
    else:
        final_input = prompt_text

    # Include images in the message content
    images_to_send = []
    if image_tracker:
        images_to_send = image_tracker.get_images()
    if images_to_send:
        message_content = create_multimodal_content(final_input, images_to_send)
    else:
        message_content = final_input

    config = {
        "configurable": {"thread_id": session_state.thread_id},
        "metadata": {"assistant_id": assistant_id} if assistant_id else {},
    }
    agent_display_name = assistant_id if assistant_id and is_subagent else "Nami"
    # Use agent-specific color if available, otherwise fall back to defaults
    if assistant_id and is_subagent:
        agent_colors = get_agent_color(assistant_id)
    else:
        agent_colors = COLORS["agent"]
    # Track user message for /context command
    if token_tracker:
        token_tracker.increment_user_messages()

    has_responded = False
    captured_input_tokens = 0
    captured_output_tokens = 0
    current_todos = None  # Track current todo list state

    status = console.status(
        f"[bold {agent_colors}]{agent_display_name} is thinking...",
        spinner="dots",
    )
    status.start()
    spinner_active = True

    tool_icons = {
        "read_file": "📖",
        "write_file": "✏️",
        "edit_file": "✂️",
        "ls": "📁",
        "glob": "🔍",
        "grep": "🔎",
        "shell": "⚡",
        "execute": "🔧",
        "web_search": "🌐",
        "http_request": "🌍",
        "task": "🤖",
        "write_todos": "📋",
    }

    file_op_tracker = FileOpTracker(assistant_id=assistant_id, backend=backend)

    # Track which tool calls we've displayed to avoid duplicates
    displayed_tool_ids = set()
    # Buffer partial tool-call chunks keyed by streaming index
    tool_call_buffers: dict[str | int, dict] = {}
    # Buffer assistant text so we can render complete markdown segments
    pending_text = ""
    # Flag to prevent duplicate responses when both streams print same content
    # Set when updates stream shows a complete AI response
    response_shown_via_updates = False
    # Track when a subagent (task tool) is active - skip display in this case
    # since invoke_subagent handles subagent output
    # Track task tool calls for subagent banner display: {tool_call_id: (subagent_type, description)}
    active_subagents: dict[str, tuple[str, str]] = {}

    def flush_text_buffer(*, final: bool = False) -> None:
        """Flush accumulated assistant text as rendered markdown when appropriate."""
        nonlocal pending_text, spinner_active, has_responded
        if not final or not pending_text.strip():
            return
        if spinner_active:
            status.stop()
            spinner_active = False
        if not has_responded:
            console.print()
            console.print("●", style=agent_colors, markup=False, end=" ")
            has_responded = True
        markdown = Markdown(pending_text.rstrip())
        console.print(agent_display_name, style=agent_colors)
        console.print(markdown, justify="full")
        pending_text = ""

    # Stream input - may need to loop if there are interrupts
    stream_input = {"messages": [{"role": "user", "content": message_content}]}

    try:
        while True:
            interrupt_occurred = False
            hitl_response: dict[str, HITLResponse] = {}
            suppress_resumed_output = False
            # Reset per-turn flags and tracking
            response_shown_via_updates = False
            displayed_tool_ids.clear()
            active_subagents.clear()
            # Track all pending interrupts: {interrupt_id: request_data}
            pending_interrupts: dict[str, HITLRequest] = {}

            async for chunk in agent.astream(
                stream_input,
                stream_mode=["messages", "updates"],  # Dual-mode for HITL support
                subgraphs=True,
                config=config,
                durability="exit",
            ):
                # Unpack chunk - with subgraphs=True and dual-mode, it's (namespace, stream_mode, data)
                if not isinstance(chunk, tuple) or len(chunk) != 3:
                    continue

                _namespace, current_stream_mode, data = chunk

                # Handle UPDATES stream - for interrupts and todos
                if current_stream_mode == "updates":
                    if not isinstance(data, dict):
                        continue

                    # Check for interrupts - collect ALL pending interrupts
                    if "__interrupt__" in data:
                        interrupts: list[Interrupt] = data["__interrupt__"]
                        if interrupts:
                            for interrupt_obj in interrupts:
                                interrupt_value = interrupt_obj.value

                                # Check if this is a question interrupt (from ask_question tool)
                                if (
                                    isinstance(interrupt_value, dict)
                                    and interrupt_value.get("type") == "question"
                                ):
                                    # Handle question interrupt immediately
                                    question_request = interrupt_value.get(
                                        "request", {}
                                    )

                                    if spinner_active:
                                        status.stop()
                                        spinner_active = False

                                    # Handle the question and get user response
                                    response = await handle_agent_question(
                                        question_request
                                    )

                                    # Create a question response to resume with
                                    hitl_response[interrupt_obj.id] = {
                                        "response": response
                                    }
                                    interrupt_occurred = True

                                    # Restart spinner
                                    if not spinner_active:
                                        status.start()
                                        spinner_active = True

                                    continue

                                # Interrupt has required fields: value (HITLRequest) and id (str)
                                # Validate the HITLRequest using TypeAdapter
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

                    # Extract chunk_data from updates for todo checking
                    chunk_data = next(iter(data.values())) if data else None
                    if chunk_data and isinstance(chunk_data, dict):
                        # Check for todo updates
                        if "todos" in chunk_data:
                            new_todos = chunk_data["todos"]
                            if new_todos != current_todos:
                                current_todos = new_todos
                                # Stop spinner before rendering todos
                                if spinner_active:
                                    status.stop()
                                    spinner_active = False
                                console.print()
                                render_todo_list(new_todos)
                                console.print()

                        # Display AI response from model node (completed message)
                        # Only show the AI's final response after tool execution is complete
                        # Don't show tool call intentions or raw tool results
                        # Skip if subagent is active - invoke_subagent handles subagent output
                        if "messages" in chunk_data:
                            messages = chunk_data["messages"]
                            # Check if messages is a valid list (not a Rich Overwrite object)
                            if isinstance(messages, list) and messages:
                                last_msg = messages[-1]
                                msg_type = getattr(last_msg, "type", "")
                                msg_text = getattr(last_msg, "text", None) or getattr(
                                    last_msg, "content", ""
                                )
                                tool_calls = getattr(last_msg, "tool_calls", [])
                                # Skip tool calls, tool results, and AIMessages with tool_calls
                                # Only show AI assistant messages without tool_calls (final responses)
                                # Skip if subagent is active
                                if (
                                    msg_text
                                    and msg_type in ("ai", "assistant")
                                    and not tool_calls
                                ):
                                    # Clear any pending text from messages stream to avoid duplicate
                                    pending_text = ""
                                    # Skip if we already showed this response
                                    if response_shown_via_updates:
                                        continue
                                    response_shown_via_updates = True
                                    if spinner_active:
                                        status.stop()
                                        spinner_active = False
                                    if not has_responded:
                                        console.print()
                                        console.print(
                                            "●",
                                            style=agent_colors,
                                            markup=False,
                                            end=" ",
                                        )
                                        has_responded = True

                                    console.print(
                                        agent_display_name,
                                        style=agent_colors,
                                    )
                                    console.print(Markdown(msg_text), justify="full")

                # Handle MESSAGES stream - for content and tool calls
                elif current_stream_mode == "messages":
                    # Only process messages from root namespace to avoid duplicates
                    # With subgraphs=True, the same content can appear from multiple namespaces
                    if _namespace != ():
                        continue

                    # Messages stream returns (message, metadata) tuples
                    if not isinstance(data, tuple) or len(data) != 2:
                        continue

                    message, _metadata = data

                    if isinstance(message, HumanMessage):
                        content = message.text
                        if content:
                            flush_text_buffer(final=True)
                            if spinner_active:
                                status.stop()
                                spinner_active = False
                            if not has_responded:
                                console.print()
                                console.print(
                                    "●", style=agent_colors, markup=False, end=" "
                                )
                                has_responded = True
                            markdown = Markdown(content)
                            console.print(agent_display_name, style=agent_colors)
                            console.print(markdown, justify="full")

                        continue

                    if isinstance(message, ToolMessage):
                        # Tool results are sent to the agent, not displayed to users
                        # Exception: show shell command errors to help with debugging
                        tool_name = getattr(message, "name", "")
                        tool_status = getattr(message, "status", "success")
                        tool_content = format_tool_message_content(message.content)
                        record = file_op_tracker.complete_with_message(message)

                        # Special handling for task tool completion: display completion banner
                        tool_call_id = getattr(message, "tool_call_id", None)
                        if tool_name == "task" and tool_call_id in active_subagents:
                            subagent_type, _ = active_subagents.pop(tool_call_id)
                            subagent_color = get_agent_color(subagent_type)

                            flush_text_buffer(final=True)
                            if spinner_active:
                                status.stop()
                                spinner_active = False

                            console.print()
                            status_icon = "✓" if tool_status == "success" else "✗"
                            console.print(
                                f"{status_icon} {subagent_type} completed",
                                style=f"{subagent_color}",
                            )
                            console.print()

                            if not spinner_active:
                                status.start()
                                spinner_active = True

                        # Reset spinner message after tool completes
                        if spinner_active:
                            status.update(
                                f"[bold {COLORS['thinking']}]{agent_display_name} is thinking..."
                            )

                        if tool_name == "shell" and tool_status != "success":
                            flush_text_buffer(final=True)
                            if tool_content:
                                if spinner_active:
                                    status.stop()
                                    spinner_active = False
                                console.print()
                                console.print(tool_content, style="red", markup=False)
                                console.print()
                        elif tool_content and isinstance(tool_content, str):
                            stripped = tool_content.lstrip()
                            if stripped.lower().startswith("error"):
                                flush_text_buffer(final=True)
                                if spinner_active:
                                    status.stop()
                                    spinner_active = False
                                console.print()
                                console.print(tool_content, style="red", markup=False)
                                console.print()

                        if record:
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

                        # For all other tools (web_search, http_request, etc.),
                        # results are hidden from user - agent will process and respond
                        continue

                    # Check if this is an AIMessageChunk
                    if not hasattr(message, "content_blocks"):
                        # Fallback for messages without content_blocks
                        continue

                    # Extract token usage if available
                    if token_tracker and hasattr(message, "usage_metadata"):
                        usage = message.usage_metadata
                        if usage:
                            input_toks = usage.get("input_tokens", 0)
                            output_toks = usage.get("output_tokens", 0)
                            if input_toks or output_toks:
                                captured_input_tokens = max(
                                    captured_input_tokens, input_toks
                                )
                                captured_output_tokens = max(
                                    captured_output_tokens, output_toks
                                )

                    # Process content blocks (this is the key fix!)
                    for block in message.content_blocks:
                        block_type = block.get("type")

                        # Handle text blocks - skip if subagent is active or updates stream already showed
                        if block_type == "text":
                            text = block.get("text", "")
                            if text and not response_shown_via_updates:
                                pending_text += text

                        # Handle reasoning blocks
                        elif block_type == "reasoning":
                            flush_text_buffer(final=True)
                            reasoning = block.get("reasoning", "")
                            if reasoning and spinner_active:
                                status.stop()
                                spinner_active = False
                                # Could display reasoning differently if desired
                                # For now, skip it or handle minimally

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
                                    # Wait for more chunks to form valid JSON
                                    continue
                            elif parsed_args is None:
                                continue

                            # Ensure args are in dict form for formatter
                            if not isinstance(parsed_args, dict):
                                parsed_args = {"value": parsed_args}

                            flush_text_buffer(final=True)
                            display_needed = False
                            if buffer_id is not None:
                                if buffer_id not in displayed_tool_ids:
                                    displayed_tool_ids.add(buffer_id)
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

                                icon = tool_icons.get(buffer_name, "🔧")

                                if spinner_active:
                                    status.stop()

                                if has_responded:
                                    console.print()

                                display_str = format_tool_display(
                                    buffer_name, parsed_args
                                )

                                console.print(
                                    f"  {icon} {display_str}",
                                    style=f"dim {COLORS['tool']}",
                                    markup=False,
                                )

                                # Special handling for task tool: display subagent delegation banner
                                if (
                                    buffer_name == "task"
                                    and "subagent_type" in parsed_args
                                ):
                                    subagent_type = parsed_args["subagent_type"]
                                    description = parsed_args.get("description", "")

                                    # Store for completion banner later
                                    if buffer_id:
                                        active_subagents[buffer_id] = (
                                            subagent_type,
                                            description,
                                        )

                                    # Get subagent color if available
                                    subagent_color = get_agent_color(subagent_type)

                                    # Truncate description for banner
                                    desc_preview = (
                                        description[:60] + "..."
                                        if len(description) > 60
                                        else description
                                    )

                                    # Display delegation banner
                                    console.print()
                                    banner_text = (
                                        f"╭─ Delegating to {subagent_type} "
                                        + "─" * (50 - len(subagent_type))
                                    )
                                    console.print(
                                        banner_text, style=f"dim {subagent_color}"
                                    )
                                    if desc_preview:
                                        console.print(
                                            f"│ Task: {desc_preview}",
                                            style=f"dim {subagent_color}",
                                        )
                                    console.print(
                                        "╰" + "─" * 60, style=f"dim {subagent_color}"
                                    )
                                    console.print()

                                # Restart spinner with context about which tool is executing
                                status.update(
                                    f"[bold {COLORS['thinking']}]{agent_display_name} is executing {display_str}..."
                                )
                                status.start()
                                spinner_active = True

                    if getattr(message, "chunk_position", None) == "last":
                        flush_text_buffer(final=True)

            # After streaming loop - handle interrupt if it occurred
            flush_text_buffer(final=True)

            # Handle human-in-the-loop after stream completes
            if interrupt_occurred:
                any_rejected = False

                for interrupt_id, hitl_request in pending_interrupts.items():
                    # Check if auto-approve is enabled
                    if session_state.auto_approve:
                        # Auto-approve all commands without prompting
                        decisions = []
                        for action_request in hitl_request["action_requests"]:
                            # Show what's being auto-approved (brief, dim message)
                            if spinner_active:
                                status.stop()
                                spinner_active = False

                            description = action_request.get(
                                "description", "tool action"
                            )
                            console.print()
                            console.print(f"  [dim]⚡ {description}[/dim]")

                            decisions.append({"type": "approve"})

                        hitl_response[interrupt_id] = {"decisions": decisions}

                        # Restart spinner for continuation
                        if not spinner_active:
                            status.start()
                            spinner_active = True
                    else:
                        # Normal HITL flow - stop spinner and prompt user
                        if spinner_active:
                            status.stop()
                            spinner_active = False

                        # Handle human-in-the-loop approval
                        decisions = []
                        for action_index, action_request in enumerate(
                            hitl_request["action_requests"]
                        ):
                            decision = prompt_for_tool_approval(
                                action_request,
                                assistant_id,
                            )

                            # Check if user wants to switch to auto-approve mode
                            if (
                                isinstance(decision, dict)
                                and decision.get("type") == "auto_approve_all"
                            ):
                                # Switch to auto-approve mode
                                session_state.auto_approve = True
                                console.print()
                                console.print(
                                    "[bold blue]✓ Auto-approve mode enabled[/bold blue]"
                                )
                                console.print(
                                    "[dim]All future tool actions will be automatically approved.[/dim]"
                                )
                                console.print()

                                # Approve this action and all remaining actions in the batch
                                decisions.append({"type": "approve"})
                                for _remaining_action in hitl_request[
                                    "action_requests"
                                ][action_index + 1 :]:
                                    decisions.append({"type": "approve"})
                                break
                            decisions.append(decision)

                            # Mark file operations as HIL-approved if user approved
                            if decision.get("type") == "approve":
                                tool_name = action_request.get("name")
                                if tool_name in {"write_file", "edit_file"}:
                                    file_op_tracker.mark_hitl_approved(
                                        tool_name, action_request.get("args", {})
                                    )

                        if any(
                            decision.get("type") == "reject" for decision in decisions
                        ):
                            any_rejected = True

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
                    return

                # Resume the agent with the human decision
                stream_input = Command(resume=hitl_response)
                # Continue the while loop to restream
            else:
                # No interrupt, break out of while loop
                break

    except asyncio.CancelledError:
        # Event loop cancelled the task (e.g. Ctrl+C during streaming) - clean up and return
        if spinner_active:
            status.stop()
        console.print("\n[yellow]Interrupted by user[/yellow]")
        console.print("Updating agent state...", style="dim")

        try:
            await agent.aupdate_state(
                config=config,
                values={
                    "messages": [
                        HumanMessage(
                            content="[The previous request was cancelled by the system]"
                        )
                    ]
                },
            )
            console.print("Ready for next command.\n", style="dim")
        except Exception as e:
            console.print(f"[red]Warning: Failed to update agent state: {e}[/red]\n")

        return

    except KeyboardInterrupt:
        # User pressed Ctrl+C - clean up and exit gracefully
        if spinner_active:
            status.stop()
        console.print("\n[yellow]Interrupted by user[/yellow]")
        console.print("Updating agent state...", style="dim")

        # Inform the agent synchronously (in async context)
        try:
            await agent.aupdate_state(
                config=config,
                values={
                    "messages": [
                        HumanMessage(
                            content="[User interrupted the previous request with Ctrl+C]"
                        )
                    ]
                },
            )
            console.print("Ready for next command.\n", style="dim")
        except Exception as e:
            console.print(f"[red]Warning: Failed to update agent state: {e}[/red]\n")

        return

    if spinner_active:
        status.stop()

    if has_responded:
        console.print()
        # Track token usage (display only via /tokens command)
        if token_tracker and (captured_input_tokens or captured_output_tokens):
            token_tracker.add(captured_input_tokens, captured_output_tokens)
        # Track assistant response and tool calls for /context command
        if token_tracker:
            token_tracker.increment_assistant_messages()
            # Track tool calls (count of unique tool call IDs displayed)
            if displayed_tool_ids:
                token_tracker.increment_tool_calls(len(displayed_tool_ids))

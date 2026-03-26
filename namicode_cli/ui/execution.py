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
import time
from pathlib import Path

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
from rich.text import Text

from namicode_cli.config.config import COLORS, console, get_agent_color
from namicode_cli.config.model_create import get_current_model_name
from namicode_cli.errors.handlers import ErrorHandler
from namicode_cli.file_ops import (
    build_approval_preview,
    get_session_file_op_tracker,
)
from namicode_cli.image_utils import create_multimodal_content
from namicode_cli.input import ImageTracker, parse_file_mentions
from namicode_cli.ui.question_prompt import handle_agent_question
from namicode_cli.ui.ui_elements import (
    TokenTracker,
    format_tool_display,
    format_tool_message_content,
    format_tool_result_preview,
    render_diff_block,
    render_file_operation,
    render_todo_list,
)
from namicode_cli.vision import model_supports_vision, suggest_vision_model

_HITL_REQUEST_ADAPTER = TypeAdapter(HITLRequest)


# Tool icons for display
TOOL_ICONS: dict[str, str] = {
    # File operations
    "read_file": "📖",
    "write_file": "✏️",
    "edit_file": "✂️",
    "ls": "📁",
    "glob": "🔍",
    "grep": "🔎",
    # Shell
    "shell": "⚡",
    "execute": "🔧",
    # Web
    "web_search": "🌐",
    "duckduckgo_search": "🦆",
    "fetch_url": "🔗",
    "http_request": "🌐",
    # Task
    "task": "🤖",
    # Todos
    "write_todos": "📋",
    # Server management
    "start_dev_server": "🚀",
    "stop_server": "🛑",
    "list_servers": "📋",
    # Test runner
    "run_tests": "🧪",
    # Memory
    "write_memory": "💾",
    "read_memory": "📖",
    "list_memories": "📑",
    "delete_memory": "🗑️",
    # Code quality
    "lint_code": "🔍",
    "check_types": "🔎",
    "package_info": "📦",
    # Question/Plan
    "ask_question": "❓",
    "exit_plan_mode": "✅",
    # Browser
    "browser_navigate": "🌐",
    "browser_click": "👆",
    "browser_type": "⌨️",
    "browser_screenshot": "📸",
    "browser_query": "❓",
    "browser_get_content": "📄",
    "browser_get_url": "🔗",
    # Git
    "git_status": "📊",
    "git_log": "📜",
    "git_diff": "📝",
    "git_blame": "🔍",
    "git_branch": "🌿",
    "git_stash": "📦",
}


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
    seen_message_ids: set[str] | None = None,
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
        # Check if current model supports vision
        current_model = get_current_model_name()
        if not model_supports_vision(current_model):
            suggested = suggest_vision_model(current_model)
            console.print()
            console.print(
                f"[yellow]Warning: Current model '{current_model}' may not support images.[/yellow]"
            )
            if suggested:
                console.print(
                    f"[dim]Consider using a vision model like '{suggested}'[/dim]"
                )
                console.print("[dim]Use /model to change models.[/dim]")
            console.print()
        message_content = create_multimodal_content(final_input, images_to_send)
    else:
        message_content = final_input

    config = {
        "configurable": {"thread_id": session_state.thread_id},
        # Metadata is passed through to LangSmith as filterable run metadata.
        # thread_id lets you correlate all runs in a session; assistant_id identifies the agent.
        "metadata": {
            "thread_id": session_state.thread_id,
            **({"assistant_id": assistant_id} if assistant_id else {}),
        },
        # run_name becomes the trace name in LangSmith (replaces generic "LangGraph").
        "run_name": assistant_id or "nami-agent",
        # tags appear as filterable labels on every run in this session.
        "tags": ["nami", assistant_id] if assistant_id else ["nami"],
    }

    # Display agent names properly
    agent_display_name = assistant_id

    if assistant_id == "nami-agent":
        agent_display_name = "Nami"
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
    captured_cache_read_tokens = 0
    captured_cache_creation_tokens = 0
    current_todos = None  # Track current todo list state
    _prev_auto_approve: bool | None = None  # Saved auto_approve for plan execution restore

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

    # Track which tool calls we've displayed to avoid duplicates
    displayed_tool_ids = set()
    # Buffer partial tool-call chunks keyed by streaming index
    tool_call_buffers: dict[str | int, dict] = {}
    # Buffer assistant text so we can render complete markdown segments
    pending_text = ""
    # Track task tool calls for subagent banner display: {tool_call_id: (subagent_type, description)}
    active_subagents: dict[str, tuple[str, str]] = {}
    # Track tool names by tool_call_id for reliable ToolMessage handling
    tool_call_to_name: dict[str, str] = {}
    # Track subagent nesting for indentation: [(tool_call_id, subagent_type), ...]
    subagent_stack: list[tuple[str, str]] = []
    # Track subagent activity by namespace: {namespace_tuple: {"calls": [...], "categories": {...}, ...}}
    subagent_activity_by_ns: dict[tuple, dict] = {}
    # Map task tool_call_id to expected subagent namespace
    tool_call_id_to_ns: dict[str, tuple] = {}
    # Track when each tool call was first displayed (for elapsed-time display)
    tool_call_start_times: dict[str, float] = {}
    # Track the AI message ID whose text is currently in pending_text (for dedup)
    current_ai_message_id: str | None = None
    # Track last displayed activity line for each subagent (for in-place updates)
    subagent_last_line: dict[tuple, str] = {}
    # Deferred subagent completion banners — printed together just before main-agent synthesis
    pending_completions: list[dict] = []

    # Tool category icons for summary display
    TOOL_CATEGORY_ICONS: dict[str, str] = {
        "files_read": "📖",
        "files_written": "✏️",
        "search": "🔎",
        "web": "🌐",
        "shell": "⚡",
        "tests": "🧪",
        "server": "🚀",
        "git": "📊",
        "browser": "🌐",
        "memory": "💾",
        "other": "🔧",
    }

    # Tool category mapping for summary categorization
    TOOL_CATEGORIES: dict[str, str] = {
        # Files read
        "read_file": "files_read",
        "ls": "files_read",
        "glob": "files_read",
        "grep": "files_read",
        # Files written
        "write_file": "files_written",
        "edit_file": "files_written",
        # Search
        "web_search": "search",
        "duckduckgo_search": "search",
        "docs_search": "search",
        "semantic_search": "search",
        "find_similar_code": "search",
        "find_function": "search",
        # Web
        "fetch_url": "web",
        "http_request": "web",
        # Shell
        "shell": "shell",
        "execute": "shell",
        "execute_bash": "shell",
        # Tests
        "run_tests": "tests",
        # Server
        "start_dev_server": "server",
        "stop_server": "server",
        "list_servers": "server",
        # Git
        "git_status": "git",
        "git_log": "git",
        "git_diff": "git",
        "git_blame": "git",
        "git_branch": "git",
        "git_stash": "git",
        # Browser
        "browser_navigate": "browser",
        "browser_click": "browser",
        "browser_screenshot": "browser",
        "browser_type": "browser",
        "browser_query": "browser",
        "browser_fill_form": "browser",
        "browser_upload": "browser",
        # Memory
        "write_memory": "memory",
        "read_memory": "memory",
        "list_memories": "memory",
        "delete_memory": "memory",
    }

    # Category display order for summary
    CATEGORY_ORDER = [
        "files_read",
        "files_written",
        "search",
        "web",
        "shell",
        "tests",
        "server",
        "git",
        "browser",
        "memory",
    ]

    def get_subagent_indent() -> str:
        """Get indentation based on current subagent nesting depth."""
        return "  " * len(subagent_stack)

    def format_condensed_activity(activity: dict, max_items: int = 3) -> str:
        """Format a condensed activity summary for display.

        Shows key files/operations in a compact format:
        - File paths: "auth.py, utils.py, +2 more"
        - Categories: "🔎 3 searches • 🌐 2 web"
        """
        parts = []

        # Show file operations with paths (most useful)
        files_read = activity.get("files_read", [])
        if files_read:
            # Get just filenames, not full paths
            filenames = [Path(f).name for f in files_read[:max_items]]
            remaining = len(files_read) - max_items
            if remaining > 0:
                parts.append(f"📖 {', '.join(filenames)}, +{remaining}")
            else:
                parts.append(f"📖 {', '.join(filenames)}")

        files_written = activity.get("files_written", [])
        if files_written:
            filenames = [Path(f).name for f in files_written[:max_items]]
            remaining = len(files_written) - max_items
            if remaining > 0:
                parts.append(f"✏️ {', '.join(filenames)}, +{remaining}")
            else:
                parts.append(f"✏️ {', '.join(filenames)}")

        # Show other categories as counts
        categories = activity.get("categories", {})
        for cat in CATEGORY_ORDER:
            if cat in ("files_read", "files_written"):
                continue  # Already handled above
            count = categories.get(cat, 0)
            if count > 0:
                icon = TOOL_CATEGORY_ICONS.get(cat, "🔧")
                parts.append(f"{icon} {count}")

        # Show errors count
        errors = activity.get("errors", [])
        if errors:
            parts.append(f"❌ {len(errors)}")

        return " • ".join(parts) if parts else "starting..."

    def flush_pending_completions() -> None:
        """Print all deferred subagent completion banners as one grouped block."""
        nonlocal spinner_active
        if not pending_completions:
            return
        if spinner_active:
            status.stop()
            spinner_active = False
        console.print()
        for comp in pending_completions:
            icon = comp["status_icon"]
            name = comp["subagent_type"]
            dur = comp["duration_str"]
            cond = comp["condensed"]
            ind = comp["indent"]
            color = comp["subagent_color"]
            if cond:
                console.print(f"{ind}└─ {icon} {name}{dur}: {cond}", style=color)
            else:
                console.print(f"{ind}└─ {icon} {name}{dur}", style=color)
        pending_completions.clear()
        console.print()

    def flush_text_buffer(*, final: bool = False) -> None:
        """Flush accumulated assistant text as rendered markdown when appropriate."""
        nonlocal pending_text, spinner_active, has_responded, current_ai_message_id
        if not final or not pending_text.strip():
            return
        # Skip if this specific AI message was already shown via the updates stream.
        # Use per-message-ID deduplication so subsequent responses in the same turn
        # (e.g. after tool calls) are NOT suppressed.
        if current_ai_message_id and current_ai_message_id in seen_message_ids:
            pending_text = ""
            current_ai_message_id = None
            return

        # Show all deferred subagent completions together before the synthesis response
        flush_pending_completions()
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
        # Mark this message as shown so the updates stream won't duplicate it
        if current_ai_message_id:
            seen_message_ids.add(current_ai_message_id)
            current_ai_message_id = None
        pending_text = ""

    # Stream input - may need to loop if there are interrupts
    stream_input = {"messages": [{"role": "user", "content": message_content}]}
    # Dedup state persists across HITL resume iterations AND across turns
    # (when caller passes a persistent set) so re-emitted messages/tool-calls
    # from agent state are not displayed a second time.
    if seen_message_ids is None:
        seen_message_ids = set()

    # Snapshot message count before streaming to detect auto-compaction
    pre_stream_msg_count: int | None = None
    try:
        _pre_state = await agent.aget_state(config)
        _pre_msgs = _pre_state.values.get("messages", [])
        pre_stream_msg_count = len(_pre_msgs)
        # Pre-seed seen_message_ids with all existing state message IDs.
        # The messages stream replays ALL state messages at the start of each
        # astream() call; without this, old HumanMessages and AIMessages would
        # be re-displayed on every turn.
        for _m in _pre_msgs:
            _mid = getattr(_m, "id", None)
            if _mid:
                seen_message_ids.add(_mid)
    except Exception:
        pass

    try:
        while True:
            interrupt_occurred = False
            hitl_response: dict[str, HITLResponse] = {}
            suppress_resumed_output = False
            # Reset per-iteration tracking (in-progress state only)
            active_subagents.clear()
            subagent_stack.clear()
            subagent_activity_by_ns.clear()
            tool_call_id_to_ns.clear()
            tool_call_start_times.clear()
            current_ai_message_id = None
            pending_completions.clear()
            # Track all pending interrupts: {interrupt_id: request_data}
            pending_interrupts: dict[str, HITLRequest] = {}

            async for chunk in agent.astream(
                stream_input,
                stream_mode=["updates", "messages"],  # Dual-mode for HITL support
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

                                # Check if this is a plan approval interrupt (from exit_plan_mode tool)
                                if (
                                    isinstance(interrupt_value, dict)
                                    and interrupt_value.get("type") == "plan_approval"
                                ):
                                    if spinner_active:
                                        status.stop()
                                        spinner_active = False

                                    # Import and show plan approval dialog
                                    from namicode_cli.ui.question_prompt import (
                                        prompt_for_plan_approval,
                                    )

                                    console.print()
                                    console.print(
                                        "[cyan]Planning complete.[/cyan] Review the plan:",
                                        style="bold",
                                    )

                                    result = prompt_for_plan_approval(
                                        todos=current_todos,
                                        plan_summary="Agent has created a plan for your task",
                                    )

                                    if result["approved"]:
                                        # User approved - exit plan mode
                                        session_state.plan_mode_enabled = False
                                        try:
                                            from namicode_cli.agents.core_agent import (
                                                set_agent_plan_mode_state,
                                            )

                                            await set_agent_plan_mode_state(
                                                agent, session_state.thread_id, False
                                            )
                                        except Exception:
                                            pass

                                        if result["action"] == "proceed_auto":
                                            # Auto-accept: temporarily enable auto-approve
                                            _prev_auto_approve = session_state.auto_approve
                                            session_state.auto_approve = True
                                            hitl_response[interrupt_obj.id] = {
                                                "approved": True,
                                                "mode": "auto",
                                            }
                                        else:
                                            # Manual-accept: ensure HITL is active
                                            _prev_auto_approve = session_state.auto_approve
                                            session_state.auto_approve = False
                                            hitl_response[interrupt_obj.id] = {
                                                "approved": True,
                                                "mode": "manual",
                                            }
                                    else:
                                        # User rejected or wants to edit - stay in plan mode
                                        hitl_response[interrupt_obj.id] = {
                                            "approved": False
                                        }

                                    console.print()
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

                        # AI responses are displayed exclusively via the messages
                        # stream (token-by-token in pending_text → flush_text_buffer).
                        # Displaying them here too caused double-printing because IDs
                        # can differ between the updates and messages streams.

                # Handle MESSAGES stream - for content and tool calls
                elif current_stream_mode == "messages":
                    # Determine if this is main agent or subagent
                    is_main_agent = _namespace == ()
                    is_subagent = _namespace != ()

                    # Get subagent type from namespace if this is a subagent
                    subagent_type_for_ns = None
                    if is_subagent and len(_namespace) > 0:
                        # Namespace is like ('general-purpose',) or ('code-reviewer',)
                        subagent_type_for_ns = _namespace[0]

                    # For main agent: process fully for display
                    # For subagent: track tool calls only (no display), skip reasoning text
                    if not is_main_agent:
                        # Subagent: track tool calls but don't display
                        # We still need to process ToolMessage and tool_call chunks for tracking
                        pass

                    # Messages stream returns (message, metadata) tuples
                    if not isinstance(data, tuple) or len(data) != 2:
                        continue

                    message, _metadata = data

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

                        # Track subagent tool errors for summary
                        if is_subagent and subagent_type_for_ns:
                            if tool_status != "success" or (
                                tool_content
                                and str(tool_content).lower().startswith("error")
                            ):
                                activity = subagent_activity_by_ns.get(_namespace)
                                if activity:
                                    activity["errors"].append(tool_name)

                        # Special handling for task tool completion: display completion banner with summary
                        if tool_name == "task" and tool_call_id in active_subagents:
                            subagent_type, _ = active_subagents.pop(tool_call_id)
                            subagent_color = get_agent_color(subagent_type)

                            # Pop from stack for indentation
                            stack_idx = None
                            for i, (tid, _) in enumerate(subagent_stack):
                                if tid == tool_call_id:
                                    stack_idx = i
                                    break
                            if stack_idx is not None:
                                subagent_stack.pop(stack_idx)

                            indent = get_subagent_indent()

                            # Get activity from namespace mapping (more reliable)
                            expected_ns = tool_call_id_to_ns.pop(tool_call_id, None)
                            activity = (
                                subagent_activity_by_ns.pop(expected_ns, None)
                                if expected_ns
                                else None
                            )

                            # Status icon
                            status_icon = "✓" if tool_status == "success" else "✗"

                            # Calculate duration
                            duration_str = ""
                            if activity and "start_time" in activity:
                                elapsed = time.time() - activity["start_time"]
                                if elapsed >= 60:
                                    mins = int(elapsed // 60)
                                    secs = int(elapsed % 60)
                                    duration_str = f" ({mins}m {secs}s)"
                                else:
                                    duration_str = f" ({int(elapsed)}s)"

                            # Defer completion banner — all banners print together
                            # just before the main agent's synthesis response
                            pending_completions.append(
                                {
                                    "status_icon": status_icon,
                                    "subagent_type": subagent_type,
                                    "duration_str": duration_str,
                                    "condensed": (
                                        format_condensed_activity(activity)
                                        if activity
                                        else None
                                    ),
                                    "indent": indent,
                                    "subagent_color": subagent_color,
                                }
                            )

                            # Always update spinner to show aggregation progress,
                            # including when the last subagent finishes.
                            remaining = len(active_subagents)
                            done_count = len(pending_completions)
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

                        # Reset spinner message after non-task tools complete.
                        # For task completions the message was already set above.
                        elif spinner_active:
                            if pending_completions and active_subagents:
                                # Still aggregating — keep current progress text
                                pass
                            elif pending_completions:
                                # All subagents done, synthesis imminent
                                label = (
                                    "subagent"
                                    if len(pending_completions) == 1
                                    else "subagents"
                                )
                                status.update(
                                    f"[bold {COLORS['thinking']}]"
                                    f"All {len(pending_completions)} {label} done, synthesizing..."
                                )
                            else:
                                status.update(
                                    f"[bold {COLORS['thinking']}]{agent_display_name} is thinking..."
                                )

                        # Main agent: display errors and file operations
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
                            elif tool_call_id in displayed_tool_ids:
                                # Show a one-line result preview for every other tool the user
                                # saw announced (grep, ls, glob, execute, web_search, …).
                                # Errors that were already printed above are skipped.
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
                                    start = tool_call_start_times.pop(
                                        tool_call_id, None
                                    )
                                    if start is not None:
                                        elapsed = time.time() - start
                                    preview = format_tool_result_preview(
                                        tool_name, tool_content, tool_status, elapsed
                                    )
                                    if preview:
                                        flush_text_buffer(final=True)
                                        if spinner_active:
                                            status.stop()
                                            spinner_active = False
                                        is_err = preview.startswith("✗")
                                        sty = (
                                            "red" if is_err else f"dim {COLORS['tool']}"
                                        )
                                        detail = Text()
                                        detail.append("  ⎿  ", style=sty)
                                        detail.append(preview, style=sty)
                                        console.print(detail)
                                        if not spinner_active:
                                            status.start()
                                            spinner_active = True

                        # For all other tools (web_search, http_request, etc.),
                        # results are shown via the preview above; agent will also process them
                        continue

                    # Build a normalized blocks list that works for all model families:
                    # - Anthropic: content_blocks is a list of typed dicts
                    # - Ollama / OpenAI / Gemini: content is a plain string, tool calls in tool_call_chunks
                    if hasattr(message, "content_blocks"):
                        blocks: list[dict] = message.content_blocks
                    else:
                        # Synthesize blocks from flat content + tool_call_chunks
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

                    # Extract token usage — only from main agent to avoid subagent contamination
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
                                    # Track tool name for reliable ToolMessage lookup
                                    tool_call_to_name[buffer_id] = buffer_name
                                    # Record start time for elapsed-time display
                                    tool_call_start_times[buffer_id] = time.time()
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
                                icon = TOOL_ICONS.get(buffer_name, "🔧")
                                display_str = format_tool_display(
                                    buffer_name, parsed_args
                                )

                                # Main agent: display tool call
                                if is_main_agent:
                                    if spinner_active:
                                        status.stop()
                                        spinner_active = False

                                    if has_responded:
                                        console.print()

                                    console.print(
                                        f"  {icon} {display_str}",
                                        style=f"dim {COLORS['tool']}",
                                        markup=False,
                                    )

                                # Subagent: track but don't display
                                elif is_subagent and subagent_type_for_ns:
                                    activity = subagent_activity_by_ns.get(_namespace)
                                    if activity:
                                        # Track call with category
                                        category = TOOL_CATEGORIES.get(
                                            buffer_name, "other"
                                        )
                                        activity["calls"].append(
                                            (buffer_name, category)
                                        )
                                        activity["categories"][category] = (
                                            activity["categories"].get(category, 0) + 1
                                        )

                                        # Track specific paths for file operations
                                        if category == "files_read":
                                            path = (
                                                parsed_args.get("path")
                                                or parsed_args.get("file_path")
                                                or "?"
                                            )
                                            activity["files_read"].append(path)
                                        elif category == "files_written":
                                            path = (
                                                parsed_args.get("path")
                                                or parsed_args.get("file_path")
                                                or "?"
                                            )
                                            activity["files_written"].append(path)

                            # Special handling for task tool: display subagent delegation banner
                            if buffer_name == "task" and "subagent_type" in parsed_args:
                                subagent_type = parsed_args["subagent_type"]
                                description = parsed_args.get("description", "")

                                # Store for completion banner later
                                if buffer_id:
                                    active_subagents[buffer_id] = (
                                        subagent_type,
                                        description,
                                    )
                                    # Initialize activity tracking by namespace
                                    # Namespace will be (subagent_type,) when subagent runs
                                    expected_ns = (subagent_type,)
                                    subagent_activity_by_ns[expected_ns] = {
                                        "name": subagent_type,
                                        "calls": [],
                                        "files_read": [],
                                        "files_written": [],
                                        "errors": [],
                                        "categories": {},
                                        "start_time": time.time(),
                                    }
                                    # Map tool_call_id -> namespace for summary lookup
                                    tool_call_id_to_ns[buffer_id] = expected_ns
                                    # Track nesting for indentation
                                    subagent_stack.append((buffer_id, subagent_type))

                                    # Get subagent color (with fallback)
                                    subagent_color = get_agent_color(subagent_type)

                                    # Calculate indentation based on nesting depth
                                    indent = get_subagent_indent()
                                    desc_preview = (
                                        description[:100] + "..."
                                        if len(description) > 100
                                        else description
                                    )

                                    # Display delegation banner with indentation
                                    console.print()
                                    banner_text = (
                                        f"{indent}┌─ {subagent_type} "
                                        + "─"
                                        * max(20, 40 - len(subagent_type) - len(indent))
                                    )
                                    console.print(
                                        banner_text, style=f"dim {subagent_color}"
                                    )
                                    if desc_preview:
                                        console.print(
                                            f"{indent}│ {desc_preview}",
                                            style=f"dim {subagent_color}",
                                        )
                                    console.print(
                                        f"{indent}│", style=f"dim {subagent_color}"
                                    )

                                    # Restart spinner with context about which tool is executing
                                    status.update(
                                        f"[bold {COLORS['thinking']}]{agent_display_name} is executing {display_str}..."
                                    )
                                    status.start()
                                    spinner_active = True

                    if getattr(message, "chunk_position", None) == "last":  # ← HERE
                        if hasattr(message, "id"):
                            seen_message_ids.add(message.id)
                        flush_text_buffer(final=True)

            # After streaming loop - handle interrupt if it occurred
            flush_text_buffer(final=True)
            # Safety net: flush any completion banners that weren't printed
            # (e.g. if the agent responded via updates-stream and flush_text_buffer
            # was never triggered with pending_text)
            flush_pending_completions()

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

        # Detect if SummarizationMiddleware auto-compacted during this turn
        if pre_stream_msg_count is not None:
            try:
                _post_state = await agent.aget_state(config)
                post_msg_count = len(_post_state.values.get("messages", []))
                if post_msg_count < pre_stream_msg_count - 2:
                    console.print()
                    console.print(
                        "[dim]⟳ Context auto-compacted to stay within window[/dim]"
                    )
            except Exception:
                pass

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

    # Safety flush: show any pending subagent completions that weren't shown yet
    # (e.g., if the main agent produced no text this turn)
    flush_pending_completions()

    if spinner_active:
        status.stop()

    # Update session_state.todos if we have any
    if current_todos:
        session_state.todos = current_todos

    # Restore auto_approve if it was temporarily changed for plan execution
    if _prev_auto_approve is not None:
        session_state.auto_approve = _prev_auto_approve

    if has_responded:
        console.print()
        # Track token usage (display only via /tokens command)
        if token_tracker and (captured_input_tokens or captured_output_tokens):
            token_tracker.add(
                captured_input_tokens,
                captured_output_tokens,
                cache_read_tokens=captured_cache_read_tokens,
                cache_creation_tokens=captured_cache_creation_tokens,
            )
        # Track assistant response and tool calls for /context command
        if token_tracker:
            token_tracker.increment_assistant_messages()
            # Track tool calls (count of unique tool call IDs displayed)
            if displayed_tool_ids:
                token_tracker.increment_tool_calls(len(displayed_tool_ids))

            # Build detailed context breakdown from agent state
            try:
                from namicode_cli.context.context_manager import build_context_breakdown

                _bd_state = await agent.aget_state(config)
                _bd_msgs = _bd_state.values.get("messages", [])
                if _bd_msgs and token_tracker.model_name:
                    breakdown = build_context_breakdown(_bd_msgs, token_tracker.model_name)
                    token_tracker.set_breakdown(breakdown)
            except Exception:
                pass

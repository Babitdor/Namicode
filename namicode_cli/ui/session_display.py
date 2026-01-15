"""Display logic for restored sessions.

This module provides CLI display functions for showing restored session history
in a Claude Code style format with proper formatting and warnings.
"""

from datetime import datetime
from pathlib import Path

from langchain_core.messages import (
    BaseMessage,
    HumanMessage,
    AIMessage,
    SystemMessage,
    ToolMessage,
)
from rich import box
from rich.markdown import Markdown
from rich.panel import Panel

from namicode_cli.config.config import COLORS, console
from namicode_cli.session.session_persistence import SessionData


def display_restored_session(
    session_data: SessionData,
    warnings: list[str],
    nami_md_loaded: bool = False,
) -> None:
    """Display restored conversation history Claude Code style.

    Shows:
    - Session metadata (ID, age, message count)
    - Warnings (if any) about drift
    - Recent messages with proper formatting
    - Continuation indicator

    Args:
        session_data: The loaded session data
        warnings: List of warning messages about drift or compatibility
        nami_md_loaded: Whether NAMI.md was loaded for this session
    """
    meta = session_data.meta

    # Display session header
    console.print()
    console.print(
        f"[bold cyan]↺ Continuing session[/bold cyan] "
        f"[dim]{meta.session_id[:8]}...[/dim]"
    )

    # Display message count
    if meta.message_count > 0:
        recent_count = len(session_data.messages)
        console.print(
            f"  [dim]{meta.message_count} total messages "
            f"({recent_count} recent in context)[/dim]"
        )

    # Display session age
    try:
        created_at = datetime.fromisoformat(meta.created_at)
        # Handle both timezone-aware and timezone-naive datetimes
        if created_at.tzinfo is not None:
            from datetime import timezone

            current_time = datetime.now(timezone.utc)
        else:
            current_time = datetime.now()

        age = current_time - created_at
        if age.days > 0:
            age_str = f"{age.days} day{'s' if age.days > 1 else ''} ago"
        elif age.seconds > 3600:
            hours = age.seconds // 3600
            age_str = f"{hours} hour{'s' if hours > 1 else ''} ago"
        else:
            minutes = age.seconds // 60
            age_str = f"{minutes} minute{'s' if minutes > 1 else ''} ago"
        console.print(f"  [dim]Created: {age_str}[/dim]")
    except (ValueError, AttributeError):
        # If we can't parse the date, just show the raw timestamp
        console.print(f"  [dim]Created: {meta.created_at}[/dim]")

    # Display task state if available
    if meta.current_task:
        console.print(f"  [dim]Task: {meta.current_task}[/dim]")
        console.print(f"  [dim]Status: {meta.task_status}[/dim]")

        if meta.task_status == "blocked" and meta.blocked_reason:
            console.print(f"  [yellow]⚠ Blocked: {meta.blocked_reason}[/yellow]")

        if meta.next_step_hint:
            console.print(f"  [dim cyan]Next: {meta.next_step_hint}[/dim cyan]")

    # Display warnings (compatibility + drift)
    if warnings:
        console.print()
        for warning in warnings:
            # Color code warnings by severity
            if "NAMI.md" in warning or "changed" in warning.lower():
                console.print(f"  [yellow]⚠ {warning}[/yellow]")
            elif "uncommitted" in warning.lower():
                console.print(f"  [blue]ℹ {warning}[/blue]")
            else:
                console.print(f"  [yellow]⚠ {warning}[/yellow]")

    # Display memory summary if available
    # if session_data.memory:
    #     memory_preview = session_data.memory[:200]
    #     if len(session_data.memory) > 200:
    #         memory_preview += "..."
    #     console.print(f"  [dim cyan]Session Context: {memory_preview}[/dim cyan]")

    # Display NAMI.md status
    if nami_md_loaded:
        console.print(
            f"  [dim green]✓ NAMI.md loaded (project rules active)[/dim green]"
        )

    console.print()

    # Display recent messages (last few for context)
    _display_recent_messages(session_data.messages)

    # Continuation indicator - smooth transition back to conversation
    console.print()
    console.print(
        "[dim]────────────────────────────────────────────────────────────────────────────────────[/dim]"
    )


def _display_recent_messages(
    messages: list[BaseMessage], max_display: int = 10
) -> None:
    """Display recent messages from conversation history.

    Args:
        messages: List of recent messages to display
        max_display: Maximum number of messages to show (default: 4)
    """
    if not messages:
        return

    # Filter out system messages for display (they're in the new system prompt)
    displayable_messages = [
        msg for msg in messages if not isinstance(msg, SystemMessage)
    ]

    # Only show last max_display messages
    messages_to_show = (
        displayable_messages[-max_display:]
        if len(displayable_messages) > max_display
        else displayable_messages
    )

    if not messages_to_show:
        return

    console.print("[bold]Recent Conversation:[/bold]")
    console.print()

    for msg in messages_to_show:
        if isinstance(msg, HumanMessage):
            # User message with > prefix
            content = _get_message_content(msg)
            if content:
                console.print(f"[bold cyan]> You:[/bold cyan]")
                console.print(f"  {content}")
                console.print()

        elif isinstance(msg, AIMessage):
            # AI message with proper markdown rendering
            content = _get_message_content(msg)
            if (
                content and not msg.tool_calls
            ):  # Don't show messages that are just tool calls
                console.print(
                    f"[bold {COLORS['agent']}]> Nami:[/bold {COLORS['agent']}]"
                )
                # Display full content without truncation
                console.print(Markdown(content))
                console.print()

        elif isinstance(msg, ToolMessage):
            # Tool results - show only if they contain useful info
            tool_name = getattr(msg, "name", "unknown")
            status = getattr(msg, "status", "success")
            if status != "success":
                console.print(f"  [dim red]⚠ {tool_name} failed[/dim red]")
                console.print()

    # Show truncation indicator if we didn't show all messages
    if len(displayable_messages) > max_display:
        console.print(
            f"[dim]... and {len(displayable_messages) - max_display} more messages[/dim]"
        )
        console.print()


def _get_message_content(msg: BaseMessage) -> str:
    """Extract content from a message, handling various formats.

    Args:
        msg: The message to extract content from

    Returns:
        String content of the message
    """
    if hasattr(msg, "content"):
        content = msg.content
        if isinstance(content, str):
            return content
        elif isinstance(content, list):
            # Handle multimodal content (list of dicts)
            text_parts = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    text_parts.append(item.get("text", ""))
            return "\n".join(text_parts)
    return ""


def _truncate_content(content: str, max_length: int = 200) -> str:
    """Truncate content for display with ellipsis if needed.

    Args:
        content: The content to truncate
        max_length: Maximum length before truncation

    Returns:
        Truncated content with ellipsis if needed
    """
    if len(content) <= max_length:
        return content

    # Try to truncate at a word boundary
    truncated = content[:max_length]
    last_space = truncated.rfind(" ")
    if last_space > max_length * 0.8:  # Only use word boundary if reasonably close
        truncated = truncated[:last_space]

    return truncated + "..."

"""UI rendering and display utilities for the CLI.

This module provides rich console-based UI components and formatting functions:

Key Components:
- TokenTracker: Track and display token usage statistics
- show_help(): Display help information for CLI commands
- format_tool_display(): Format tool calls for display
- format_tool_message_content(): Format tool execution results
- render_diff_block(): Render code diffs with syntax highlighting
- render_file_operation(): Display file operations with formatting
- render_todo_list(): Display task lists with progress indicators

Features:
- Rich console output with colors and formatting
- Token usage tracking and context window display
- Tool call visualization with arguments and results
- Code diff rendering with line-by-line comparison
- Todo list rendering with status indicators
- Markdown rendering for rich text content

Color Scheme:
Uses the COLORS constant from config.py for consistent styling:
- primary: Bright red for headings and primary actions
- secondary: Deep red for highlights
- success: Green for success states
- error: Deep red for errors
- warning: Orange for warnings

The UI is built on Rich library for terminal formatting and uses
consistent styling across all components.
"""

import json
import re
import shutil
from pathlib import Path
from typing import Any

from rich import box
from rich.markup import escape
from rich.panel import Panel
from rich.text import Text

from namicode_cli.context.context_manager import ContextBreakdown

from ..config.config import COLORS, COMMANDS, NAMI_CODE_ASCII, MAX_ARG_LENGTH, console
from ..file_ops import FileOperationRecord


def truncate_value(value: str, max_length: int = MAX_ARG_LENGTH) -> str:
    """Truncate a string value if it exceeds max_length."""
    if len(value) > max_length:
        return value[:max_length] + "..."
    return value


def format_tool_display(tool_name: str, tool_args: dict) -> str:
    """Format tool calls for display with tool-specific smart formatting.

    Shows the most relevant information for each tool type rather than all arguments.

    Args:
        tool_name: Name of the tool being called
        tool_args: Dictionary of tool arguments

    Returns:
        Formatted string for display (e.g., "read_file(config.py)")

    Examples:
        read_file(path="/long/path/file.py") → "read_file(file.py)"
        web_search(query="how to code", max_results=5) → 'web_search("how to code")'
        shell(command="pip install foo") → 'shell("pip install foo")'
    """

    def abbreviate_path(path_str: str, max_length: int = 60) -> str:
        """Abbreviate a file path intelligently - show basename or relative path."""
        try:
            path = Path(path_str)

            # If it's just a filename (no directory parts), return as-is
            if len(path.parts) == 1:
                return path_str

            # Try to get relative path from current working directory
            try:
                rel_path = path.relative_to(Path.cwd())
                rel_str = str(rel_path)
                # Use relative if it's shorter and not too long
                if len(rel_str) < len(path_str) and len(rel_str) <= max_length:
                    return rel_str
            except (ValueError, Exception):
                pass

            # If absolute path is reasonable length, use it
            if len(path_str) <= max_length:
                return path_str

            # Otherwise, just show basename (filename only)
            return path.name
        except Exception:
            # Fallback to original string if any error
            return truncate_value(path_str, max_length)

    # Tool-specific formatting - show the most important argument(s)
    if tool_name in ("read_file", "write_file", "edit_file"):
        # File operations: show the primary file path argument (file_path or path)
        path_value = tool_args.get("file_path")
        if path_value is None:
            path_value = tool_args.get("path")
        if path_value is not None:
            path = abbreviate_path(str(path_value))
            return f"{tool_name}({path})"

    elif tool_name == "web_search":
        # Web search: show the query string
        if "query" in tool_args:
            query = str(tool_args["query"])
            query = truncate_value(query, 100)
            return f'{tool_name}("{query}")'

    elif tool_name == "grep":
        # Grep: show the search pattern
        if "pattern" in tool_args:
            pattern = str(tool_args["pattern"])
            pattern = truncate_value(pattern, 70)
            return f'{tool_name}("{pattern}")'

    elif tool_name == "shell":
        # Shell: show the command being executed
        if "command" in tool_args:
            command = str(tool_args["command"])
            command = truncate_value(command, 120)
            return f'{tool_name}("{command}")'

    elif tool_name == "ls":
        # ls: show directory, or empty if current directory
        if tool_args.get("path"):
            path = abbreviate_path(str(tool_args["path"]))
            return f"{tool_name}({path})"
        return f"{tool_name}()"

    elif tool_name == "glob":
        # Glob: show the pattern
        if "pattern" in tool_args:
            pattern = str(tool_args["pattern"])
            pattern = truncate_value(pattern, 80)
            return f'{tool_name}("{pattern}")'

    elif tool_name == "http_request":
        # HTTP: show method and URL
        parts = []
        if "method" in tool_args:
            parts.append(str(tool_args["method"]).upper())
        if "url" in tool_args:
            url = str(tool_args["url"])
            url = truncate_value(url, 80)
            parts.append(url)
        if parts:
            return f"{tool_name}({' '.join(parts)})"

    elif tool_name == "fetch_url":
        # Fetch URL: show the URL being fetched
        if "url" in tool_args:
            url = str(tool_args["url"])
            url = truncate_value(url, 80)
            return f'{tool_name}("{url}")'

    elif tool_name == "task":
        # Task: show the subagent type and task description
        subagent_type = tool_args.get("subagent_type", "unknown")
        if "description" in tool_args:
            desc = str(tool_args["description"])
            desc = truncate_value(desc, 80)
            return f'{tool_name}[{subagent_type}]("{desc}")'
        else:
            return f'{tool_name}[{subagent_type}]'

    elif tool_name == "write_todos":
        # Todos: show count of items
        if "todos" in tool_args and isinstance(tool_args["todos"], list):
            count = len(tool_args["todos"])
            return f"{tool_name}({count} items)"

    # Fallback: generic formatting for unknown tools
    # Show all arguments in key=value format
    args_str = ", ".join(
        f"{k}={truncate_value(str(v), 50)}" for k, v in tool_args.items()
    )
    return f"{tool_name}({args_str})"


def format_tool_message_content(content: Any) -> str:
    """Convert ToolMessage content into a printable string."""
    if content is None:
        return ""
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            else:
                try:
                    parts.append(json.dumps(item))
                except Exception:
                    parts.append(str(item))
        return "\n".join(parts)
    return str(content)


class TokenTracker:
    """Track token usage across the conversation.

    Enhanced to support detailed context breakdown and visual display
    for the /context command.
    """

    def __init__(self) -> None:
        self.baseline_context = 0  # Baseline system context (system + agent.md + tools)
        self.current_context = 0  # Total context including messages
        self.last_output = 0

        # Model information for context window calculation
        self.model_name: str | None = None
        self.context_window_size: int = 128_000

        # Message counts for detailed breakdown
        self.user_message_count = 0
        self.assistant_message_count = 0
        self.tool_call_count = 0

    def set_model(self, model_name: str) -> None:
        """Set the model name for context window calculation.

        Args:
            model_name: The name of the model being used
        """
        from namicode_cli.context.context_manager import get_context_window_size

        self.model_name = model_name
        self.context_window_size = get_context_window_size(model_name)

    def set_baseline(self, tokens: int) -> None:
        """Set the baseline context token count.

        Args:
            tokens: The baseline token count (system prompt + agent.md + tools)
        """
        self.baseline_context = tokens
        self.current_context = tokens

    def reset(self) -> None:
        """Reset to baseline (for /clear and /compact commands)."""
        self.current_context = self.baseline_context
        self.last_output = 0
        self.user_message_count = 0
        self.assistant_message_count = 0
        self.tool_call_count = 0

    def add(self, input_tokens: int, output_tokens: int) -> None:
        """Add tokens from a response."""
        # input_tokens IS the current context size (what was sent to the model)
        self.current_context = input_tokens
        self.last_output = output_tokens

    def increment_user_messages(self) -> None:
        """Increment user message count."""
        self.user_message_count += 1

    def increment_assistant_messages(self) -> None:
        """Increment assistant message count."""
        self.assistant_message_count += 1

    def increment_tool_calls(self, count: int = 1) -> None:
        """Increment tool call count."""
        self.tool_call_count += count

    def get_breakdown(self) -> ContextBreakdown:
        """Get detailed context breakdown.

        Returns:
            ContextBreakdown with current usage statistics
        """
        from namicode_cli.context.context_manager import ContextBreakdown

        # Calculate conversation tokens
        conversation_tokens = self.current_context - self.baseline_context
        if conversation_tokens < 0:
            conversation_tokens = 0

        return ContextBreakdown(
            system_prompt_tokens=self.baseline_context,
            total_tokens=self.current_context,
            context_window_size=self.context_window_size,
            user_message_count=self.user_message_count,
            assistant_message_count=self.assistant_message_count,
            tool_call_count=self.tool_call_count,
        )

    def display_last(self) -> None:
        """Display current context size after this turn."""
        if self.last_output and self.last_output >= 1000:
            console.print(f"  Generated: {self.last_output:,} tokens", style="dim")
        if self.current_context:
            console.print(
                f"  Current context: {self.current_context:,} tokens", style="dim"
            )

    def display_session(self) -> None:
        """Display current context size."""
        console.print("\n[bold]Token Usage:[/bold]", style=COLORS["primary"])

        # Check if we've had any actual API calls yet (current > baseline means we have conversation)
        has_conversation = self.current_context > self.baseline_context

        if self.baseline_context > 0:
            console.print(
                f"  Baseline: {self.baseline_context:,} tokens [dim](system + agent.md)[/dim]",
                style=COLORS["dim"],
            )

            if not has_conversation:
                # Before first message - warn that tools aren't counted yet
                console.print(
                    "  [dim]Note: Tool definitions (~5k tokens) included after first message[/dim]"
                )

        if has_conversation:
            tools_and_conversation = self.current_context - self.baseline_context
            console.print(
                f"  Tools + conversation: {tools_and_conversation:,} tokens",
                style=COLORS["dim"],
            )

        console.print(
            f"  Total: {self.current_context:,} tokens", style="bold " + COLORS["dim"]
        )
        console.print()

    def display_context(self) -> None:
        """Display detailed context window usage with visual progress bar.

        This is the handler for the /context command.
        """
        from rich import box
        from rich.table import Table

        from namicode_cli.context.context_manager import (
            CONTEXT_CRITICAL_THRESHOLD,
            CONTEXT_WARNING_THRESHOLD,
        )

        breakdown = self.get_breakdown()

        console.print()
        console.print("[bold]Context Window Usage[/bold]", style=COLORS["primary"])
        console.print()

        # Determine progress bar color based on usage (red theme)
        usage_pct = breakdown.usage_percentage
        if usage_pct < CONTEXT_WARNING_THRESHOLD * 100:
            bar_color = COLORS["success"]  # Green for low usage
        elif usage_pct < CONTEXT_CRITICAL_THRESHOLD * 100:
            bar_color = COLORS["warning"]  # Orange for medium usage
        else:
            bar_color = COLORS["error"]  # Red for high usage

        # Create visual progress bar with modern design
        bar_width = 50
        filled = int(bar_width * usage_pct / 100)
        empty = bar_width - filled
        bar = f"[{bar_color}]{'━' * filled}[/{bar_color}][dim]{'─' * empty}[/dim]"

        console.print(f"  {bar} [bold {bar_color}]{usage_pct:.1f}%[/bold {bar_color}]")
        console.print()

        # Token breakdown table
        table = Table(box=box.SIMPLE, show_header=False, padding=(0, 2))
        table.add_column("Category", style="dim")
        table.add_column("Tokens", justify="right")
        table.add_column("Percent", justify="right", style="dim")

        # Baseline row
        baseline_pct = (breakdown.baseline_tokens / breakdown.context_window_size) * 100
        table.add_row(
            "Baseline (system + memory)",
            f"{breakdown.baseline_tokens:,}",
            f"{baseline_pct:.1f}%",
        )

        # Conversation row
        conv_tokens = breakdown.total_tokens - breakdown.baseline_tokens
        if conv_tokens < 0:
            conv_tokens = 0
        conv_pct = (conv_tokens / breakdown.context_window_size) * 100
        table.add_row(
            "Conversation + tools",
            f"{conv_tokens:,}",
            f"{conv_pct:.1f}%",
        )

        table.add_section()

        # Total row
        table.add_row(
            "[bold]Total Used[/bold]",
            f"[bold]{breakdown.total_tokens:,}[/bold]",
            f"[bold]{usage_pct:.1f}%[/bold]",
        )

        # Remaining row
        remaining_pct = 100 - usage_pct
        table.add_row(
            "Available",
            f"{breakdown.remaining_tokens:,}",
            f"{remaining_pct:.1f}%",
        )

        console.print(table)
        console.print()

        # Message counts
        console.print(
            f"  [dim]Messages: {breakdown.user_message_count} user, "
            f"{breakdown.assistant_message_count} assistant, "
            f"{breakdown.tool_call_count} tool calls[/dim]"
        )
        console.print()

        # Context window info
        model_display = self.model_name or "unknown model"
        console.print(
            f"  [dim]Context window: {breakdown.context_window_size:,} tokens "
            f"({model_display})[/dim]"
        )
        console.print()

        # Warnings based on thresholds
        if breakdown.is_critical:
            console.print(
                "  [bold red]⚠ Critical: Context nearly full! "
                "Use /compact to summarize conversation.[/bold red]"
            )
        elif breakdown.is_warning:
            console.print(
                "  [yellow]⚠ Warning: Context usage high. "
                "Consider using /compact soon.[/yellow]"
            )
        console.print()


class StreamingOutputRenderer:
    """Render streaming output from processes in real-time.

    Provides buffered output handling with optional line limits and styling.
    Useful for displaying test output, server logs, and other streaming content.
    """

    def __init__(
        self,
        max_lines: int = 1000,
        prefix: str = "",
        style: str = "dim",
    ) -> None:
        """Initialize the streaming renderer.

        Args:
            max_lines: Maximum lines to display (older lines discarded)
            prefix: Prefix to add to each line
            style: Rich style for output lines
        """
        self.max_lines = max_lines
        self.prefix = prefix
        self.style = style
        self._line_count = 0
        self._buffer = ""
        self._truncated = False

    def write(self, data: str) -> None:
        """Write data to the renderer, handling partial lines.

        Args:
            data: String data to write (may contain partial lines)
        """
        if not data:
            return

        # Add to buffer
        self._buffer += data

        # Process complete lines
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            self._write_line(line)

    def _write_line(self, line: str) -> None:
        """Write a complete line to output.

        Args:
            line: Complete line to write
        """
        if self._line_count >= self.max_lines:
            if not self._truncated:
                console.print(
                    f"[yellow]... output truncated (max {self.max_lines} lines)[/yellow]"
                )
                self._truncated = True
            return

        # Escape Rich markup in the line to prevent formatting issues
        escaped_line = escape(line)
        if self.prefix:
            console.print(f"[{self.style}]{self.prefix}{escaped_line}[/{self.style}]")
        else:
            console.print(f"[{self.style}]{escaped_line}[/{self.style}]")

        self._line_count += 1

    def flush(self) -> None:
        """Flush any remaining buffer content."""
        if self._buffer:
            self._write_line(self._buffer)
            self._buffer = ""

    @property
    def line_count(self) -> int:
        """Get the number of lines written."""
        return self._line_count

    @property
    def was_truncated(self) -> bool:
        """Check if output was truncated."""
        return self._truncated


def render_todo_list(todos: list[dict]) -> None:
    """Render todo list as a rich Panel with checkboxes."""
    if not todos:
        return

    lines = []
    for todo in todos:
        status = todo.get("status", "pending")
        content = todo.get("content", "")

        if status == "completed":
            icon = "✓"
            style = COLORS["success"]
        elif status == "in_progress":
            icon = "►"
            style = COLORS["primary"]
        else:  # pending
            icon = "○"
            style = COLORS["dim"]

        lines.append(f"[{style}]{icon} {content}[/{style}]")

    panel = Panel(
        "\n".join(lines),
        title=f"[bold {COLORS['primary']}]📋 Task List[/bold {COLORS['primary']}]",
        border_style=COLORS["accent"],
        box=box.DOUBLE,
        padding=(0, 1),
    )
    console.print(panel)


def _format_line_span(start: int | None, end: int | None) -> str:
    if start is None and end is None:
        return ""
    if start is not None and end is None:
        return f"(starting at line {start})"
    if start is None and end is not None:
        return f"(through line {end})"
    if start == end:
        return f"(line {start})"
    return f"(lines {start}-{end})"


def render_file_operation(record: FileOperationRecord) -> None:
    """Render a concise summary of a filesystem tool call."""
    label_lookup = {
        "read_file": "Read",
        "write_file": "Write",
        "edit_file": "Update",
    }
    label = label_lookup.get(record.tool_name, record.tool_name)
    header = Text()
    header.append("⏺ ", style=COLORS["tool"])
    header.append(f"{label}({record.display_path})", style=f"bold {COLORS['tool']}")
    console.print(header)

    def _print_detail(message: str, *, style: str = COLORS["dim"]) -> None:
        detail = Text()
        detail.append("  ⎿  ", style=style)
        detail.append(message, style=style)
        console.print(detail)

    if record.status == "error":
        _print_detail(record.error or "Error executing file operation", style="red")
        return

    if record.tool_name == "read_file":
        lines = record.metrics.lines_read
        span = _format_line_span(record.metrics.start_line, record.metrics.end_line)
        detail = f"Read {lines} line{'s' if lines != 1 else ''}"
        if span:
            detail = f"{detail} {span}"
        _print_detail(detail)
    else:
        if record.tool_name == "write_file":
            added = record.metrics.lines_added
            removed = record.metrics.lines_removed
            lines = record.metrics.lines_written
            detail = f"Wrote {lines} line{'s' if lines != 1 else ''}"
            if added or removed:
                detail = f"{detail} (+{added} / -{removed})"
        else:
            added = record.metrics.lines_added
            removed = record.metrics.lines_removed
            detail = f"Edited {record.metrics.lines_written} total line{'s' if record.metrics.lines_written != 1 else ''}"
            if added or removed:
                detail = f"{detail} (+{added} / -{removed})"
        _print_detail(detail)

    # Skip diff display for HIL-approved operations that succeeded
    # (user already saw the diff during approval)
    if record.diff and not (record.hitl_approved and record.status == "success"):
        render_diff(record)


def render_diff(record: FileOperationRecord) -> None:
    """Render diff for a file operation."""
    if not record.diff:
        return
    render_diff_block(record.diff, f"Diff {record.display_path}")


def _wrap_diff_line(
    code: str,
    marker: str,
    color: str,
    line_num: int | None,
    width: int,
    term_width: int,
) -> list[str]:
    """Wrap long diff lines with proper indentation.

    Args:
        code: Code content to wrap
        marker: Diff marker ('+', '-', ' ')
        color: Color for the line
        line_num: Line number to display (None for continuation lines)
        width: Width for line number column
        term_width: Terminal width

    Returns:
        List of formatted lines (may be multiple if wrapped)
    """
    # Escape Rich markup in code content
    code = escape(code)

    prefix_len = width + 4  # line_num + space + marker + 2 spaces
    available_width = term_width - prefix_len

    if len(code) <= available_width:
        if line_num is not None:
            return [
                f"[dim]{line_num:>{width}}[/dim] [{color}]{marker}  {code}[/{color}]"
            ]
        return [f"{' ' * width} [{color}]{marker}  {code}[/{color}]"]

    lines = []
    remaining = code
    first = True

    while remaining:
        if len(remaining) <= available_width:
            chunk = remaining
            remaining = ""
        else:
            # Try to break at a good point (space, comma, etc.)
            chunk = remaining[:available_width]
            # Look for a good break point in the last 20 chars
            break_point = max(
                chunk.rfind(" "),
                chunk.rfind(","),
                chunk.rfind("("),
                chunk.rfind(")"),
            )
            if break_point > available_width - 20:
                # Found a good break point
                chunk = remaining[: break_point + 1]
                remaining = remaining[break_point + 1 :]
            else:
                # No good break point, just split
                chunk = remaining[:available_width]
                remaining = remaining[available_width:]

        if first and line_num is not None:
            lines.append(
                f"[dim]{line_num:>{width}}[/dim] [{color}]{marker}  {chunk}[/{color}]"
            )
            first = False
        else:
            lines.append(f"{' ' * width} [{color}]{marker}  {chunk}[/{color}]")

    return lines


def format_diff_rich(diff_lines: list[str]) -> str:
    """Format diff lines with line numbers and colors.

    Args:
        diff_lines: Diff lines from unified diff

    Returns:
        Rich-formatted diff string with line numbers
    """
    if not diff_lines:
        return "[dim]No changes detected[/dim]"

    # Get terminal width
    term_width = shutil.get_terminal_size().columns

    # Find max line number for width calculation
    max_line = max(
        (
            int(m.group(i))
            for line in diff_lines
            if (m := re.match(r"@@ -(\d+)(?:,\d+)? \+(\d+)", line))
            for i in (1, 2)
        ),
        default=0,
    )
    width = max(3, len(str(max_line)))

    formatted_lines = []
    old_num = new_num = 0

    # Rich colors with backgrounds for better visibility
    # White text on dark backgrounds for additions/deletions
    addition_color = "white on dark_green"
    deletion_color = "white on dark_red"
    context_color = "dim"

    for line in diff_lines:
        if line.strip() == "...":
            formatted_lines.append(f"[{context_color}]...[/{context_color}]")
        elif line.startswith(("---", "+++")):
            continue
        elif m := re.match(r"@@ -(\d+)(?:,\d+)? \+(\d+)", line):
            old_num, new_num = int(m.group(1)), int(m.group(2))
        elif line.startswith("-"):
            formatted_lines.extend(
                _wrap_diff_line(
                    line[1:], "-", deletion_color, old_num, width, term_width
                )
            )
            old_num += 1
        elif line.startswith("+"):
            formatted_lines.extend(
                _wrap_diff_line(
                    line[1:], "+", addition_color, new_num, width, term_width
                )
            )
            new_num += 1
        elif line.startswith(" "):
            formatted_lines.extend(
                _wrap_diff_line(
                    line[1:], " ", context_color, old_num, width, term_width
                )
            )
            old_num += 1
            new_num += 1

    return "\n".join(formatted_lines)


def render_diff_block(diff: str, title: str) -> None:
    """Render a diff string with line numbers and colors."""
    try:
        # Parse diff into lines and format with line numbers
        diff_lines = diff.splitlines()
        formatted_diff = format_diff_rich(diff_lines)

        # Print with a simple header
        console.print()
        console.print(
            f"[bold {COLORS['primary']}]═══ {title} ═══[/bold {COLORS['primary']}]"
        )
        console.print(formatted_diff)
        console.print()
    except (ValueError, AttributeError, IndexError, OSError):
        # Fallback to simple rendering if formatting fails
        console.print()
        console.print(f"[bold {COLORS['primary']}]{title}[/bold {COLORS['primary']}]")
        console.print(diff)
        console.print()


def show_interactive_help() -> None:
    """Show available commands during interactive session."""
    console.print()
    console.print("[bold]Interactive Commands:[/bold]", style=COLORS["primary"])
    console.print()

    for cmd, desc in COMMANDS.items():
        console.print(f"  /{cmd:<12} {desc}", style=COLORS["dim"])

    console.print()
    console.print("[bold]Editing Features:[/bold]", style=COLORS["primary"])
    console.print("  Enter           Submit your message", style=COLORS["dim"])
    console.print(
        "  Alt+Enter       Insert newline (Option+Enter on Mac, or ESC then Enter)",
        style=COLORS["dim"],
    )
    console.print(
        "  Ctrl+E          Open in external editor (nano by default)",
        style=COLORS["dim"],
    )
    console.print("  Ctrl+T          Toggle auto-approve mode", style=COLORS["dim"])
    console.print("  Arrow keys      Navigate input", style=COLORS["dim"])
    console.print(
        "  Ctrl+C          Cancel input or interrupt agent mid-work",
        style=COLORS["dim"],
    )
    console.print()
    console.print("[bold]Special Features:[/bold]", style=COLORS["primary"])
    console.print(
        "  @filename       Type @ to auto-complete files and inject content",
        style=COLORS["dim"],
    )
    console.print(
        "  /command        Type / to see available commands", style=COLORS["dim"]
    )
    console.print(
        "  !command        Type ! to run bash commands (e.g., !ls, !git status)",
        style=COLORS["dim"],
    )
    console.print(
        "                  Completions appear automatically as you type",
        style=COLORS["dim"],
    )
    console.print()
    console.print("[bold]Auto-Approve Mode:[/bold]", style=COLORS["primary"])
    console.print("  Ctrl+T          Toggle auto-approve mode", style=COLORS["dim"])
    console.print(
        "  --auto-approve  Start CLI with auto-approve enabled (via command line)",
        style=COLORS["dim"],
    )
    console.print(
        "  When enabled, tool actions execute without confirmation prompts",
        style=COLORS["dim"],
    )
    console.print()


def show_help() -> None:
    """Show help information."""
    console.print()
    console.print(NAMI_CODE_ASCII, style=f"bold {COLORS['primary']}")
    console.print()

    console.print("[bold]Usage:[/bold]", style=COLORS["primary"])
    console.print(
        "  nami [OPTIONS]                           Start interactive session"
    )
    console.print(
        "  nami list                                List all available agents"
    )
    console.print(
        "  nami reset --agent AGENT                 Reset agent to default prompt"
    )
    console.print(
        "  nami reset --agent AGENT --target SOURCE Reset agent to copy of another agent"
    )
    console.print("  nami help                                Show this help message")
    console.print()

    console.print("[bold]Options:[/bold]", style=COLORS["primary"])
    console.print("  --agent NAME                  Agent identifier (default: agent)")
    console.print(
        "  --auto-approve                Auto-approve tool usage without prompting"
    )
    console.print(
        "  --sandbox TYPE                Remote sandbox for execution (modal, runloop, daytona)"
    )
    console.print(
        "  --sandbox-id ID               Reuse existing sandbox (skips creation/cleanup)"
    )
    console.print()

    console.print("[bold]Examples:[/bold]", style=COLORS["primary"])
    console.print(
        "  nami                              # Start with default agent",
        style=COLORS["dim"],
    )
    console.print(
        "  nami --agent mybot                # Start with agent named 'mybot'",
        style=COLORS["dim"],
    )
    console.print(
        "  nami --auto-approve               # Start with auto-approve enabled",
        style=COLORS["dim"],
    )
    console.print(
        "  nami --sandbox runloop            # Execute code in Runloop sandbox",
        style=COLORS["dim"],
    )
    console.print(
        "  nami --sandbox modal              # Execute code in Modal sandbox",
        style=COLORS["dim"],
    )
    console.print(
        "  nami --sandbox runloop --sandbox-id dbx_123  # Reuse existing sandbox",
        style=COLORS["dim"],
    )
    console.print(
        "  nami list                         # List all agents", style=COLORS["dim"]
    )
    console.print(
        "  nami reset --agent mybot          # Reset mybot to default",
        style=COLORS["dim"],
    )
    console.print(
        "  nami reset --agent mybot --target other # Reset mybot to copy of 'other' agent",
        style=COLORS["dim"],
    )
    console.print()

    console.print("[bold]Long-term Memory:[/bold]", style=COLORS["primary"])
    console.print(
        "  By default, long-term memory is ENABLED using agent name 'nami-agent'.",
        style=COLORS["dim"],
    )
    console.print("  Memory includes:", style=COLORS["dim"])
    console.print(
        "  - Persistent agent.md file with your instructions", style=COLORS["dim"]
    )
    console.print(
        "  - /memories/ folder for storing context across sessions", style=COLORS["dim"]
    )
    console.print()

    console.print("[bold]Agent Storage:[/bold]", style=COLORS["primary"])
    console.print("  Agents are stored in: ~/.nami/AGENT_NAME/", style=COLORS["dim"])
    console.print(
        "  Each agent has an agent.md file containing its prompt", style=COLORS["dim"]
    )
    console.print()

    console.print("[bold]Interactive Features:[/bold]", style=COLORS["primary"])
    console.print("  Enter           Submit your message", style=COLORS["dim"])
    console.print(
        "  Alt+Enter       Insert newline for multi-line (Option+Enter or ESC then Enter)",
        style=COLORS["dim"],
    )
    console.print("  Ctrl+J          Insert newline (alternative)", style=COLORS["dim"])
    console.print("  Ctrl+T          Toggle auto-approve mode", style=COLORS["dim"])
    console.print("  Arrow keys      Navigate input", style=COLORS["dim"])
    console.print(
        "  @filename       Type @ to auto-complete files and inject content",
        style=COLORS["dim"],
    )
    console.print(
        "  /command        Type / to see available commands (auto-completes)",
        style=COLORS["dim"],
    )
    console.print()

    console.print("[bold]Interactive Commands:[/bold]", style=COLORS["primary"])
    console.print(
        "  /help           Show available commands and features", style=COLORS["dim"]
    )
    console.print(
        "  /clear          Clear screen and reset conversation", style=COLORS["dim"]
    )
    console.print(
        "  /tokens         Show token usage for current session", style=COLORS["dim"]
    )
    console.print(
        "  /context        Show detailed context window usage", style=COLORS["dim"]
    )
    console.print(
        "  /compact        Summarize conversation to free context", style=COLORS["dim"]
    )
    console.print(
        "  /init           Explore codebase and create NAMI.MD file",
        style=COLORS["dim"],
    )
    console.print(
        "  /sessions       List and manage saved sessions", style=COLORS["dim"]
    )
    console.print(
        "  /save           Manually save current session", style=COLORS["dim"]
    )
    console.print("  /quit, /exit    Exit the session", style=COLORS["dim"])
    console.print(
        "  quit, exit, q   Exit the session (just type and press Enter)",
        style=COLORS["dim"],
    )
    console.print()

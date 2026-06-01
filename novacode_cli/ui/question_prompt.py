"""Question prompt UI for plan mode and agent questions.

This module provides UI components for:
1. Rendering structured (multiple choice) questions
2. Rendering open-ended questions with text input
3. Handling user responses and returning to the agent

Uses similar patterns to prompt_for_tool_approval in execution.py.
"""

import sys
from typing import TypedDict

from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML
from rich import box
from rich.markup import escape
from rich.panel import Panel

from novacode_cli.config.config import console


class QuestionResponse(TypedDict):
    """Response from user to an agent question."""

    answer: str
    selected_index: int | None  # For structured questions


def prompt_for_structured_question(
    question: str,
    options: list[str],
    context: str | None = None,
) -> QuestionResponse:
    """Prompt user with a multiple choice question.

    Uses arrow key navigation similar to tool approval menu.

    Args:
        question: The question text.
        options: List of options to choose from.
        context: Optional context about why asking.

    Returns:
        QuestionResponse with selected answer and index.
    """
    # Build question panel with beautiful styling
    body_lines = [
        "",  # Top padding
        f"  [bold]{escape(question)}[/bold]",  # Question with proper spacing
    ]
    if context:
        body_lines.append("")  # Spacing
        body_lines.append(f"  [dim]{escape(context)}[/dim]")  # Context with dim styling
    body_lines.append("")  # Bottom padding

    # Get terminal width and calculate responsive panel width
    terminal_width = console.width
    # Use 80% of terminal width, minimum 50, maximum 140
    panel_width = max(50, min(140, int(terminal_width * 0.8)))

    # Create beautiful title with decorative elements
    title_text = "[bold cyan]◆[/bold cyan] [bold]Agent Question[/bold] [bold cyan]◆[/bold cyan]"

    console.print()
    console.print(
        Panel(
            "\n".join(body_lines),
            title=title_text,
            border_style="cyan",
            box=box.DOUBLE,
            padding=(0, 2),
            width=panel_width,
            expand=False,
        )
    )
    console.print()

    selected = 0

    try:
        # Import termios/tty only when needed (Unix-only modules)
        import termios
        import tty

        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)

        try:
            tty.setraw(fd)
            sys.stdout.write("\033[?25l")  # Hide cursor
            sys.stdout.flush()

            first_render = True

            while True:
                if not first_render:
                    # Move cursor back to start of menu
                    sys.stdout.write(f"\033[{len(options)}A\r")

                first_render = False

                # Render options
                for i, option in enumerate(options):
                    sys.stdout.write("\r\033[K")  # Clear line

                    if i == selected:
                        sys.stdout.write(f"\033[1;36m\u25cf {option}\033[0m\n")
                    else:
                        sys.stdout.write(f"\033[2m\u25cb {option}\033[0m\n")

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
                    sys.stdout.write("\r\n")
                    break
                elif char.isdigit():
                    idx = int(char) - 1
                    if 0 <= idx < len(options):
                        selected = idx
                        sys.stdout.write("\r\n")
                        break
                elif char == "\x03":  # Ctrl+C
                    sys.stdout.write("\r\n")
                    raise KeyboardInterrupt

        finally:
            sys.stdout.write("\033[?25h")  # Show cursor
            sys.stdout.flush()
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

    except (ImportError, AttributeError, Exception):
        # Fallback for non-Unix systems (Windows)
        console.print("Options:")
        for i, option in enumerate(options, 1):
            console.print(f"  {i}. {option}")

        choice = input(f"\nEnter number (1-{len(options)}): ").strip()
        try:
            selected = int(choice) - 1
            if not 0 <= selected < len(options):
                selected = 0
        except ValueError:
            selected = 0

    console.print(f"[cyan]Selected: {options[selected]}[/cyan]")
    console.print()

    return QuestionResponse(
        answer=options[selected],
        selected_index=selected,
    )


async def prompt_for_open_question(
    question: str,
    context: str | None = None,
) -> QuestionResponse:
    """Prompt user with an open-ended question.

    Uses prompt_toolkit for text input.

    Args:
        question: The question text.
        context: Optional context about why asking.

    Returns:
        QuestionResponse with user's free-form answer.
    """
    # Build question panel with beautiful styling
    body_lines = [
        "",  # Top padding
        f"  [bold]{escape(question)}[/bold]",  # Question with proper spacing
    ]
    if context:
        body_lines.append("")  # Spacing
        body_lines.append(f"  [dim]{escape(context)}[/dim]")  # Context with dim styling
    body_lines.append("")  # Bottom padding

    # Get terminal width and calculate responsive panel width
    terminal_width = console.width
    # Use 80% of terminal width, minimum 50, maximum 140
    panel_width = max(50, min(140, int(terminal_width * 0.8)))

    # Create beautiful title with decorative elements
    title_text = "[bold cyan]◆[/bold cyan] [bold]Agent Question[/bold] [bold cyan]◆[/bold cyan]"

    console.print()
    console.print(
        Panel(
            "\n".join(body_lines),
            title=title_text,
            border_style="cyan",
            box=box.DOUBLE,
            padding=(0, 2),
            width=panel_width,
            expand=False,
        )
    )

    console.print("[dim]Enter your response:[/dim]")
    console.print()

    session: PromptSession[str] = PromptSession()

    try:
        answer = await session.prompt_async(
            HTML('<style fg="#00bfff">> </style>'),
            multiline=False,
        )
    except KeyboardInterrupt:
        answer = ""

    console.print()

    return QuestionResponse(
        answer=answer.strip(),
        selected_index=None,
    )


async def handle_agent_question(
    question_request: dict,
) -> QuestionResponse:
    """Handle an agent question based on its type.

    Routes to appropriate prompt function based on question_type.

    Args:
        question_request: The question request from the agent.

    Returns:
        QuestionResponse with user's answer.
    """
    question = question_request.get("question", "")
    question_type = question_request.get("question_type", "open_ended")
    options = question_request.get("options", [])
    context = question_request.get("context")

    if question_type == "structured" and options:
        return prompt_for_structured_question(question, options, context)
    return await prompt_for_open_question(question, context)


class PlanApprovalResult(TypedDict):
    """Result of plan approval prompt."""

    approved: bool
    action: str  # "proceed_auto", "proceed_manual", "reject", "edit"
    feedback: str  # User feedback text for reject/edit actions


def prompt_for_plan_approval(
    todos: list[dict] | None = None,
    plan_summary: str | None = None,
) -> PlanApprovalResult:
    """Prompt user to approve the plan before proceeding.

    Similar to Claude Code's plan approval flow.

    Args:
        todos: List of todo items from the agent's plan.
        plan_summary: Optional summary text for the plan.

    Returns:
        PlanApprovalResult with approval status and action taken.
    """
    # Build plan display
    body_lines = []

    if plan_summary:
        body_lines.append(f"[bold]{escape(plan_summary)}[/bold]\n")

    if todos:
        body_lines.append("[bold cyan]Plan Steps:[/bold cyan]\n")
        for i, todo in enumerate(todos, 1):
            content = todo.get("content", "Unknown task")
            status = todo.get("status", "pending")

            # Status indicator
            if status == "completed":
                indicator = "[green]✓[/green]"
            elif status == "in_progress":
                indicator = "[yellow]●[/yellow]"
            else:
                indicator = "[dim]○[/dim]"

            body_lines.append(f"  {indicator} {i}. {escape(content)}")
    else:
        body_lines.append("[dim]Plan written to file — review it above before choosing.[/dim]")

    body_lines.append("\n[dim]Would you like to proceed with this plan?[/dim]")

    console.print()
    console.print(
        Panel(
            "\n".join(body_lines),
            title="[bold cyan]📋 Plan Approval[/bold cyan]",
            border_style="cyan",
            box=box.ROUNDED,
            padding=(1, 2),
        )
    )
    console.print()

    # Colors per option index: green (auto), blue (manual), red (reject), yellow (edit)
    option_colors = ["\033[1;32m", "\033[1;34m", "\033[1;31m", "\033[1;33m"]

    options = [
        "Auto-accept: execute the full plan autonomously (a)",
        "Manual-accept: approve each step as it runs (m)",
        "Reject: stay in plan mode and revise (n)",
        "Edit: continue planning (e)",
    ]

    selected = 0

    try:
        # Import termios/tty only when needed (Unix-only modules)
        import termios
        import tty

        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)

        try:
            tty.setraw(fd)
            sys.stdout.write("\033[?25l")  # Hide cursor
            sys.stdout.flush()

            first_render = True

            while True:
                if not first_render:
                    # Move cursor back to start of menu
                    sys.stdout.write(f"\033[{len(options)}A\r")

                first_render = False

                # Render options
                for i, option in enumerate(options):
                    sys.stdout.write("\r\033[K")  # Clear line

                    if i == selected:
                        sys.stdout.write(f"{option_colors[i]}\u25cf {option}\033[0m\n")
                    else:
                        sys.stdout.write(f"\033[2m\u25cb {option}\033[0m\n")

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
                    sys.stdout.write("\r\n")
                    break
                elif char in {"a", "A"}:  # Quick key for auto-accept
                    selected = 0
                    sys.stdout.write("\r\n")
                    break
                elif char in {"m", "M"}:  # Quick key for manual-accept
                    selected = 1
                    sys.stdout.write("\r\n")
                    break
                elif char in {"n", "N"}:  # Quick key for reject
                    selected = 2
                    sys.stdout.write("\r\n")
                    break
                elif char in {"e", "E"}:  # Quick key for edit
                    selected = 3
                    sys.stdout.write("\r\n")
                    break
                elif char.isdigit():
                    idx = int(char) - 1
                    if 0 <= idx < len(options):
                        selected = idx
                        sys.stdout.write("\r\n")
                        break
                elif char == "\x03":  # Ctrl+C
                    sys.stdout.write("\r\n")
                    raise KeyboardInterrupt

        finally:
            sys.stdout.write("\033[?25h")  # Show cursor
            sys.stdout.flush()
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)

    except (ImportError, AttributeError, Exception):
        # Fallback for non-Unix systems (Windows)
        console.print("[bold]Options:[/bold]")
        console.print("  [green]1. Auto-accept: execute the full plan autonomously (a)[/green]")
        console.print("  [blue]2. Manual-accept: approve each step as it runs (m)[/blue]")
        console.print("  [red]3. Reject: stay in plan mode and revise (n)[/red]")
        console.print("  [yellow]4. Edit: continue planning (e)[/yellow]")

        choice = input("\nEnter choice (1-4 or a/m/n/e): ").strip().lower()
        if choice in {"1", "a", "auto"}:
            selected = 0
        elif choice in {"2", "m", "manual"}:
            selected = 1
        elif choice in {"3", "n", "no", "reject"}:
            selected = 2
        elif choice in {"4", "e", "edit"}:
            selected = 3
        else:
            selected = 2  # Default to reject on invalid input

    # Collect feedback text if user wants to reject or request edits
    feedback = ""
    if selected in {2, 3}:
        try:
            console.print()
            feedback = input("Feedback for the agent (optional, press Enter to skip): ").strip()
        except (EOFError, KeyboardInterrupt):
            feedback = ""

    # Map selection to result
    if selected == 0:
        console.print("[green]Plan approved — executing autonomously[/green]")
        console.print()
        return PlanApprovalResult(approved=True, action="proceed_auto", feedback="")
    if selected == 1:
        console.print("[blue]Plan approved — you'll review each step[/blue]")
        console.print()
        return PlanApprovalResult(approved=True, action="proceed_manual", feedback="")
    if selected == 2:
        console.print("[yellow]Plan rejected — staying in plan mode[/yellow]")
        console.print()
        return PlanApprovalResult(approved=False, action="reject", feedback=feedback)
    console.print("[cyan]Continuing to edit plan[/cyan]")
    console.print()
    return PlanApprovalResult(approved=False, action="edit", feedback=feedback)


__all__ = [
    "PlanApprovalResult",
    "QuestionResponse",
    "handle_agent_question",
    "prompt_for_open_question",
    "prompt_for_plan_approval",
    "prompt_for_structured_question",
]

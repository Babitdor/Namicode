"""Question prompt UI for plan mode and agent questions.

This module provides UI components for:
1. Rendering structured (multiple choice) questions
2. Rendering open-ended questions with text input
3. Handling user responses and returning to the agent

Uses similar patterns to prompt_for_tool_approval in execution.py.
"""

import sys
from typing import TypedDict

from rich import box
from rich.panel import Panel
from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import HTML

from namicode_cli.config.config import COLORS, console


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
    # Build question panel
    body_lines = [f"[bold]{question}[/bold]"]
    if context:
        body_lines.append(f"\n[dim]{context}[/dim]")

    console.print()
    console.print(
        Panel(
            "\n".join(body_lines),
            title="[bold cyan]Agent Question[/bold cyan]",
            border_style="cyan",
            box=box.ROUNDED,
            padding=(1, 2),
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
    # Build question panel
    body_lines = [f"[bold]{question}[/bold]"]
    if context:
        body_lines.append(f"\n[dim]{context}[/dim]")

    console.print()
    console.print(
        Panel(
            "\n".join(body_lines),
            title="[bold cyan]Agent Question[/bold cyan]",
            border_style="cyan",
            box=box.ROUNDED,
            padding=(1, 2),
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
    else:
        return await prompt_for_open_question(question, context)


__all__ = [
    "prompt_for_structured_question",
    "prompt_for_open_question",
    "handle_agent_question",
    "QuestionResponse",
]

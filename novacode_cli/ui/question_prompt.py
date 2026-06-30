"""Question prompt UI for plan mode and agent questions.

This module provides UI components for:
1. Rendering structured (multiple choice) questions
2. Rendering open-ended questions with text input
3. Handling user responses and returning to the agent

Uses simple input() calls (no prompt_toolkit dependency).
"""

from __future__ import annotations

import sys  # noqa: F401 — patched by tests (question_prompt.sys) for stdin control

from typing import TypedDict

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
) -> QuestionResponse:
    """Display a structured multiple-choice question and get the user's answer.

    Args:
        question: The question text
        options: List of answer options

    Returns:
        QuestionResponse with the user's answer
    """
    console.print()
    console.print(Panel(
        f"[bold]{escape(question)}[/bold]",
        border_style="cyan",
        box=box.ROUNDED,
    ))
    console.print()

    for i, option in enumerate(options, 1):
        console.print(f"  [bold cyan]{i}.[/bold cyan] {escape(option)}")

    console.print()
    console.print("[dim]Enter the number of your choice, or type your answer:[/dim]")

    while True:
        try:
            choice = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[yellow]Question skipped.[/yellow]")
            return QuestionResponse(answer="", selected_index=None)

        if not choice:
            continue

        # Check if it's a number
        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(options):
                return QuestionResponse(answer=options[idx], selected_index=idx)
            console.print(f"[yellow]Please enter a number between 1 and {len(options)}.[/yellow]")
        else:
            # Free text answer
            return QuestionResponse(answer=choice, selected_index=None)


def prompt_for_plan_approval(todos: list | None = None) -> dict:
    """Prompt the user for plan approval with three options.

    Returns:
        Dict with keys: approved (bool), action (str), feedback (str | None)
    """
    console.print()
    console.print("[bold]Plan Approval[/bold]")
    console.print()
    console.print("  [green]a[/green] - Approve and auto-execute")
    console.print("  [yellow]m[/yellow] - Approve and execute manually")
    console.print("  [cyan]r[/cyan] - Request changes (refine)")
    console.print()

    while True:
        try:
            choice = input("Your choice (a/m/r): ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[yellow]Plan rejected.[/yellow]")
            return {"approved": False, "action": "refine", "feedback": ""}

        if choice in ("a", "auto"):
            console.print("[green]Plan approved (auto-execute).[/green]")
            return {"approved": True, "action": "proceed_auto", "feedback": None}
        if choice in ("m", "manual"):
            console.print("[green]Plan approved (manual execution).[/green]")
            return {"approved": True, "action": "proceed_manual", "feedback": None}
        if choice in ("r", "refine"):
            try:
                feedback = input("Describe the changes needed: ").strip()
            except (EOFError, KeyboardInterrupt):
                feedback = ""
            console.print("[cyan]Plan sent back for refinement.[/cyan]")
            return {"approved": False, "action": "refine", "feedback": feedback}

        # Unknown input: default to refine (safe fallback)
        try:
            feedback = input("Describe the changes needed: ").strip()
        except (EOFError, KeyboardInterrupt):
            feedback = ""
        console.print("[cyan]Plan sent back for refinement.[/cyan]")
        return {"approved": False, "action": "refine", "feedback": feedback}


def handle_agent_question(
    question: str,
    options: list[str] | None = None,
) -> dict:
    """Handle an agent question and return the response.

    Args:
        question: The question text
        options: Optional list of answer options

    Returns:
        Response dict with answer and selected_index
    """
    if options:
        response = prompt_for_structured_question(question, options)
        return {
            "answer": response["answer"],
            "selected_index": response["selected_index"],
        }
    else:
        console.print()
        console.print(f"[bold]Question:[/bold] {question}")
        console.print()
        try:
            answer = input("Your answer: ").strip()
            return {"answer": answer, "selected_index": None}
        except (EOFError, KeyboardInterrupt):
            console.print("\n[yellow]Question skipped.[/yellow]")
            return {"answer": "", "selected_index": None}

"""Interrupt handlers for human-in-the-loop interactions.

This module handles special interrupt types:
- Question interrupts from ask_question tool
- Plan approval interrupts from exit_plan_mode tool

Shared between the TUI and headless mode.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from rich.markdown import Markdown
from rich.rule import Rule

from novacode_cli.config.config import console
from novacode_cli.ui.question_prompt import handle_agent_question

if TYPE_CHECKING:
    pass


def find_latest_plan_file(
    plans_dir: Path,
    backend: Any = None,
) -> Path | None:
    """Find the most recently modified plan file in the plans directory.

    When a backend is provided, uses the backend's ls() method to find
    plan files via virtual paths. Falls back to direct filesystem glob
    when backend is None or the ls() call fails.

    Args:
        plans_dir: Directory to search for plan files
        backend: Optional backend for virtual path listing

    Returns:
        Path to the most recent plan file, or None
    """
    try:
        if backend is not None:
            try:
                entries = backend.ls(str(plans_dir))
                plan_files = [
                    plans_dir / e["name"]
                    for e in entries
                    if e.get("name", "").endswith(".md")
                ]
                if plan_files:
                    return max(plan_files, key=lambda p: p.stat().st_mtime)
            except Exception:
                pass

        # Fallback: direct filesystem glob
        plan_files = list(plans_dir.glob("*.md"))
        if plan_files:
            return max(plan_files, key=lambda p: p.stat().st_mtime)
    except Exception:
        pass
    return None


def resolve_plan_content(
    todos: Any,
    session_state: Any,
    backend: Any = None,
    inline_plan: str | None = None,
) -> tuple[str | None, Path | None]:
    """Resolve the plan content from inline text or the latest plan file.

    Args:
        todos: Current todos from session state
        session_state: Current session state
        backend: Optional backend for virtual path listing
        inline_plan: Optional inline plan text

    Returns:
        Tuple of (plan_content, plan_file_path)
    """
    if inline_plan:
        return inline_plan, None

    # Same root exit_plan_mode writes to (settings.get_workspace_root()).
    # A bare Path.cwd() here silently missed every saved plan whenever Nova
    # was launched from outside the project root.
    from novacode_cli.config.config import settings

    try:
        plans_dir = settings.get_workspace_root() / ".nova" / "plans"
    except Exception:  # noqa: BLE001
        plans_dir = Path.cwd() / ".nova" / "plans"
    if not plans_dir.exists():
        return None, None

    plan_file = find_latest_plan_file(plans_dir, backend=backend)
    if plan_file and plan_file.exists():
        try:
            content = plan_file.read_text(encoding="utf-8")
            return content, plan_file
        except Exception:
            pass

    return None, None


def handle_plan_approval_interrupt(
    payload: Any,
    session_state: Any,
    backend: Any = None,
) -> dict:
    """Handle a plan approval interrupt by showing the plan and prompting.

    Args:
        payload: The interrupt payload
        session_state: Current session state
        backend: Optional backend for virtual path listing

    Returns:
        Response dict with approval decision
    """
    inline_plan = (payload or {}).get("plan") if isinstance(payload, dict) else None
    content, plan_file = resolve_plan_content(
        getattr(session_state, "todos", None),
        session_state,
        backend=backend,
        inline_plan=inline_plan,
    )

    if content:
        console.print()
        console.print(Rule(style="dim"))
        console.print(Markdown(content))
        console.print(Rule(style="dim"))
        console.print()

    if plan_file:
        console.print(f"[dim]Plan file: {plan_file}[/dim]")

    console.print("[bold]Approve this plan?[/bold]")
    console.print("  [green]y[/green] - Yes, approve and execute")
    console.print("  [red]n[/red] - No, reject and continue editing")
    console.print("  [yellow]e[/yellow] - Edit the plan file")
    console.print()

    while True:
        try:
            choice = input("Your choice (y/n/e): ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            console.print("\n[yellow]Plan rejected.[/yellow]")
            return {"approved": False, "mode": "rejected"}

        if choice in ("y", "yes"):
            console.print("[green]Plan approved![/green]")
            return {"approved": True, "mode": "approved"}
        if choice in ("n", "no"):
            console.print("[yellow]Plan rejected.[/yellow]")
            return {"approved": False, "mode": "rejected"}
        if choice in ("e", "edit"):
            if plan_file:
                import subprocess
                import os

                editor = os.environ.get("EDITOR", "nano")
                try:
                    subprocess.call([editor, str(plan_file)])
                    # Re-read the edited file
                    content = plan_file.read_text(encoding="utf-8")
                    console.print("[green]Plan updated. Review and approve?[/green]")
                    console.print()
                    console.print(Rule(style="dim"))
                    console.print(Markdown(content))
                    console.print(Rule(style="dim"))
                    console.print()
                except Exception as ex:
                    console.print(f"[red]Could not open editor: {ex}[/red]")
            else:
                console.print("[yellow]No plan file to edit.[/yellow]")
        else:
            console.print("[yellow]Please enter y, n, or e.[/yellow]")


def handle_question_interrupt(
    payload: Any,
    session_state: Any,
) -> dict:
    """Handle a question interrupt by showing the question and prompting.

    Args:
        payload: The interrupt payload
        session_state: Current session state

    Returns:
        Response dict with answer
    """
    if isinstance(payload, dict):
        question = payload.get("question", "")
        options = payload.get("options", [])
    else:
        question = str(payload)
        options = []

    if options:
        return handle_agent_question(question, options)
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

"""Interrupt handlers for human-in-the-loop interactions.

This module handles special interrupt types:
- Question interrupts from ask_question tool
- Plan approval interrupts from exit_plan_mode tool
"""

from pathlib import Path

from rich.markdown import Markdown
from rich.rule import Rule

from novacode_cli.config.config import console
from novacode_cli.ui.question_prompt import QuestionResponse, handle_agent_question


async def handle_question_interrupt(
    question_request: dict,
    auto_approve: bool,
    spinner_active: bool,
    status,
) -> tuple[dict, bool]:
    """Handle a question interrupt from ask_question tool.

    Args:
        question_request: The question request data
        auto_approve: Whether auto-approve mode is enabled
        spinner_active: Whether spinner is currently active
        status: The status spinner object

    Returns:
        Tuple of (response dict, new spinner_active state)
    """
    if spinner_active:
        status.stop()
        spinner_active = False

    # Auto-answer questions in background/auto-approve mode
    # to avoid blocking the main CLI with prompts
    if auto_approve:
        # Auto-select first option for structured questions,
        # or provide a generic response for open questions
        question_type = question_request.get("question_type", "open_ended")
        options = question_request.get("options", [])

        if question_type == "structured" and options:
            # Pick the first option as default
            response = QuestionResponse(
                answer=options[0],
                selected_index=0,
            )
            console.print(
                f"[dim][Background mode] Auto-selected: {options[0]}[/dim]"
            )
        else:
            # Provide a generic response for open questions
            response = QuestionResponse(
                answer="Please proceed with a reasonable default approach.",
                selected_index=None,
            )
            console.print(
                "[dim][Background mode] Auto-responded to open question[/dim]"
            )
    else:
        # Handle the question and get user response
        response = await handle_agent_question(question_request)

    return {"response": response}, spinner_active


def resolve_plan_content(current_todos, dbg_func=None) -> tuple[str | None, Path | None]:
    """Resolve plan content from file or todos.

    Args:
        current_todos: Current todo list state (fallback for plan content)
        dbg_func: Optional debug logging function

    Returns:
        Tuple of (plan_content, plan_path) or (None, None) if not found
    """
    plan_content: str | None = None
    plan_path = None

    try:
        from novacode_cli.config.config import settings

        Nova_dir = settings.ensure_project_deepagents_dir()
        if not Nova_dir:
            Nova_dir = Path.cwd() / ".Nova"

        # Case 1: agent wrote plan.md directly
        direct_plan = Nova_dir / "plans" / "plan.md"
        if direct_plan.exists():
            plan_content = direct_plan.read_text(encoding="utf-8")
            plan_path = direct_plan

        # Case 2: todos-based plan (fallback)
        if not plan_content and current_todos:
            from novacode_cli.plans import (
                todos_to_markdown,
                write_plan_file,
            )

            Nova_dir.mkdir(parents=True, exist_ok=True)
            plan_path = write_plan_file(current_todos, Nova_dir)
            plan_content = todos_to_markdown(current_todos)

        if plan_path:
            try:
                rel = plan_path.relative_to(Path.cwd())
            except ValueError:
                rel = plan_path
            console.print(f"[dim]Plan file → {rel}[/dim]")

    except Exception as e:
        if dbg_func:
            dbg_func("PLAN-SAVE-ERROR", f"Failed to resolve plan file: {e}")

    return plan_content, plan_path


def render_plan_content(plan_content: str, max_lines: int = 80) -> None:
    """Render plan content inline with truncation.

    Args:
        plan_content: The plan markdown content
        max_lines: Maximum lines to display before truncating
    """
    try:
        console.print(Rule(style="cyan dim"))
        lines = plan_content.splitlines()
        if len(lines) > max_lines:
            shown = "\n".join(lines[:max_lines])
            console.print(Markdown(shown))
            console.print(
                f"[dim]... {len(lines) - max_lines} more lines"
                f" — open the plan file to see the full plan[/dim]"
            )
        else:
            console.print(Markdown(plan_content))
        console.print(Rule(style="cyan dim"))
        console.print()
    except Exception as e:
        console.print(f"[yellow]Failed to render plan: {e}[/yellow]")


async def handle_plan_approval_interrupt(
    current_todos,
    session_state,
    spinner_active: bool,
    status,
    dbg_func=None,
) -> tuple[dict, bool, bool, dict]:
    """Handle a plan approval interrupt from exit_plan_mode tool.

    Args:
        current_todos: Current todo list state
        session_state: Session state object
        spinner_active: Whether spinner is currently active
        status: The status spinner object
        dbg_func: Optional debug logging function

    Returns:
        Tuple of (hitl_response dict, interrupt_occurred bool, 
                  new spinner_active state, command_state_update dict)
    """
    from novacode_cli.ui.question_prompt import prompt_for_plan_approval

    if dbg_func:
        dbg_func("PLAN-APPROVE", "entering plan approval dialog")

    if spinner_active:
        status.stop()
        spinner_active = False

    console.print()
    console.print(
        "[cyan]Planning complete.[/cyan] Review the plan:",
        style="bold",
    )

    # Resolve plan content and file path
    plan_content, plan_path = resolve_plan_content(current_todos, dbg_func)

    # Render plan content inline
    if plan_content:
        render_plan_content(plan_content)

    # Get user approval
    result = prompt_for_plan_approval(
        todos=current_todos if current_todos else None,
        plan_summary=None,
    )

    if dbg_func:
        dbg_func(
            "PLAN-RESULT",
            f"approved={result['approved']} action={result.get('action', '?')}",
        )

    hitl_response = {}
    command_state_update = {}
    prev_auto_approve = None

    if result["approved"]:
        # User approved - exit plan mode.
        # Set plan_mode_enabled=False via command_state_update
        # so it is applied ATOMICALLY when the graph resumes.
        session_state.plan_mode_enabled = False
        command_state_update["plan_mode_enabled"] = False

        if result["action"] == "proceed_auto":
            # Auto-accept: temporarily enable auto-approve
            prev_auto_approve = session_state.auto_approve
            session_state.auto_approve = True
            hitl_response = {"approved": True, "mode": "auto"}
        else:
            # Manual-accept: ensure HITL is active
            prev_auto_approve = session_state.auto_approve
            session_state.auto_approve = False
            hitl_response = {"approved": True, "mode": "manual"}
    else:
        # User rejected or wants to edit - stay in plan mode
        hitl_response = {"approved": False}

    console.print()

    # Restart spinner
    if not spinner_active:
        status.start()
        spinner_active = True

    return hitl_response, True, spinner_active, command_state_update

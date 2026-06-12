"""Interrupt handlers for human-in-the-loop interactions.

This module handles special interrupt types:
- Question interrupts from ask_question tool
- Plan approval interrupts from exit_plan_mode tool
"""

from pathlib import Path
from typing import TYPE_CHECKING, Any

from rich.markdown import Markdown
from rich.rule import Rule

from novacode_cli.config.config import console
from novacode_cli.ui.question_prompt import QuestionResponse, handle_agent_question

if TYPE_CHECKING:
    from deepagents.backends.protocol import BackendProtocol


def find_latest_plan_file(
    plans_dir: Path,
    backend: Any = None,
) -> Path | None:
    """Find the most recently modified plan file in the plans directory.

    When a backend is provided, uses the backend's ls() method to find
    plan files via virtual paths. Falls back to direct filesystem glob
    when backend is None or the ls() call fails.

    Searches for files matching `plan*.md` and returns the one with the
    most recent modification time. This supports both the old `plan.md`
    naming convention and the new `plan-<name>.md` convention.

    Args:
        plans_dir: Path to the `.nova/plans/` directory
        backend: Optional CompositeBackend for virtual path access

    Returns:
        Path to the latest plan file, or None if no plan files exist
    """
    # Try backend-based lookup when available.
    if backend is not None:
        try:
            from novacode_cli.utils.backend_paths import find_latest_plan_file_virtual

            virtual_path = find_latest_plan_file_virtual(backend, "/.nova/plans/")
            if virtual_path:
                from novacode_cli.utils.backend_paths import virtual_to_real_path

                real_path = virtual_to_real_path(
                    virtual_path,
                    workspace_root=plans_dir.parent.parent,
                )
                if real_path and real_path.exists():
                    return real_path
        except Exception:
            pass

    # Filesystem fallback.
    if not plans_dir.exists():
        return None

    plan_files = list(plans_dir.glob("plan*.md"))
    if not plan_files:
        return None

    # Return the most recently modified plan file
    return max(plan_files, key=lambda p: p.stat().st_mtime)


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
            console.print(f"[dim][Background mode] Auto-selected: {options[0]}[/dim]")
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


def resolve_plan_content(
    current_todos,
    session_state=None,
    dbg_func=None,
    backend: Any = None,
    inline_plan: str | None = None,
) -> tuple[str | None, Path | None]:
    """Resolve plan content from inline arg, session state, file, or todos.

    Priority:
    0. ``inline_plan`` passed to ``exit_plan_mode(plan=...)`` (Claude-style)
    1. Session state plan_content (most recent, from current session)
    2. Latest plan file in .nova/plans/ (supports plan-<name>.md naming)
    3. todos-based plan (fallback)

    When a backend is provided, uses it to find and read plan files via
    virtual paths. Falls back to direct filesystem access when backend
    is None or the backend call fails.

    Args:
        current_todos: Current todo list state (fallback for plan content)
        session_state: Optional session state to check for stored plan content
        dbg_func: Optional debug logging function
        backend: Optional CompositeBackend for virtual path access
        inline_plan: Plan markdown supplied directly by the agent via
            ``exit_plan_mode(plan=...)``. Takes precedence over all other
            sources when non-empty.

    Returns:
        Tuple of (plan_content, plan_path) or (None, None) if not found
    """
    plan_content: str | None = None
    plan_path = None

    # Priority 0: Inline plan passed straight to exit_plan_mode (Claude-style).
    if isinstance(inline_plan, str) and inline_plan.strip():
        if dbg_func:
            dbg_func(
                "PLAN-CONTENT",
                f"Using inline plan from exit_plan_mode ({len(inline_plan)} chars)",
            )
        return inline_plan, None

    # Priority 1: Check session state for stored plan content (current session)
    if (
        session_state
        and hasattr(session_state, "plan_content")
        and session_state.plan_content
    ):
        plan_content = session_state.plan_content
        # Guard: plan_content must be a string (may be a stale object from a
        # previous buggy read).
        if not isinstance(plan_content, str):
            plan_content = None
        else:
            if dbg_func:
                dbg_func("PLAN-CONTENT", f"Using plan content from session state ({len(plan_content)} chars)")  # type: ignore
            # Still try to get the path for display
            try:
                from novacode_cli.config.config import settings

                Nova_dir = settings.ensure_project_deepagents_dir()
                if Nova_dir:
                    plans_dir = Nova_dir / "plans"
                    plan_path = find_latest_plan_file(plans_dir, backend=backend)
            except Exception:
                pass
            return plan_content, plan_path

    try:
        from novacode_cli.config.config import settings

        Nova_dir = settings.ensure_project_deepagents_dir()
        if not Nova_dir:
            Nova_dir = Path.cwd() / ".nova"

        # Priority 2: agent wrote a plan file (plan.md or plan-<name>.md)
        plans_dir = Nova_dir / "plans"
        direct_plan = find_latest_plan_file(plans_dir, backend=backend)
        if direct_plan:
            # Try reading through backend first, fall back to filesystem.
            plan_content = None
            if backend is not None:
                try:
                    from novacode_cli.utils.backend_paths import (
                        read_via_backend,
                        real_to_virtual_path,
                    )

                    virtual = real_to_virtual_path(
                        direct_plan,
                        workspace_root=settings.project_root,
                    )
                    if virtual:
                        plan_content = read_via_backend(virtual, backend)
                except Exception:
                    pass

            if plan_content is None:
                plan_content = direct_plan.read_text(encoding="utf-8")
            plan_path = direct_plan
            # Store in session state for future use
            if session_state and hasattr(session_state, "plan_content"):
                session_state.plan_content = plan_content
                if dbg_func:
                    dbg_func(
                        "PLAN-CACHE",
                        f"Cached plan content in session state ({len(plan_content)} chars)",
                    )

        # Priority 3: todos-based plan (fallback)
        if not plan_content and current_todos:
            from novacode_cli.plans import (
                todos_to_markdown,
                write_plan_file,
            )

            Nova_dir.mkdir(parents=True, exist_ok=True)
            plan_path = write_plan_file(current_todos, Nova_dir)
            plan_content = todos_to_markdown(current_todos)
            # Store in session state for future use
            if session_state and hasattr(session_state, "plan_content"):
                session_state.plan_content = plan_content
                if dbg_func:
                    dbg_func(
                        "PLAN-CACHE",
                        f"Cached todos-based plan in session state ({len(plan_content)} chars)",
                    )

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
    interrupt_payload: dict | None = None,
) -> tuple[dict, bool, bool, dict]:
    """Handle a plan approval interrupt from exit_plan_mode tool.

    Args:
        current_todos: Current todo list state
        session_state: Session state object
        spinner_active: Whether spinner is currently active
        status: The status spinner object
        dbg_func: Optional debug logging function
        interrupt_payload: The raw interrupt payload from exit_plan_mode, which
            may carry an inline ``plan`` (Claude-style) to display directly.

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

    # Resolve plan content and file path (prioritize the inline plan supplied
    # to exit_plan_mode(plan=...), then session state, then plan files).
    inline_plan = (interrupt_payload or {}).get("plan")
    plan_content, plan_path = resolve_plan_content(
        current_todos, session_state, dbg_func, inline_plan=inline_plan
    )

    if getattr(session_state, "auto_approve", False):
        if dbg_func:
            dbg_func("PLAN-APPROVE", "auto-approving plan")
        session_state.plan_mode_enabled = False
        command_state_update = {"plan_mode_enabled": False}
        using_separate_plan_agent = (
            hasattr(session_state, "plan_agent") and session_state.plan_agent is not None
        )
        if plan_content and using_separate_plan_agent:
            session_state.set_approved_plan(plan_content)
        session_state.plan_content = None

        console.print("[green]Plan auto-approved.[/green]")
        console.print()

        hitl_response = {"approved": True, "mode": "auto"}
        return hitl_response, False, spinner_active, command_state_update

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

        # Only store approved plan for hand-off when using a separate plan agent
        # (i.e. /plan command). When Nova auto-plans via decide_complexity, it
        # resumes its own graph with the plan already in context — no hand-off needed.
        using_separate_plan_agent = (
            hasattr(session_state, "plan_agent") and session_state.plan_agent is not None
        )
        if plan_content and using_separate_plan_agent:
            session_state.set_approved_plan(plan_content)
            if dbg_func:
                dbg_func(
                    "PLAN-APPROVED",
                    f"Stored plan content ({len(plan_content)} chars) for Nova agent hand-off",
                )
        # Clear the current plan content since it's now approved
        session_state.plan_content = None

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
        hitl_response = {
            "approved": False,
            "action": result.get("action", "reject"),
            "feedback": result.get("feedback", ""),
        }

    console.print()

    if result["approved"]:
        # Plan approved — hand off to Nova agent. Do NOT resume the plan agent;
        # returning occurred=False lets the streaming loop break naturally so the
        # main.py code can kick off Nova agent execution with the approved plan.
        return hitl_response, False, spinner_active, command_state_update

    # Plan rejected — restart spinner so plan agent can continue planning.
    if not spinner_active:
        status.start()
        spinner_active = True

    return hitl_response, True, spinner_active, command_state_update

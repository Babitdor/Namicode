"""Human-in-the-loop approval flow for tool actions.

This module handles the approval/rejection flow for tool actions
that require user confirmation, including plan mode blocking.
"""

from namicode_cli.config.config import console
from namicode_cli.file_ops import get_session_file_op_tracker

# Plan mode blocking - imported here to enforce plan mode at execution layer
from nami_deepagents.middleware.planning import (
    BLOCKED_TOOLS_IN_PLAN_MODE,
    _is_plan_file_path,
)


def check_plan_mode_blocked(
    hitl_request: dict,
    plan_mode_enabled: bool,
    dbg_func=None,
) -> tuple[bool, dict | None]:
    """Check if any actions are blocked by plan mode.

    Args:
        hitl_request: The HITL request containing action_requests
        plan_mode_enabled: Whether plan mode is currently enabled
        dbg_func: Optional debug logging function

    Returns:
        Tuple of (is_blocked, rejection_response or None)
    """
    if not plan_mode_enabled:
        return False, None

    blocked_actions = []
    for action_request in hitl_request.get("action_requests", []):
        tool_name = action_request.get("name", "")
        if tool_name in BLOCKED_TOOLS_IN_PLAN_MODE:
            # Allow write_file/edit_file only for plan files
            if tool_name in ("write_file", "edit_file"):
                file_path = str(
                    action_request.get("args", {}).get("file_path", "")
                )
                if _is_plan_file_path(file_path):
                    continue  # Allowed
            blocked_actions.append(action_request)

    if blocked_actions:
        # Reject ALL actions in this interrupt silently
        if dbg_func:
            dbg_func(
                "PLAN-MODE-BLOCK",
                f"blocked {len(blocked_actions)} actions",
            )
        decisions = [
            {"type": "reject", "message": "Plan mode active - tool blocked"}
            for _ in hitl_request.get("action_requests", [])
        ]
        return True, {"decisions": decisions}

    return False, None


async def process_hitl_approval(
    hitl_request: dict,
    session_state,
    assistant_id: str | None,
    backend,
    spinner_active: bool,
    status,
    dbg_func=None,
) -> tuple[list, bool, bool]:
    """Process human-in-the-loop approval for tool actions.

    Args:
        hitl_request: The HITL request containing action_requests
        session_state: Session state object
        assistant_id: Optional assistant ID
        backend: Backend object
        spinner_active: Whether spinner is currently active
        status: The status spinner object
        dbg_func: Optional debug logging function

    Returns:
        Tuple of (decisions list, any_rejected bool, new spinner_active state)
    """
    from namicode_cli.ui.tool_approval import prompt_for_tool_approval

    # Check plan mode blocking first
    is_blocked, rejection_response = check_plan_mode_blocked(
        hitl_request,
        session_state.plan_mode_enabled,
        dbg_func,
    )
    if is_blocked and rejection_response:
        return rejection_response["decisions"], True, spinner_active

    # Check if auto-approve is enabled
    if session_state.auto_approve:
        # Auto-approve all commands without prompting
        decisions = []
        for action_request in hitl_request["action_requests"]:
            if spinner_active:
                status.stop()
                spinner_active = False
            decisions.append({"type": "approve"})

        # Restart spinner for continuation
        if not spinner_active:
            status.start()
            spinner_active = True

        return decisions, False, spinner_active

    # Normal HITL flow - stop spinner and prompt user
    if spinner_active:
        status.stop()
        spinner_active = False

    # Handle human-in-the-loop approval
    decisions = []
    file_op_tracker = get_session_file_op_tracker(assistant_id=assistant_id, backend=backend)

    for action_index, action_request in enumerate(hitl_request["action_requests"]):
        decision = prompt_for_tool_approval(
            action_request,
            assistant_id,
        )

        # Check if user wants to switch to auto-approve mode
        if isinstance(decision, dict) and decision.get("type") == "auto_approve_all":
            # Switch to auto-approve mode
            session_state.auto_approve = True
            console.print()
            console.print("[bold blue]✓ Auto-approve mode enabled[/bold blue]")
            console.print(
                "[dim]All future tool actions will be automatically approved.[/dim]"
            )
            console.print()

            # Approve this action and all remaining actions in the batch
            decisions.append({"type": "approve"})
            for _remaining_action in hitl_request["action_requests"][action_index + 1:]:
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

    any_rejected = any(
        decision.get("type") == "reject" for decision in decisions
    )

    return decisions, any_rejected, spinner_active


def build_hitl_response(
    interrupt_id: str,
    decisions: list | None = None,
    response: dict | None = None,
    approved: bool | None = None,
    mode: str | None = None,
) -> dict:
    """Build a HITL response dict for resuming execution.

    Args:
        interrupt_id: The interrupt ID
        decisions: List of decision dicts (for tool approvals)
        response: Response dict (for questions)
        approved: Whether approved (for plan approvals)
        mode: Approval mode (for plan approvals)

    Returns:
        HITL response dict keyed by interrupt_id
    """
    if decisions is not None:
        return {"decisions": decisions}
    elif response is not None:
        return {"response": response}
    elif approved is not None:
        result: dict[str, bool | str] = {"approved": approved}
        if mode:
            result["mode"] = mode
        return result
    else:
        return {}
"""Human-in-the-loop approval flow for tool actions.

This module handles the approval/rejection flow for tool actions
that require user confirmation, including plan mode blocking.
"""

from pathlib import Path

from novacode_cli.config.config import console
from novacode_cli.config.plan_mode import BLOCKED_TOOLS, RESTRICTED_WRITE_TOOLS
from novacode_cli.file_ops import get_session_file_op_tracker
from novacode_cli.security.remember import apply_remember
from novacode_cli.security.rule_synthesis import synthesize_rule
from novacode_cli.ui.tool_approval import prompt_for_batch_approval


def _confirm_remember(rule):  # noqa: ANN001, ANN202
    """Confirm an 'always allow' rule: show it, pick project/global, optional edit.

    Returns ``(target, edited_rule_or_None)`` where target is ``"project"`` /
    ``"global"``, or ``(None, None)`` if the user cancels.
    """
    from dataclasses import replace

    console.print()
    console.print(f"[bold]Always allow:[/bold] {rule.human}")
    console.print(f"[dim]Rule ({rule.category}):[/dim] {rule.value}")
    choice = input("Save where?  [P]roject  [G]lobal  [E]dit  [C]ancel: ").strip().lower()
    if choice in {"e", "edit"}:
        new_value = input(f"Edit rule value [{rule.value}]: ").strip() or rule.value
        rule = replace(rule, value=new_value)
        choice = input("Save where?  [P]roject  [G]lobal  [C]ancel: ").strip().lower()
        edited = rule
    else:
        edited = None
    if choice in {"p", "project"}:
        return "project", edited
    if choice in {"g", "global"}:
        return "global", edited
    return None, None


def _is_plan_file_path(file_path: str) -> bool:
    """Return True if the path targets an allowed plan or metadata file, which is allowed in plan mode.

    Matches any file inside `.nova/plans/` or `.nova/ralph/` directory, or any file whose
    basename starts with "plan" (supports both plan.md and plan-<name>.md).
    """
    import os

    normalized = file_path.replace("\\", "/").lower()
    basename = os.path.basename(normalized)
    return (
        ".nova/plans/" in normalized
        or ".nova/ralph/" in normalized
        or (basename.startswith("plan") and basename.endswith(".md"))
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
        if tool_name in BLOCKED_TOOLS:
            # Completely blocked during planning
            blocked_actions.append(action_request)
        elif tool_name in RESTRICTED_WRITE_TOOLS:
            # Allow only when targeting a plan file
            file_path = str(action_request.get("args", {}).get("file_path", ""))
            if not _is_plan_file_path(file_path):
                blocked_actions.append(action_request)

    if blocked_actions:
        # Reject ALL actions in this interrupt silently
        if dbg_func:
            dbg_func(
                "PLAN-MODE-BLOCK",
                f"blocked {len(blocked_actions)} actions",
            )
        decisions = []
        for action_request in hitl_request.get("action_requests", []):
            tool_name = action_request.get("name", "")
            if tool_name in BLOCKED_TOOLS:
                msg = (
                    f"[Plan Mode Blocked] `{tool_name}` is blocked during planning. "
                    "You are currently in the planning phase and cannot execute commands or modify task state yet. "
                    "Please research the codebase using read-only tools, design a plan, and call `exit_plan_mode(plan=...)` to request user approval. "
                    "Do NOT attempt to run implementation tools or write todos yet."
                )
            elif tool_name in RESTRICTED_WRITE_TOOLS:
                file_path = str(action_request.get("args", {}).get("file_path", ""))
                msg = (
                    f"[Plan Mode Blocked] `{tool_name}` on `{file_path or '(unknown path)'}` is blocked during planning. "
                    "During planning, writes/edits are only allowed to `.nova/plans/` and `.nova/ralph/`. "
                    "Write your plan there, then call `exit_plan_mode(plan=...)` to request user approval. "
                    "Do NOT modify project code files before approval."
                )
            else:
                msg = "Plan mode active - tool blocked"
            decisions.append({"type": "reject", "message": msg})
        return True, {"decisions": decisions}

    return False, None


def evaluate_tool_actions(
    hitl_request: dict,
    session_state,
    *,
    plan_mode_enabled: bool = False,
) -> list[dict | None]:
    """Resolve each action in a tool interrupt against the pre-HITL gate.

    Folds the three short-circuits that don't need a prompt — plan-mode blocking,
    session ``auto_approve``, and the risk-tiered approval policy — into a single
    per-action verdict. This runs in the UI-agnostic agent loop, so the TUI, the
    Rich REPL, and remote turns all behave identically.

    Args:
        hitl_request: The validated HITL request (has ``action_requests``).
        session_state: Session state (read for ``auto_approve``).
        plan_mode_enabled: Whether plan mode is active.

    Returns:
        A list aligned with ``action_requests`` where each element is either a
        resolved decision dict (``{"type": "approve"}`` /
        ``{"type": "reject", "message": ...}``) or ``None`` meaning "ask the
        user". When no element is ``None`` the caller can resolve the interrupt
        without surfacing a prompt.
    """
    from novacode_cli.security.policy import get_policy

    action_requests = list(hitl_request.get("action_requests", []))
    if not action_requests:
        return []

    # Plan mode blocks the whole interrupt (rejects every action).
    is_blocked, rejection = check_plan_mode_blocked(hitl_request, plan_mode_enabled)
    if is_blocked and rejection:
        return list(rejection["decisions"])

    # auto_approve (e.g. a /remote turn) approves everything, no prompt.
    if getattr(session_state, "auto_approve", False):
        return [{"type": "approve"} for _ in action_requests]

    # Per-action policy: allow → approve silently, deny → reject, ask → prompt.
    try:
        policy = get_policy()
    except Exception:  # noqa: BLE001 — a policy failure must never break the turn
        return [None for _ in action_requests]

    resolutions: list[dict | None] = []
    for action_request in action_requests:
        name = action_request.get("name", "")
        args = action_request.get("args", {}) or {}
        try:
            decision = policy.evaluate(name, args)
        except Exception:  # noqa: BLE001 — fail safe: ask the user
            resolutions.append(None)
            continue
        if decision.tier == "allow":
            resolutions.append({"type": "approve"})
        elif decision.tier == "deny":
            resolutions.append(
                {
                    "type": "reject",
                    "message": decision.reason or "Blocked by approval policy",
                }
            )
        else:
            # ask tier: honor an in-session "allow for session" rule the user
            # accepted earlier this run; otherwise surface the prompt.
            from novacode_cli.security.session_allow import get_session_allow

            if get_session_allow().matches(name, args):
                resolutions.append({"type": "approve"})
            else:
                resolutions.append(None)
    return resolutions


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
        if spinner_active:
            status.stop()
            spinner_active = False
        decisions = [{"type": "approve"} for _ in hitl_request["action_requests"]]
        if not spinner_active:
            status.start()
            spinner_active = True
        return decisions, False, spinner_active

    # Normal HITL flow - stop spinner and prompt user
    if spinner_active:
        status.stop()
        spinner_active = False

    action_requests = hitl_request["action_requests"]
    file_op_tracker = get_session_file_op_tracker(assistant_id=assistant_id, backend=backend)

    # Batch prompt: shows all actions at once when there are multiple, letting the
    # user approve/reject in one keystroke instead of N sequential prompts.
    raw_decisions = prompt_for_batch_approval(action_requests, assistant_id)

    decisions = []
    auto_approve_triggered = False
    for action_index, decision in enumerate(raw_decisions):
        if isinstance(decision, dict) and decision.get("type") == "allow_session":
            ar = action_requests[action_index]
            apply_remember("session", ar.get("name", ""), ar.get("args", {}))
            console.print(f"[green]✓ Allowed for this session:[/green] {ar.get('name')}")
            decisions.append({"type": "approve"})
            continue

        if isinstance(decision, dict) and decision.get("type") == "allow_always":
            ar = action_requests[action_index]
            rule = synthesize_rule(ar.get("name", ""), ar.get("args", {}))
            target, edited = _confirm_remember(rule)
            if target is not None:
                result = apply_remember(
                    "always",
                    ar.get("name", ""),
                    ar.get("args", {}),
                    target=target,
                    project_root=Path.cwd(),
                    rule=edited or rule,
                )
                if result.saved_path is not None:
                    console.print(f"[green]✓ Saved to[/green] {result.saved_path}")
                else:
                    console.print(
                        f"[yellow]⚠ Could not save rule ({result.error}); "
                        f"kept for this session.[/yellow]"
                    )
            else:
                console.print("[dim]Not saved — approved this call only.[/dim]")
            decisions.append({"type": "approve"})
            continue

        if isinstance(decision, dict) and decision.get("type") == "auto_approve_all":
            session_state.auto_approve = True
            auto_approve_triggered = True
            console.print()
            console.print("[bold blue]✓ Auto-approve mode enabled[/bold blue]")
            console.print("[dim]All future tool actions will be automatically approved.[/dim]")
            console.print()
            decisions.append({"type": "approve"})
            for _remaining in action_requests[action_index + 1 :]:
                decisions.append({"type": "approve"})
            break

        decisions.append(decision)

        # Mark file operations as HIL-approved if user approved
        if decision.get("type") == "approve":
            tool_name = action_requests[action_index].get("name")
            if tool_name in {"write_file", "edit_file"}:
                file_op_tracker.mark_hitl_approved(
                    tool_name, action_requests[action_index].get("args", {})
                )

    any_rejected = any(d.get("type") == "reject" for d in decisions)
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

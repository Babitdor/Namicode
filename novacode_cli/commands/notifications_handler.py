"""Handler for the /notifications command — review and manage notifications."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.table import Table
from rich.text import Text

from novacode_cli.config.config import COLORS, console

if TYPE_CHECKING:
    from novacode_cli.states.Session import SessionState

_LEVEL_COLORS = {
    "info": "cyan",
    "success": "green",
    "warning": "yellow",
    "error": "red",
}


async def handle_notifications_command(
    session_state: "SessionState",
    args: str | None = None,
) -> bool:
    """Handle /notifications command.

    Usage:
        /notifications                  - List all notifications (default)
        /notifications list             - List all notifications
        /notifications clear            - Dismiss all notifications
        /notifications dismiss <id>     - Dismiss (reject) a notification
        /notifications approve <id>     - Approve a pending approval notification

    When a notification has an ``action_id`` (level "approval"), dismissing it
    rejects the pending approval. Approving it resolves the approval.

    Returns:
        True (command always handled)
    """
    parts = (args or "").strip().split(maxsplit=1)
    subcmd = parts[0].lower() if parts else "list"
    subarg = parts[1].strip() if len(parts) > 1 else None

    if subcmd in ("clear", "reset"):
        # Dismiss all — reject any pending approvals.
        for n in list(session_state.notifications):
            if n.action_id and not n.dismissed:
                session_state.resolve_approval(n.action_id, approve=False)
        count = session_state.clear_notifications()
        console.print(f"[green]✓[/green] Cleared {count} notification(s)")
        console.print()
        return True

    if subcmd in ("dismiss", "rm", "ack") and subarg:
        # Dismiss = reject any associated pending approval.
        n = _find_notification(session_state, subarg)
        if n is None:
            console.print(f"[yellow]Notification {subarg} not found[/yellow]")
            console.print()
            return True
        if n.action_id and not n.dismissed:
            session_state.resolve_approval(n.action_id, approve=False)
        elif session_state.dismiss_notification(subarg):
            pass  # already marked by resolve_approval
        console.print(f"[green]✓[/green] Dismissed notification {subarg}")
        console.print()
        return True

    if subcmd == "approve" and subarg:
        n = _find_notification(session_state, subarg)
        if n is None:
            console.print(f"[yellow]Notification {subarg} not found[/yellow]")
            console.print()
            return True
        if n.action_id and not n.dismissed:
            if session_state.resolve_approval(n.action_id, approve=True):
                console.print(f"[green]✓[/green] Approved notification {subarg}")
            else:
                console.print(f"[yellow]Approval {subarg} already resolved[/yellow]")
        else:
            console.print(f"[yellow]Notification {subarg} has no pending approval[/yellow]")
        console.print()
        return True

    # Default: list
    notifications = list(session_state.notifications)
    if not notifications:
        console.print("[dim]No notifications[/dim]")
        console.print()
        return True

    table = Table(show_header=True, header_style="bold")
    table.add_column("", width=2)
    table.add_column("ID", style="dim", width=8)
    table.add_column("Time", width=8)
    table.add_column("Source", width=8)
    table.add_column("Title")
    table.add_column("Message", style="dim")

    for n in notifications:
        color = _LEVEL_COLORS.get(n.level, "white")
        marker = "●" if not n.dismissed else "○"
        # Add ⚡ marker for pending approvals that require user action.
        prefix = ""
        if n.action_id and not n.dismissed and n.action_type == "approve":
            prefix = "⚡"
            marker = f"{prefix}{marker}"
        table.add_row(
            marker,
            n.id,
            n.timestamp.strftime("%H:%M:%S"),
            n.source,
            Text(n.title, style=color),
            n.message[:60],
        )

    unread = session_state.unread_notification_count()
    pending = session_state.pending_approval_count()
    console.print()
    title = f"[bold]Notifications[/bold] ({unread} unread"
    if pending:
        title += f", [yellow]{pending} pending approval[/yellow]"
    title += ")"
    console.print(title, style=COLORS["primary"])
    console.print(table)
    usage = (
        "[dim]Usage: /notifications dismiss <id> | /notifications approve <id> "
        "| /notifications clear[/dim]"
    )
    console.print(usage)
    console.print()
    return True


def _find_notification(
    session_state: "SessionState", nid: str
) -> object | None:
    """Return the Notification with the given id, or None."""

    for n in session_state.notifications:
        if n.id == nid:
            return n
    return None


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

def register_commands(registry) -> None:
    from novacode_cli.commands import CommandContext

    async def _handle(ctx: CommandContext) -> bool:
        return await handle_notifications_command(ctx.session_state, args=ctx.cmd_args)

    registry.register("notifications", _handle)

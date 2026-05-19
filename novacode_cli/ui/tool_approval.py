"""Tool approval UI for human-in-the-loop confirmation.

This module provides the interactive approval prompt for tool actions
that require user confirmation before execution.
"""

import sys

from rich import box
from rich.panel import Panel

from novacode_cli.config.config import console

# Import types from langchain
from langchain.agents.middleware.human_in_the_loop import (
    ActionRequest,
    ApproveDecision,
    Decision,
    RejectDecision,
)

from novacode_cli.file_ops import build_approval_preview
from novacode_cli.ui.ui_elements import render_diff_block


def prompt_for_batch_approval(
    action_requests: list[ActionRequest],
    assistant_id: str | None,
) -> list[Decision | dict]:
    """Prompt the user to approve/reject multiple tool actions at once.

    Shows a summary of all pending actions in a single panel, then offers:
      (A)pprove all  /  (R)eject all  /  (I)ndividual  /  (Auto)-accept all

    Falls back to sequential ``prompt_for_tool_approval`` calls when the user
    chooses "Individual" or on terminals that don't support raw mode.

    Returns a list of decisions in the same order as *action_requests*.
    """
    if len(action_requests) == 1:
        return [prompt_for_tool_approval(action_requests[0], assistant_id)]

    # Build a compact summary of all pending actions
    lines = ["[bold yellow]Multiple Tool Actions Require Approval[/bold yellow]\n"]
    for i, req in enumerate(action_requests, 1):
        name = req.get("name", "?")
        desc = req.get("description", "")
        preview = build_approval_preview(name, req.get("args", {}), assistant_id)
        summary = (preview.title if preview else None) or desc or name
        lines.append(f"  [dim]{i}.[/dim] [bold]{name}[/bold]  {summary}")

    console.print(
        Panel(
            "\n".join(lines),
            border_style="yellow",
            box=box.ROUNDED,
            padding=(0, 1),
        )
    )

    options = [
        "approve all",
        "reject all",
        "decide individually",
        "auto-accept all going forward",
    ]
    selected = 0

    try:
        import termios, tty  # noqa: E401

        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)  # type: ignore
        try:
            tty.setraw(fd)  # type: ignore
            sys.stdout.write("\033[?25l")
            sys.stdout.flush()
            first_render = True
            while True:
                if not first_render:
                    sys.stdout.write(f"\033[{len(options)}A\r")
                first_render = False
                for i, opt in enumerate(options):
                    sys.stdout.write("\r\033[K")
                    label = opt.capitalize()
                    if i == selected:
                        colours = {0: "1;32", 1: "1;31", 2: "1;33", 3: "1;34"}
                        sys.stdout.write(f"\033[{colours[i]}m☑ {label}\033[0m\n")
                    else:
                        sys.stdout.write(f"\033[2m☐ {label}\033[0m\n")
                sys.stdout.flush()
                char = sys.stdin.read(1)
                if char == "\x1b":
                    n1, n2 = sys.stdin.read(1), sys.stdin.read(1)
                    if n1 == "[":
                        if n2 == "B":
                            selected = (selected + 1) % len(options)
                        elif n2 == "A":
                            selected = (selected - 1) % len(options)
                elif char in {"\r", "\n"}:
                    sys.stdout.write("\r\n")
                    break
                elif char == "\x03":
                    sys.stdout.write("\r\n")
                    raise KeyboardInterrupt
                elif char.lower() == "a":
                    selected = 0
                    sys.stdout.write("\r\n")
                    break
                elif char.lower() == "r":
                    selected = 1
                    sys.stdout.write("\r\n")
                    break
                elif char.lower() == "i":
                    selected = 2
                    sys.stdout.write("\r\n")
                    break
        finally:
            sys.stdout.write("\033[?25h")
            sys.stdout.flush()
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)  # type: ignore

    except Exception:
        # Fallback for Windows / restricted terminals
        console.print("  (A)pprove all  (R)eject all  (I)ndividual  (Auto)-accept all")
        choice = input("\nChoice (A/R/I/Auto, default=Approve all): ").strip().lower()
        if choice in {"r", "reject"}:
            selected = 1
        elif choice in {"i", "individual"}:
            selected = 2
        elif choice in {"auto"}:
            selected = 3
        else:
            selected = 0

    if selected == 0:  # approve all
        return [ApproveDecision(type="approve") for _ in action_requests]
    if selected == 1:  # reject all
        return [RejectDecision(type="reject", message="User rejected the command") for _ in action_requests]
    if selected == 3:  # auto-accept all going forward
        return [{"type": "auto_approve_all"}, *[ApproveDecision(type="approve") for _ in action_requests[1:]]]
    # Individual — fall back to sequential prompts
    return [prompt_for_tool_approval(req, assistant_id) for req in action_requests]


def prompt_for_tool_approval(
    action_request: ActionRequest,
    assistant_id: str | None,
) -> Decision | dict:
    """Prompt user to approve/reject a tool action with interactive menu.

    Uses a cross-platform prompt_toolkit-based menu with arrow key navigation
    that works consistently on Windows, Linux, and Mac.

    Args:
        action_request: The action request containing tool name, args, and description.
        assistant_id: Optional assistant ID for context.

    Returns:
        Decision (ApproveDecision or RejectDecision) OR
        dict with {"type": "auto_approve_all"} to switch to auto-approve mode
    """
    description = action_request.get("description", "No description available")
    name = action_request["name"]
    args = action_request["args"]
    preview = build_approval_preview(name, args, assistant_id) if name else None

    body_lines = []
    if preview:
        body_lines.append(f"[bold]{preview.title}[/bold]")
        body_lines.extend(preview.details)
        if preview.error:
            body_lines.append(f"[red]{preview.error}[/red]")
    else:
        body_lines.append(description)

    # Display action info first
    console.print(
        Panel(
            "[bold yellow]Tool Action Requires Approval[/bold yellow]\n\n"
            + "\n".join(body_lines),
            border_style="yellow",
            box=box.ROUNDED,
            padding=(0, 1),
        )
    )
    if preview and preview.diff and not preview.error:
        console.print()
        render_diff_block(preview.diff, preview.diff_title or preview.title)

    options = ["approve", "reject", "auto-accept all going forward"]
    selected = 0  # Start with approve selected

    try:
        # Import termios/tty only when needed (Unix-only modules)
        import termios
        import tty

        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)  # type: ignore

        try:
            tty.setraw(fd)  # type: ignore
            # Hide cursor during menu interaction
            sys.stdout.write("\033[?25l")
            sys.stdout.flush()

            # Initial render flag
            first_render = True

            while True:
                if not first_render:
                    # Move cursor back to start of menu (up 3 lines, then to start of line)
                    sys.stdout.write("\033[3A\r")

                first_render = False

                # Display options vertically with ANSI color codes
                for i, option in enumerate(options):
                    sys.stdout.write("\r\033[K")  # Clear line from cursor to end

                    if i == selected:
                        if option == "approve":
                            # Green bold with filled checkbox
                            sys.stdout.write("\033[1;32m☑ Approve\033[0m\n")
                        elif option == "reject":
                            # Red bold with filled checkbox
                            sys.stdout.write("\033[1;31m☑ Reject\033[0m\n")
                        else:
                            # Blue bold with filled checkbox for auto-accept
                            sys.stdout.write(
                                "\033[1;34m☑ Auto-accept all going forward\033[0m\n"
                            )
                    elif option == "approve":
                        # Dim with empty checkbox
                        sys.stdout.write("\033[2m☐ Approve\033[0m\n")
                    elif option == "reject":
                        # Dim with empty checkbox
                        sys.stdout.write("\033[2m☐ Reject\033[0m\n")
                    else:
                        # Dim with empty checkbox
                        sys.stdout.write(
                            "\033[2m☐ Auto-accept all going forward\033[0m\n"
                        )

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
                    sys.stdout.write("\r\n")  # Move to start of line and add newline
                    break
                elif char == "\x03":  # Ctrl+C
                    sys.stdout.write("\r\n")  # Move to start of line and add newline
                    raise KeyboardInterrupt
                elif char.lower() == "a":
                    selected = 0
                    sys.stdout.write("\r\n")  # Move to start of line and add newline
                    break
                elif char.lower() == "r":
                    selected = 1
                    sys.stdout.write("\r\n")  # Move to start of line and add newline
                    break

        finally:
            # Show cursor again
            sys.stdout.write("\033[?25h")
            sys.stdout.flush()
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)  # type: ignore

    except (ImportError, AttributeError, Exception):
        # Fallback for non-Unix systems (ImportError when termios/tty not available)
        # or any other terminal-related errors
        console.print("  ☐ (A)pprove  (default)")
        console.print("  ☐ (R)eject")
        console.print("  ☐ (Auto)-accept all going forward")
        choice = input("\nChoice (A/R/Auto, default=Approve): ").strip().lower()
        if choice in {"r", "reject"}:
            selected = 1
        elif choice in {"auto", "auto-accept"}:
            selected = 2
        else:
            selected = 0

    # Return decision based on selection
    if selected == 0:
        return ApproveDecision(type="approve")
    if selected == 1:
        return RejectDecision(type="reject", message="User rejected the command")
    # Return special marker for auto-approve mode
    return {"type": "auto_approve_all"}

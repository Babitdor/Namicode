"""Handler for the /plan command to toggle or manage plan mode."""

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from namicode_cli.config.config import COLORS, console


async def handle_plan_command(agent, session_state, args: str | None = None) -> bool:
    """Handle the /plan command to toggle or check plan mode.

    Usage:
        /plan        - Toggle plan mode
        /plan on     - Enable plan mode
        /plan off    - Disable plan mode
        /plan status - Show current status

    Args:
        agent: The current agent.
        session_state: Current session state.
        args: Optional arguments (on, off, status).

    Returns:
        True (always handled).
    """
    from namicode_cli.agents.core_agent import (
        get_agent_plan_mode_state,
        set_agent_plan_mode_state,
    )

    # Get current plan mode state from agent
    try:
        current_state = await get_agent_plan_mode_state(agent, session_state.thread_id)
    except Exception:
        # Agent state might not be initialized yet
        current_state = False

    if args is None or args.strip() == "":
        # Toggle mode
        new_state = not current_state

        if new_state:
            # Enabling plan mode - no approval needed
            try:
                await set_agent_plan_mode_state(
                    agent, session_state.thread_id, new_state
                )
            except Exception:
                pass
            session_state.plan_mode_enabled = new_state
            console.print()
            console.print(
                Panel(
                    "[bold]Plan Mode Enabled[/bold]\n\n"
                    "• Agent will focus on understanding before executing\n"
                    "• Questions will be asked to clarify requirements\n"
                    "• Plans will be presented before implementation\n\n"
                    "[dim]Use Shift+Tab or /plan off to exit[/dim]",
                    title="[cyan]Plan Mode[/cyan]",
                    border_style="cyan",
                    box=box.ROUNDED,
                )
            )
        else:
            # Disabling plan mode - show approval dialog
            from namicode_cli.ui.question_prompt import prompt_for_plan_approval

            result = prompt_for_plan_approval(
                todos=session_state.todos,
                plan_summary="Review your plan before proceeding",
            )
            if result["approved"]:
                try:
                    await set_agent_plan_mode_state(
                        agent, session_state.thread_id, False
                    )
                except Exception:
                    pass
                session_state.plan_mode_enabled = False
                console.print("[green]Plan Mode Disabled - ready to execute[/green]")
            else:
                console.print("[cyan]Staying in Plan Mode[/cyan]")
        console.print()
        return True

    arg = args.strip().lower()

    if arg == "on":
        try:
            await set_agent_plan_mode_state(agent, session_state.thread_id, True)
        except Exception:
            pass
        session_state.plan_mode_enabled = True
        console.print("[cyan]Plan Mode Enabled[/cyan]")
        console.print()
        return True

    if arg == "off":
        # Show plan approval before exiting plan mode
        from namicode_cli.ui.question_prompt import prompt_for_plan_approval

        result = prompt_for_plan_approval(
            todos=session_state.todos,
            plan_summary="Review your plan before proceeding",
        )
        if result["approved"]:
            try:
                await set_agent_plan_mode_state(agent, session_state.thread_id, False)
            except Exception:
                pass
            session_state.plan_mode_enabled = False
            console.print("[green]Plan Mode Disabled - ready to execute[/green]")
        else:
            console.print("[cyan]Staying in Plan Mode[/cyan]")
        console.print()
        return True

    if arg == "status":
        status = "enabled" if current_state else "disabled"
        color = "cyan" if current_state else "yellow"
        console.print(f"[{color}]Plan Mode: {status}[/{color}]")
        console.print()
        return True

    console.print("[red]Invalid argument. Use: /plan [on|off|status][/red]")
    console.print()
    return True
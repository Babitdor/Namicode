"""Handler for the /trello command - task board in the browser.

Usage:
    /trello              - Start the task board server and open browser
    /trello stop         - Stop the task board server
    /trello status       - Show current task board state

The task board is a self-contained HTML page served from a local HTTP server.
Tasks are added in the browser. When a task moves to "Processing", the agent
picks it up, processes it, and marks it "Done".
"""

from __future__ import annotations

import asyncio
import webbrowser
from typing import Any

from novacode_cli.config.config import COLORS, console
from novacode_cli.ui.ui_elements import TokenTracker


async def handle_trello_command(
    agent: Any,
    session_state: Any,
    assistant_id: str | None,
    token_tracker: TokenTracker | None = None,
    cmd_args: str | None = None,
    execute_fn: Any = None,
) -> bool:
    """Handle the /trello command.

    Args:
        agent: The compiled agent graph.
        session_state: Current session state.
        assistant_id: Agent ID.
        token_tracker: Token tracker instance.
        cmd_args: Command arguments (e.g., "stop", "status").
        execute_fn: Optional custom execution function (for TUI integration).

    Returns:
        True if the command was handled.
    """
    from novacode_cli.commands.trello_server import TrelloServer

    if execute_fn is None:
        from novacode_cli.ui.execution import execute_task

        execute_fn = execute_task

    # Handle subcommands
    if cmd_args and cmd_args.strip() == "stop":
        return _handle_stop(session_state)

    if cmd_args and cmd_args.strip() == "status":
        return _handle_status(session_state)

    # Check if already running
    existing_server: TrelloServer | None = getattr(
        session_state, "trello_server", None
    )
    if existing_server and existing_server.is_running:
        console.print()
        console.print(
            f"[yellow]Trello board is already running at "
            f"[cyan]http://localhost:{existing_server.port}[/cyan][/yellow]"
        )
        console.print("[dim]Use /trello stop to stop it.[/dim]")
        console.print()
        return True

    # Start the server
    server = TrelloServer()
    port = await server.start()

    # Store on session_state for lifecycle management
    session_state.trello_server = server

    # Open browser
    try:
        webbrowser.open(f"http://localhost:{port}")
    except Exception:
        pass  # Browser opening is best-effort

    console.print()
    console.print(
        f"[green]✓[/green] Trello board started at "
        f"[cyan]http://localhost:{port}[/cyan]"
    )
    console.print(
        "[dim]Add tasks in the browser. "
        "The agent will process them one at a time.[/dim]"
    )
    console.print("[dim]Use /trello stop to shut down the server.[/dim]")
    console.print()

    # Watch for processing tasks
    while server.is_running:
        # First check for tasks explicitly moved to "processing" (web UI click)
        task = await server.get_next_processing_task()
        if not task:
            # Auto-pick the first "loaded" task
            task = server.pop_next_loaded_task()
        if task:
            console.print()
            console.print(
                f"[bold {COLORS['primary']}]📋 Processing task:[/] "
                f"{task['description']}"
            )
            console.print()

            # Send to agent
            await execute_fn(
                task["description"],
                agent,
                assistant_id,
                session_state,
                token_tracker,
            )

            # Mark done
            await server.mark_done(task["id"])

            console.print()
            console.print(
                f"[green]✓[/green] Task completed: "
                f"[dim]{task['description']}[/dim]"
            )
            console.print()
        else:
            await asyncio.sleep(0.5)

    return True


def _handle_stop(session_state: Any) -> bool:
    """Handle /trello stop - shut down the server."""
    server: Any = getattr(session_state, "trello_server", None)
    if server and server.is_running:
        server.stop()
        session_state.trello_server = None
        console.print()
        console.print("[green]✓[/green] Trello board server stopped.")
        console.print()
    else:
        console.print()
        console.print("[yellow]No Trello board server is running.[/yellow]")
        console.print()
    return True


def _handle_status(session_state: Any) -> bool:
    """Handle /trello status - show current task board state."""
    server: Any = getattr(session_state, "trello_server", None)
    if not server or not server.is_running:
        console.print()
        console.print("[yellow]No Trello board server is running.[/yellow]")
        console.print("[dim]Start one with /trello[/dim]")
        console.print()
        return True

    counts = server.get_task_counts()
    processing_task = server.get_processing_task()

    console.print()
    console.print("[bold]📋 Trello Board Status[/bold]")
    console.print(f"  Server: [cyan]http://localhost:{server.port}[/cyan]")
    console.print(f"  📥 Loaded:    [bold]{counts['loaded']}[/bold]")
    console.print(f"  ⚙️ Processing: [bold]{counts['processing']}[/bold]")
    console.print(f"  ✅ Done:      [bold]{counts['done']}[/bold]")
    if processing_task:
        console.print(
            f"  Currently processing: [dim]{processing_task['description']}[/dim]"
        )
    console.print()
    return True


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

def register_commands(registry) -> None:
    from novacode_cli.commands import CommandContext

    async def _handle(ctx: CommandContext) -> bool:
        return await handle_trello_command(
            agent=ctx.agent, session_state=ctx.session_state,
            assistant_id=ctx.assistant_id, token_tracker=ctx.token_tracker,
            cmd_args=ctx.cmd_args,
        )

    registry.register("trello", _handle)

"""Command handlers for slash commands and bash execution.

This module provides the main handle_command function that routes
slash commands to their respective handlers.
"""

import argparse
import asyncio
import io
import subprocess
import sys
import uuid
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from datetime import UTC, datetime
from pathlib import Path

from rich.text import Text

from namicode_cli.config.config import COLORS, NAMI_CODE_ASCII, console
from namicode_cli.states.Session import RalphTaskStatus
from namicode_cli.ui.ui_elements import TokenTracker, show_interactive_help

# Import command handlers from component modules
from namicode_cli.commands.init_handler import handle_init_command
from namicode_cli.commands.mcp_handler import handle_mcp_command
from namicode_cli.commands.model_handler import handle_model_command
from namicode_cli.commands.session_commands import (
    handle_compact_command,
    handle_save_command,
    handle_sessions_command,
)
from namicode_cli.commands.server_commands import (
    handle_kill_command,
    handle_servers_command,
    handle_tests_command,
)
from namicode_cli.commands.skills_commands import handle_skills_command
from namicode_cli.commands.agents_commands import handle_agents_command
from namicode_cli.commands.file_commands import (
    handle_files_command,
    handle_images_command,
    handle_restore_command,
)
from namicode_cli.commands.plan_handler import handle_plan_command
from namicode_cli.commands.trace_handler import handle_trace_command
from namicode_cli.commands.ralph_handler import (
    handle_ralph_command,
    _stop_and_save_all_ralph_tasks,
)


@contextmanager
def silent_console_mode():
    """Context manager that suppresses all Rich console output.

    Works by redirecting the console's file handle to /dev/null.
    This suppresses all console output including print, status, tables, etc.
    """
    from namicode_cli.config.config import console

    # Save the original file handle
    original_file = console.file

    try:
        # Redirect console output to a black hole (StringIO that's never read)
        console.file = io.StringIO()
        yield
    finally:
        # Restore the original file handle
        console.file = original_file


async def handle_command(
    command: str,
    agent,
    token_tracker: TokenTracker,
    session_state,
    assistant_id: str,
    session_manager=None,
    model_name: str | None = None,
    image_tracker=None,
) -> str | bool:
    """Handle slash commands. Returns 'exit' to exit, True if handled, False to pass to agent."""
    # Parse command and optional arguments
    cmd_parts = command.strip().lstrip("/").split(maxsplit=1)
    cmd = cmd_parts[0].lower()
    cmd_args = cmd_parts[1] if len(cmd_parts) > 1 else None

    if cmd in ["quit", "exit", "q"]:
        # Check if Ralph is still running
        running_ralph_tasks = [
            task
            for task in session_state.background_ralph_tasks.values()
            if task.status == RalphTaskStatus.RUNNING
        ]

        if running_ralph_tasks:
            print()
            print("⚠️  Ralph is still running in the background")
            print()

            # Show which tasks are running
            for task in running_ralph_tasks:
                elapsed = (datetime.now(UTC) - task.created_at).total_seconds()
                print(
                    f"  ⏳ Iteration {task.iteration}/{task.max_iterations} (elapsed: {elapsed:.0f}s)"
                )
                task_desc = (
                    task.task_description[:50] + "..."
                    if len(task.task_description) > 50
                    else task.task_description
                )
                print(f"  📝 {task_desc}")

            print()
            print("What would you like to do?")
            print(
                "  1 - Stop Ralph and save checkpoint (resume later with /ralph --resume)"
            )
            print("  2 - Keep Ralph running and exit anyway")
            print("  3 - Cancel exit and continue")
            print()
            sys.stdout.flush()

            # Get user choice with validation using async-safe approach
            loop = asyncio.get_event_loop()
            choice = None
            while True:
                try:
                    choice = await loop.run_in_executor(
                        None, input, "Enter your choice (1-3): "
                    )
                    choice = choice.strip()
                    if choice in ["1", "2", "3"]:
                        break
                    print("Invalid choice. Please enter 1, 2, or 3.")
                    sys.stdout.flush()
                except EOFError:
                    return True

            print()
            sys.stdout.flush()

            if choice == "1":
                if _stop_and_save_all_ralph_tasks(session_state):
                    console.print()
                    console.print(
                        "[green]✓[/green] Ralph has been stopped and state saved"
                    )
                    console.print(
                        "[dim]You can resume your work anytime with: /ralph --resume[/dim]"
                    )
                    console.print()
                    return "exit"
            elif choice == "2":
                print("Ralph will continue running in the background.")
                print()
                sys.stdout.flush()
                return "exit"
            else:
                print("Exit cancelled. Continuing...")
                print()
                sys.stdout.flush()
                return True

        return "exit"

    if cmd == "clear":
        session_state.thread_id = str(uuid.uuid4())
        token_tracker.reset()
        console.clear()
        console.print(NAMI_CODE_ASCII, style=f"bold {COLORS['primary']}")
        console.print()
        console.print(
            "... Fresh start! Conversation history cleared.",
            style=COLORS["agent"],
        )
        console.print()
        return True

    if cmd == "help":
        show_interactive_help()
        return True

    if cmd == "tokens":
        token_tracker.display_session()
        return True

    if cmd == "context":
        try:
            token_tracker.display_context()
        except Exception as e:
            console.print(f"[red]Error running /context command: {e}[/red]")
        return True

    if cmd == "compact":
        try:
            return await handle_compact_command(
                agent, session_state, token_tracker, focus_instructions=cmd_args
            )
        except Exception as e:
            console.print(f"[red]Error running /compact command: {e}[/red]")
        return True

    if cmd == "init":
        try:
            await handle_init_command(agent, session_state, assistant_id, token_tracker)
        except Exception as e:
            console.print(f"[red]Error running /init command: {e}[/red]")
        return True

    if cmd == "mcp":
        try:
            return await handle_mcp_command()
        except Exception as e:
            console.print(f"[red]Error running /mcp command: {e}[/red]")
        return True

    if cmd == "model":
        try:
            return await handle_model_command()
        except Exception as e:
            console.print(f"[red]Error running /model command: {e}[/red]")
        return True

    if cmd == "sessions":
        try:
            return await handle_sessions_command(session_state)
        except Exception as e:
            console.print(f"[red]Error running /sessions command: {e}[/red]")
        return True

    if cmd == "save":
        try:
            return await handle_save_command(
                agent, session_state, assistant_id, session_manager, model_name
            )
        except Exception as e:
            console.print(f"[red]Error running /save command: {e}[/red]")
        return True

    if cmd == "servers":
        try:
            return await handle_servers_command(session_state)
        except Exception as e:
            console.print(f"[red]Error running /servers command: {e}[/red]")
        return True

    if cmd == "tests":
        try:
            return await handle_tests_command(session_state, cmd_args)
        except Exception as e:
            console.print(f"[red]Error running /tests command: {e}[/red]")
        return True

    if cmd == "kill":
        try:
            return await handle_kill_command(session_state, cmd_args)
        except Exception as e:
            console.print(f"[red]Error running /kill command: {e}[/red]")
        return True

    if cmd == "skills":
        try:
            return await handle_skills_command(cmd_args, assistant_id)
        except Exception as e:
            console.print(f"[red]Error running /skills command: {e}[/red]")
        return True

    if cmd == "agents":
        try:
            return await handle_agents_command(cmd_args, assistant_id)
        except Exception as e:
            console.print(f"[red]Error running /agents command: {e}[/red]")
        return True

    if cmd == "trace":
        try:
            args_list = cmd_args.split() if cmd_args else []
            return await handle_trace_command(args_list)
        except Exception as e:
            console.print(f"[red]Error running /trace command: {e}[/red]")
        return True

    if cmd == "files":
        try:
            return await handle_files_command()
        except Exception as e:
            console.print(f"[red]Error running /files command: {e}[/red]")
        return True

    if cmd == "plan":
        try:
            return await handle_plan_command(agent, session_state, cmd_args)
        except Exception as e:
            console.print(f"[red]Error running /plan command: {e}[/red]")
        return True

    if cmd == "verbose":
        new_state = session_state.toggle_verbose()
        if new_state:
            console.print()
            console.print(
                "  [bold green]Verbose mode enabled[/bold green] — internal agent context will be shown"
            )
            console.print()
        else:
            console.print()
            console.print(
                "  [bold yellow]Verbose mode disabled[/bold yellow] — internal agent context will be collapsed"
            )
            console.print()
        return True

    if cmd == "images":
        try:
            return await handle_images_command(cmd_args, image_tracker)
        except Exception as e:
            console.print(f"[red]Error running /images command: {e}[/red]")
        return True

    if cmd == "restore":
        try:
            return await handle_restore_command(cmd_args)
        except Exception as e:
            console.print(f"[red]Error running /restore command: {e}[/red]")
        return True

    if cmd == "ralph":
        try:
            return await handle_ralph_command(
                agent, session_state, assistant_id, token_tracker, cmd_args
            )
        except Exception as e:
            console.print(f"[red]Error running /ralph command: {e}[/red]")
        return True

    console.print()
    console.print(f"[yellow]Unknown command: /{cmd}[/yellow]")
    console.print("[dim]Type /help for available commands.[/dim]")
    console.print()
    return True


def execute_bash_command(command: str) -> bool:
    """Execute a bash command and display output. Returns True if handled."""
    cmd = command.strip().lstrip("!")

    if not cmd:
        return True

    try:
        console.print()
        console.print(f"[dim]$ {cmd}[/dim]")

        result = subprocess.run(
            cmd,
            check=False,
            shell=True,
            capture_output=True,
            timeout=30,
            cwd=Path.cwd(),
        )

        stdout = (result.stdout or b"").decode("utf-8", errors="replace")
        stderr = (result.stderr or b"").decode("utf-8", errors="replace")

        if stdout.strip():
            console.print(stdout, style=COLORS["dim"], markup=False)
        if stderr.strip():
            console.print(stderr, style="red", markup=False)

        if result.returncode != 0:
            console.print(f"[dim]Exit code: {result.returncode}[/dim]")

        console.print()
        return True

    except subprocess.TimeoutExpired:
        console.print("[red]Command timed out after 30 seconds[/red]")
        console.print()
        return True
    except Exception as e:
        console.print(f"[red]Error executing command: {e}[/red]")
        console.print()
        return True


def execute_skills_command(args: argparse.Namespace) -> None:
    """Execute skills subcommands based on parsed arguments.

    Args:
        args: Parsed command line arguments with skills_command attribute
    """
    from namicode_cli.skills.skill_creation import (
        _add,
        _create,
        _find,
        _info,
        _list,
        _remove,
        _update,
        _validate_name,
    )

    if args.agent:
        is_valid, error_msg = _validate_name(args.agent)
        if not is_valid:
            console.print(
                f"[bold red]Error:[/bold red] Invalid agent name: {error_msg}"
            )
            console.print(
                "[dim]Agent names must only contain letters, numbers, hyphens, and underscores.[/dim]",
                style=COLORS["dim"],
            )
            return

    if args.skills_command == "list":
        _list(
            agent=args.agent,
            project=args.project,
            global_scope=getattr(args, "global_scope", False),
        )
    elif args.skills_command == "create":
        _create(
            args.name,
            agent=args.agent,
            project=args.project,
            global_scope=getattr(args, "global_scope", False),
        )
    elif args.skills_command == "info":
        _info(
            args.name,
            agent=args.agent,
            project=args.project,
            global_scope=getattr(args, "global_scope", False),
        )
    elif args.skills_command == "add":
        _add(
            args.url,
            agent=args.agent,
            project=args.project,
            global_scope=getattr(args, "global_scope", False),
            force=getattr(args, "force", False),
            skill_name=getattr(args, "skill_name", None),
        )
    elif args.skills_command == "remove":
        _remove(
            args.name,
            agent=args.agent,
            project=args.project,
            global_scope=getattr(args, "global_scope", False),
            yes=getattr(args, "yes", False),
        )
    elif args.skills_command == "update":
        _update(
            skill_name=getattr(args, "name", None),
            agent=args.agent,
            project=args.project,
            global_scope=getattr(args, "global_scope", False),
            all_skills=getattr(args, "all_skills", False),
        )
    elif args.skills_command in ("find", "search"):
        _find(args.query)
    else:
        console.print("[yellow]Please specify a skills subcommand.[/yellow]")
        console.print("\n[bold]Usage:[/bold]", style=COLORS["primary"])
        console.print("  nami skills <command> [options]\n")
        console.print("[bold]Available commands:[/bold]", style=COLORS["primary"])
        console.print("  list                    List all available skills")
        console.print("  create <name>           Create a new skill")
        console.print("  info <name>             Show detailed information about a skill")
        console.print("  add <url>               Install a skill from GitHub URL")
        console.print("  remove <name>           Remove an installed skill")
        console.print("  update [name]           Update skill(s) from their original source")
        console.print("  find <query>            Search GitHub for skills")
        console.print("  search <query>          Alias for find")
        console.print("\n[bold]Examples:[/bold]", style=COLORS["primary"])
        console.print("  nami skills add https://github.com/owner/repo --skill my-skill")
        console.print("  nami skills remove my-skill -y")
        console.print("  nami skills update my-skill")
        console.print("  nami skills update --all --global")
        console.print("  nami skills find kubernetes")
        console.print("\n[dim]For more help on a specific command:[/dim]", style=COLORS["dim"])
        console.print("  nami skills <command> --help", style=COLORS["dim"])

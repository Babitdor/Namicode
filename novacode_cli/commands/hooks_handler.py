"""Handler for the /hooks command for hook management."""

import json
import shutil
import time
from pathlib import Path

from prompt_toolkit import PromptSession
from rich.table import Table

from novacode_cli.config.config import COLORS, console
from novacode_cli.hooks import (
    HOOKS_DIR,
    HOOKS_FILE,
    HookEvent,
    _load_hooks,
    reload_hooks,
)


async def handle_hooks_command(cmd_args: str | None = None) -> bool:
    """Handle the /hooks command for hook management.
    
    Args:
        cmd_args: Optional command arguments (e.g., 'list', 'add', 'test')
        
    Returns:
        True (command always handled)
    """
    session = PromptSession()

    # Parse command arguments
    if cmd_args:
        args = cmd_args.strip().split()
        subcommand = args[0].lower() if args else None
        subargs = args[1:] if len(args) > 1 else []
    else:
        subcommand = None
        subargs = []

    # Handle subcommands
    if subcommand == "list":
        return _list_hooks()
    if subcommand == "add":
        return await _add_hook(session, subargs)
    if subcommand == "remove":
        return await _remove_hook(session, subargs)
    if subcommand == "enable":
        return await _enable_hook(session, subargs)
    if subcommand == "disable":
        return await _disable_hook(session, subargs)
    if subcommand == "test":
        return await _test_hook(session, subargs)
    if subcommand == "reload":
        return _reload_hooks()
    if subcommand == "logs":
        return _view_logs(subargs)
    if subcommand == "events":
        return _list_events()
    if subcommand == "help":
        return _show_help()
    # Interactive menu
    return await _interactive_menu(session)


def _list_hooks() -> bool:
    """List all configured hooks."""
    hooks = _load_hooks()

    if not hooks:
        console.print()
        console.print("[yellow]No hooks configured[/yellow]")
        console.print()
        console.print("[dim]Use '/hooks add' to add a new hook[/dim]")
        console.print()
        return True

    table = Table(title="Configured Hooks", show_header=True, header_style="bold")
    table.add_column("#", style="dim", width=3)
    table.add_column("Command", style="cyan")
    table.add_column("Events", style="green")
    table.add_column("Status", style="yellow")

    for i, hook in enumerate(hooks, 1):
        command = " ".join(hook.get("command", []))
        events = ", ".join(hook.get("events", ["<all>"]))
        status = "✓" if hook.get("enabled", True) else "✗"
        table.add_row(str(i), command, events, status)

    console.print()
    console.print(table)
    console.print()
    console.print(f"[dim]{len(hooks)} hook(s) configured[/dim]")
    console.print()
    return True


async def _add_hook(session: PromptSession, args: list[str]) -> bool:
    """Add a new hook interactively."""
    console.print()
    console.print("[bold]Add New Hook[/bold]", style=COLORS["primary"])
    console.print()

    # Get command
    if args:
        command_str = " ".join(args)
    else:
        console.print("[dim]Enter the command to execute (e.g., 'python /path/to/script.py')[/dim]")
        command_str = (await session.prompt_async("Command: ")).strip()

    if not command_str:
        console.print("[red]✗ Command is required[/red]")
        return True

    # Validate command before splitting
    _SHELL_METACHARACTERS = set("`$|;&")
    for c in _SHELL_METACHARACTERS:
        if c in command_str:
            console.print(f"[red]✗ Shell metacharacter '{c}' not allowed in command[/red]")
            return True

    command = command_str.split()

    # Validate the binary exists
    binary = command[0]
    if "/" in binary and not Path(binary).is_file():
        console.print(f"[red]✗ Command binary not found: {binary}[/red]")
        return True
    if "/" not in binary and not shutil.which(binary):
        console.print(f"[red]✗ Command not found on PATH: {binary}[/red]")
        console.print("[dim]Install the tool or use an absolute path[/dim]")
        return True

    # Get events
    console.print()
    console.print("[dim]Enter events to subscribe to (comma-separated), or press Enter for all events[/dim]")
    console.print(f"[dim]Available events: {', '.join([e for e in dir(HookEvent) if not e.startswith('_')])}[/dim]")

    events_str = (await session.prompt_async("Events: ")).strip()

    if events_str:
        events = [e.strip() for e in events_str.split(",")]
        # Validate events
        valid_events = {e for e in dir(HookEvent) if not e.startswith("_")}
        invalid_events = [e for e in events if e not in valid_events]

        if invalid_events:
            console.print(f"[red]✗ Invalid events: {', '.join(invalid_events)}[/red]")
            console.print(f"[dim]Valid events: {', '.join(valid_events)}[/dim]")
            return True
    else:
        events = []

    # Load existing hooks
    hooks = _load_hooks()

    # Add new hook
    new_hook = {
        "command": command,
        "events": events,
        "enabled": True
    }

    hooks.append(new_hook)

    # Save hooks
    if _save_hooks(hooks):
        console.print()
        console.print("[green]✓ Hook added successfully[/green]")
        console.print(f"[dim]Command: {' '.join(command)}[/dim]")
        if events:
            console.print(f"[dim]Events: {', '.join(events)}[/dim]")
        else:
            console.print("[dim]Events: <all>[/dim]")
        console.print()
    else:
        console.print("[red]✗ Failed to save hook configuration[/red]")

    return True


async def _remove_hook(session: PromptSession, args: list[str]) -> bool:
    """Remove a hook by index."""
    hooks = _load_hooks()

    if not hooks:
        console.print()
        console.print("[yellow]No hooks configured[/yellow]")
        return True

    # Get hook index
    if args:
        try:
            index = int(args[0]) - 1
        except ValueError:
            console.print("[red]✗ Invalid hook number[/red]")
            return True
    else:
        console.print()
        console.print("[bold]Remove Hook[/bold]", style=COLORS["primary"])
        console.print()

        # Show hooks
        _list_hooks()

        index_str = (await session.prompt_async("Enter hook number to remove: ")).strip()

        try:
            index = int(index_str) - 1
        except ValueError:
            console.print("[red]✗ Invalid hook number[/red]")
            return True

    if index < 0 or index >= len(hooks):
        console.print(f"[red]✗ Hook {index + 1} does not exist[/red]")
        return True

    # Remove hook
    removed_hook = hooks.pop(index)

    # Save hooks
    if _save_hooks(hooks):
        console.print()
        console.print("[green]✓ Hook removed successfully[/green]")
        console.print(f"[dim]Removed: {' '.join(removed_hook.get('command', []))}[/dim]")
        console.print()
    else:
        console.print("[red]✗ Failed to save hook configuration[/red]")

    return True


async def _enable_hook(session: PromptSession, args: list[str]) -> bool:
    """Enable a hook by index."""
    return await _toggle_hook(session, args, enabled=True)


async def _disable_hook(session: PromptSession, args: list[str]) -> bool:
    """Disable a hook by index."""
    return await _toggle_hook(session, args, enabled=False)


async def _toggle_hook(session: PromptSession, args: list[str], enabled: bool) -> bool:
    """Toggle hook enabled/disabled status."""
    hooks = _load_hooks()

    if not hooks:
        console.print()
        console.print("[yellow]No hooks configured[/yellow]")
        return True

    # Get hook index
    if args:
        try:
            index = int(args[0]) - 1
        except ValueError:
            console.print("[red]✗ Invalid hook number[/red]")
            return True
    else:
        console.print()
        action = "Enable" if enabled else "Disable"
        console.print(f"[bold]{action} Hook[/bold]", style=COLORS["primary"])
        console.print()

        # Show hooks
        _list_hooks()

        index_str = (await session.prompt_async(f"Enter hook number to {action.lower()}: ")).strip()

        try:
            index = int(index_str) - 1
        except ValueError:
            console.print("[red]✗ Invalid hook number[/red]")
            return True

    if index < 0 or index >= len(hooks):
        console.print(f"[red]✗ Hook {index + 1} does not exist[/red]")
        return True

    # Toggle hook
    hooks[index]["enabled"] = enabled

    # Save hooks
    if _save_hooks(hooks):
        action = "enabled" if enabled else "disabled"
        console.print()
        console.print(f"[green]✓ Hook {action} successfully[/green]")
        console.print()
    else:
        console.print("[red]✗ Failed to save hook configuration[/red]")

    return True


async def _test_hook(session: PromptSession, args: list[str]) -> bool:
    """Test a hook by firing a test event."""
    hooks = _load_hooks()

    if not hooks:
        console.print()
        console.print("[yellow]No hooks configured[/yellow]")
        return True

    # Get hook index
    if args:
        try:
            index = int(args[0]) - 1
        except ValueError:
            console.print("[red]✗ Invalid hook number[/red]")
            return True
    else:
        console.print()
        console.print("[bold]Test Hook[/bold]", style=COLORS["primary"])
        console.print()

        # Show hooks
        _list_hooks()

        index_str = (await session.prompt_async("Enter hook number to test: ")).strip()

        try:
            index = int(index_str) - 1
        except ValueError:
            console.print("[red]✗ Invalid hook number[/red]")
            return True

    if index < 0 or index >= len(hooks):
        console.print(f"[red]✗ Hook {index + 1} does not exist[/red]")
        return True

    # Test hook
    hook = hooks[index]
    command = hook.get("command", [])

    console.print()
    console.print(f"[bold]Testing hook {index + 1}:[/bold] {' '.join(command)}")
    console.print("[dim]Sending test event...[/dim]")
    console.print()

    # Import here to avoid circular dependency

    from novacode_cli.hooks import dispatch_hook

    # Fire test event
    test_payload = {
        "test": True,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "message": "This is a test event"
    }

    try:
        await dispatch_hook("test", test_payload)
        console.print("[green]✓ Test event fired successfully[/green]")
        console.print("[dim]Check hook logs for output[/dim]")
        console.print()
    except Exception as e:
        console.print(f"[red]✗ Test failed: {e}[/red]")
        console.print()

    return True


def _reload_hooks() -> bool:
    """Reload hooks configuration from disk."""
    reload_hooks()
    console.print()
    console.print("[green]✓ Hooks configuration reloaded[/green]")
    console.print()
    return True


def _view_logs(args: list[str]) -> bool:
    """View hook logs."""
    log_dir = HOOKS_DIR / "logs"

    if not log_dir.exists():
        console.print()
        console.print("[yellow]No logs directory found[/yellow]")
        console.print("[dim]Logs will appear here after hooks are executed[/dim]")
        console.print()
        return True

    # Get log file
    log_file = log_dir / "hooks.log"

    if not log_file.exists():
        console.print()
        console.print("[yellow]No hook logs found[/yellow]")
        console.print("[dim]Logs will appear after hooks are executed[/dim]")
        console.print()
        return True

    # Read last N lines
    try:
        lines_count = int(args[0]) if args else 20
    except ValueError:
        lines_count = 20

    try:
        with open(log_file) as f:
            lines = f.readlines()
            last_lines = lines[-lines_count:]

        console.print()
        console.print(f"[bold]Last {lines_count} log entries:[/bold]")
        console.print()

        for line in last_lines:
            console.print(line.rstrip())

        console.print()
        console.print(f"[dim]{log_file}[/dim]")
        console.print()
    except Exception as e:
        console.print(f"[red]✗ Failed to read logs: {e}[/red]")

    return True


def _list_events() -> bool:
    """List all available hook events."""
    console.print()
    console.print("[bold]Available Hook Events[/bold]", style=COLORS["primary"])
    console.print()

    # Session events
    console.print("[bold]Session Events:[/bold]")
    console.print(f"  • {HookEvent.SESSION_START} - New session begins")
    console.print(f"  • {HookEvent.SESSION_END} - Session ends")
    console.print(f"  • {HookEvent.SESSION_SAVE} - Session saved")
    console.print(f"  • {HookEvent.SESSION_CONTINUE} - Session continued")
    console.print()

    # Model events
    console.print("[bold]Model Events:[/bold]")
    console.print(f"  • {HookEvent.MODEL_SWITCH} - Model switched")
    console.print()

    # Tool events
    console.print("[bold]Tool Events:[/bold]")
    console.print(f"  • {HookEvent.TOOL_CALL} - Tool invoked")
    console.print(f"  • {HookEvent.TOOL_RESULT} - Tool completed")
    console.print()

    # Message events
    console.print("[bold]Message Events:[/bold]")
    console.print(f"  • {HookEvent.AGENT_MESSAGE} - Agent sends message")
    console.print(f"  • {HookEvent.USER_MESSAGE} - User sends message")
    console.print()

    # Error events
    console.print("[bold]Error Events:[/bold]")
    console.print(f"  • {HookEvent.ERROR} - Error occurred")
    console.print()

    # Lifecycle events
    console.print("[bold]Lifecycle Events:[/bold]")
    console.print(f"  • {HookEvent.PROMPT_DECOMPOSE} - Prompt decomposed into sub-prompts")
    console.print(f"  • {HookEvent.REMOTE_MESSAGE} - Remote (Discord/Telegram) message received")
    console.print(f"  • {HookEvent.CONTEXT_WARNING} - Context usage warning/critical")
    console.print(f"  • {HookEvent.COMPACT} - Conversation compacted")
    console.print(f"  • {HookEvent.INIT_COMPLETE} - /init pipeline completed")
    console.print()

    console.print("[dim]Leave 'events' empty to subscribe to all events[/dim]")
    console.print()

    return True


def _show_help() -> bool:
    """Show hooks command help."""
    console.print()
    console.print("[bold]Hooks Command Help[/bold]", style=COLORS["primary"])
    console.print()
    console.print("Usage: /hooks [command] [arguments]")
    console.print()
    console.print("[bold]Commands:[/bold]")
    console.print("  list              List all configured hooks")
    console.print("  add               Add a new hook interactively")
    console.print("  remove <#>        Remove hook by number")
    console.print("  enable <#>        Enable a hook")
    console.print("  disable <#>       Disable a hook")
    console.print("  test <#>          Test a hook with a test event")
    console.print("  reload            Reload hooks configuration")
    console.print("  logs [N]          View last N log entries (default: 20)")
    console.print("  events            List all available events")
    console.print("  help              Show this help message")
    console.print()
    console.print("[bold]Examples:[/bold]")
    console.print("  /hooks list                    # List all hooks")
    console.print("  /hooks add                     # Add a hook interactively")
    console.print("  /hooks remove 1                # Remove hook #1")
    console.print("  /hooks test 2                  # Test hook #2")
    console.print("  /hooks logs 50                 # View last 50 log entries")
    console.print()
    console.print(f"[dim]Configuration file: {HOOKS_FILE}[/dim]")
    console.print(f"[dim]Logs directory: {HOOKS_DIR / 'logs'}[/dim]")
    console.print()

    return True


async def _interactive_menu(session: PromptSession) -> bool:
    """Show interactive hooks menu."""
    console.print()
    console.print("[bold]Hook Management[/bold]", style=COLORS["primary"])
    console.print()

    console.print("What would you like to do?")
    console.print("  1. List configured hooks")
    console.print("  2. Add a new hook")
    console.print("  3. Remove a hook")
    console.print("  4. Enable/disable a hook")
    console.print("  5. Test a hook")
    console.print("  6. Reload configuration")
    console.print("  7. View logs")
    console.print("  8. List available events")
    console.print("  9. Cancel")
    console.print()

    choice = (await session.prompt_async("Choose (1-9): ")).strip()

    if choice == "1":
        return _list_hooks()
    if choice == "2":
        return await _add_hook(session, [])
    if choice == "3":
        return await _remove_hook(session, [])
    if choice == "4":
        console.print()
        console.print("[bold]Toggle Hook[/bold]")
        console.print("  1. Enable a hook")
        console.print("  2. Disable a hook")
        console.print()
        toggle_choice = (await session.prompt_async("Choose (1-2): ")).strip()

        if toggle_choice == "1":
            return await _enable_hook(session, [])
        if toggle_choice == "2":
            return await _disable_hook(session, [])
        console.print("[red]✗ Invalid choice[/red]")
        return True
    if choice == "5":
        return await _test_hook(session, [])
    if choice == "6":
        return _reload_hooks()
    if choice == "7":
        return _view_logs([])
    if choice == "8":
        return _list_events()
    if choice == "9":
        console.print("[dim]Cancelled[/dim]")
        return True
    console.print("[red]✗ Invalid choice[/red]")
    return True


def _save_hooks(hooks: list[dict]) -> bool:
    """Save hooks configuration to disk.
    
    Args:
        hooks: List of hook configurations
        
    Returns:
        True if saved successfully, False otherwise
    """
    try:
        # Ensure directory exists
        HOOKS_DIR.mkdir(parents=True, exist_ok=True)

        # Write configuration
        config = {"hooks": hooks}
        HOOKS_FILE.write_text(json.dumps(config, indent=2))

        # Reload hooks
        reload_hooks()

        return True
    except Exception as e:
        console.print(f"[red]✗ Failed to save hooks: {e}[/red]")
        return False


__all__ = ["handle_hooks_command"]


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

def register_commands(registry) -> None:
    from novacode_cli.commands import CommandContext

    async def _handle(ctx: CommandContext) -> bool:
        return await handle_hooks_command(cmd_args=ctx.cmd_args)

    registry.register("hooks", _handle)

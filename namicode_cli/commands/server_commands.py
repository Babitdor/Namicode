"""Handlers for server-related commands: /servers, /tests, /kill."""

import webbrowser
from pathlib import Path
from prompt_toolkit import PromptSession
from rich.console import Console
from rich.table import Table
from rich.text import Text

from namicode_cli.config.config import COLORS, console
from namicode_cli.process_manager import ProcessManager
from namicode_cli.server_runner.dev_server import list_servers, stop_server
from namicode_cli.server_runner.test_runner import (
    detect_test_framework,
    get_default_test_command,
    run_tests,
)


async def handle_servers_command(session_state) -> bool:
    """Handle /servers - list and manage dev servers.

    Args:
        session_state: Current session state

    Returns:
        True (command always handled)
    """
    ps = PromptSession()

    console.print()
    console.print("[bold]Dev Server Management[/bold]", style=COLORS["primary"])
    console.print()

    # Get running servers (including external servers not managed by CLI)
    servers = list_servers(include_external=True)

    if not servers:
        console.print("[yellow]No dev servers running[/yellow]")
        console.print("[dim]Use the start_dev_server tool to start a server[/dim]")
        console.print()
        return True

    # Display servers in a table
    table = Table(show_header=True, header_style="bold")
    table.add_column("PID", style="dim")
    table.add_column("Name")
    table.add_column("URL")
    table.add_column("Status")
    table.add_column("Command", style="dim")

    # Separate managed and external servers for display
    managed_servers = []
    external_servers = []
    for server in servers:
        if server.pid == 0 and "external" in server.name:
            external_servers.append(server)
        else:
            managed_servers.append(server)

    for server in managed_servers:
        status_style = "green" if server.status.value == "healthy" else "yellow"
        table.add_row(
            str(server.pid),
            server.name,
            server.url,
            f"[{status_style}]{server.status.value}[/{status_style}]",
            server.command[:40] + "..." if len(server.command) > 40 else server.command,
        )

    for server in external_servers:
        status_style = "green" if server.status.value == "healthy" else "yellow"
        table.add_row(
            "[dim]external[/dim]",
            f"[dim]{server.name}[/dim]",
            server.url,
            f"[{status_style}]{server.status.value}[/{status_style}]",
            "[dim](not managed by CLI)[/dim]",
        )

    console.print(table)
    if external_servers:
        console.print("[dim]Note: External servers (marked 'external') were started outside this CLI and cannot be stopped here.[/dim]")
    console.print()

    # Show menu
    console.print("What would you like to do?", style=COLORS["primary"])
    console.print("  1. Open server in browser")
    console.print("  2. Stop a server (managed only)")
    console.print("  3. Stop all servers (managed only)")
    console.print("  4. Cancel")
    console.print()

    choice = (await ps.prompt_async("Choose (1-4): ")).strip()

    if choice == "1":
        # Open in browser
        if len(servers) == 1:
            webbrowser.open(servers[0].url)
            console.print(f"[green]✓ Opened {servers[0].url} in browser[/green]")
        else:
            console.print()
            console.print(
                "[bold]Select server to open:[/bold]", style=COLORS["primary"]
            )
            for i, server in enumerate(servers, 1):
                console.print(f"  {i}. {server.name} ({server.url})")
            console.print()
            server_choice = (await ps.prompt_async("Choose server number: ")).strip()
            try:
                idx = int(server_choice) - 1
                if 0 <= idx < len(servers):
                    webbrowser.open(servers[idx].url)
                    console.print(
                        f"[green]✓ Opened {servers[idx].url} in browser[/green]"
                    )
                else:
                    console.print("[yellow]Invalid choice[/yellow]")
            except ValueError:
                console.print("[yellow]Invalid choice[/yellow]")

    elif choice == "2":
        # Stop a server
        if len(servers) == 1:
            result = await stop_server(pid=servers[0].pid)
            if result:
                console.print(
                    f"[green]✓ Stopped server '{servers[0].name}' (PID: {servers[0].pid})[/green]"
                )
            else:
                console.print("[red]Failed to stop server[/red]")
        else:
            # Only show managed servers for stopping
            stoppable_servers = [s for s in servers if s.pid > 0]
            if not stoppable_servers:
                console.print("[yellow]No managed servers to stop[/yellow]")
                console.print("[dim]External servers must be stopped manually[/dim]")
            else:
                console.print()
                console.print(
                    "[bold]Select server to stop:[/bold]", style=COLORS["primary"]
                )
                for i, server in enumerate(stoppable_servers, 1):
                    console.print(f"  {i}. {server.name} (PID: {server.pid})")
                console.print()
                server_choice = (await ps.prompt_async("Choose server number: ")).strip()
                try:
                    idx = int(server_choice) - 1
                    if 0 <= idx < len(stoppable_servers):
                        result = await stop_server(pid=stoppable_servers[idx].pid)
                        if result:
                            console.print(
                                f"[green]✓ Stopped server '{stoppable_servers[idx].name}'[/green]"
                            )
                        else:
                            console.print("[red]Failed to stop server[/red]")
                    else:
                        console.print("[yellow]Invalid choice[/yellow]")
                except ValueError:
                    console.print("[yellow]Invalid choice[/yellow]")

    elif choice == "3":
        # Stop all managed servers
        manager = ProcessManager.get_instance()
        count = await manager.stop_all()
        if count > 0:
            console.print(f"[green]✓ Stopped {count} managed server(s)[/green]")
        else:
            console.print("[yellow]No managed servers to stop[/yellow]")
        if external_servers:
            console.print(f"[dim]Note: {len(external_servers)} external server(s) still running[/dim]")

    console.print()
    return True


async def handle_tests_command(session_state, cmd_args: str | None = None) -> bool:
    """Handle /tests - run project tests.

    Args:
        session_state: Current session state
        cmd_args: Optional test command arguments

    Returns:
        True (command always handled)
    """
    console.print()
    console.print("[bold]Running Tests[/bold]", style=COLORS["primary"])
    console.print()

    working_dir = str(Path.cwd())

    # Detect framework if no command specified
    if not cmd_args:
        framework = detect_test_framework(working_dir)
        command = get_default_test_command(framework)

        if not command:
            console.print("[yellow]Could not auto-detect test framework[/yellow]")
            console.print(
                "[dim]Specify a command: /tests pytest or /tests npm test[/dim]"
            )
            console.print()
            return True

        console.print(f"[dim]Detected framework: {framework.value}[/dim]")
        console.print(f"[dim]Running: {command}[/dim]")
    else:
        command = cmd_args.strip()
        console.print(f"[dim]Running: {command}[/dim]")

    console.print()

    # Stream output callback
    def output_callback(line: str) -> None:
        console.print(f"[dim]{line}[/dim]", markup=False)

    # Run tests with streaming output
    result = await run_tests(
        command=command,
        working_dir=working_dir,
        output_callback=output_callback,
    )

    console.print()

    # Show summary
    if result.success:
        console.print("[green]✓ Tests passed![/green]")
    else:
        console.print("[red]✗ Tests failed[/red]")

    # Show statistics if available
    stats_parts = []
    if result.tests_run is not None:
        stats_parts.append(f"{result.tests_run} tests")
    if result.tests_passed is not None:
        stats_parts.append(f"{result.tests_passed} passed")
    if result.tests_failed is not None:
        stats_parts.append(f"{result.tests_failed} failed")
    if result.duration_seconds is not None:
        stats_parts.append(f"{result.duration_seconds:.2f}s")

    if stats_parts:
        console.print(f"[dim]{', '.join(stats_parts)}[/dim]")

    if result.error:
        console.print(f"[red]Error: {result.error}[/red]")

    console.print()
    return True


async def handle_kill_command(session_state, cmd_args: str | None = None) -> bool:
    """Handle /kill - kill a running process by PID or name.

    Args:
        session_state: Current session state
        cmd_args: Optional PID or name to kill

    Returns:
        True (command always handled)
    """
    ps = PromptSession()
    manager = ProcessManager.get_instance()

    console.print()

    # If argument provided, try to kill directly
    if cmd_args:
        arg = cmd_args.strip()

        # Try as PID first
        try:
            pid = int(arg)
            result = await manager.stop_process(pid)
            if result:
                console.print(f"[green]✓ Killed process {pid}[/green]")
            else:
                console.print(f"[yellow]No process found with PID {pid}[/yellow]")
            console.print()
            return True
        except ValueError:
            pass

        # Try as name
        result = await manager.stop_by_name(arg)
        if result:
            console.print(f"[green]✓ Killed process '{arg}'[/green]")
        else:
            console.print(f"[yellow]No process found with name '{arg}'[/yellow]")
        console.print()
        return True

    # No argument - show list and let user choose
    processes = manager.list_processes(alive_only=True)

    if not processes:
        console.print("[yellow]No managed processes running[/yellow]")
        console.print()
        return True

    console.print("[bold]Running Processes[/bold]", style=COLORS["primary"])
    console.print()

    for i, info in enumerate(processes, 1):
        port_info = f" (port {info.port})" if info.port else ""
        console.print(f"  {i}. [{info.pid}] {info.name}{port_info}")
        console.print(
            f"     [dim]{info.command[:60]}...[/dim]"
            if len(info.command) > 60
            else f"     [dim]{info.command}[/dim]"
        )

    console.print()
    choice = (await ps.prompt_async("Enter number to kill (or 'cancel'): ")).strip()

    if choice.lower() == "cancel":
        console.print("[dim]Cancelled[/dim]")
        console.print()
        return True

    try:
        idx = int(choice) - 1
        if 0 <= idx < len(processes):
            info = processes[idx]
            result = await manager.stop_process(info.pid)
            if result:
                console.print(
                    f"[green]✓ Killed '{info.name}' (PID: {info.pid})[/green]"
                )
            else:
                console.print("[red]Failed to kill process[/red]")
        else:
            console.print("[yellow]Invalid choice[/yellow]")
    except ValueError:
        console.print("[yellow]Invalid choice[/yellow]")

    console.print()
    return True
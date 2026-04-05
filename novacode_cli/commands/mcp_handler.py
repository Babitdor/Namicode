"""Handler for the /mcp command for MCP server management."""

import os

from prompt_toolkit import PromptSession
from rich.console import Console
from rich.text import Text

from novacode_cli.config.config import COLORS, console
from novacode_cli.mcp import presets as mcp_presets
from novacode_cli.mcp.config import MCPConfig, MCPServerConfig


async def handle_mcp_command() -> bool:
    """Handle the /mcp command for MCP server management.
    
    Returns:
        True (command always handled)
    """
    session = PromptSession()

    console.print()
    console.print("[bold]MCP Server Management[/bold]", style=COLORS["primary"])
    console.print()

    # Show menu
    console.print("What would you like to do?", style=COLORS["primary"])
    console.print("  1. List available MCP presets")
    console.print("  2. Install a preset MCP")
    console.print("  3. Add custom MCP")
    console.print("  4. List configured MCPs")
    console.print("  5. Remove an MCP")
    console.print("  6. Cancel")
    console.print()

    choice = (await session.prompt_async("Choose (1-6): ")).strip()

    if choice == "1":
        # List presets
        presets = mcp_presets.list_presets()
        console.print()
        console.print("[bold]Available MCP Presets:[/bold]", style=COLORS["primary"])
        console.print()
        for preset_id, preset in presets.items():
            console.print(f"  • [bold]{preset_id}[/bold]", style=COLORS["primary"])
            console.print(f"    {preset['name']}", style=COLORS["dim"])
            console.print(f"    {preset['description']}", style=COLORS["dim"])
            console.print()

    elif choice == "2":
        # Install preset
        presets = mcp_presets.list_presets()
        console.print()
        console.print("[bold]Available Presets:[/bold]", style=COLORS["primary"])
        for i, (preset_id, preset) in enumerate(presets.items(), 1):
            console.print(f"  {i}. {preset['name']} ({preset_id})")
            console.print(f"     {preset['description']}", style=COLORS["dim"])

        console.print()
        preset_choice = (
            await session.prompt_async("Choose preset number (or 'cancel'): ")
        ).strip()

        if preset_choice.lower() != "cancel":
            try:
                preset_idx = int(preset_choice) - 1
                preset_items = list(presets.items())
                if 0 <= preset_idx < len(preset_items):
                    preset_id, preset = preset_items[preset_idx]

                    # Collect user inputs for configuration
                    user_inputs = {}

                    if "setup_prompt" in preset:
                        value = (
                            await session.prompt_async(f"{preset['setup_prompt']} ")
                        ).strip()
                        user_inputs[preset["setup_key"]] = value

                    if "setup_secondary_prompt" in preset:
                        value = (
                            await session.prompt_async(
                                f"{preset['setup_secondary_prompt']} "
                            )
                        ).strip()
                        user_inputs[preset["setup_secondary_key"]] = value

                    # Create config from preset
                    config = mcp_presets.create_config_from_preset(
                        preset_id, user_inputs
                    )

                    if config:
                        # Save to MCP config
                        mcp_config = MCPConfig()
                        mcp_config.add_server(preset_id, config)

                        console.print()
                        console.print(
                            f"✓ MCP '{preset['name']}' installed successfully!",
                            style=COLORS["primary"],
                        )
                        console.print(
                            f"   Configuration saved to: {mcp_config.config_path}",
                            style=COLORS["dim"],
                        )
                        console.print()
                        console.print(
                            "[dim]Restart your session for changes to take effect.[/dim]"
                        )
                else:
                    console.print()
                    console.print("[yellow]Invalid choice[/yellow]")
            except (ValueError, IndexError):
                console.print()
                console.print("[yellow]Invalid choice[/yellow]")

    elif choice == "3":
        # Add custom MCP
        console.print()
        console.print("[bold]Add Custom MCP[/bold]", style=COLORS["primary"])
        console.print()

        name = (
            await session.prompt_async("Server name (e.g., my-custom-mcp): ")
        ).strip()
        if not name:
            console.print("[yellow]Cancelled[/yellow]")
            return True

        console.print()
        console.print("Transport type:")
        console.print("  1. stdio (local command)")
        console.print("  2. HTTP (remote server)")
        transport_choice = (
            await session.prompt_async("Choose (1 or 2): ", default="1")
        ).strip()

        transport = "stdio" if transport_choice == "1" else "http"

        if transport == "stdio":
            command = (
                await session.prompt_async("Command to run (e.g., npx, python, node): ")
            ).strip()
            args_input = (
                await session.prompt_async(
                    "Arguments (space-separated, optional): ", default=""
                )
            ).strip()
            args = args_input.split() if args_input else []

            env_input = (
                await session.prompt_async(
                    "Environment variables (KEY=VALUE, comma-separated, optional): ",
                    default="",
                )
            ).strip()
            env = {}
            if env_input:
                for pair in env_input.split(","):
                    if "=" in pair:
                        key, value = pair.split("=", 1)
                        env[key.strip()] = value.strip()

            description = (
                await session.prompt_async("Description (optional): ", default="")
            ).strip()

            config = MCPServerConfig(
                transport="stdio",
                command=command,
                args=args,
                env=env,
                description=description or None,
            )
        else:
            url = (await session.prompt_async("Server URL: ")).strip()
            description = (
                await session.prompt_async("Description (optional): ", default="")
            ).strip()

            config = MCPServerConfig(
                transport="http",
                url=url,
                description=description or None,
            )

        mcp_config = MCPConfig()
        mcp_config.add_server(name, config)

        console.print()
        console.print(
            f"✓ Custom MCP '{name}' added successfully!",
            style=COLORS["primary"],
        )
        console.print(
            f"   Configuration saved to: {mcp_config.config_path}",
            style=COLORS["dim"],
        )
        console.print()
        console.print("[dim]Restart your session for changes to take effect.[/dim]")

    elif choice == "4":
        # List configured MCPs
        mcp_config = MCPConfig()
        servers = mcp_config.list_servers()

        console.print()
        if servers:
            # Get active servers from MCP middleware
            active_servers = set()
            try:
                from novacode_cli.mcp import get_shared_mcp_middleware
                
                # Get the middleware to check which servers are connected
                middleware = get_shared_mcp_middleware()
                
                # Extract server names from tools cache
                for tool_meta in middleware._tools_cache:
                    server_name = tool_meta.get("server")
                    if server_name:
                        active_servers.add(server_name)
            except Exception:
                # If middleware isn't initialized yet, just show all as inactive
                pass

            console.print(
                "[bold]Configured MCP Servers:[/bold]", style=COLORS["primary"]
            )
            console.print()
            for name, config in servers.items():
                # Show active indicator
                is_active = name in active_servers
                status_indicator = "[green]✓[/green]" if is_active else "[red]✗[/red]"
                status_text = "[green]active[/green]" if is_active else "[red]inactive[/red]"
                
                console.print(
                    f"  {status_indicator} [bold]{name}[/bold] ({status_text})",
                    style=COLORS["primary"],
                )
                console.print(f"    Transport: {config.transport}", style=COLORS["dim"])
                if config.transport == "http":
                    console.print(f"    URL: {config.url}", style=COLORS["dim"])
                elif config.transport == "stdio":
                    console.print(f"    Command: {config.command}", style=COLORS["dim"])
                    if config.args:
                        console.print(
                            f"    Args: {' '.join(config.args)}", style=COLORS["dim"]
                        )
                if config.description:
                    console.print(f"    {config.description}", style=COLORS["dim"])
                
                # Show tool count for active servers
                if is_active:
                    tool_count = sum(1 for t in middleware._tools_cache if t.get("server") == name)
                    console.print(f"    Tools: {tool_count}", style=COLORS["dim"])
                
                console.print()
        else:
            console.print("[yellow]No MCP servers configured[/yellow]")
            console.print("[dim]Use /mcp to install preset or custom MCP servers[/dim]")

    elif choice == "5":
        # Remove MCP
        mcp_config = MCPConfig()
        servers = mcp_config.list_servers()

        if not servers:
            console.print()
            console.print("[yellow]No MCP servers configured[/yellow]")
            return True

        console.print()
        console.print("[bold]Configured MCPs:[/bold]", style=COLORS["primary"])
        for i, name in enumerate(servers.keys(), 1):
            console.print(f"  {i}. {name}")

        console.print()
        remove_choice = (
            await session.prompt_async("Choose MCP to remove (or 'cancel'): ")
        ).strip()

        if remove_choice.lower() != "cancel":
            try:
                remove_idx = int(remove_choice) - 1
                server_names = list(servers.keys())
                if 0 <= remove_idx < len(server_names):
                    name = server_names[remove_idx]
                    if mcp_config.remove_server(name):
                        console.print()
                        console.print(
                            f"✓ MCP '{name}' removed successfully!",
                            style=COLORS["primary"],
                        )
                        console.print()
                        console.print(
                            "[dim]Restart your session for changes to take effect.[/dim]"
                        )
                else:
                    console.print()
                    console.print("[yellow]Invalid choice[/yellow]")
            except (ValueError, IndexError):
                console.print()
                console.print("[yellow]Invalid choice[/yellow]")

    console.print()
    return True

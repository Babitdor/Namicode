"""Handler for the /mcp command for MCP server management."""

import os

from prompt_toolkit import PromptSession
from rich.console import Console
from rich.text import Text

from novacode_cli.commands import CommandContext
from novacode_cli.commands.menu_helper import MenuOption, run_interactive_menu
from novacode_cli.config.config import COLORS, console
from novacode_cli.mcp import presets as mcp_presets
from novacode_cli.mcp.config import MCPConfig, MCPServerConfig


async def handle_mcp_command(ctx: CommandContext) -> bool:
    """Handle the /mcp command — delegates to interactive menu."""
    options = [
        MenuOption("List available MCP presets", _action_list_presets),
        MenuOption("Install a preset MCP", _action_install_preset),
        MenuOption("Add custom MCP", _action_add_custom),
        MenuOption("List configured MCPs", _action_list_configured),
        MenuOption("Remove an MCP", _action_remove_mcp),
    ]
    return await run_interactive_menu("MCP Server Management", options, ctx)


async def _action_list_presets(
    ctx: CommandContext, session: PromptSession,
) -> bool:
    """Option 1: list available MCP presets."""
    presets = mcp_presets.list_presets()
    console.print()
    console.print("[bold]Available MCP Presets:[/bold]", style=COLORS["primary"])
    console.print()
    for preset_id, preset in presets.items():
        console.print(f"  • [bold]{preset_id}[/bold]", style=COLORS["primary"])
        console.print(f"    {preset['name']}", style=COLORS["dim"])
        console.print(f"    {preset['description']}", style=COLORS["dim"])
        console.print()
    return True


async def _action_install_preset(
    ctx: CommandContext, session: PromptSession,
) -> bool:
    """Option 2: install a preset MCP."""
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

                config = mcp_presets.create_config_from_preset(
                    preset_id, user_inputs
                )

                if config:
                    mcp_config = MCPConfig()
                    await mcp_config.add_server_async(preset_id, config)

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
    return True


async def _action_add_custom(
    ctx: CommandContext, session: PromptSession,
) -> bool:
    """Option 3: add a custom MCP server."""
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
    await mcp_config.add_server_async(name, config)

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
    return True


async def _action_list_configured(
    ctx: CommandContext, session: PromptSession,
) -> bool:
    """Option 4: list configured MCPs."""
    mcp_config = MCPConfig()
    servers = mcp_config.list_servers()

    console.print()
    if servers:
        active_servers = set()
        try:
            from novacode_cli.mcp import get_shared_mcp_middleware

            middleware = get_shared_mcp_middleware()

            if not middleware._tools_discovered:
                middleware._discover_tools_sync()

            for tool_meta in middleware._tools_cache:
                server_name = tool_meta.get("server")
                if server_name:
                    active_servers.add(server_name)
        except Exception:
            pass

        console.print(
            "[bold]Configured MCP Servers:[/bold]", style=COLORS["primary"]
        )
        console.print()
        for name, config in servers.items():
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

            if is_active:
                tool_count = sum(1 for t in middleware._tools_cache if t.get("server") == name)
                console.print(f"    Tools: {tool_count}", style=COLORS["dim"])

            console.print()
    else:
        console.print("[yellow]No MCP servers configured[/yellow]")
        console.print("[dim]Use /mcp to install preset or custom MCP servers[/dim]")
    return True


async def _action_remove_mcp(
    ctx: CommandContext, session: PromptSession,
) -> bool:
    """Option 5: remove an MCP server."""
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
    return True


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

def register_commands(registry) -> None:
    from novacode_cli.commands import CommandContext

    async def _handle(ctx: CommandContext) -> bool:
        return await handle_mcp_command(ctx)

    registry.register("mcp", _handle)

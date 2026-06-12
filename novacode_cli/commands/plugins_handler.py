"""Handler for the /plugins command for Nova plugin management.

Supports listing installed plugins, enabling/disabling them, and showing
details about what each plugin provides.
"""

from __future__ import annotations

from prompt_toolkit import PromptSession

from novacode_cli.commands import CommandContext
from novacode_cli.commands.menu_helper import MenuOption, run_interactive_menu
from novacode_cli.config.config import COLORS, console
from novacode_cli.plugins.loader import (
    discover_plugins,
    enable_plugin,
    disable_plugin,
    list_enabled_plugins,
)


async def handle_plugins_command(ctx: CommandContext) -> bool:
    """Handle the /plugins command — delegates to interactive menu."""
    options = [
        MenuOption("List installed plugins", _action_list_plugins),
        MenuOption("Enable a plugin", _action_enable_plugin),
        MenuOption("Disable a plugin", _action_disable_plugin),
        MenuOption("Show plugin details", _action_show_details),
    ]
    return await run_interactive_menu("Nova Plugin Management", options, ctx)


async def _action_list_plugins(
    ctx: CommandContext, session: PromptSession,
) -> bool:
    """Option 1: list installed plugins."""
    _list_plugins(discover_plugins(), set(list_enabled_plugins()))
    return True


async def _action_enable_plugin(
    ctx: CommandContext, session: PromptSession,
) -> bool:
    """Option 2: enable a plugin."""
    all_plugins = discover_plugins()
    name = (
        await session.prompt_async(
            "Plugin name to enable (or press Enter to cancel): "
        )
    ).strip()
    names = {n for n, _ in all_plugins}
    if name and name in names:
        ok = enable_plugin(name)
        if ok:
            console.print()
            console.print(
                f"✓ Plugin '[bold]{name}[/bold]' enabled.",
                style=COLORS["primary"],
            )
        else:
            console.print()
            console.print(
                f"[yellow]Plugin '{name}' is already enabled.[/yellow]"
            )
        console.print(
            "[dim]Restart your session for changes to take effect.[/dim]"
        )
    elif name:
        console.print(
            f"[yellow]Unknown plugin '{name}'. Use option 1 to list available plugins.[/yellow]"
        )
    return True


async def _action_disable_plugin(
    ctx: CommandContext, session: PromptSession,
) -> bool:
    """Option 3: disable a plugin."""
    all_plugins = discover_plugins()
    name = (
        await session.prompt_async(
            "Plugin name to disable (or press Enter to cancel): "
        )
    ).strip()
    names = {n for n, _ in all_plugins}
    if name and name in names:
        ok = disable_plugin(name)
        if ok:
            console.print()
            console.print(
                f"✗ Plugin '[bold]{name}[/bold]' disabled.",
                style=COLORS["primary"],
            )
        else:
            console.print()
            console.print(
                f"[yellow]Plugin '{name}' was not enabled.[/yellow]"
            )
        console.print(
            "[dim]Restart your session for changes to take effect.[/dim]"
        )
    elif name:
        console.print(
            f"[yellow]Unknown plugin '{name}'. Use option 1 to list available plugins.[/yellow]"
        )
    return True


async def _action_show_details(
    ctx: CommandContext, session: PromptSession,
) -> bool:
    """Option 4: show plugin details."""
    all_plugins = discover_plugins()
    enabled = set(list_enabled_plugins())
    name = (
        await session.prompt_async(
            "Plugin name to inspect (or press Enter to cancel): "
        )
    ).strip()
    if name:
        match = [s for n, s in all_plugins if n == name]
        if match:
            _show_plugin_detail(name, match[0], name in enabled)
        else:
            console.print(
                f"[yellow]Unknown plugin '{name}'. Use option 1 to list available plugins.[/yellow]"
            )
    return True


def _list_plugins(
    all_plugins: list[tuple[str, dict]], enabled: set[str]
) -> None:
    """Print a table of all discovered Nova plugins."""
    console.print()
    console.print(
        "[bold]Installed Nova Plugins[/bold]", style=COLORS["primary"]
    )
    console.print()
    for pkg_name, spec in all_plugins:
        status = "[green]✓ enabled[/green]" if pkg_name in enabled else "[dim]disabled[/dim]"
        mid_count = len(spec.get("middleware", []))
        tool_count = len(spec.get("tools", []))
        desc = spec.get("description", "")
        console.print(
            f"  • [bold]{pkg_name}[/bold] — {status}"
        )
        if desc:
            console.print(f"    [dim]{desc}[/dim]")
        console.print(
            f"    [dim]{mid_count} middleware, {tool_count} tools[/dim]"
        )
        console.print()


def _show_plugin_detail(
    pkg_name: str, spec: dict, enabled: bool
) -> None:
    """Print detailed information about a single plugin."""
    from rich.table import Table

    status = "Enabled" if enabled else "Disabled"
    console.print()
    console.print(
        f"[bold]Plugin: {pkg_name}[/bold]  [dim]({status})[/dim]",
        style=COLORS["primary"],
    )
    console.print()

    desc = spec.get("description") or "(no description)"
    console.print(f"  [bold]Description:[/bold] {desc}")
    console.print()

    # Middleware details — MiddlewareSlot instances
    for i, mw_slot in enumerate(spec.get("middleware", [])):
        instance = mw_slot.get("instance")
        slot = mw_slot.get("slot", "tail")
        mid_name = type(instance).__name__ if instance else f"Middleware #{i+1}"
        console.print(f"  [bold]Middleware #{i+1}:[/bold] {mid_name}")
        console.print(f"    Slot: {slot}")
        if instance and hasattr(instance, "__doc__") and instance.__doc__:
            doc = instance.__doc__.strip().split("\n")[0]
            console.print(f"    Description: {doc}")
        console.print()

    # Tool details — BaseTool instances
    for i, tool in enumerate(spec.get("tools", [])):
        tool_name = getattr(tool, "name", f"Tool #{i+1}")
        tool_desc = getattr(tool, "description", "")
        console.print(f"  [bold]Tool #{i+1}:[/bold] {tool_name}")
        if tool_desc:
            console.print(f"    Description: {tool_desc}")
        console.print()

    # Hooks
    hooks = spec.get("hooks") or {}
    if hooks:
        console.print("  [bold]Lifecycle Hooks:[/bold]")
        for hook_name in hooks:
            console.print(f"    • {hook_name}")
        console.print()


def register_commands(registry):
    """Register /plugin and /plugins."""
    from novacode_cli.commands import CommandContext

    async def _plugins_handler(ctx: CommandContext) -> str | bool:
        return await handle_plugins_command(ctx)

    registry.register("plugin", _plugins_handler)
    registry.register("plugins", _plugins_handler)
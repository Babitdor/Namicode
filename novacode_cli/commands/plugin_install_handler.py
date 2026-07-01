"""`/plugins` — install/list/remove Claude-compatible plugins.

    /plugins install <owner/repo | git-url | local-dir>
    /plugins list
    /plugins remove <name>

Skills and MCP servers wire in automatically; commands/agents/hooks are
detected and shown but not yet loaded (no md-loaders yet).
"""

from __future__ import annotations

import re

from novacode_cli.commands import CommandContext
from novacode_cli.config.config import COLORS, console
from novacode_cli.plugins import claude_plugins as cp
from novacode_cli.plugins import marketplaces as mp

_MARKETPLACE_SPEC = re.compile(r"^[\w.-]+@[\w.-]+$")  # plugin@marketplace (not git@…)


async def handle_plugin_install_command(ctx: CommandContext) -> bool:
    parts = (ctx.cmd_args or "").strip().split(maxsplit=1)
    sub = parts[0] if parts else "list"
    arg = parts[1].strip() if len(parts) > 1 else ""

    if sub == "install":
        if not arg:
            console.print(
                "[yellow]Usage: /plugins install <owner/repo | git-url | dir | plugin@marketplace>[/yellow]"
            )
            return True
        try:
            with console.status(f"Installing {arg}…"):
                name = mp.install_plugin(arg) if _MARKETPLACE_SPEC.match(arg) else cp.install(arg)
        except (ValueError, RuntimeError) as e:
            console.print(f"[red]Install failed:[/red] {e}")
            return True
        console.print(f"[green]✓ Installed[/green] [bold]{name}[/bold]")
        _print_components(cp.plugin_components(name))
        console.print("[dim]Restart Nova to activate.[/dim]")

    elif sub == "marketplace":
        return await _handle_marketplace(arg)

    elif sub == "search":
        _search(arg)

    elif sub == "remove":
        if not arg:
            console.print("[yellow]Usage: /plugins remove <name>[/yellow]")
            return True
        console.print(
            f"[green]✓ Removed {arg}[/green]" if cp.remove(arg)
            else f"[yellow]No plugin named '{arg}'[/yellow]"
        )

    elif sub == "list":
        plugins = cp.list_plugins()
        if not plugins:
            console.print("[dim]No plugins installed. /plugins install <owner/repo>[/dim]")
            return True
        console.print("[bold]Installed plugins:[/bold]", style=COLORS["primary"])
        for p in plugins:
            flag = "" if p.get("enabled", True) else " [dim](disabled)[/dim]"
            console.print(f"  • [bold]{p['name']}[/bold]{flag}  [dim]{p['source']}[/dim]")
            _print_components(cp.plugin_components(p["name"]), indent="      ")
    else:
        console.print(
            "[yellow]Usage: /plugins install|list|remove|search|marketplace[/yellow]"
        )
    return True


async def _handle_marketplace(arg: str) -> bool:
    msub, _, marg = arg.partition(" ")
    marg = marg.strip()
    if msub == "add":
        if not marg:
            console.print("[yellow]Usage: /plugins marketplace add <owner/repo | git-url | dir>[/yellow]")
            return True
        try:
            with console.status(f"Adding marketplace {marg}…"):
                name = mp.add(marg)
        except (ValueError, RuntimeError) as e:
            console.print(f"[red]Failed:[/red] {e}")
            return True
        n = len(mp.list_marketplace_plugins())
        console.print(f"[green]✓ Added marketplace[/green] [bold]{name}[/bold]  [dim]({n} plugins available — /plugins search)[/dim]")
    elif msub == "remove":
        console.print(
            f"[green]✓ Removed marketplace {marg}[/green]" if mp.remove_marketplace(marg)
            else f"[yellow]No marketplace named '{marg}'[/yellow]"
        )
    else:  # list
        mkts = mp.list_marketplaces()
        if not mkts:
            console.print("[dim]No marketplaces. /plugins marketplace add <owner/repo>[/dim]")
            return True
        console.print("[bold]Marketplaces:[/bold]", style=COLORS["primary"])
        for m in mkts:
            console.print(f"  • [bold]{m['name']}[/bold]  [dim]{m['source']}[/dim]")
    return True


def _search(query: str) -> None:
    plugins = mp.list_marketplace_plugins()
    if query:
        q = query.lower()
        plugins = [p for p in plugins if q in p["name"].lower() or q in p["description"].lower()]
    if not plugins:
        console.print("[dim]No matching plugins. Add a marketplace: /plugins marketplace add <owner/repo>[/dim]")
        return
    console.print("[bold]Available plugins:[/bold]", style=COLORS["primary"])
    for p in plugins:
        console.print(
            f"  • [bold]{p['name']}[/bold]@{p['marketplace']}  [dim]{p['description']}[/dim]"
        )


def _print_components(comps: dict[str, list[str]], indent: str = "  ") -> None:
    for kind in ("skills", "commands", "agents", "mcp", "hooks"):
        items = comps.get(kind) or []
        if items:
            console.print(f"{indent}[cyan]{kind}[/cyan]: {', '.join(items)}")


def register_commands(registry) -> None:
    """Register /plugins (Claude-compatible plugin installer)."""

    async def _handler(ctx: CommandContext) -> bool:
        return await handle_plugin_install_command(ctx)

    registry.register("plugins", _handler)

"""Generic interactive menu runner for slash command handlers.

Replaces the repetitive "print options → prompt → dispatch" pattern
that was duplicated across ~8 handler modules.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable

from prompt_toolkit import PromptSession

from novacode_cli.commands import CommandContext
from novacode_cli.config.config import COLORS, console


@dataclass
class MenuOption:
    """A single option in an interactive menu.

    Attributes:
        label: Human-readable label shown in the menu list.
        handler: Async callable invoked when the option is selected.
                 Receives the standard CommandContext and a PromptSession
                 for any nested prompts the handler may need.
    """

    label: str
    handler: Callable[[CommandContext, PromptSession], Awaitable[bool]]


async def run_interactive_menu(
    title: str,
    options: list[MenuOption],
    ctx: CommandContext,
    cancel_label: str = "Cancel",
) -> bool:
    """Render an interactive numbered menu and dispatch to the selected option.

    Args:
        title: Bold heading shown at the top of the menu.
        options: Ordered list of MenuOption items (numbered 1..N).
        ctx: Standard CommandContext forwarded to every handler.
        cancel_label: Label for the cancel/exit option (always last).

    Returns:
        ``True`` — commands are always considered handled.
    """
    session = PromptSession()

    console.print()
    console.print(f"[bold]{title}[/bold]", style=COLORS["primary"])
    console.print()

    for i, opt in enumerate(options, 1):
        console.print(f"  {i}. {opt.label}")
    console.print(f"  {len(options) + 1}. {cancel_label}")
    console.print()

    choice = (
        await session.prompt_async(
            f"Choose (1-{len(options) + 1}, or 'cancel'): "
        )
    ).strip()

    if choice == str(len(options) + 1) or choice.lower() in ("cancel", "c", "q"):
        console.print("[dim]Cancelled[/dim]")
        console.print()
        return True

    try:
        idx = int(choice) - 1
        if 0 <= idx < len(options):
            return await options[idx].handler(ctx, session)
        console.print("[yellow]Invalid choice[/yellow]")
        console.print()
        return True
    except (ValueError, IndexError):
        console.print("[yellow]Invalid choice[/yellow]")
        console.print()
        return True
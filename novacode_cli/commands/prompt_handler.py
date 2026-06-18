"""``/prompt`` command — manage evolving system-prompt templates (Enhancement 2).

Subcommands::

    /prompt status              show templates with active/candidate overrides
    /prompt rollback <name>     undo the latest change (drop candidate, else revert active)
    /prompt accept <name>       force-promote the candidate now
    /prompt reject <name>       discard the candidate now

All overrides live under ``~/.nova/prompt_history/``; the packaged ``.jinja``
files are never modified.
"""

from __future__ import annotations

import shlex
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from rich.console import Console

    from novacode_cli.hermes.prompt_evolution import PromptEvolutionEngine
    from novacode_cli.states.Session import SessionState

_MIN_ACTION_TOKENS = 2


def _engine() -> PromptEvolutionEngine:
    """Build a PromptEvolutionEngine bound to the durable store."""
    from novacode_cli.hermes.prompt_evolution import PromptEvolutionEngine
    from novacode_cli.memory.store import get_durable_store

    return PromptEvolutionEngine(get_durable_store())


async def handle_prompt_command(
    cmd_args: str | None,
    session_state: SessionState,  # noqa: ARG001 — uniform command-handler signature
    console: Console,
) -> bool:
    """Dispatch a ``/prompt`` subcommand. Returns ``True`` (command handled)."""
    try:
        tokens = shlex.split((cmd_args or "").strip())
    except ValueError as exc:
        console.print(f"[red]Could not parse arguments: {exc}[/red]")
        return True

    action = tokens[0] if tokens else "status"
    engine = _engine()

    if action == "status":
        _print_status(engine, console)
        return True

    if action in ("rollback", "accept", "reject"):
        if len(tokens) < _MIN_ACTION_TOKENS:
            console.print(f"[yellow]Usage:[/yellow] /prompt {action} <template>")
            return True
        name = tokens[1]
        if not name.endswith(".jinja"):
            name = f"{name}.jinja"
        await _run_action(engine, action, name, console)
        return True

    console.print(f"[yellow]Unknown /prompt subcommand:[/yellow] {action}")
    return True


async def _run_action(
    engine: PromptEvolutionEngine, action: str, name: str, console: Console
) -> None:
    """Execute rollback / accept / reject for one template."""
    if action == "rollback":
        result = await engine.rollback(name)
        console.print(f"  [green]✓[/green] {name}: {result}")
    elif action == "accept":
        promoted = await engine.promote(name)
        console.print(
            f"  [green]✓[/green] Promoted candidate for {name}"
            if promoted
            else f"  [dim]No candidate to promote for {name}[/dim]"
        )
    else:  # reject
        discarded = await engine.discard(name)
        console.print(
            f"  [green]✓[/green] Discarded candidate for {name}"
            if discarded
            else f"  [dim]No candidate to discard for {name}[/dim]"
        )


def _print_status(engine: PromptEvolutionEngine, console: Console) -> None:
    """Render the override status table."""
    rows = engine.status()
    if not rows:
        console.print(
            "[dim]No prompt overrides. Templates evolve automatically from reviews.[/dim]"
        )
        return
    console.print("[bold]Prompt templates[/bold]")
    for row in rows:
        flags = []
        if row["has_active"]:
            flags.append("[green]active-override[/green]")
        if row["has_candidate"]:
            flags.append("[yellow]candidate (A/B testing)[/yellow]")
        console.print(f"  [cyan]{row['template']}[/cyan] — {', '.join(flags) or 'packaged'}")

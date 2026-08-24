"""Handler for the ``/refine`` command.

Currently supports ``/refine history`` — prints the unified refinement audit
trail (the cross-domain log of prompt/skill/memory changes). This is the
"what have I changed and did it work" view inspired by Prime Agent's
``refinement_events.json`` (see ``docs/PRIME-AGENT-LEARNING-ANALYSIS.md``).
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.table import Table


def _nova_root() -> Path:
    """Resolve the shared ``~/.nova`` root from the prompt-history location."""
    from novacode_cli.hermes.prompt_evolution import PROMPT_HISTORY_DIR

    return PROMPT_HISTORY_DIR.parent


def _read_events(nova_root: Path) -> list[dict]:
    path = nova_root / "refinement_events.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
    except (json.JSONDecodeError, OSError):
        return []
    return []


def _fmt_ts(ts: float) -> str:
    try:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
    except (ValueError, OSError):
        return "?"


async def handle_refine_command(
    cmd_args: str | None,
    session_state: Any,
    console: Console,
) -> bool:
    """Handle ``/refine`` subcommands (currently ``history``)."""
    args = (cmd_args or "").strip().split()
    sub = args[0].lower() if args else "history"

    if sub == "history":
        nova_root = _nova_root()
        events = _read_events(nova_root)
        if not events:
            console.print(
                "[yellow]No refinement events recorded yet. "
                "The audit trail fills in as you evolve prompts, create/refine "
                "skills, and consolidate memory.[/yellow]"
            )
            return True

        table = Table(title="Refinement History (unified audit trail)")
        table.add_column("When", style="dim")
        table.add_column("Domain", style="cyan")
        table.add_column("Action", style="magenta")
        table.add_column("Target")
        table.add_column("Outcome", style="green")
        for ev in reversed(events[-50:]):
            table.add_row(
                _fmt_ts(ev.get("ts", 0)),
                str(ev.get("domain", "?")),
                str(ev.get("action", "?")),
                str(ev.get("target", "")),
                str(ev.get("outcome", "applied")),
            )
        console.print(table)
        return True

    if sub == "rollback":
        event_id = args[1] if len(args) > 1 else ""
        if not event_id:
            console.print("[red]Usage: /refine rollback <event_id>[/red]")
            return True
        from novacode_cli.hermes.refinement_log import rollback_refinement

        ok, message = rollback_refinement(_nova_root(), event_id)
        if ok:
            console.print(f"[green]{message}[/green]")
        else:
            console.print(f"[yellow]{message}[/yellow]")
        return True

    console.print(
        f"[red]Unknown /refine subcommand '{sub}'. "
        "Supported: history, rollback <event_id>.[/red]"
    )
    return True

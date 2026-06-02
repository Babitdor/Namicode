"""Handler for the /research command - multi-agent research swarm.

Usage:
    /research <query>                    - General research (3 agents)
    /research academic <query>           - Academic / literature review
    /research market <query>             - Market research & competitive analysis
    /research stocks <query>             - Stock & financial research
    /research technical <query>          - Technical docs & API research
    /research <mode> <query> -n <count>  - Custom agent count (default: 3)
    /research <query> --fast             - Skip fact-checking (faster)
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from novacode_cli.prompts import render_template

ResearchMode = Literal["academic", "market", "stocks", "technical", "general"]

# Mode → which researcher agent type to spawn (plural)
_MODE_AGENTS: dict[ResearchMode, list[str]] = {
    "academic":  ["literature-reviewer", "literature-reviewer", "literature-reviewer"],
    "market":    ["market-analyst", "market-analyst", "web-researcher"],
    "stocks":    ["financial-analyst", "financial-analyst", "web-researcher"],
    "technical": ["technical-researcher", "technical-researcher", "technical-researcher"],
    "general":   ["web-researcher", "web-researcher", "web-researcher"],
}

_MODE_DESCRIPTIONS: dict[ResearchMode, str] = {
    "academic":  "Academic literature review",
    "market":    "Market research & competitive analysis",
    "stocks":    "Stock & financial research",
    "technical": "Technical documentation research",
    "general":   "General research",
}

_VALID_MODES = set(_MODE_AGENTS)


def _parse_args(raw: str) -> tuple[ResearchMode, str, int, bool]:
    """Parse raw command args into (mode, query, agent_count, fast_mode).

    Handles:
        <query>
        <mode> <query>
        <mode> <query> -n <count>
        <query> -n <count>
        <query> --fast
    """
    parts = raw.strip().split()
    mode: ResearchMode = "general"
    agent_count = 3
    fast_mode = False

    # Extract --fast flag
    if "--fast" in parts:
        fast_mode = True
        parts.remove("--fast")

    # Extract -n / --agents flag
    for flag in ("-n", "--agents"):
        if flag in parts:
            idx = parts.index(flag)
            if idx + 1 < len(parts) and parts[idx + 1].isdigit():
                agent_count = max(1, min(6, int(parts[idx + 1])))
                parts = parts[:idx] + parts[idx + 2:]

    # Extract mode if first word matches
    if parts and parts[0].lower() in _VALID_MODES:
        mode = parts[0].lower()  # type: ignore[assignment]
        parts = parts[1:]

    query = " ".join(parts)
    return mode, query, agent_count, fast_mode


async def handle_research_command(
    agent,
    session_state,
    token_tracker,
    cmd_args: str | None = None,
    execute_fn=None,
) -> None:
    """Handle the /research command.

    Builds the research swarm prompt and executes it via Dora (research agent).

    ``execute_fn`` lets callers (e.g. the Textual TUI) substitute their own
    renderer for the agent run; defaults to the classic ``execute_task``.
    """
    from novacode_cli.config.config import console

    if execute_fn is None:
        from novacode_cli.ui.execution import execute_task

        execute_fn = execute_task

    if not cmd_args or not cmd_args.strip():
        console.print()
        console.print("[bold]Usage:[/bold] /research [mode] <query> [-n <agents>]")
        console.print()
        console.print("[bold]Modes:[/bold]")
        for m, desc in _MODE_DESCRIPTIONS.items():
            console.print(f"  [cyan]{m:<12}[/cyan] {desc}")
        console.print()
        console.print("[bold]Flags:[/bold]")
        console.print("  [cyan]--fast[/cyan]       Skip fact-checking (2-3× faster, less verified)")
        console.print("  [cyan]-n <count>[/cyan]   Number of researcher agents (default: 3, max: 6)")
        console.print()
        console.print("[bold]Examples:[/bold]")
        console.print("  /research What are the latest advances in quantum computing?")
        console.print("  /research academic transformer architecture efficiency")
        console.print("  /research stocks NVIDIA competitive positioning")
        console.print("  /research market AI coding assistants -n 4")
        console.print("  /research technical React Server Components --fast")
        console.print()
        return

    mode, query, agent_count, fast_mode = _parse_args(cmd_args)

    if not query:
        console.print("[red]Error: no research query provided.[/red]")
        console.print(f"[dim]Usage: /research {mode} <your question>[/dim]")
        console.print()
        return

    # Build agent list — respect custom count, repeat/trim base team
    base_agents = _MODE_AGENTS[mode]
    agents = (base_agents * ((agent_count // len(base_agents)) + 1))[:agent_count]

    # Output folder, relative to the project root so it resolves the same way
    # in local mode and inside a bind-mounted sandbox (/workspace/.nova/research).
    base_dir = Path(".nova") / "research"

    # Pre-create the base dir on the host so the swarm always has a real folder
    # to write into — even if the agent's shell/backend can't create it. The
    # per-query subfolder is still created by the agents.
    try:
        base_dir.mkdir(parents=True, exist_ok=True)
    except OSError as ex:
        console.print(f"[yellow]Could not create {base_dir}: {ex}[/yellow]")

    if fast_mode:
        console.print("[dim]Fast mode: skipping fact-check phase[/dim]")

    # Ground the swarm in the prior conversation so it (and its subagents)
    # proceed from what was already discussed with the core agent.
    conversation_context = ""
    try:
        from novacode_cli.utils.conversation_context import (
            get_recent_conversation_digest,
        )

        conversation_context = await get_recent_conversation_digest(
            agent, session_state.thread_id
        )
    except Exception:  # noqa: BLE001
        conversation_context = ""

    prompt = render_template(
        "research_swarm.jinja",
        research_query=query,
        mode=mode,
        mode_description=_MODE_DESCRIPTIONS[mode],
        agent_count=agent_count,
        agents=agents,
        # POSIX form (forward slashes) so the model never sees a backslashed,
        # Windows-style ".nova\\research" — which it tends to mangle into a
        # dotless "nova" folder. The virtual filesystem accepts forward slashes
        # on every platform.
        base_dir=base_dir.as_posix(),
        fast_mode=fast_mode,
        conversation_context=conversation_context,
    )

    backend = getattr(agent, "backend", None)

    await execute_fn(
        prompt,
        agent,
        "dora",  # Display as Dora instead of Nova
        session_state,
        token_tracker,
        backend=backend,
    )

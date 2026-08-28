"""Handler for /log command — query and inspect structured run logs (Meta-Harness F2).

Subcommands:
  list   [--limit N]             List recent runs
  show   <id>                    Print full detail for a run
  grep   <pattern>               Search prompt/response text across all runs
  diff   <id-a> <id-b>           Side-by-side summary diff of two runs
  verdict <id> accept|reject|edit  Record a quality verdict for a run
  frontier [--by <axes>]         Print Pareto-optimal runs (F4)
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from novacode_cli.config.config import COLORS, console


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _runs_dir(workspace_root: str | None = None) -> Path:
    root = Path(workspace_root) if workspace_root else Path.cwd()
    return root / ".nova" / "runs"


def _list_runs(runs_dir: Path) -> list[Path]:
    """Return run directories sorted newest-first."""
    if not runs_dir.exists():
        return []
    return sorted(
        [p for p in runs_dir.iterdir() if p.is_dir()],
        reverse=True,
    )


def _load_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _run_summary_line(run_dir: Path) -> str:
    """Single line: <id>  turns=N  tools=N  status  time"""
    meta = _load_json(run_dir / "meta.json")
    summary = _load_json(run_dir / "summary.json")
    verdict = _load_json(run_dir / "user_verdict.json")

    run_id = run_dir.name
    turns = summary.get("turns", "?")
    tools = summary.get("tool_calls", "?")
    status = summary.get("exit_status", "incomplete")
    wall = summary.get("wall_seconds", "?")
    model = meta.get("model", "?")
    v_str = f"  [{verdict.get('verdict', '')}]" if verdict else ""

    return f"{run_id}  turns={turns}  tools={tools}  {status}  {wall}s  {model}{v_str}"


# ---------------------------------------------------------------------------
# Subcommand implementations
# ---------------------------------------------------------------------------

def _cmd_list(runs_dir: Path, limit: int) -> None:
    runs = _list_runs(runs_dir)[:limit]
    if not runs:
        console.print("[dim]No runs found. Start a session to generate logs.[/dim]")
        return
    console.print()
    console.print("[bold]Recent runs[/bold]", style=COLORS["primary"])
    console.print()
    for run in runs:
        console.print(f"  {_run_summary_line(run)}")
    console.print()


def _cmd_show(runs_dir: Path, run_id: str) -> None:
    matches = [p for p in _list_runs(runs_dir) if p.name.startswith(run_id)]
    if not matches:
        console.print(f"[red]No run matching '{run_id}'[/red]")
        return
    run_dir = matches[0]

    meta = _load_json(run_dir / "meta.json")
    summary = _load_json(run_dir / "summary.json")
    verdict = _load_json(run_dir / "user_verdict.json")

    console.print()
    console.print(f"[bold]Run: {run_dir.name}[/bold]", style=COLORS["primary"])
    console.print()
    if meta:
        console.print("[bold]Meta:[/bold]")
        for k, v in meta.items():
            console.print(f"  {k}: {v}")
        console.print()
    if summary:
        console.print("[bold]Summary:[/bold]")
        for k, v in summary.items():
            console.print(f"  {k}: {v}")
        console.print()
    if verdict:
        console.print("[bold]Verdict:[/bold]")
        for k, v in verdict.items():
            console.print(f"  {k}: {v}")
        console.print()

    turns_dir = run_dir / "turns"
    if turns_dir.exists():
        turn_dirs = sorted(turns_dir.iterdir())
        console.print(f"[bold]Turns ({len(turn_dirs)}):[/bold]")
        for turn in turn_dirs:
            tools_file = turn / "tools.jsonl"
            tool_count = 0
            if tools_file.exists():
                tool_count = sum(1 for _ in tools_file.open(encoding="utf-8"))
            console.print(f"  {turn.name}  tools={tool_count}")
        console.print()


def _cmd_grep(runs_dir: Path, pattern: str, limit: int) -> None:
    try:
        rx = re.compile(pattern, re.IGNORECASE)
    except re.error as e:
        console.print(f"[red]Invalid pattern: {e}[/red]")
        return

    hits = 0
    console.print()
    for run_dir in _list_runs(runs_dir):
        turns_dir = run_dir / "turns"
        if not turns_dir.exists():
            continue
        for turn in sorted(turns_dir.iterdir()):
            for fname in ("prompt.txt", "response.json"):
                fpath = turn / fname
                if not fpath.exists():
                    continue
                text = fpath.read_text(encoding="utf-8", errors="replace")
                for lineno, line in enumerate(text.splitlines(), 1):
                    if rx.search(line):
                        short_id = run_dir.name[:16]
                        console.print(
                            f"[dim]{short_id}/{turn.name}/{fname}:{lineno}[/dim]  {line.strip()[:120]}"
                        )
                        hits += 1
                        if hits >= limit:
                            console.print(f"\n[dim]... stopped at {limit} hits[/dim]")
                            return
    if hits == 0:
        console.print(f"[dim]No matches for '{pattern}'[/dim]")
    console.print()


def _cmd_diff(runs_dir: Path, id_a: str, id_b: str) -> None:
    def _find(prefix: str) -> Path | None:
        matches = [p for p in _list_runs(runs_dir) if p.name.startswith(prefix)]
        return matches[0] if matches else None

    a = _find(id_a)
    b = _find(id_b)
    if not a:
        console.print(f"[red]Run not found: {id_a}[/red]")
        return
    if not b:
        console.print(f"[red]Run not found: {id_b}[/red]")
        return

    sa = _load_json(a / "summary.json")
    sb = _load_json(b / "summary.json")

    keys = sorted(set(sa) | set(sb))
    console.print()
    console.print(f"[bold]Diff: {a.name[:16]} vs {b.name[:16]}[/bold]", style=COLORS["primary"])
    console.print()
    console.print(f"  {'field':<20} {'A':>12}  {'B':>12}")
    console.print(f"  {'-'*20} {'-'*12}  {'-'*12}")
    for k in keys:
        va = str(sa.get(k, "—"))
        vb = str(sb.get(k, "—"))
        diff = " *" if va != vb else ""
        console.print(f"  {k:<20} {va:>12}  {vb:>12}{diff}")
    console.print()


def _cmd_verdict(runs_dir: Path, run_id: str, verdict: str) -> None:
    valid = {"accept", "reject", "edit"}
    if verdict not in valid:
        console.print(f"[red]Verdict must be one of: {', '.join(sorted(valid))}[/red]")
        return

    matches = [p for p in _list_runs(runs_dir) if p.name.startswith(run_id)]
    if not matches:
        console.print(f"[red]No run matching '{run_id}'[/red]")
        return
    run_dir = matches[0]

    from datetime import UTC, datetime
    data = {"verdict": verdict, "recorded_at": datetime.now(UTC).isoformat()}
    (run_dir / "user_verdict.json").write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8"
    )
    console.print(f"[green]Verdict '{verdict}' saved for {run_dir.name}[/green]")


def _cmd_frontier(runs_dir: Path, by: list[str]) -> None:
    """Print Pareto-optimal runs on (quality, efficiency) axes (F4)."""
    _VERDICT_SCORE = {"accept": 1.0, "edit": 0.5, "reject": 0.0}
    _STATUS_SCORE = {"success": 0.8, "complete": 0.6, "incomplete": 0.3, "error": 0.1}

    runs = _list_runs(runs_dir)
    if not runs:
        console.print("[dim]No runs found.[/dim]")
        return

    points: list[dict] = []
    for run_dir in runs:
        summary = _load_json(run_dir / "summary.json")
        verdict = _load_json(run_dir / "user_verdict.json")

        quality: float
        if verdict:
            quality = _VERDICT_SCORE.get(verdict.get("verdict", ""), 0.3)
        else:
            quality = _STATUS_SCORE.get(summary.get("exit_status", ""), 0.3)

        tool_calls = int(summary.get("tool_calls", 0)) or 1
        wall = float(summary.get("wall_seconds", 0)) or 1.0
        efficiency = 1.0 / tool_calls

        points.append({
            "id": run_dir.name,
            "quality": quality,
            "efficiency": efficiency,
            "tool_calls": tool_calls,
            "wall": wall,
            "status": summary.get("exit_status", "?"),
            "verdict": verdict.get("verdict", "") if verdict else "",
        })

    # Non-dominated sort: a dominates b if quality >= b.quality AND efficiency >= b.efficiency
    # (with at least one strict)
    def dominates(a: dict, b: dict) -> bool:
        return (
            a["quality"] >= b["quality"]
            and a["efficiency"] >= b["efficiency"]
            and (a["quality"] > b["quality"] or a["efficiency"] > b["efficiency"])
        )

    frontier = [p for p in points if not any(dominates(q, p) for q in points if q is not p)]
    frontier.sort(key=lambda p: (-p["quality"], -p["efficiency"]))

    console.print()
    console.print("[bold]Pareto Frontier[/bold]", style=COLORS["primary"])
    console.print(f"[dim]{len(frontier)} of {len(points)} runs are non-dominated[/dim]")
    console.print()
    console.print(f"  {'id':<20} {'quality':>8} {'tools':>6} {'wall':>8}  status  verdict")
    console.print(f"  {'-'*20} {'-'*8} {'-'*6} {'-'*8}  {'------'}  {'-------'}")
    for p in frontier:
        console.print(
            f"  {p['id'][:20]:<20} {p['quality']:>8.2f} {p['tool_calls']:>6} "
            f"{p['wall']:>7.1f}s  {p['status']:<8} {p['verdict']}"
        )
    console.print()


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def handle_log_command(cmd_args: str | None, workspace_root: str | None = None) -> bool:
    """Handle the /log command with subcommands: list show grep diff verdict frontier."""
    runs_dir = _runs_dir(workspace_root)

    parts = cmd_args.strip().split() if cmd_args else []
    subcmd = parts[0].lower() if parts else "list"
    rest = parts[1:]

    if subcmd in ("list", "ls"):
        limit = 20
        if rest and rest[0].isdigit():
            limit = int(rest[0])
        elif "--limit" in rest:
            idx = rest.index("--limit")
            if idx + 1 < len(rest):
                try:
                    limit = int(rest[idx + 1])
                except ValueError:
                    pass
        _cmd_list(runs_dir, limit)

    elif subcmd == "show":
        if not rest:
            console.print("[red]Usage: /log show <run-id>[/red]")
        else:
            _cmd_show(runs_dir, rest[0])

    elif subcmd == "grep":
        if not rest:
            console.print("[red]Usage: /log grep <pattern>[/red]")
        else:
            limit = 50
            if "--limit" in rest:
                idx = rest.index("--limit")
                if idx + 1 < len(rest):
                    try:
                        limit = int(rest[idx + 1])
                        rest = rest[:idx] + rest[idx + 2:]
                    except ValueError:
                        pass
            _cmd_grep(runs_dir, rest[0], limit)

    elif subcmd == "diff":
        if len(rest) < 2:
            console.print("[red]Usage: /log diff <id-a> <id-b>[/red]")
        else:
            _cmd_diff(runs_dir, rest[0], rest[1])

    elif subcmd == "verdict":
        if len(rest) < 2:
            console.print("[red]Usage: /log verdict <id> accept|reject|edit[/red]")
        else:
            _cmd_verdict(runs_dir, rest[0], rest[1])

    elif subcmd == "frontier":
        by = ["accept", "tokens"]
        if "--by" in rest:
            idx = rest.index("--by")
            if idx + 1 < len(rest):
                by = rest[idx + 1].split(",")
        _cmd_frontier(runs_dir, by)

    else:
        console.print()
        console.print("[bold]nova log — run log viewer[/bold]", style=COLORS["primary"])
        console.print()
        console.print("  [bold]list[/bold] [--limit N]            List recent runs (default 20)")
        console.print("  [bold]show[/bold] <id>                   Full detail for a run")
        console.print("  [bold]grep[/bold] <pattern>              Search text across all runs")
        console.print("  [bold]diff[/bold] <id-a> <id-b>          Compare two runs")
        console.print("  [bold]verdict[/bold] <id> accept|reject|edit  Record quality verdict")
        console.print("  [bold]frontier[/bold] [--by axes]        Pareto-optimal runs (F4)")
        console.print()

    return True


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

def register_commands(registry) -> None:
    from novacode_cli.commands import CommandContext

    async def _handle(ctx: CommandContext) -> bool:
        workspace_root = str(getattr(ctx.session_state, "workspace_root", None) or "")
        return await handle_log_command(ctx.cmd_args, workspace_root or None)

    registry.register("log", _handle)

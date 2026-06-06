"""Project graph query tool."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from langchain.tools import tool


def _load_raw_graph(workspace_root: Path) -> dict[str, Any] | None:
    graph_path = workspace_root / ".nova" / "project-graph.json"
    if not graph_path.exists():
        return None
    try:
        return json.loads(graph_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return None


def _matches(text: str | None, query_lower: str) -> bool:
    # `or ""` because node label/id/source_file may be null in the graph.
    return query_lower in (text or "").lower()


@tool
def query_project_graph(query: str) -> str:
    """Query the project graph for targeted architectural information.

    Searches the project graph (built by /init) for nodes, communities, god
    nodes, and cross-module connections that match the query. Use this when
    you need to understand which modules a file connects to, what community
    it belongs to, or whether a symbol is a high-degree hub.

    Args:
        query: File path fragment, symbol name, or module keyword
               (e.g. "bootstrap", "AgentMemoryMiddleware", "core_agent").

    Returns:
        Matching nodes, communities, god nodes, and cross-module connections.
        Returns a "no graph" message if /init has not been run.
    """
    from novacode_cli.config.config import settings

    workspace_root = settings.project_root or Path.cwd()
    data = _load_raw_graph(Path(workspace_root))
    if data is None:
        return "No project graph available. Run /init to build the project graph."

    query_lower = query.strip().lower()
    if not query_lower:
        return "Empty query. Provide a file name, symbol, or module keyword."

    results: list[str] = []
    meta = data.get("metadata", {})

    # Nodes
    nodes = data.get("nodes", [])
    matched = [
        n for n in nodes
        if _matches(n.get("label", ""), query_lower)
        or _matches(n.get("id", ""), query_lower)
        or _matches(n.get("source_file", ""), query_lower)
    ]
    if matched:
        results.append(f"### Matching Nodes ({len(matched)} found)")
        for n in matched[:10]:
            label = n.get("label", n.get("id", "?"))
            sf = n.get("source_file", "")
            loc = n.get("source_location", "")
            comm = n.get("community")
            line = f"- **{label}**"
            if sf:
                line += f" — `{sf}`"
                if loc:
                    line += f" {loc}"
            if comm is not None:
                line += f" (community {comm})"
            results.append(line)
        if len(matched) > 10:
            results.append(f"  ... and {len(matched) - 10} more")
        results.append("")

    # Communities
    communities = meta.get("communities", [])
    matched_comms = [
        c for c in communities
        if _matches(c.get("label", ""), query_lower)
        or any(_matches(nid, query_lower) for nid in c.get("nodes", []))
    ]
    if matched_comms:
        results.append(f"### Matching Communities ({len(matched_comms)} found)")
        for c in matched_comms[:5]:
            label = c.get("label", f"Community {c.get('id', '?')}")
            count = c.get("node_count", len(c.get("nodes", [])))
            results.append(f"- **{label}**: {count} components (id={c.get('id', '?')})")
        results.append("")

    # God nodes
    god_nodes = meta.get("god_nodes", [])
    matched_gods = [
        g for g in god_nodes
        if _matches(g.get("label", ""), query_lower)
        or _matches(g.get("id", ""), query_lower)
    ]
    if matched_gods:
        results.append("### God Nodes (Central Hubs)")
        for g in matched_gods:
            label = g.get("label", g.get("id", "?"))
            degree = g.get("degree", g.get("edges", "?"))
            results.append(f"- **{label}** — {degree} connections")
        results.append("")

    # Surprising connections
    surp = meta.get("surprising_connections", [])
    matched_surp = [
        s for s in surp
        if _matches(s.get("source", ""), query_lower)
        or _matches(s.get("target", ""), query_lower)
    ]
    if matched_surp:
        results.append("### Cross-Module Connections")
        for s in matched_surp[:5]:
            src = s.get("source", "?")[:60]
            tgt = s.get("target", "?")
            why = s.get("why", "")
            line = f"- `{src}` ↔ `{tgt}`"
            if why:
                line += f"\n  {why[:120]}"
            results.append(line)
        results.append("")

    if not results:
        return f"No matches found for '{query}' in the project graph."

    return f"Project graph query: '{query}'\n\n" + "\n".join(results)

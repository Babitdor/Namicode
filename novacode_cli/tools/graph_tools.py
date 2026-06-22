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


def _find_connected(
    node_id: str, links: list[dict[str, Any]], nodes: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Find nodes connected to *node_id* via edges/links.

    Args:
        node_id: The node ID to find connections for.
        links: List of edge/link dicts with ``source`` and ``target`` keys.
        nodes: List of node dicts with ``id`` and ``label`` keys.

    Returns:
        List of connected node dicts (label, id, source_file).
    """
    connected: list[dict[str, Any]] = []
    seen: set[str] = set()
    node_lookup = {n.get("id", ""): n for n in nodes}
    for link in links:
        src = link.get("source", "")
        tgt = link.get("target", "")
        if src == node_id and tgt not in seen:
            seen.add(tgt)
            n = node_lookup.get(tgt)
            if n:
                connected.append({
                    "label": n.get("label", n.get("id", tgt)),
                    "id": tgt,
                    "source_file": n.get("source_file", ""),
                })
        elif tgt == node_id and src not in seen:
            seen.add(src)
            n = node_lookup.get(src)
            if n:
                connected.append({
                    "label": n.get("label", n.get("id", src)),
                    "id": src,
                    "source_file": n.get("source_file", ""),
                })
    return connected


def _format_json(
    query_lower: str,
    nodes: list[dict[str, Any]],
    links: list[dict[str, Any]],
    meta: dict[str, Any],
) -> str:
    """Format query results as structured JSON.

    Args:
        query_lower: Lowercased query string.
        nodes: List of node dicts from the graph.
        links: List of edge/link dicts from the graph.
        meta: Metadata dict from the graph.

    Returns:
        JSON string with matched nodes, communities, and god nodes.
    """
    # Matched nodes with connected_to
    matched_nodes = [
        n for n in nodes
        if _matches(n.get("label", ""), query_lower)
        or _matches(n.get("id", ""), query_lower)
        or _matches(n.get("source_file", ""), query_lower)
    ]
    node_results = []
    for n in matched_nodes:
        nid = n.get("id", "")
        node_results.append({
            "label": n.get("label", nid),
            "id": nid,
            "source_file": n.get("source_file", ""),
            "source_location": n.get("source_location", ""),
            "community": n.get("community"),
            "connections": n.get("edges", 0),
            "connected_to": _find_connected(nid, links, nodes),
        })

    # Matched communities
    communities = meta.get("communities", [])
    matched_comms = [
        c for c in communities
        if _matches(c.get("label", ""), query_lower)
        or any(_matches(nid, query_lower) for nid in c.get("nodes", []))
    ]
    community_results = [
        {
            "id": c.get("id"),
            "label": c.get("label", f"Community {c.get('id', '?')}"),
            "node_count": c.get("node_count", len(c.get("nodes", []))),
        }
        for c in matched_comms
    ]

    # Matched god nodes
    god_nodes = meta.get("god_nodes", [])
    matched_gods = [
        g for g in god_nodes
        if _matches(g.get("label", ""), query_lower)
        or _matches(g.get("id", ""), query_lower)
    ]
    god_results = [
        {
            "label": g.get("label", g.get("id", "?")),
            "connections": g.get("degree", g.get("edges", 0)),
            "source_file": g.get("source_file", ""),
        }
        for g in matched_gods
    ]

    output = {
        "query": query_lower,
        "matched_nodes": node_results,
        "matched_communities": community_results,
        "matched_god_nodes": god_results,
    }
    return json.dumps(output, indent=2, default=str)


@tool
async def query_project_graph(  # noqa: PLR0912, PLR0915
    query: str,
    output_format: str = "text",
) -> str:
    """Query the project graph for targeted architectural information.

    Searches the project graph (built by /init) for nodes, communities, god
    nodes, and cross-module connections that match the query. Use this when
    you need to understand which modules a file connects to, what community
    it belongs to, or whether a symbol is a high-degree hub.

    Args:
        query: File path fragment, symbol name, or module keyword
               (e.g. "bootstrap", "AgentMemoryMiddleware", "core_agent").
        output_format: Output format — ``"text"`` (default, markdown) or
                ``"json"`` (structured JSON for programmatic use).

    Returns:
        Matching nodes, communities, god nodes, and cross-module connections.
        Returns a "no graph" message if /init has not been run.
    """
    import asyncio

    from novacode_cli.config.config import settings

    workspace_root = settings.project_root or Path.cwd()
    try:
        loop = asyncio.get_running_loop()
        data = await loop.run_in_executor(None, _load_raw_graph, Path(workspace_root))
    except RuntimeError:
        data = _load_raw_graph(Path(workspace_root))

    if data is None:
        return "No project graph available. Run /init to build the project graph."

    query_lower = query.strip().lower()
    if not query_lower:
        return "Empty query. Provide a file name, symbol, or module keyword."

    meta = data.get("metadata", {})
    nodes = data.get("nodes", [])
    links = data.get("links", data.get("edges", []))

    # --- JSON output path ---
    if output_format == "json":
        return _format_json(query_lower, nodes, links, meta)

    # --- Text (markdown) output path ---
    results: list[str] = []

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
        if len(matched) > 10:  # noqa: PLR2004
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

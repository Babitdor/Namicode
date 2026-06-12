"""Project graph building, clustering, and analysis for /init pipeline.

Wraps graphify's build, cluster, analyze, and export functions to
create a knowledge graph from extraction results, detect communities,
find important nodes, and export to multiple formats.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from rich.console import Console
from rich.panel import Panel

from novacode_cli.config.config import COLORS


def _make_console() -> Console:
    """Create a Console that handles Unicode on Windows.

    On Windows, the default console encoding (cp1252) cannot represent
    characters like emojis and special symbols that Rich renders in panel
    titles. Wrapping stdout with UTF-8 avoids UnicodeEncodeError.
    """
    from novacode_cli.config.config import console as _global_console
    return _global_console

def _coerce_float(value: Any, default: float) -> float:
    """Coerce a value to ``float``, returning ``default`` when impossible.

    ``bool`` is treated as non-numeric here (an LLM "weight": true is junk), and
    dict/list/None fall through to the default.
    """
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return default
    return default


def _coerce_str(value: Any, default: str) -> str:
    """Coerce a value to ``str``; ``None`` → *default*, other types → ``str(value)``."""
    if isinstance(value, str):
        return value
    if value is None:
        return default
    return str(value)


_NUMERIC_EDGE_FIELDS = frozenset({"weight", "confidence_score", "confidence"})
"""Edge fields that must be numeric for NetworkX arithmetic."""
_STRING_EDGE_FIELDS = frozenset({"source", "target", "relation"})
"""Edge fields that must be strings — dicts here cause '>' comparison crashes."""
_STRING_NODE_FIELDS = frozenset(
    {"label", "name", "title", "source_file", "type", "file_type", "relation"}
)
"""Node fields graphify runs string ops on (``.lower()``, ``re.sub``, ``Path()``,
``unicodedata.normalize()``). A ``None`` or dict here crashes build/export with
``expected string or bytes-like object, got 'NoneType'`` or a ``normalize()`` /
``.lower()`` ``TypeError``."""
_NUMERIC_NODE_FIELDS = frozenset(
    {"weight", "size", "value", "score", "degree", "betweenness", "confidence_score"}
)
"""Node fields used in arithmetic / sorting — a dict here raises
``'>' not supported between instances of 'float' and 'dict'``."""


def _sanitize_node(node: dict[str, Any]) -> bool:
    """Coerce one node's fields in place. Return False if it must be dropped.

    A node with a ``None``/empty ``id`` makes NetworkX raise "None cannot be a
    node" and dangles every edge referencing it, so it is dropped.
    """
    nid = node.get("id")
    nid = nid.strip() if isinstance(nid, str) else ("" if nid is None else str(nid).strip())
    if not nid:
        return False
    node["id"] = nid
    # String fields graphify runs str ops / regex / Path() on.
    for key in _STRING_NODE_FIELDS:
        if key in node and not isinstance(node[key], str):
            node[key] = _coerce_str(node[key], "")
    # label is special: graphify falls back to id only when the key is MISSING,
    # not when it's present-but-empty/None — so force a usable one.
    if not node.get("label"):
        node["label"] = nid
    # Numeric fields used in arithmetic / sorting.
    for key in _NUMERIC_NODE_FIELDS:
        if key in node and not isinstance(node[key], (int, float)):
            node[key] = _coerce_float(node[key], 0.0)
    # community / group must be int-able for clustering.
    for key in ("community", "group"):
        val = node.get(key)
        if val is not None and not isinstance(val, (int, float)):
            try:
                node[key] = int(val)
            except (TypeError, ValueError):
                node.pop(key, None)
    return True


def _sanitize_edge(edge: dict[str, Any]) -> None:
    """Coerce one edge's fields in place (endpoints/weights, never dropped)."""
    # Guarantee a numeric weight on EVERY edge — NetworkX/graphify arithmetic
    # needs it, and a missing/dict weight crashes clustering.
    edge["weight"] = _coerce_float(edge.get("weight"), 1.0)
    for key in ("confidence_score", "confidence"):
        if key in edge:
            edge[key] = _coerce_float(edge[key], 1.0)
    for key in _STRING_EDGE_FIELDS:
        if key in edge and not isinstance(edge[key], str):
            edge[key] = _coerce_str(edge[key], "")
    # Edge path fields graphify export reads via Path()/regex.
    if "source_file" in edge and not isinstance(edge["source_file"], str):
        edge["source_file"] = _coerce_str(edge["source_file"], "")
    sf = edge.get("source_files")
    if isinstance(sf, list):
        edge["source_files"] = [_coerce_str(x, "") for x in sf]


def sanitize_graph_extraction(extraction: dict[str, Any]) -> dict[str, Any]:
    """Coerce all fields so malformed extraction can't crash the graph.

    The semantic-extraction stage is LLM-authored, and weak models sometimes
    emit a numeric field (``weight``, ``confidence_score``) as a dict, a string
    field (``label``, ``source_file``, ``source``) as ``None``/an object, or a
    node with a ``None``/empty ``id``. graphify's build/analysis/export then
    raise one of::

        '>' not supported between instances of 'float' and 'dict'
        expected string or bytes-like object, got 'NoneType'
        None cannot be a node

    We coerce every known field — and drop nodes with an unusable id — at the
    graph boundary so a single bad fragment can't fail the whole ``/init``.
    Mutates in place and returns it. Keys absent on the input stay absent.
    """
    if not isinstance(extraction, dict):
        return extraction

    nodes = extraction.get("nodes")
    if isinstance(nodes, list):
        extraction["nodes"] = [
            n for n in nodes if isinstance(n, dict) and _sanitize_node(n)
        ]

    edges = extraction.get("edges")
    if isinstance(edges, list):
        for edge in edges:
            if isinstance(edge, dict):
                _sanitize_edge(edge)

    for hyper in extraction.get("hyperedges") or []:
        if isinstance(hyper, dict):
            for key in _NUMERIC_EDGE_FIELDS:
                if key in hyper:
                    hyper[key] = _coerce_float(hyper[key], 1.0)

    return extraction


if TYPE_CHECKING:
    import networkx as nx


def build_project_graph(
    extraction: dict[str, Any],
    console: Console | None = None,
) -> nx.Graph | None:
    """Build a knowledge graph from extraction results.

    Uses graphify.build_from_json to create a NetworkX graph from
    the extracted nodes and edges.

    Args:
        extraction: Extraction result from extract_project().
        console: Rich console for output.

    Returns:
        NetworkX Graph, or None if graphify is not available.
    """
    if console is None:
        console = _make_console()

    try:
        from graphify.build import build_from_json
    except ImportError:
        console.print(
            "[yellow]graphify not installed — install with: "
            "pip install novacode-cli[graphify][/yellow]"
        )
        return None

    if not extraction.get("nodes"):
        console.print("[yellow]⚠ No nodes to build graph from[/yellow]")
        return None

    # Guarantee numeric edge weights before handing off to graphify/NetworkX —
    # catches LLM-malformed semantic fragments AND any poisoned extraction cache.
    extraction = sanitize_graph_extraction(extraction)

    G = build_from_json(extraction)

    console.print(
        f"  [cyan]Graph:[/cyan] {G.number_of_nodes()} nodes, "
        f"{G.number_of_edges()} edges"
    )

    return G


# Minimum community size. Communities with ≤ this many nodes are merged
# into their most-connected neighbor community. This eliminates the
# long tail of singleton/pair communities that Leiden produces on
# real-world graphs, yielding a cleaner module structure for the agent.
_MIN_COMMUNITY_SIZE = 3


def cluster_project_graph(
    G: nx.Graph,
    console: Console | None = None,
) -> dict[int, list[str]]:
    """Detect communities in the project graph using Leiden algorithm.

    After clustering, tiny communities (≤2 nodes) are merged into their
    most-connected neighbor community to produce a cleaner module map.

    Args:
        G: NetworkX graph from build_project_graph().
        console: Rich console for output.

    Returns:
        Dict mapping community ID to list of node IDs.
    """
    if console is None:
        console = _make_console()

    try:
        from graphify.cluster import cluster, score_all
    except ImportError:
        console.print("[yellow]graphify not installed[/yellow]")
        return {}

    communities = cluster(G)

    # Merge tiny communities into their most-connected neighbor
    communities = _merge_tiny_communities(G, communities, min_size=_MIN_COMMUNITY_SIZE)

    scores = score_all(G, communities)

    # Show clustering results
    _show_cluster_panel(communities, scores, console)

    return communities


def analyze_project_graph(
    G: nx.Graph,
    communities: dict[int, list[str]],
    console: Console | None = None,
) -> dict[str, Any]:
    """Analyze the project graph for important nodes and connections.

    Finds god nodes (high-degree hubs), surprising cross-community
    connections, and suggests questions about the architecture.

    Args:
        G: NetworkX graph from build_project_graph().
        communities: Community assignments from cluster_project_graph().
        console: Rich console for output.

    Returns:
        Dict with keys: god_nodes, surprising_connections,
        suggested_questions, community_labels.
    """
    if console is None:
        console = _make_console()

    try:
        from graphify.analyze import god_nodes, surprising_connections, suggest_questions
    except ImportError:
        console.print("[yellow]graphify not installed[/yellow]")
        return {}

    # Generate community labels from community members
    community_labels = _generate_community_labels(G, communities)

    # Find god nodes (high-degree hubs)
    god_node_list = god_nodes(G, top_n=10)

    # Find surprising cross-community connections
    surprise_list = surprising_connections(G, communities, top_n=5)

    # Suggest questions about the architecture
    question_list = suggest_questions(G, communities, community_labels, top_n=7)

    # Show analysis results
    _show_analysis_panel(god_node_list, surprise_list, question_list, console)

    return {
        "god_nodes": god_node_list,
        "surprising_connections": surprise_list,
        "suggested_questions": question_list,
        "community_labels": community_labels,
    }


def export_project_graph(
    G: nx.Graph,
    communities: dict[int, list[str]],
    analysis: dict[str, Any],
    output_dir: Path,
    console: Console | None = None,
    include_html: bool = True,
) -> dict[str, Path]:
    """Export the project graph to multiple formats.

    Exports to JSON (node-link format), and optionally to an interactive
    HTML visualization.

    Args:
        G: NetworkX graph from build_project_graph().
        communities: Community assignments from cluster_project_graph().
        analysis: Analysis results from analyze_project_graph().
        output_dir: Directory to write output files.
        console: Rich console for output.
        include_html: Whether to generate HTML visualization.

    Returns:
        Dict mapping format name to output file path.
    """
    if console is None:
        console = _make_console()

    try:
        from graphify.export import to_json, to_html
    except ImportError:
        console.print("[yellow]graphify not installed[/yellow]")
        return {}

    output_dir.mkdir(parents=True, exist_ok=True)
    community_labels = analysis.get("community_labels", {})
    outputs: dict[str, Path] = {}

    # Export JSON
    json_path = str(output_dir / "project-graph.json")
    to_json(G, communities, json_path)
    outputs["json"] = Path(json_path)

    # Enrich the JSON with analysis metadata for GraphContextMiddleware
    _enrich_graph_json(json_path, communities, analysis, community_labels)

    # Export HTML visualization
    if include_html:
        html_path = str(output_dir / "project-graph.html")
        to_html(G, communities, html_path, community_labels=community_labels)
        outputs["html"] = Path(html_path)

    # Show export results
    _show_export_panel(outputs, console)

    return outputs


def _enrich_graph_json(
    json_path: str,
    communities: dict[int, list[str]],
    analysis: dict[str, Any],
    community_labels: dict[int, str],
) -> None:
    """Enrich the exported graph JSON with analysis metadata.

    Adds god_nodes, surprising_connections, community_labels, key_files,
    and community summaries to the JSON file so that GraphContextMiddleware
    can read them without needing to re-run the analysis pipeline.

    Normalizes field names to match what GraphContextMiddleware expects:
    - god_nodes get "edges" key (graphify returns "degree")
    - key_files are extracted from god nodes' source_file attributes

    Args:
        json_path: Path to the exported graph JSON file.
        communities: Community assignments from cluster_project_graph().
        analysis: Analysis results from analyze_project_graph().
        community_labels: Human-readable community labels.
    """
    try:
        data = json.loads(Path(json_path).read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return

    # Build community summaries
    community_summaries = []
    for cid in sorted(communities.keys()):
        community_summaries.append({
            "id": cid,
            "label": community_labels.get(cid, f"Community {cid}"),
            "node_count": len(communities[cid]),
            "nodes": communities[cid],
        })

    # Normalize god_nodes: graphify returns "degree" but the middleware
    # reads "edges".  Add "edges" as an alias so both work.
    god_nodes_raw = analysis.get("god_nodes", [])
    god_nodes_normalized = []
    for gn in god_nodes_raw:
        normalized = dict(gn)
        if "edges" not in normalized and "degree" in normalized:
            normalized["edges"] = normalized["degree"]
        if "source_file" not in normalized:
            # Try to find source_file from node attributes in the graph data
            nid = normalized.get("id", "")
            for node in data.get("nodes", []):
                if node.get("id") == nid and "source_file" in node:
                    normalized["source_file"] = node["source_file"]
                    break
        god_nodes_normalized.append(normalized)

    # Extract key files from god nodes' source_file attributes
    key_files: list[dict[str, str]] = []
    seen_files: set[str] = set()
    for gn in god_nodes_normalized:
        sf = gn.get("source_file", "")
        if sf and sf not in seen_files:
            seen_files.add(sf)
            label = gn.get("label", gn.get("id", "?"))
            key_files.append({
                "path": sf,
                "purpose": f"Central hub: {label}",
            })

    # Also add entry points from nodes in the graph
    for node in data.get("nodes", []):
        # `.get("label", "")` returns None when the key exists but is null
        # (graphify can emit null labels) — `or ""` guards `.lower()`.
        label = (node.get("label") or "").lower()
        nid = node.get("id", "")
        sf = node.get("source_file", "")
        if sf and sf not in seen_files:
            if any(kw in label for kw in ["main", "cli", "app", "entry"]):
                seen_files.add(sf)
                key_files.append({
                    "path": sf,
                    "purpose": f"Entry point: {node.get('label', nid)}",
                })
    key_files = key_files[:10]  # Limit

    # Add metadata
    data["metadata"] = {
        "god_nodes": god_nodes_normalized,
        "surprising_connections": analysis.get("surprising_connections", []),
        "suggested_questions": analysis.get("suggested_questions", []),
        "community_labels": community_labels,
        "communities": community_summaries,
        "key_files": key_files,
    }

    # Write back
    Path(json_path).write_text(
        json.dumps(data, indent=2, default=str), encoding="utf-8"
    )


def _merge_tiny_communities(
    G: nx.Graph,
    communities: dict[int, list[str]],
    min_size: int = _MIN_COMMUNITY_SIZE,
) -> dict[int, list[str]]:
    """Merge communities with fewer than min_size nodes into neighbors.

    Leiden on real-world graphs often produces a long tail of singleton
    and pair communities (isolates, bridge nodes, etc.). These aren't
    meaningful modules and pollute the community list the agent sees.

    Algorithm: for each tiny community, find the neighboring community
    (by edge count across the cut) with the most connections and merge
    into it. If a tiny community has no edges to any other community,
    merge it into the largest community.

    Args:
        G: NetworkX graph.
        communities: Raw community assignments from cluster().
        min_size: Communities with fewer than this many nodes are merged.

    Returns:
        Re-keyed communities dict with tiny communities merged.
    """
    if not communities:
        return communities

    # Build node -> community mapping
    node_to_comm: dict[str, int] = {}
    for cid, nodes in communities.items():
        for nid in nodes:
            node_to_comm[nid] = cid

    # Identify tiny communities
    tiny_cids = {cid for cid, nodes in communities.items() if len(nodes) < min_size}
    if not tiny_cids:
        return communities  # Nothing to merge

    # Find the largest community (fallback merge target)
    largest_cid = max(communities.keys(), key=lambda c: len(communities[c]))

    # For each tiny community, find the best neighbor to merge into
    merge_plan: dict[int, int] = {}  # tiny_cid -> target_cid
    for tiny_cid in tiny_cids:
        # Count edges from this community to each other community
        neighbor_edges: dict[int, int] = {}
        for nid in communities[tiny_cid]:
            if nid in G:
                for neighbor in G.neighbors(nid):
                    neighbor_cid = node_to_comm.get(neighbor)
                    if neighbor_cid is not None and neighbor_cid != tiny_cid and neighbor_cid not in tiny_cids:
                        neighbor_edges[neighbor_cid] = neighbor_edges.get(neighbor_cid, 0) + 1

        # Choose the neighbor with the most connections, or the largest community
        if neighbor_edges:
            best_neighbor = max(neighbor_edges, key=neighbor_edges.get)
        else:
            best_neighbor = largest_cid
        merge_plan[tiny_cid] = best_neighbor

    # Apply merges
    merged: dict[int, list[str]] = {}
    for cid, nodes in communities.items():
        if cid in merge_plan:
            # This tiny community gets absorbed into the target
            target = merge_plan[cid]
            if target not in merged:
                merged[target] = list(communities.get(target, []))
            merged[target].extend(nodes)
        elif cid not in merge_plan.values() or cid in merged:
            # Normal community, or a target that's already been initialized
            if cid not in merged:
                merged[cid] = list(nodes)
        else:
            # Target community not yet in merged dict
            merged[cid] = list(nodes)

    # Re-key communities sequentially
    result: dict[int, list[str]] = {}
    for i, cid in enumerate(sorted(merged.keys())):
        result[i] = merged[cid]

    return result


def _generate_community_labels(
    G: nx.Graph, communities: dict[int, list[str]]
) -> dict[int, str]:
    """Generate human-readable labels for communities.

    Uses the most-connected node in each community as the label.

    Args:
        G: NetworkX graph.
        communities: Community assignments.

    Returns:
        Dict mapping community ID to label string.
    """
    labels: dict[int, str] = {}
    for cid, node_ids in communities.items():
        # Find the best label for this community.
        # Prefer short, class-like names (e.g. "Settings", "MCPConfig") over
        # long docstrings (e.g. "Display the current model information...")
        # that graphify sometimes uses as node labels for rationale nodes.
        best_node = None
        best_degree = -1
        best_label = None

        for nid in node_ids:
            if nid not in G:
                continue
            deg = G.degree(nid)
            node_label = G.nodes[nid].get("label", "")
            source_file = G.nodes[nid].get("source_file", "")

            # Score label quality: prefer short names < long docstrings
            label_score = 0
            if node_label and len(node_label) <= 40:
                label_score = 100  # Good short label
                # Bonus for class-like names (CamelCase, no spaces at start)
                if node_label and node_label[0].isupper() and " " not in node_label[:20]:
                    label_score = 200
            elif node_label and len(node_label) <= 80:
                label_score = 50  # Medium label
            else:
                label_score = 10  # Long docstring

            # Bonus for having a source_file (not a pure rationale node)
            if source_file:
                label_score += 50

            # Tiebreak by degree
            combined = label_score * 1000 + deg
            if best_label is None or combined > best_degree:
                best_degree = combined
                best_node = nid
                best_label = node_label

        if best_label:
            # Clean up the label
            label = best_label.replace("_", " ").strip()
            if len(label) > 40:
                label = label[:37] + "..."
            labels[cid] = label
        elif best_node and best_node in G:
            labels[cid] = best_node
        else:
            labels[cid] = f"Community {cid}"

    return labels


def _show_cluster_panel(
    communities: dict[int, list[str]],
    scores: dict[int, float],
    console: Console,
) -> None:
    """Show a Rich panel with clustering results."""
    # Count community size tiers for a cleaner summary
    total = len(communities)
    meaningful = sum(1 for c in communities.values() if len(c) > 5)
    small = sum(1 for c in communities.values() if 3 <= len(c) <= 5)
    tiny = sum(1 for c in communities.values() if len(c) <= 2)

    lines = []
    for cid in sorted(communities.keys()):
        n_nodes = len(communities[cid])
        score = scores.get(cid, 0.0)
        lines.append(f"  Community {cid}: {n_nodes} nodes (cohesion: {score:.2f})")

    content = "\n".join([
        f"[cyan]Communities:[/cyan] {total} ({meaningful} major, {small} small, {tiny} trivial)",
        "",
        *lines,
    ])

    panel = Panel(
        content,
        title=f"[bold {COLORS['primary']}]🔗 Clustering[/bold {COLORS['primary']}]",
        border_style=COLORS["primary"],
        padding=(1, 2),
    )
    console.print(panel)


def _show_analysis_panel(
    god_node_list: list[dict],
    surprise_list: list[dict],
    question_list: list[dict],
    console: Console,
) -> None:
    """Show a Rich panel with analysis results."""
    lines = []

    if god_node_list:
        lines.append("[bold]God Nodes (hubs):[/bold]")
        for gn in god_node_list[:5]:
            degree = gn.get('edges', gn.get('degree', 0))
            lines.append(f"  • {gn.get('label', gn.get('id', '?'))} ({degree} edges)")
        lines.append("")

    if surprise_list:
        lines.append("[bold]Surprising Connections:[/bold]")
        for sc in surprise_list[:3]:
            lines.append(f"  • {sc.get('source', '?')} ↔ {sc.get('target', '?')}")
        lines.append("")

    if question_list:
        lines.append("[bold]Suggested Questions:[/bold]")
        for q in question_list[:3]:
            lines.append(f"  • {q.get('question', '?')}")

    panel = Panel(
        "\n".join(lines),
        title=f"[bold {COLORS['primary']}]🔍 Analysis[/bold {COLORS['primary']}]",
        border_style=COLORS["primary"],
        padding=(1, 2),
    )
    console.print(panel)


def _show_export_panel(outputs: dict[str, Path], console: Console) -> None:
    """Show a Rich panel with export results."""
    lines = []
    for fmt, path in outputs.items():
        size = path.stat().st_size if path.exists() else 0
        lines.append(f"  [cyan]{fmt.upper():6s}[/cyan] {path} ({size:,} bytes)")

    panel = Panel(
        "\n".join(lines),
        title=f"[bold {COLORS['primary']}]📦 Export[/bold {COLORS['primary']}]",
        border_style=COLORS["primary"],
        padding=(1, 2),
    )
    console.print(panel)
"""Project graph reader — load, parse, and summarize the project graph.

Extracted from ``GraphContextMiddleware`` so the graph parsing logic is
reusable outside the middleware stack (TUI dashboard, CLI reports, tests).

Usage::

    from novacode_cli.bootstrap.graph_reader import ProjectGraphReader

    reader = ProjectGraphReader(workspace_root="/path/to/project")
    summary = reader.load()
    if summary:
        print(summary.to_prompt_section())
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

# Maximum characters for the graph context section (~1,500 tokens at 4 chars/token).
MAX_GRAPH_CONTEXT_CHARS = 6_000

# Cache TTL in seconds — reload graph if it's been more than this since last load.
_GRAPH_CACHE_TTL = 300.0  # 5 minutes


class GraphSummary:
    """Parsed summary of a project graph, ready for injection into prompts.

    Attributes:
        communities: Dict mapping community ID to label and node count.
        god_nodes: List of high-degree hub nodes.
        surprising_connections: List of cross-community connections.
        key_files: List of important source files.
        total_nodes: Total number of nodes in the graph.
        total_edges: Total number of edges in the graph.
    """

    def __init__(self, graph_data: dict[str, Any]) -> None:
        """Parse graph data into a structured summary.

        Args:
            graph_data: Parsed JSON from project-graph.json.
        """
        self.total_nodes = graph_data.get("total_nodes", 0)
        self.total_edges = graph_data.get("total_edges", 0)

        # Parse communities
        self.communities: list[dict[str, Any]] = graph_data.get("communities", [])

        # Parse god nodes
        self.god_nodes: list[dict[str, Any]] = graph_data.get("god_nodes", [])

        # Parse surprising connections
        self.surprising_connections: list[dict[str, Any]] = graph_data.get(
            "surprising_connections", []
        )

        # Parse key files
        self.key_files: list[dict[str, str]] = graph_data.get("key_files", [])

    def to_prompt_section(self) -> str:
        """Format a minimal *legend* of the project graph for the system prompt.

        Deliberately limited to total counts + module (community) names — the
        cheap orientation the agent needs to know a graph exists and what the
        module boundaries are. The detailed "insight" payloads (god nodes,
        cross-module connections, key files, and per-symbol locations) are
        intentionally NOT injected: they live behind ``query_project_graph`` so
        the agent looks them up on demand instead of reasoning from a stale,
        heuristic summary that would sit in every prompt and suppress tool use.

        Returns:
            Formatted markdown legend, or an empty string when the graph has no
            content (so the caller skips injection).
        """
        if not self.total_nodes and not self.communities:
            return ""

        lines: list[str] = [
            f"Project graph: {self.total_nodes} nodes, {self.total_edges} edges"
        ]

        # Communities (module boundaries) — names only, the one thing worth
        # standing in context. Everything else is tool-only.
        if self.communities:
            lines.append("")
            lines.append("### Module Boundaries (Communities)")
            for comm in self.communities[:12]:  # Limit to 12 communities
                label = comm.get("label", f"Community {comm.get('id', '?')}")
                count = comm.get("node_count", len(comm.get("nodes", [])))
                lines.append(f"- **{label}**: {count} components")
            if len(self.communities) > 12:
                lines.append(f"- ... and {len(self.communities) - 12} more modules")

        result = "\n".join(lines)
        if len(result) > MAX_GRAPH_CONTEXT_CHARS:
            result = result[: MAX_GRAPH_CONTEXT_CHARS - 3] + "..."
        return result


class ProjectGraphReader:
    """Load, cache, and parse the project graph from ``.nova/project-graph.json``.

    The reader handles file I/O, caching (TTL + mtime), and extraction of
    structured summaries (communities, god nodes, key files) from the raw
    node-link JSON format produced by ``/init``.

    Thread-safe for read operations; the cache is updated atomically.
    """

    def __init__(self, workspace_root: str | Path) -> None:
        """Initialize the reader.

        Args:
            workspace_root: Path to the project workspace root.
        """
        self._workspace_root = Path(workspace_root)
        self._graph_summary: GraphSummary | None = None
        self._graph_mtime: float = 0.0
        self._last_load_time: float = 0.0

    def graph_path(self) -> Path:
        """Return the path to the project graph JSON file."""
        return self._workspace_root / ".nova" / "project-graph.json"

    def _index_path(self) -> Path:
        """Return the path to the graph index JSON file."""
        return self._workspace_root / ".nova" / "graph-index.json"

    def _load_index(self) -> dict[str, Any] | None:
        """Load the pre-computed graph index.

        Returns:
            Parsed index data, or None if no index exists.
        """
        index_path = self._index_path()
        if not index_path.exists():
            return None
        try:
            return json.loads(index_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            return None

    def _extract_from_index(self, index: dict[str, Any]) -> dict[str, Any]:
        """Convert index data into the same format as _extract_summary.

        Args:
            index: Parsed graph-index.json data.

        Returns:
            Dict with communities, god_nodes, total_nodes, total_edges.
        """
        community_map = index.get("community_map", {})
        communities = []
        for cid, cdata in community_map.items():
            communities.append({
                "id": int(cid),
                "label": cdata.get("label", f"Community {cid}"),
                "node_count": cdata.get("node_count", 0),
                "nodes": cdata.get("files", []),
            })

        return {
            "total_nodes": sum(c.get("node_count", 0) for c in communities),
            "total_edges": index.get("total_edges", 0),
            "communities": communities,
            "god_nodes": index.get("god_nodes", []),
            "surprising_connections": [],
            "key_files": [],
        }

    def load(self) -> GraphSummary | None:
        """Load and parse the project graph, with caching.

        Returns:
            Parsed graph summary, or None if no graph exists.
        """
        # Try index first (fast path)
        index_path = self._index_path()
        if index_path.exists():
            try:
                current_mtime = index_path.stat().st_mtime
            except OSError:
                current_mtime = 0.0

            now = time.time()
            cache_expired = (now - self._last_load_time) > _GRAPH_CACHE_TTL
            file_changed = current_mtime != self._graph_mtime

            if not self._graph_summary or cache_expired or file_changed:
                index = self._load_index()
                if index is not None:
                    graph_data = self._extract_from_index(index)
                    self._graph_summary = GraphSummary(graph_data)
                    self._graph_mtime = current_mtime
                    self._last_load_time = now
                    return self._graph_summary

            return self._graph_summary

        # Fall back to full graph JSON (slow path)
        graph_path = self.graph_path()
        if not graph_path.exists():
            return None

        # Check if we need to reload (file changed or cache expired)
        try:
            current_mtime = graph_path.stat().st_mtime
        except OSError:
            return self._graph_summary

        now = time.time()
        cache_expired = (now - self._last_load_time) > _GRAPH_CACHE_TTL
        file_changed = current_mtime != self._graph_mtime

        if self._graph_summary and not cache_expired and not file_changed:
            return self._graph_summary

        # Load and parse
        try:
            data = json.loads(graph_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            return self._graph_summary  # Return cached if available, else None

        # Extract structured data from the node-link format
        graph_data = self._extract_summary(data)

        self._graph_summary = GraphSummary(graph_data)
        self._graph_mtime = current_mtime
        self._last_load_time = now

        return self._graph_summary

    def _extract_summary(self, data: dict[str, Any]) -> dict[str, Any]:
        """Extract a structured summary from the node-link graph JSON.

        The project-graph.json is in NetworkX node-link format with
        additional metadata from graphify export.

        Args:
            data: Parsed JSON from project-graph.json.

        Returns:
            Dict with communities, god_nodes, surprising_connections,
            key_files, total_nodes, total_edges.
        """
        result: dict[str, Any] = {
            "total_nodes": 0,
            "total_edges": 0,
            "communities": [],
            "god_nodes": [],
            "surprising_connections": [],
            "key_files": [],
        }

        # Node-link format (graphify uses "links" not "edges")
        nodes = data.get("nodes", [])
        links = data.get("links", data.get("edges", []))
        result["total_nodes"] = len(nodes)
        result["total_edges"] = len(links)

        # Build node lookup
        node_map: dict[str, dict] = {}
        for node in nodes:
            nid = node.get("id", "")
            node_map[nid] = node

        # Compute degree for each node from links
        degree_map: dict[str, int] = {}
        for link in links:
            src = link.get("source", "")
            tgt = link.get("target", "")
            degree_map[src] = degree_map.get(src, 0) + 1
            degree_map[tgt] = degree_map.get(tgt, 0) + 1

        # Check for metadata from graphify export first (fast path)
        # The /init pipeline enriches the JSON with pre-computed analysis
        if "metadata" in data:
            meta = data["metadata"]
            if "god_nodes" in meta:
                result["god_nodes"] = meta["god_nodes"][:6]
            if "surprising_connections" in meta:
                result["surprising_connections"] = meta["surprising_connections"][:4]
            if "key_files" in meta:
                result["key_files"] = meta["key_files"][:10]
            if "communities" in meta:
                # Use pre-computed community summaries from metadata
                result["communities"] = meta["communities"][:12]
            elif "community_labels" in meta:
                # Update community labels from metadata
                labels = meta["community_labels"]
                for comm in result["communities"]:
                    cid = comm.get("id")
                    if cid in labels:
                        comm["label"] = labels[cid]

        # Extract communities from node attributes (if not already in metadata)
        if not result["communities"]:
            communities_map: dict[int, list[str]] = {}
            for node in nodes:
                cid = node.get("community", node.get("group", None))
                if cid is not None:
                    cid = int(cid)
                    if cid not in communities_map:
                        communities_map[cid] = []
                    communities_map[cid].append(node.get("id", ""))

            if communities_map:
                for cid in sorted(communities_map.keys()):
                    members = communities_map[cid]
                    # Find the best label — prefer short class-like names over
                    # long docstrings that graphify uses for rationale nodes.
                    best_label = f"Community {cid}"
                    best_score = -1
                    for mid in members:
                        deg = degree_map.get(mid, 0)
                        node = node_map.get(mid, {})
                        # `or mid` because a node may have an explicit null label
                        # (else best_label could become None → .replace crash).
                        nl = node.get("label") or mid
                        sf = node.get("source_file", "")

                        score = 0
                        if nl and len(nl) <= 40:
                            score = 100
                            if nl and nl[0].isupper() and " " not in nl[:20]:
                                score = 200
                        elif nl and len(nl) <= 80:
                            score = 50
                        else:
                            score = 10
                        if sf:
                            score += 50
                        combined = score * 1000 + deg
                        if combined > best_score:
                            best_score = combined
                            best_label = nl

                    best_label = best_label.replace("_", " ").strip()
                    if len(best_label) > 40:
                        best_label = best_label[:37] + "..."
                    result["communities"].append({
                        "id": cid,
                        "label": best_label,
                        "node_count": len(members),
                        "nodes": members,
                    })

        # Normalize existing god_nodes: ensure 'edges' key exists for middleware.
        # graphify.analyze.god_nodes returns 'degree', not 'edges'.
        if result["god_nodes"]:
            for gn in result["god_nodes"]:
                if "edges" not in gn and "degree" in gn:
                    gn["edges"] = gn["degree"]

        # Compute god nodes from degree (if not already in metadata)
        if not result["god_nodes"]:
            sorted_nodes = sorted(degree_map.items(), key=lambda x: x[1], reverse=True)
            for nid, degree in sorted_nodes[:6]:
                node = node_map.get(nid, {})
                result["god_nodes"].append({
                    "id": nid,
                    "label": node.get("label", nid),
                    "edges": degree,
                    "source_file": node.get("source_file", ""),
                })

        # Extract key files from god nodes
        if not result["key_files"]:
            seen_files: set[str] = set()
            for gn in result["god_nodes"]:
                sf = gn.get("source_file", "")
                if sf and sf not in seen_files:
                    seen_files.add(sf)
                    result["key_files"].append({
                        "path": sf,
                        "purpose": f"Central hub: {gn.get('label', gn.get('id', '?'))}",
                    })

            # Also add entry points
            for node in nodes:
                label = (node.get("label") or "").lower()
                nid = node.get("id", "")
                sf = node.get("source_file", "")
                if sf and sf not in seen_files:
                    if any(kw in label for kw in ["main", "cli", "app", "entry"]):
                        seen_files.add(sf)
                        result["key_files"].append({
                            "path": sf,
                            "purpose": f"Entry point: {node.get('label', nid)}",
                        })

            # Limit key files
            result["key_files"] = result["key_files"][:8]

        return result


__all__ = [
    "GraphSummary",
    "ProjectGraphReader",
    "MAX_GRAPH_CONTEXT_CHARS",
]
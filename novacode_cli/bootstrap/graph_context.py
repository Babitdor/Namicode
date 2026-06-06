"""Graph context middleware for injecting project graph knowledge into system prompts.

This middleware loads the project graph from `.nova/project-graph.json` (created
by `/init`) on the first agent turn and injects a structured summary into every
system prompt. This gives the agent architectural awareness — communities, god
nodes, key files, and surprising connections — on every session, not just during
`/init`.

The graph summary includes:
- Community structure (module boundaries)
- God nodes (central hubs that connect many modules)
- Surprising connections (cross-community links)
- Key files (most important files in the project)

Enabled by default when `.nova/project-graph.json` exists; silently skipped
when no graph is available.
"""

from __future__ import annotations

import json
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from langchain.agents.middleware.types import (
    AgentMiddleware,
    AgentState,
    ModelRequest,
    ModelResponse,
)
from langchain_core.messages import SystemMessage

# Maximum characters for the graph context section (~1,500 tokens at 4 chars/token).
MAX_GRAPH_CONTEXT_CHARS = 6_000

# Cache TTL in seconds — reload graph if it's been more than this since last load.
_GRAPH_CACHE_TTL = 300.0  # 5 minutes


class _GraphSummary:
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
        """Format the graph summary as a system prompt section.

        Returns:
            Formatted markdown section for injection into the system prompt.
            Empty string if the graph has no useful content.
        """
        lines: list[str] = []

        # Header
        lines.append(f"Project graph: {self.total_nodes} nodes, {self.total_edges} edges")
        lines.append("")

        # Communities (module boundaries)
        if self.communities:
            lines.append("### Module Boundaries (Communities)")
            lines.append("")
            for comm in self.communities[:12]:  # Limit to 12 communities
                label = comm.get("label", f"Community {comm.get('id', '?')}")
                count = comm.get("node_count", len(comm.get("nodes", [])))
                lines.append(f"- **{label}**: {count} components")
            if len(self.communities) > 12:
                lines.append(f"- ... and {len(self.communities) - 12} more modules")
            lines.append("")

        # God nodes (central hubs)
        if self.god_nodes:
            lines.append("### Central Hubs (God Nodes)")
            lines.append("")
            for gn in self.god_nodes[:6]:
                label = gn.get("label", gn.get("id", "?"))
                edges = gn.get("edges", gn.get("degree", 0))
                lines.append(f"- **{label}** ({edges} connections) — changes here affect many modules")
            lines.append("")

        # Surprising connections
        if self.surprising_connections:
            lines.append("### Cross-Module Connections")
            lines.append("")
            for sc in self.surprising_connections[:4]:
                source = sc.get("source", "?")
                target = sc.get("target", "?")
                # graphify often uses docstrings as 'source' labels for rationale
                # nodes — they're not useful as display names.  Prefer source_files.
                source_files = sc.get("source_files", [])
                if source_files:
                    source_display = source_files[0]
                    if len(source_files) > 1:
                        source_display += f", {source_files[1]}"
                else:
                    # Truncate long docstring labels
                    if len(source) > 50:
                        source_display = source[:47] + "..."
                    else:
                        source_display = source
                reason = sc.get("why", "")
                # graphify's 'why' often embeds the full source docstring as a quote;
                # strip it to keep the reason concise for the agent
                if "peripheral node" in reason:
                    reason = "cross-module link"
                elif len(reason) > 80:
                    reason = reason[:77] + "..."
                lines.append(f"- `{source_display}` ↔ `{target}` — {reason}" if reason else f"- `{source_display}` ↔ `{target}`")
            lines.append("")

        # Key files
        if self.key_files:
            lines.append("### Key Files")
            lines.append("")
            for kf in self.key_files[:8]:
                path = kf.get("path", "?")
                purpose = kf.get("purpose", "")
                lines.append(f"- `{path}` — {purpose}")
            lines.append("")

        result = "\n".join(lines)
        if len(result) > MAX_GRAPH_CONTEXT_CHARS:
            result = result[: MAX_GRAPH_CONTEXT_CHARS - 3] + "..."
        return result


class GraphContextMiddleware(AgentMiddleware):
    """Inject project graph context into the system prompt.

    Loads `.nova/project-graph.json` on the first turn and caches it for
    the session. Injects a structured summary of communities, god nodes,
    and key files into every system prompt.

    This gives the agent architectural awareness without requiring the
    user to run `/init` every session — the graph is loaded automatically
    when available.
    """

    state_schema = AgentState

    def __init__(
        self,
        *,
        workspace_root: str,
        enabled: bool | None = None,
    ) -> None:
        """Initialize the graph context middleware.

        Args:
            workspace_root: Path to the project workspace root.
            enabled: If False, this middleware is a no-op. Defaults to True.
        """
        self._workspace_root = Path(workspace_root)
        self._enabled = enabled if enabled is not None else True
        self._graph_summary: _GraphSummary | None = None
        self._graph_mtime: float = 0.0
        self._last_load_time: float = 0.0

    def _graph_path(self) -> Path:
        """Return the path to the project graph JSON file."""
        return self._workspace_root / ".nova" / "project-graph.json"

    def _load_graph(self) -> _GraphSummary | None:
        """Load and parse the project graph, with caching.

        Returns:
            Parsed graph summary, or None if no graph exists.
        """
        graph_path = self._graph_path()
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

        self._graph_summary = _GraphSummary(graph_data)
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

    def before_agent(  # type: ignore[override]
        self,
        state: AgentState,
    ) -> None:
        """Pre-warm the instance cache on session start."""
        if not self._enabled:
            return None
        self._load_graph()
        return None

    def _inject(self, request: ModelRequest) -> ModelRequest:
        """Inject graph context into the system prompt."""
        if not self._enabled:
            return request

        summary = self._load_graph()
        if not summary:
            return request

        graph_context = summary.to_prompt_section()
        if not graph_context:
            return request

        block = (
            f"[Project Graph]\n{graph_context}\n"
            "This is a high-level summary only — most files and symbols are NOT "
            "listed above. Before reading or editing an unfamiliar file, and to "
            "find what a specific file/symbol connects to, its community, or "
            "whether it's a high-degree hub (blast radius), call "
            '`query_project_graph("<file or symbol>")` for the targeted detail.\n'
            "[/Project Graph]"
        )
        system_prompt = request.system_prompt
        new_prompt = (system_prompt + "\n\n" + block) if system_prompt else block
        return request.override(system_message=SystemMessage(new_prompt))

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        """Inject graph context into the system prompt."""
        return handler(self._inject(request))

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        """Async version of wrap_model_call."""
        return await handler(self._inject(request))
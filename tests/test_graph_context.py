"""Tests for the slimmed GraphContextMiddleware injection.

The always-on system-prompt injection is a *legend* only: total counts + module
(community) names. God nodes, cross-module connections, key files, and per-symbol
detail are intentionally NOT injected — they live behind ``query_project_graph``.
"""

from __future__ import annotations

from novacode_cli.bootstrap.graph_context import _GraphSummary


def _summary() -> _GraphSummary:
    return _GraphSummary(
        {
            "total_nodes": 100,
            "total_edges": 250,
            "communities": [
                {"id": 0, "label": "Auth", "node_count": 12},
                {"id": 1, "label": "API", "node_count": 8},
            ],
            # These richer payloads must NOT appear in the injected legend.
            "god_nodes": [{"label": "core_agent", "edges": 42}],
            "surprising_connections": [
                {"source": "a.py", "target": "b.py", "why": "shared state"}
            ],
            "key_files": [{"path": "main.py", "purpose": "entry point"}],
        }
    )


class TestLegendInjection:
    def test_includes_counts_and_community_names(self):
        section = _summary().to_prompt_section()
        assert "100 nodes, 250 edges" in section
        assert "Module Boundaries" in section
        assert "Auth" in section and "API" in section

    def test_excludes_tool_only_detail(self):
        section = _summary().to_prompt_section()
        # Hubs / connections / key files are tool-only now.
        assert "Central Hubs" not in section
        assert "Cross-Module" not in section
        assert "Key Files" not in section
        assert "core_agent" not in section  # god node label
        assert "a.py" not in section and "b.py" not in section  # connection
        assert "main.py" not in section  # key file

    def test_empty_graph_returns_empty_string(self):
        empty = _GraphSummary({"total_nodes": 0, "total_edges": 0, "communities": []})
        assert empty.to_prompt_section() == ""

    def test_legend_is_compact(self):
        # The whole point: the standing injection is small.
        section = _summary().to_prompt_section()
        assert len(section) < 600, len(section)

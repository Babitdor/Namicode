"""Tests for the slimmed GraphContextMiddleware injection.

The always-on system-prompt injection is a *legend* only: total counts + module
(community) names. God nodes, cross-module connections, key files, and per-symbol
detail are intentionally NOT injected — they live behind ``query_project_graph``.
"""

from __future__ import annotations

import importlib.util
import sys
import pytest

# Import graph_reader directly to avoid bootstrap/__init__.py pulling in langchain
_spec = importlib.util.spec_from_file_location(
    "novacode_cli.bootstrap.graph_reader",
    "novacode_cli/bootstrap/graph_reader.py",
)
_graph_reader = importlib.util.module_from_spec(_spec)
sys.modules["novacode_cli.bootstrap.graph_reader"] = _graph_reader
_spec.loader.exec_module(_graph_reader)
_GraphSummary = _graph_reader.GraphSummary


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


@pytest.mark.asyncio
async def test_query_project_graph_async(monkeypatch):
    import pytest
    from pathlib import Path
    from novacode_cli.tools.graph_tools import query_project_graph

    monkeypatch.setattr("novacode_cli.config.config.settings.project_root", Path("/dummy"))
    monkeypatch.setattr(
        "novacode_cli.tools.graph_tools._load_raw_graph",
        lambda path: {
            "nodes": [{"id": "node1", "label": "NodeOne", "source_file": "src/node1.py", "community": 0}],
            "metadata": {
                "communities": [{"id": 0, "label": "Community Zero", "node_count": 1, "nodes": ["node1"]}],
                "god_nodes": [],
                "surprising_connections": [],
            }
        }
    )

    res = await query_project_graph.ainvoke("NodeOne")
    assert "Matching Nodes (1 found)" in res
    assert "NodeOne" in res


@pytest.mark.asyncio
async def test_graph_context_middleware_async(monkeypatch):
    import pytest
    from pathlib import Path
    from langchain_core.messages import SystemMessage
    from novacode_cli.bootstrap.graph_context import GraphContextMiddleware

    class _Req:
        def __init__(self, system_prompt="Base prompt"):
            self.system_prompt = system_prompt
            self.system_message = None

        def override(self, system_message):
            self.system_message = system_message
            self.system_prompt = getattr(system_message, "content", "")
            return self

    # Mock settings and the reader's load method
    middleware = GraphContextMiddleware(workspace_root="/dummy")
    monkeypatch.setattr(middleware._reader, "load", lambda: _summary())

    request = _Req("Base prompt")

    async def dummy_handler(req):
        return req

    # Wrap the call
    res = await middleware.awrap_model_call(request, dummy_handler)
    assert "[Project Graph]" in res.system_prompt
    assert "100 nodes, 250 edges" in res.system_prompt



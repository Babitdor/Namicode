"""Tests for graph index building."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest


def _make_sample_graph_data() -> dict:
    """Build a minimal graph dataset matching the enriched JSON format."""
    return {
        "total_nodes": 4,
        "total_edges": 3,
        "nodes": [
            {"id": "func_a", "label": "func_a", "source_file": "src/a.py",
             "community": 0, "edges": 2},
            {"id": "func_b", "label": "func_b", "source_file": "src/b.py",
             "community": 0, "edges": 1},
            {"id": "ClassC", "label": "ClassC", "source_file": "src/c.py",
             "community": 1, "edges": 3},
            {"id": "func_d", "label": "func_d", "source_file": "src/a.py",
             "community": 0, "edges": 0},
        ],
        "links": [
            {"source": "func_a", "target": "func_b"},
            {"source": "func_a", "target": "ClassC"},
            {"source": "ClassC", "target": "func_d"},
        ],
        "metadata": {
            "communities": [
                {"id": 0, "label": "Core", "nodes": ["func_a", "func_b", "func_d"]},
                {"id": 1, "label": "UI", "nodes": ["ClassC"]},
            ],
            "god_nodes": [
                {"label": "func_a", "edges": 2, "source_file": "src/a.py"},
            ],
        },
    }


def test_build_graph_index_creates_file():
    """_build_graph_index writes a valid JSON index file."""
    from novacode_cli.init.graph import _build_graph_index

    data = _make_sample_graph_data()
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "graph-index.json"
        _build_graph_index(data, str(out))
        assert out.exists()
        idx = json.loads(out.read_text(encoding="utf-8"))
        assert idx["version"] == 1
        assert "symbol_map" in idx
        assert "file_map" in idx
        assert "community_map" in idx
        assert "god_nodes" in idx


def test_build_graph_index_symbol_map():
    """symbol_map maps symbol names to community/file/connections."""
    from novacode_cli.init.graph import _build_graph_index

    data = _make_sample_graph_data()
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "graph-index.json"
        _build_graph_index(data, str(out))
        idx = json.loads(out.read_text(encoding="utf-8"))
        sm = idx["symbol_map"]
        assert sm["func_a"] == {"community": 0, "file": "src/a.py", "connections": 2}
        assert sm["ClassC"] == {"community": 1, "file": "src/c.py", "connections": 3}


def test_build_graph_index_file_map():
    """file_map groups symbols by source file."""
    from novacode_cli.init.graph import _build_graph_index

    data = _make_sample_graph_data()
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "graph-index.json"
        _build_graph_index(data, str(out))
        idx = json.loads(out.read_text(encoding="utf-8"))
        fm = idx["file_map"]
        assert "src/a.py" in fm
        assert fm["src/a.py"]["community"] == 0
        assert set(fm["src/a.py"]["symbols"]) == {"func_a", "func_d"}
        assert fm["src/a.py"]["connections"] == 2


def test_build_graph_index_community_map():
    """community_map lists files per community."""
    from novacode_cli.init.graph import _build_graph_index

    data = _make_sample_graph_data()
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "graph-index.json"
        _build_graph_index(data, str(out))
        idx = json.loads(out.read_text(encoding="utf-8"))
        cm = idx["community_map"]
        assert "0" in cm
        assert cm["0"]["label"] == "Core"
        assert cm["0"]["node_count"] == 3
        assert "src/a.py" in cm["0"]["files"]
        assert "src/b.py" in cm["0"]["files"]


def test_build_graph_index_god_nodes():
    """god_nodes are passed through from metadata."""
    from novacode_cli.init.graph import _build_graph_index

    data = _make_sample_graph_data()
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "graph-index.json"
        _build_graph_index(data, str(out))
        idx = json.loads(out.read_text(encoding="utf-8"))
        assert len(idx["god_nodes"]) == 1
        assert idx["god_nodes"][0]["label"] == "func_a"

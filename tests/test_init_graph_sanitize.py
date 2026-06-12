"""Regression tests for graph-extraction sanitization.

The semantic-extraction stage of /init is LLM-authored; weak models sometimes
emit an edge ``weight`` (or ``confidence_score``) as an object rather than a
number, which crashed NetworkX/graphify's weighted clustering with
``'>' not supported between instances of 'float' and 'dict'`` (and similar).
``sanitize_graph_extraction`` coerces those fields so /init can't be crashed by
a single bad fragment.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from novacode_cli.init.graph import (
    _coerce_float,
    build_project_graph,
    sanitize_graph_extraction,
)


class TestCoerceFloat:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (1, 1.0),
            (2.5, 2.5),
            ("3.5", 3.5),
            ("  4 ", 4.0),
            ({"v": 1}, 1.0),     # dict → default
            ([1], 1.0),          # list → default
            (None, 1.0),         # None → default
            (True, 1.0),         # bool → default (not numeric here)
            ("nope", 1.0),       # unparseable str → default
        ],
    )
    def test_coerce(self, value, expected):
        assert _coerce_float(value, 1.0) == expected


class TestSanitizeExtraction:
    def test_dict_weight_coerced(self):
        ext = {"edges": [{"weight": {"value": 1.0}}, {"weight": "2"}, {}]}
        out = sanitize_graph_extraction(ext)
        assert [e["weight"] for e in out["edges"]] == [1.0, 2.0, 1.0]

    def test_confidence_score_coerced_only_when_present(self):
        ext = {"edges": [{"weight": 1, "confidence_score": {"x": 1}}, {"weight": 1}]}
        out = sanitize_graph_extraction(ext)
        assert out["edges"][0]["confidence_score"] == 1.0
        assert "confidence_score" not in out["edges"][1]

    def test_hyperedge_confidence_coerced(self):
        ext = {"hyperedges": [{"confidence_score": {"bad": True}}]}
        out = sanitize_graph_extraction(ext)
        assert out["hyperedges"][0]["confidence_score"] == 1.0

    def test_non_dict_input_passes_through(self):
        assert sanitize_graph_extraction(None) is None

    def test_handles_missing_keys(self):
        assert sanitize_graph_extraction({}) == {}

    # ── node sanitization (the second class of /init crash) ──────────────

    def test_drops_nodes_with_unusable_id(self):
        ext = {
            "nodes": [
                {"id": "good", "label": "A"},
                {"id": None, "label": "B"},      # None id → "None cannot be a node"
                {"id": "   ", "label": "C"},     # blank id
                {"label": "D"},                  # missing id
            ]
        }
        out = sanitize_graph_extraction(ext)
        assert [n["id"] for n in out["nodes"]] == ["good"]

    def test_none_label_falls_back_to_id(self):
        # graphify only falls back to id when the label key is MISSING, not when
        # present-but-None — a None label crashes export (re.sub/normalize on None).
        ext = {"nodes": [{"id": "n1", "label": None}, {"id": "n2"}]}
        out = sanitize_graph_extraction(ext)
        assert out["nodes"][0]["label"] == "n1"
        assert out["nodes"][1]["label"] == "n2"

    def test_node_dict_weight_and_none_source_file_coerced(self):
        ext = {"nodes": [{"id": "n1", "weight": {"v": 1}, "source_file": None}]}
        out = sanitize_graph_extraction(ext)
        node = out["nodes"][0]
        assert node["weight"] == 0.0
        assert node["source_file"] == ""

    def test_dict_edge_endpoints_coerced_to_str(self):
        ext = {
            "nodes": [{"id": "n1", "label": "A"}],
            "edges": [{"source": {"k": 1}, "target": "n1", "relation": "r"}],
        }
        out = sanitize_graph_extraction(ext)
        assert isinstance(out["edges"][0]["source"], str)

    def test_every_edge_gets_numeric_weight(self):
        # Weight is guaranteed on every edge (NetworkX needs it), even when the
        # fragment omitted it or emitted a dict.
        ext = {"edges": [{"weight": {"v": 1}}, {"weight": "2"}, {}]}
        out = sanitize_graph_extraction(ext)
        assert [e["weight"] for e in out["edges"]] == [1.0, 2.0, 1.0]


def test_build_and_export_survive_none_label(tmp_path: Path):
    """A node with label=None must not crash graphify build/export.

    Error 2 repro: ``expected string or bytes-like object, got 'NoneType'`` /
    ``normalize()`` TypeError from a None label reaching the exporter.
    """
    from novacode_cli.init.graph import (
        analyze_project_graph,
        cluster_project_graph,
        export_project_graph,
    )

    ext = {
        "nodes": [
            {"id": "n1", "label": None, "type": "concept", "source_file": None},
            {"id": "n2", "label": "B", "type": "code", "source_file": "b.py"},
        ],
        "edges": [{"source": "n1", "target": "n2", "relation": "r", "weight": 1.0}],
        "hyperedges": [],
    }
    G = build_project_graph(ext, None)
    if G is None:
        pytest.skip("graphify not available")
    communities = cluster_project_graph(G, None)
    analysis = analyze_project_graph(G, communities, None)
    export_project_graph(
        G=G, communities=communities, analysis=analysis,
        output_dir=tmp_path, console=None, include_html=True,
    )
    assert (tmp_path / "project-graph.json").exists()


def test_build_project_graph_survives_malformed_weights():
    """The reproduced /init crash: a dict-valued weight no longer kills the build."""
    ext = {
        "nodes": [
            {"id": "a_x", "label": "X", "file_type": "code", "source_file": "a.py"},
            {"id": "b_y", "label": "Y", "file_type": "code", "source_file": "b.py"},
        ],
        "edges": [
            {"source": "a_x", "target": "b_y", "relation": "calls",
             "weight": {"value": 1.0}, "confidence_score": {"v": 1}, "source_file": "a.py"},
        ],
        "hyperedges": [],
    }
    G = build_project_graph(ext, None)
    if G is None:  # graphify not installed in this environment
        pytest.skip("graphify not available")
    # Every edge weight is numeric after the build.
    assert all(isinstance(G[u][v].get("weight", 1.0), (int, float)) for u, v in G.edges())

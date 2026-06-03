"""Tests for graphify Stage B: LLM semantic extraction + merge in /init."""

import asyncio
from pathlib import Path

import novacode_cli.init.extract as ex


class _Resp:
    def __init__(self, content):
        self.content = content


def test_parse_extraction_json_handles_fences_and_prose():
    fence = "`" * 3
    assert ex._parse_extraction_json(f'{fence}json\n{{"nodes":[],"edges":[]}}\n{fence}') == {
        "nodes": [],
        "edges": [],
    }
    got = ex._parse_extraction_json('blah {"nodes":[{"id":"a"}],"edges":[]} end')
    assert got["nodes"][0]["id"] == "a"
    assert ex._parse_extraction_json("not json") is None


def test_parse_extraction_json_recovers_model_malformations():
    """Weak models mangle the fragment in predictable ways — all must recover."""
    import json

    ok = {"nodes": [{"id": "a"}], "edges": []}
    raw = json.dumps(ok)

    # whole JSON wrapped in surrounding quotes (single and double)
    assert ex._parse_extraction_json("'" + raw + "'") == ok
    assert ex._parse_extraction_json('"' + raw + '"') == ok
    # double-encoded: a JSON string whose value is the JSON object
    assert ex._parse_extraction_json(json.dumps(raw)) == ok
    # trailing "Extra data" after a complete object
    assert ex._parse_extraction_json(raw + "\n" + raw) == ok
    # Python-repr dict (single quotes) — e.g. a str()'d dict
    assert ex._parse_extraction_json(str(ok)) == ok
    # fenced + surrounding whitespace
    fence = "`" * 3
    assert ex._parse_extraction_json(f"{fence}\n{raw}\n{fence}") == ok


def test_merge_ast_semantic_ast_wins_and_keeps_hyperedges():
    ast = {
        "nodes": [{"id": "x"}],
        "edges": [{"source": "x", "target": "y", "relation": "imports"}],
        "input_tokens": 1,
        "output_tokens": 0,
        "hyperedges": [],
    }
    sem = {
        "nodes": [{"id": "c"}],
        "edges": [{"source": "c", "target": "d", "relation": "calls"}],
        "hyperedges": [{"id": "h1"}],
    }
    m = ex.merge_ast_semantic(ast, sem)
    assert {n["id"] for n in m["nodes"]} == {"x", "c"}
    assert len(m["edges"]) == 2
    assert len(m["hyperedges"]) == 1


def _model_returning(payload):
    class _M:
        async def ainvoke(self, msgs):
            return _Resp(payload)

    return _M()


def test_semantic_extract_runs_over_docs(tmp_path, monkeypatch):
    (tmp_path / "README.md").write_text("Auth uses JWT.", encoding="utf-8")
    detection = {"files": {"document": ["README.md"], "paper": [], "code": []}}
    payload = (
        '{"nodes":[{"id":"readme_jwt","label":"JWT","file_type":"document",'
        '"source_file":"README.md"}],"edges":[{"source":"readme_jwt",'
        '"target":"readme_db","relation":"conceptually_related_to",'
        '"confidence":"INFERRED","confidence_score":0.7,"source_file":"README.md"}],'
        '"hyperedges":[]}'
    )
    monkeypatch.setattr(
        "novacode_cli.config.model_create.create_model",
        lambda *a, **k: _model_returning(payload),
    )
    out = asyncio.run(ex.semantic_extract_project(tmp_path, detection, deep=False))
    assert out["nodes"][0]["id"] == "readme_jwt"
    assert out["edges"][0]["relation"] == "conceptually_related_to"


def test_semantic_extract_empty_corpus_no_model(tmp_path, monkeypatch):
    # No docs/papers/code -> returns empty without needing a model.
    called = {"n": 0}

    def _boom(*a, **k):
        called["n"] += 1
        raise AssertionError("model should not be created for empty corpus")

    monkeypatch.setattr("novacode_cli.config.model_create.create_model", _boom)
    out = asyncio.run(
        ex.semantic_extract_project(
            tmp_path, {"files": {"document": [], "paper": [], "code": []}}
        )
    )
    assert out["nodes"] == [] and out["edges"] == []
    assert called["n"] == 0


def test_semantic_extract_model_error_returns_empty(tmp_path, monkeypatch):
    (tmp_path / "a.md").write_text("hello", encoding="utf-8")

    class _Err:
        async def ainvoke(self, msgs):
            raise RuntimeError("boom")

    monkeypatch.setattr(
        "novacode_cli.config.model_create.create_model", lambda *a, **k: _Err()
    )
    out = asyncio.run(
        ex.semantic_extract_project(
            tmp_path, {"files": {"document": ["a.md"], "paper": [], "code": []}}
        )
    )
    assert out["nodes"] == [] and out["edges"] == []

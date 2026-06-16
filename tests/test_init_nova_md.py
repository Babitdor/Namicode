"""Generated NOVA.md must document the project graph and render graph data."""

import asyncio

import novacode_cli.init.generate as gen
from novacode_cli.prompts import render_template

_FACTS_CTX = {
    "project_name": "nova",
    "project_description": "A CLI",
    "total_files": 10,
    "total_words": 100,
    "community_count": 3,
    "commands": [{"task": "Test", "command": "pytest"}],
    "architecture": [{"insight": "core_agent is a hub", "detail": "42 conns"}],
    "conventions": [],
    "guardrails": [],
    "key_files": [{"path": "main.py", "purpose": "entry"}],
    "god_nodes": [{"label": "core_agent", "degree": 42, "source_file": "x.py"}],
    "surprising_connections": [{"source_files": ["a.py"], "target": "b.py"}],
    "suggested_questions": ["How does X work?"],
}


class _Resp:
    def __init__(self, content):
        self.content = content


def test_facts_brief_includes_graph_data():
    brief = gen._build_facts_brief(_FACTS_CTX)
    assert "core_agent (42 connections)" in brief
    assert "a.py <-> b.py" in brief
    assert "pytest" in brief


def test_strip_doc_fence():
    fence = "`" * 3
    assert gen._strip_doc_fence(f"{fence}markdown\n# Hi\n{fence}") == "# Hi"
    assert gen._strip_doc_fence("# Plain") == "# Plain"  # no fence: unchanged


def _run_llm_gen(model, monkeypatch):
    monkeypatch.setattr(gen, "_build_nova_md_context", lambda *a, **k: _FACTS_CTX)
    monkeypatch.setattr(
        "novacode_cli.config.model_create.create_model", lambda *a, **k: model
    )
    from pathlib import Path

    return asyncio.run(gen.generate_nova_md_llm(Path("."), {}, {}, {}, {}))


def test_hybrid_llm_returns_grounded_doc(monkeypatch):
    fence = "`" * 3
    body = (
        f"{fence}markdown\n# NOVA.md\n\n## Project Graph\n"
        "Use query_project_graph; see .nova/project-graph.json\n" + "x" * 150 + f"\n{fence}"
    )

    class _M:
        async def ainvoke(self, msgs):
            return _Resp(body)

    out = _run_llm_gen(_M(), monkeypatch)
    assert out and out.startswith("# NOVA.md")  # fence stripped
    assert "query_project_graph" in out and ".nova/project-graph.json" in out


def test_hybrid_llm_invalid_output_falls_back(monkeypatch):
    class _M:
        async def ainvoke(self, msgs):
            return _Resp("nope")  # too short / not markdown

    assert _run_llm_gen(_M(), monkeypatch) is None


def test_hybrid_llm_model_error_falls_back(monkeypatch):
    class _M:
        async def ainvoke(self, msgs):
            raise RuntimeError("boom")

    assert _run_llm_gen(_M(), monkeypatch) is None

_BASE = dict(
    project_description="A CLI",
    commands=[],
    architecture=[],
    conventions=[],
    guardrails=[],
    key_files=[],
    total_files=10,
    total_words=100,
    community_count=4,
)


def _render(**overrides):
    ctx = dict(_BASE)
    ctx.setdefault("god_nodes", [])
    ctx.setdefault("surprising_connections", [])
    ctx.setdefault("suggested_questions", [])
    ctx.update(overrides)
    return render_template("init_generate.jinja", **ctx)


def test_nova_md_documents_graph_usage():
    r = _render()
    assert "## Project Graph" in r
    assert "query_project_graph" in r
    assert ".nova/project-graph.json" in r
    assert "/init --update" in r
    # The how-to is present even when the graph analysis returned nothing.


def test_nova_md_renders_god_nodes_and_connections():
    r = _render(
        god_nodes=[
            {"label": "core_agent", "source_file": "x/core_agent.py", "degree": 42},
            {"id": "main", "edges": 30},
        ],
        surprising_connections=[
            {"source_files": ["a.py"], "target": "b.py"},
            {"source": "x", "target": "y"},
        ],
        suggested_questions=["How does auth flow?", {"question": "Where are LLM calls?"}],
    )
    assert "core_agent" in r and "42 connections" in r
    assert "main" in r and "30 connections" in r
    assert "a.py" in r and "b.py" in r and "x" in r and "y" in r
    assert "How does auth flow?" in r and "Where are LLM calls?" in r


# ── Agent-driven NOVA.md authoring ──────────────────────────────────────────


def test_author_prompt_grounds_in_facts_and_targets_file(monkeypatch):
    monkeypatch.setattr(gen, "_build_nova_md_context", lambda *a, **k: _FACTS_CTX)
    from pathlib import Path

    prompt = gen.build_nova_md_author_prompt(Path("."), {}, {}, {}, {})
    # Instructs the agent to use its tools, write the file, grounded in facts.
    assert "write_file" in prompt
    assert "query_project_graph" in prompt
    assert ".nova/NOVA.md" in prompt
    assert "core_agent (42 connections)" in prompt  # facts embedded


def test_author_prompt_honors_custom_path(monkeypatch):
    monkeypatch.setattr(gen, "_build_nova_md_context", lambda *a, **k: _FACTS_CTX)
    from pathlib import Path

    prompt = gen.build_nova_md_author_prompt(
        Path("."), {}, {}, {}, {}, nova_md_rel_path="docs/NOVA.md"
    )
    assert "docs/NOVA.md" in prompt


# ── Agent-driven semantic extraction ────────────────────────────────────────


def test_read_and_merge_fragments_dedups(tmp_path):
    import json

    import novacode_cli.init.extract as ex

    frag = tmp_path / "graph_fragments"
    frag.mkdir()
    (frag / "chunk_1.json").write_text(
        json.dumps({"nodes": [{"id": "a"}, {"id": "b"}], "edges": [{"source": "a", "target": "b"}]}),
        encoding="utf-8",
    )
    (frag / "chunk_2.json").write_text(
        json.dumps({"nodes": [{"id": "b"}, {"id": "c"}], "edges": []}),
        encoding="utf-8",
    )
    out = ex._read_and_merge_fragments(frag)
    ids = {n["id"] for n in out["nodes"]}
    assert ids == {"a", "b", "c"}  # b deduped
    assert len(out["nodes"]) == 3
    assert len(out["edges"]) == 1


def test_read_and_merge_fragments_missing_dir(tmp_path):
    import novacode_cli.init.extract as ex

    out = ex._read_and_merge_fragments(tmp_path / "nope")
    assert out["nodes"] == [] and out["edges"] == []


def test_semantic_extract_via_agent_dispatches_and_merges(tmp_path, monkeypatch):
    import json

    import novacode_cli.init.extract as ex

    # A code file the chunker can target (deep=True includes code).
    (tmp_path / "mod.py").write_text("x = 1\n", encoding="utf-8")
    detection = {"files": {"document": [], "paper": [], "code": ["mod.py"]}}

    async def fake_execute(prompt):
        # The "agent" writes the fragment it was told to write.
        frag = tmp_path / ".nova" / "graph_fragments"
        frag.mkdir(parents=True, exist_ok=True)
        (frag / "chunk_1.json").write_text(
            json.dumps({"nodes": [{"id": "mod_x"}], "edges": []}), encoding="utf-8"
        )

    out = asyncio.run(
        ex.semantic_extract_via_agent(tmp_path, detection, fake_execute, deep=True)
    )
    assert any(n["id"] == "mod_x" for n in out["nodes"])


def test_semantic_extract_via_agent_no_execute_fn(tmp_path):
    import novacode_cli.init.extract as ex

    out = asyncio.run(
        ex.semantic_extract_via_agent(tmp_path, {"files": {}}, None)
    )
    assert out["nodes"] == []


def test_doc_priority_canonical_first():
    import novacode_cli.init.extract as ex

    ordered = ex._prioritize_docs(
        [
            "docs/misc/random.md",
            "CONTRIBUTING.md",
            "CHANGELOG.md",
            "README.md",
            "ARCHITECTURE.md",
        ]
    )
    # README leads, then CHANGELOG, CONTRIBUTING, ARCHITECTURE; unmatched last.
    assert ordered[0] == "README.md"
    assert ordered[1] == "CHANGELOG.md"
    assert ordered.index("CONTRIBUTING.md") < ordered.index("ARCHITECTURE.md")
    assert ordered[-1] == "docs/misc/random.md"


def test_doc_priority_stem_beats_substring():
    import novacode_cli.init.extract as ex

    # A real README.md outranks a file that merely mentions "readme" in its path.
    ordered = ex._prioritize_docs(["notes/readme-archive/old.md", "README.rst"])
    assert ordered[0] == "README.rst"


def test_semantic_extract_via_agent_caps_subagents(tmp_path):
    """Many files must NOT fan out to unbounded subagents (429 guard) — even in
    deep mode the chunk/subagent count is hard-capped."""
    import novacode_cli.init.extract as ex

    files = []
    for i in range(200):
        f = tmp_path / f"m{i}.py"
        f.write_text("x = 1\n", encoding="utf-8")
        files.append(str(f))
    detection = {"files": {"document": [], "paper": [], "code": files}}

    captured = {}

    async def fake_execute(prompt):
        captured["prompt"] = prompt

    # deep=True bypasses the file cap → exercises the worst case.
    asyncio.run(
        ex.semantic_extract_via_agent(tmp_path, detection, fake_execute, deep=True)
    )
    # One "### Chunk N" header per subagent; must stay within the hard cap.
    n_chunks = captured["prompt"].count("### Chunk ")
    assert 0 < n_chunks <= ex._SEM_AGENT_MAX_SUBAGENTS


def test_semantic_extract_via_agent_relativizes_absolute_paths(tmp_path):
    """graphify returns absolute paths; the agent prompt must list relative
    POSIX paths (the backend rejects absolute/Windows paths)."""
    import novacode_cli.init.extract as ex

    sub = tmp_path / "docs" / "plans"
    sub.mkdir(parents=True)
    f = sub / "note.md"
    f.write_text("# note\n", encoding="utf-8")
    # detection carries the ABSOLUTE path, as graphify produces.
    detection = {"files": {"document": [str(f)], "paper": [], "code": []}}

    captured = {}

    async def fake_execute(prompt):
        captured["prompt"] = prompt  # don't write a fragment → empty merge

    asyncio.run(ex.semantic_extract_via_agent(tmp_path, detection, fake_execute))
    prompt = captured["prompt"]
    assert "docs/plans/note.md" in prompt  # relative, forward slashes
    assert str(tmp_path) not in prompt  # no absolute path leaked
    assert "\\" not in prompt.split("note.md")[0][-40:]  # no backslashes near it


def test_init_orchestrator_disables_plan_mode(tmp_path, monkeypatch):
    from novacode_cli.commands.init_handler import InitOrchestrator, InitFlags, InitResult
    import json

    class FakeSessionState:
        def __init__(self):
            self.plan_mode_enabled = True

    session_state = FakeSessionState()
    called_assert = False

    async def mock_run_pipeline(*args, **kwargs):
        nonlocal called_assert
        assert session_state.plan_mode_enabled is False
        called_assert = True
        return InitResult(ok=True, nova_dir=tmp_path / ".nova", nova_md_path=tmp_path / ".nova" / "NOVA.md")

    monkeypatch.setattr("novacode_cli.init.detect.is_graphify_available", lambda: True)
    monkeypatch.setattr("novacode_cli.commands.init_handler._run_graphify_pipeline", mock_run_pipeline)

    class FakeRenderer:
        def emit(self, event):
            pass
        def result(self, result, flags):
            pass

    orchestrator = InitOrchestrator(
        project_root=tmp_path,
        nova_dir=tmp_path / ".nova",
        nova_md_path=tmp_path / ".nova" / "NOVA.md",
        agents_md_path=tmp_path / ".nova" / "AGENTS.md",
        flags=InitFlags(),
        renderer=FakeRenderer(),
        agent=None,
        session_state=session_state,
        assistant_id="fake",
        token_tracker=None,
        execute_fn=lambda x: None,
    )

    asyncio.run(orchestrator.run())
    assert called_assert is True
    assert session_state.plan_mode_enabled is True

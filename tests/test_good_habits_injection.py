"""HABITS.md is loaded into AgentMemoryMiddleware state for injection."""

from __future__ import annotations

import types


def _make_middleware(tmp_path):  # noqa: ANN001, ANN202
    from novacode_cli.memory import agent_memory

    mw = agent_memory.AgentMemoryMiddleware.__new__(agent_memory.AgentMemoryMiddleware)
    # Minimal attributes the sync loader (before_agent) reads.
    mw.assistant_id = "nova-agent"
    mw.agent_dir = tmp_path
    mw.skip_project_memory = True
    mw._backend = None
    mw._last_mtimes = {}
    agent_md = tmp_path / "agent.md"
    agent_md.write_text("# agent\n", encoding="utf-8")
    mw.settings = types.SimpleNamespace(
        get_user_agent_md_path=lambda _aid: agent_md,
        get_project_agent_md_paths=list,
    )
    return mw, agent_md


def test_habits_md_loaded_into_state(tmp_path):  # noqa: ANN001
    mw, _agent_md = _make_middleware(tmp_path)
    (tmp_path / "HABITS.md").write_text(
        "# Good Habits\n\n- Test-first for races.\n", encoding="utf-8"
    )
    result = mw.before_agent({})
    assert "Test-first for races" in result["habits_memory"]


def test_habits_md_absent_leaves_state_unset(tmp_path):  # noqa: ANN001
    mw, _agent_md = _make_middleware(tmp_path)
    result = mw.before_agent({})
    assert "habits_memory" not in result

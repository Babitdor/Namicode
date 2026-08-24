"""Tests for the learning overview builder (hermes/overview.py).

Covers:
- ``build_learning_overview`` renders a compact block from memory/skills/prompt
  state, and returns ``""`` when nothing is available.
- Topic counting from an INDEX.md.
- Skill listing from a skills dir.
- Prompt-evolution status from a manifest.
- Recent refinement events surfaced from the audit log.
"""

from pathlib import Path

import pytest

from novacode_cli.hermes.overview import (
    _count_topics,
    _list_skills,
    _prompt_status,
    _recent_events,
    build_learning_overview,
)


@pytest.fixture
def agent_dir(tmp_path: Path) -> Path:
    """A temporary agent dir with a memories/INDEX.md."""
    agent_dir = tmp_path / ".nova" / "test_agent"
    mem = agent_dir / "memories"
    mem.mkdir(parents=True, exist_ok=True)
    (mem / "INDEX.md").write_text(
        "# Memory Index\n\n- [preferences](preferences.md)\n- [workflows](workflows.md)\n",
        encoding="utf-8",
    )
    return agent_dir


class TestCountTopics:
    def test_counts_markdown_links(self):
        text = "# Index\n\n- [a](a.md)\n- [b](b.md)\nplain line\n"
        assert _count_topics(text) == 2

    def test_none_returns_zero(self):
        assert _count_topics(None) == 0


class TestListSkills:
    def test_lists_skill_dirs(self, tmp_path):
        skills = tmp_path / "skills"
        (skills / "alpha" / "SKILL.md").mkdir(parents=True)
        (skills / "beta" / "SKILL.md").mkdir(parents=True)
        (skills / "not-a-skill").mkdir()  # no SKILL.md
        names = _list_skills(skills)
        assert names == ["alpha", "beta"]

    def test_missing_dir_returns_empty(self, tmp_path):
        assert _list_skills(tmp_path / "nope") == []


class TestPromptStatus:
    def test_parses_manifest(self, tmp_path):
        hist = tmp_path / "prompt_history"
        hist.mkdir(parents=True)
        (hist / "manifest.json").write_text(
            '{"templates": [{"has_active": true}, {"has_candidate": true}]}',
            encoding="utf-8",
        )
        status = _prompt_status(hist)
        assert status is not None
        assert "1 active" in status
        assert "1 candidate" in status

    def test_missing_manifest_returns_none(self, tmp_path):
        assert _prompt_status(tmp_path / "prompt_history") is None


class TestRecentEvents:
    def test_returns_last_events(self, tmp_path):
        log = tmp_path / "refinement_events.json"
        log.write_text(
            '[{"domain": "skill", "action": "create", "target": "x"},'
            '{"domain": "prompt", "action": "promote", "target": "y"}]',
            encoding="utf-8",
        )
        events = _recent_events(log)
        assert len(events) == 2
        assert "skill:create x" in events

    def test_missing_log_returns_empty(self, tmp_path):
        assert _recent_events(tmp_path / "nope.json") == []


class TestBuildLearningOverview:
    def test_renders_block(self, agent_dir):
        overview = build_learning_overview(agent_dir=agent_dir)
        assert "<learning_overview>" in overview
        assert "Memory: 2 topic(s)" in overview

    def test_empty_when_nothing_available(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir(parents=True)
        assert build_learning_overview(agent_dir=empty) == ""

    def test_includes_skills_and_events(self, agent_dir, tmp_path):
        skills = agent_dir / "skills"
        (skills / "alpha" / "SKILL.md").mkdir(parents=True)
        log = agent_dir / "refinement_events.json"
        log.write_text(
            '[{"domain": "skill", "action": "create", "target": "alpha"}]',
            encoding="utf-8",
        )
        overview = build_learning_overview(agent_dir=agent_dir)
        assert "Skills: alpha" in overview
        assert "Recent refinements" in overview

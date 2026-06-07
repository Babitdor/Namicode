"""Tests for Nova skill discovery — pattern detection, creation, refinement.

Covers:
- Pattern detection from tool history
- Skill candidate evaluation
- Pattern naming and description generation
- Skill effectiveness tracking
"""

from pathlib import Path

import pytest

from novacode_cli.hermes.skill_discovery import (
    Pattern,
    _is_trivial,
    _sequence_key,
    analyze_tool_history,
    check_skill_effectiveness,
    detect_patterns,
    generate_skill_name,
    is_skill_candidate,
    pattern_to_description,
)


@pytest.fixture
def mock_history():
    """Sample tool usage history for pattern detection tests."""
    return [
        {"tool": "read_file", "success": True, "timestamp": 1000.0},
        {"tool": "edit_file", "success": True, "timestamp": 1001.0},
        {"tool": "run_tests", "success": True, "timestamp": 1002.0},
        # Repeat the same pattern
        {"tool": "read_file", "success": True, "timestamp": 1010.0},
        {"tool": "edit_file", "success": True, "timestamp": 1011.0},
        {"tool": "run_tests", "success": True, "timestamp": 1012.0},
        # Third occurrence of the same pattern
        {"tool": "read_file", "success": True, "timestamp": 1020.0},
        {"tool": "edit_file", "success": False, "timestamp": 1021.0},
        {"tool": "run_tests", "success": True, "timestamp": 1022.0},
        # A different trivial pattern (only read_file)
        {"tool": "read_file", "success": True, "timestamp": 1030.0},
        {"tool": "read_file", "success": True, "timestamp": 1031.0},
        {"tool": "read_file", "success": True, "timestamp": 1032.0},
    ]


class TestPatternDetection:
    """Basic pattern detection from tool history."""

    def test_detect_repeated_pattern(self, mock_history):
        """Should detect the read→edit→test pattern that appears 3 times."""
        patterns = detect_patterns(mock_history, min_length=3)
        assert len(patterns) >= 1
        pattern = next((p for p in patterns if "read_file" in str(p.sequence)), None)
        assert pattern is not None
        assert pattern.frequency >= 3

    def test_detect_trivial_pattern(self, mock_history):
        """Trivial patterns (only read_file/grep) should be rejected."""
        patterns = detect_patterns(mock_history)
        # The read-only pattern should be filtered
        for p in patterns:
            # We should not have a pattern that is ONLY read_file
            if all(t == "read_file" for t in p.sequence):
                pytest.fail(f"Trivial pattern should have been filtered: {p.sequence}")

    def test_empty_history(self):
        """Empty history should return no patterns."""
        patterns = detect_patterns([], min_length=3)
        assert patterns == []

    def test_short_history(self):
        """History shorter than min_length should return no patterns."""
        patterns = detect_patterns(
            [{"tool": "read_file", "success": True}],
            min_length=3,
        )
        assert patterns == []

    def test_single_occurrence(self):
        """Patterns appearing only once should not be detected."""
        history = [
            {"tool": "edit_file", "success": True},
            {"tool": "run_tests", "success": True},
            {"tool": "write_file", "success": True},
        ]
        patterns = detect_patterns(history, min_length=3)
        # Only 3 tools, pattern appears once = no detection
        assert len(patterns) == 0


class TestSkillCandidateEvaluation:
    """Determining which patterns are worth formalizing as skills."""

    def test_valid_candidate(self):
        """A pattern with 3+ tools and multiple repeats should be a candidate."""
        pattern = Pattern(
            sequence=["read_file", "edit_file", "run_tests"],
            frequency=3,
            success_rate=0.85,
        )
        assert is_skill_candidate(pattern)

    def test_short_pattern_rejected(self):
        """Patterns shorter than min_length should be rejected."""
        pattern = Pattern(
            sequence=["read_file", "edit_file"],
            frequency=3,
            success_rate=1.0,
        )
        assert not is_skill_candidate(pattern)

    def test_low_frequency_rejected(self):
        """Patterns appearing only once should be rejected."""
        pattern = Pattern(
            sequence=["read_file", "edit_file", "run_tests"],
            frequency=1,
            success_rate=1.0,
        )
        assert not is_skill_candidate(pattern)

    def test_low_success_rate_rejected(self):
        """Patterns with < 60% success should be rejected."""
        pattern = Pattern(
            sequence=["read_file", "edit_file", "run_tests"],
            frequency=3,
            success_rate=0.3,
        )
        assert not is_skill_candidate(pattern)

    def test_trivial_pattern_rejected(self):
        """Patterns with only read_file/grep should be rejected."""
        pattern = Pattern(
            sequence=["read_file", "grep", "read_file"],
            frequency=5,
            success_rate=1.0,
        )
        assert not is_skill_candidate(pattern)


class TestTriviality:
    """Trivial tool sequence detection."""

    def test_non_trivial(self):
        """Sequences with write/edit/execute/test should not be trivial."""
        assert not _is_trivial(["read_file", "edit_file"])
        assert not _is_trivial(["read_file", "write_file"])
        assert not _is_trivial(["grep", "execute"])
        assert not _is_trivial(["read_file", "run_tests"])

    def test_trivial(self):
        """Sequences with only read-only tools should be trivial."""
        assert _is_trivial(["read_file"])
        assert _is_trivial(["read_file", "grep"])
        assert _is_trivial(["ls", "grep"])


class TestSequenceKey:
    """Canonical sequence key generation."""

    def test_basic_key(self):
        """Sequences produce canonical keys."""
        key = _sequence_key(["read_file", "edit_file", "run_tests"])
        assert key == "read_file→edit_file→run_tests"

    def test_ordering(self):
        """Same tools in different order should produce different keys."""
        k1 = _sequence_key(["read_file", "edit_file"])
        k2 = _sequence_key(["edit_file", "read_file"])
        assert k1 != k2


class TestSkillNaming:
    """Skill name and description generation."""

    def test_generate_name_with_edit(self):
        """Patterns with edit_file should generate appropriate names."""
        pattern = Pattern(
            sequence=["read_file", "edit_file", "run_tests", "run_tests"],
            frequency=3,
            success_rate=1.0,
        )
        name = generate_skill_name(pattern)
        assert "edit" in name or "test" in name

    def test_generate_name_with_exec(self):
        """Patterns with execute should generate appropriate names."""
        pattern = Pattern(
            sequence=["read_file", "execute", "read_file"],
            frequency=2,
            success_rate=1.0,
        )
        name = generate_skill_name(pattern)
        assert "exec" in name

    def test_description_contains_info(self):
        """Descriptions should contain frequency and success rate."""
        pattern = Pattern(
            sequence=["read_file", "edit_file", "run_tests"],
            frequency=3,
            success_rate=0.85,
        )
        desc = pattern_to_description(pattern)
        assert "read_file" in desc
        assert "edit_file" in desc
        assert "run_tests" in desc
        assert "3" in desc or "85" in desc


class TestSkillEffectiveness:
    """Skill usage tracking and effectiveness analysis."""

    async def test_check_empty_stats(self):
        """No skill stats should return empty list."""
        from unittest.mock import AsyncMock, MagicMock

        store_mock = MagicMock()
        store_mock.asearch = AsyncMock(return_value=[])
        issues = await check_skill_effectiveness(store_mock)
        assert issues == []

    async def test_high_failure_rate(self):
        """Skills with high failure rate should be flagged."""
        from unittest.mock import AsyncMock, MagicMock

        store_mock = MagicMock()

        class MockItem:
            key = "my-skill"
            value = {"uses": 10, "successes": 3, "failures": 7}

        store_mock.asearch = AsyncMock(return_value=[MockItem()])
        issues = await check_skill_effectiveness(store_mock)
        assert ("my-skill", "high_failure") in issues

    async def test_low_usage(self):
        """Skills with very low usage should be flagged."""
        from unittest.mock import AsyncMock, MagicMock

        store_mock = MagicMock()

        class MockItem:
            key = "rare-skill"
            value = {"uses": 1, "successes": 1, "failures": 0}

        store_mock.asearch = AsyncMock(return_value=[MockItem()])
        issues = await check_skill_effectiveness(store_mock)
        assert ("rare-skill", "low_usage") in issues


class TestAnalyzeToolHistory:
    """High-level tool history analysis API."""

    async def test_analyze_returns_candidates(self):
        """analyze_tool_history should return skill-worthy patterns."""
        from unittest.mock import AsyncMock, MagicMock

        store_mock = MagicMock()

        class MockEntry:
            # Stored history is wrapped as {"entries": [...]} (see
            # NovaLearningMiddleware._record_tool_usage), so analyze reads
            # entry.value["entries"].
            value = {
                "entries": [
                    {"tool": "read_file", "success": True, "timestamp": 1.0},
                    {"tool": "edit_file", "success": True, "timestamp": 2.0},
                    {"tool": "run_tests", "success": True, "timestamp": 3.0},
                    # Repeat
                    {"tool": "read_file", "success": True, "timestamp": 4.0},
                    {"tool": "edit_file", "success": True, "timestamp": 5.0},
                    {"tool": "run_tests", "success": True, "timestamp": 6.0},
                ]
            }

        store_mock.aget = AsyncMock(return_value=MockEntry())
        patterns = await analyze_tool_history(store_mock, recent_n=100)
        assert len(patterns) >= 1
        assert patterns[0].frequency >= 2


class TestParseSkillSpec:
    """Parsing the <skill> block the review LLM emits (episode-grounded)."""

    def test_valid_block(self):
        from novacode_cli.hermes.skill_discovery import parse_skill_spec

        text = (
            "preamble\n<skill>\n<name>Add TUI Command</name>\n"
            "<description>Use when adding a /command to the TUI.</description>\n"
            "<body># Steps\n1. edit app.py</body>\n</skill>\nepilogue"
        )
        spec = parse_skill_spec(text)
        assert spec == {
            "name": "add-tui-command",  # slugified
            "description": "Use when adding a /command to the TUI.",
            "body": "# Steps\n1. edit app.py",
        }

    def test_no_block_returns_none(self):
        from novacode_cli.hermes.skill_discovery import parse_skill_spec

        assert parse_skill_spec("just a normal review, no skill") is None

    def test_missing_body_returns_none(self):
        from novacode_cli.hermes.skill_discovery import parse_skill_spec

        assert parse_skill_spec("<skill><name>x-y</name></skill>") is None

    def test_legacy_style_name_rejected(self):
        from novacode_cli.hermes.skill_discovery import parse_skill_spec

        text = "<skill><name>nova-edit-5628de</name><body>steps</body></skill>"
        assert parse_skill_spec(text) is None


class TestWriteSkillFromSpec:
    """Writing an episode skill to disk with real frontmatter."""

    async def test_writes_skill_md_with_frontmatter(self, tmp_path):
        from novacode_cli.hermes.skill_discovery import write_skill_from_spec

        spec = {
            "name": "add-tui-command",
            "description": "Use when adding a /command",
            "body": "# Steps\n1. do it",
        }
        name = await write_skill_from_spec(spec, tmp_path, store=None)
        assert name == "add-tui-command"
        skill_md = tmp_path / "add-tui-command" / "SKILL.md"
        assert skill_md.exists()
        content = skill_md.read_text(encoding="utf-8")
        assert content.startswith("---\n")
        assert "name: add-tui-command" in content
        assert 'description: "Use when adding a /command"' in content
        assert "# Steps\n1. do it" in content

    async def test_dedup_existing_dir_returns_none(self, tmp_path):
        from novacode_cli.hermes.skill_discovery import write_skill_from_spec

        (tmp_path / "add-tui-command").mkdir()
        spec = {"name": "add-tui-command", "description": "d", "body": "b"}
        assert await write_skill_from_spec(spec, tmp_path, store=None) is None


class TestCleanupLegacySkills:
    """Removing the old opaque nova-<hash> auto-skills, sparing real ones."""

    def test_removes_only_legacy(self, tmp_path):
        from novacode_cli.hermes.skill_discovery import cleanup_legacy_pattern_skills

        for name in ("nova-exec-b2c94a", "nova-edit-test-5628de", "add-tui-command", "my-skill"):
            (tmp_path / name).mkdir()

        removed = cleanup_legacy_pattern_skills(tmp_path)

        assert set(removed) == {"nova-exec-b2c94a", "nova-edit-test-5628de"}
        assert not (tmp_path / "nova-exec-b2c94a").exists()
        assert (tmp_path / "add-tui-command").exists()  # real skill spared
        assert (tmp_path / "my-skill").exists()

    def test_missing_dir_is_safe(self, tmp_path):
        from novacode_cli.hermes.skill_discovery import cleanup_legacy_pattern_skills

        assert cleanup_legacy_pattern_skills(tmp_path / "nope") == []
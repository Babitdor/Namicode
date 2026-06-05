"""Tests for Nova memory tiers — USER.md, MEMORY.md, compaction.

Covers:
- File creation with default templates
- Content updates and section replacement
- Memory compaction at size limits
- Session memory prepending
"""

from pathlib import Path

import pytest

from novacode_cli.hermes.memory_tiers import (
    MAX_MEMORY_CHARS,
    compact_memory_file,
    ensure_memory_tiers,
    update_session_memory,
    update_user_memory,
)


@pytest.fixture
def temp_agent_dir(tmp_path: Path) -> Path:
    """Create a temporary agent directory for testing."""
    agent_dir = tmp_path / ".nova" / "test_agent"
    agent_dir.mkdir(parents=True, exist_ok=True)
    return agent_dir


class TestEnsureMemoryTiers:
    """Memory tier file creation."""

    def test_creates_user_md(self, temp_agent_dir):
        """ensure_memory_tiers should create USER.md if missing."""
        ensure_memory_tiers(temp_agent_dir)
        user_md = temp_agent_dir / "USER.md"
        assert user_md.exists()
        content = user_md.read_text(encoding="utf-8")
        assert "# USER.md" in content
        assert "## Communication Style" in content

    def test_creates_memory_md(self, temp_agent_dir):
        """ensure_memory_tiers should create MEMORY.md if missing."""
        ensure_memory_tiers(temp_agent_dir)
        memory_md = temp_agent_dir / "MEMORY.md"
        assert memory_md.exists()
        content = memory_md.read_text(encoding="utf-8")
        assert "# MEMORY.md" in content
        assert "## Architecture Decisions" in content

    def test_does_not_overwrite_existing(self, temp_agent_dir):
        """ensure_memory_tiers should not overwrite existing files."""
        user_md = temp_agent_dir / "USER.md"
        user_md.write_text("custom content", encoding="utf-8")
        ensure_memory_tiers(temp_agent_dir)
        assert user_md.read_text(encoding="utf-8") == "custom content"


class TestCompactMemoryFile:
    """Memory file compaction at size limits."""

    def test_no_compaction_under_limit(self, temp_agent_dir):
        """Files under MAX_MEMORY_CHARS should not be compacted."""
        test_file = temp_agent_dir / "test.md"
        test_file.write_text("small content", encoding="utf-8")
        compacted = compact_memory_file(test_file)
        assert not compacted
        assert test_file.read_text(encoding="utf-8") == "small content"

    def test_compaction_over_limit(self, temp_agent_dir):
        """Files over MAX_MEMORY_CHARS should be truncated."""
        test_file = temp_agent_dir / "test.md"
        # Write content well over the limit
        large_content = "A" * (MAX_MEMORY_CHARS + 1000)
        test_file.write_text(large_content, encoding="utf-8")
        compacted = compact_memory_file(test_file)
        assert compacted
        content = test_file.read_text(encoding="utf-8")
        assert len(content) < MAX_MEMORY_CHARS
        assert "truncated" in content

    def test_non_existent_file(self, temp_agent_dir):
        """Compacting a non-existent file should return False."""
        compacted = compact_memory_file(temp_agent_dir / "nonexistent.md")
        assert not compacted

    def test_exact_limit(self, temp_agent_dir):
        """File at exactly MAX_MEMORY_CHARS should not be compacted."""
        test_file = temp_agent_dir / "test.md"
        content = "A" * MAX_MEMORY_CHARS
        test_file.write_text(content, encoding="utf-8")
        compacted = compact_memory_file(test_file)
        assert not compacted


class TestUpdateUserMemory:
    """USER.md content updates."""

    def test_append_bullet_to_existing(self, temp_agent_dir):
        """Adding a bullet should append to USER.md."""
        ensure_memory_tiers(temp_agent_dir)
        update_user_memory(temp_agent_dir, "- Prefer concise responses")
        content = (temp_agent_dir / "USER.md").read_text(encoding="utf-8")
        assert "- Prefer concise responses" in content

    def test_replace_section(self, temp_agent_dir):
        """Replacing a named section should work."""
        ensure_memory_tiers(temp_agent_dir)
        new_section = "## Communication Style\n- Very formal\n- Uses technical terms"
        update_user_memory(temp_agent_dir, new_section)
        content = (temp_agent_dir / "USER.md").read_text(encoding="utf-8")
        assert "- Very formal" in content
        # Old default should be gone
        assert "(auto-detected)" not in content.split("## Communication Style")[1].split("## ")[0]

    def test_add_new_section(self, temp_agent_dir):
        """Adding a new section should append to USER.md."""
        ensure_memory_tiers(temp_agent_dir)
        new_section = "## Custom Section\n- Custom value"
        update_user_memory(temp_agent_dir, new_section)
        content = (temp_agent_dir / "USER.md").read_text(encoding="utf-8")
        assert "## Custom Section" in content
        assert "- Custom value" in content

    def test_create_file_if_missing(self, temp_agent_dir):
        """Updating should create USER.md if it doesn't exist."""
        update_user_memory(temp_agent_dir, "- New preference")
        assert (temp_agent_dir / "USER.md").exists()


class TestUpdateSessionMemory:
    """MEMORY.md session entry updates."""

    def test_add_session_entry(self, temp_agent_dir):
        """Adding a session entry should prepend to MEMORY.md."""
        ensure_memory_tiers(temp_agent_dir)
        update_session_memory(temp_agent_dir, "Implemented auth system")
        content = (temp_agent_dir / "MEMORY.md").read_text(encoding="utf-8")
        assert "Implemented auth system" in content
        assert "## Session" in content

    def test_create_file_if_missing(self, temp_agent_dir):
        """Updating should create MEMORY.md if it doesn't exist."""
        update_session_memory(temp_agent_dir, "Test session")
        assert (temp_agent_dir / "MEMORY.md").exists()

    def test_multiple_sessions(self, temp_agent_dir):
        """Multiple session entries should stack (newest first)."""
        ensure_memory_tiers(temp_agent_dir)
        update_session_memory(temp_agent_dir, "First session")
        update_session_memory(temp_agent_dir, "Second session")
        content = (temp_agent_dir / "MEMORY.md").read_text(encoding="utf-8")
        # Most recent should appear first
        first_session_idx = content.index("First session")
        second_session_idx = content.index("Second session")
        assert second_session_idx < first_session_idx, "Newer session should appear before older"
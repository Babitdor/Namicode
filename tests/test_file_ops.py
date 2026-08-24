"""Tests for file_ops.py — pure helper functions."""

from __future__ import annotations

from pathlib import Path

import pytest

from novacode_cli.file_ops import (
    _safe_read,
    _count_lines,
    compute_unified_diff,
    resolve_physical_path,
    format_display_path,
)


class TestSafeRead:
    """_safe_read: reads file content with fallback encodings."""

    def test_reads_utf8(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("hello world", encoding="utf-8")
        assert _safe_read(f) == "hello world"

    def test_returns_none_for_missing_file(self):
        assert _safe_read(Path("/nonexistent/file.txt")) is None

    def test_returns_none_for_directory(self, tmp_path):
        assert _safe_read(tmp_path) is None


class TestCountLines:
    """_count_lines: counts lines in text."""

    def test_empty_string(self):
        assert _count_lines("") == 0

    def test_single_line(self):
        assert _count_lines("hello") == 1

    def test_multiple_lines(self):
        assert _count_lines("line1\nline2\nline3") == 3

    def test_trailing_newline(self):
        assert _count_lines("line1\nline2\n") == 2

    def test_formatted_output_with_line_numbers(self):
        text = "     1\tline one\n     2\tline two\n     3\tline three"
        assert _count_lines(text) == 3

    def test_formatted_output_skips_continuation_lines(self):
        text = "     1\tnormal line\n     1.1\tcontinuation\n     2\tsecond line"
        assert _count_lines(text) == 2


class TestComputeUnifiedDiff:
    """compute_unified_diff: generates unified diffs."""

    def test_no_changes_returns_none(self):
        result = compute_unified_diff("same", "same", "file.txt")
        assert result is None

    def test_addition(self):
        result = compute_unified_diff("before", "before\nnew line", "file.txt")
        assert result is not None
        assert "+new line" in result
        assert "file.txt" in result

    def test_deletion(self):
        result = compute_unified_diff("line1\nline2\nline3", "line1\nline3", "file.txt")
        assert result is not None
        assert "-line2" in result

    def test_max_lines_truncation(self):
        before = "\n".join(f"line{i}" for i in range(100))
        after = "\n".join(f"line{i} modified" for i in range(100))
        result = compute_unified_diff(before, after, "file.txt", max_lines=10)
        assert result is not None
        assert "..." in result  # Truncation marker

    def test_empty_before(self):
        result = compute_unified_diff("", "new content", "file.txt")
        assert result is not None
        assert "+new content" in result


class TestResolvePhysicalPath:
    """resolve_physical_path: converts virtual paths to filesystem paths."""

    def test_none_path_returns_none(self):
        assert resolve_physical_path(None, "agent-1") is None

    def test_empty_path_returns_none(self):
        assert resolve_physical_path("", "agent-1") is None

    def test_absolute_path(self, tmp_path):
        # tmp_path is absolute on every platform; "/tmp/x" is NOT absolute on
        # Windows (no drive letter), which is why a hardcoded POSIX path here
        # silently took the relative branch instead.
        target = tmp_path / "test.txt"
        assert resolve_physical_path(str(target), None) == target

    def test_relative_path(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        result = resolve_physical_path("relative/path.txt", None)
        assert result == (tmp_path / "relative" / "path.txt").resolve()

    def test_memories_path(self, monkeypatch):
        # Mock settings.get_agent_dir
        class FakeSettings:
            def get_agent_dir(self, agent_id):
                return Path(f"/tmp/nova/{agent_id}")

        import novacode_cli.file_ops as fo
        monkeypatch.setattr(fo, "settings", FakeSettings())

        result = resolve_physical_path("/memories/agent.md", "agent-1")
        assert result is not None
        assert "agent-1" in str(result)
        assert result.name == "agent.md"

    def test_project_memory_path(self, monkeypatch):
        class FakeSettings:
            project_root = Path("/tmp/project")

            def get_agent_dir(self, agent_id):
                return Path(f"/tmp/nova/{agent_id}")

        import novacode_cli.file_ops as fo
        monkeypatch.setattr(fo, "settings", FakeSettings())

        result = resolve_physical_path("/project-memory/NOVA.md", None)
        assert result is not None
        assert ".nova" in str(result)
        assert result.name == "NOVA.md"

    def test_plans_path(self, monkeypatch):
        class FakeSettings:
            project_root = Path("/tmp/project")

            def get_agent_dir(self, agent_id):
                return Path(f"/tmp/nova/{agent_id}")

        import novacode_cli.file_ops as fo
        monkeypatch.setattr(fo, "settings", FakeSettings())

        result = resolve_physical_path("/.nova/plans/plan-1.md", None)
        assert result is not None
        assert "plans" in str(result)
        assert result.name == "plan-1.md"


class TestFormatDisplayPath:
    """format_display_path: formats paths for display."""

    def test_none_returns_unknown(self):
        assert format_display_path(None) == "(unknown)"

    def test_empty_returns_unknown(self):
        assert format_display_path("") == "(unknown)"

    def test_absolute_path_returns_basename(self, tmp_path):
        # Must be absolute *for this platform* to hit the basename branch.
        assert format_display_path(str(tmp_path / "long" / "file.txt")) == "file.txt"

    def test_relative_path(self):
        # Relative paths pass through, but rendered with the native separator.
        rel = "relative/path.txt"
        assert format_display_path(rel) == str(Path(rel))

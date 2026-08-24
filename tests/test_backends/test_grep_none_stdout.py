"""Test that _ripgrep_search handles proc.stdout=None gracefully (Windows edge case)."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from novacode_cli.backends.filesystem import OptimizedFilesystemBackend


@pytest.fixture
def backend(tmp_path: Path) -> OptimizedFilesystemBackend:
    """Create a backend rooted at tmp_path."""
    return OptimizedFilesystemBackend(root_dir=str(tmp_path), virtual_mode=False)


class _FakeCompletedProcess:
    """Mimics subprocess.CompletedProcess with stdout=None."""

    def __init__(self, returncode: int = 0, stdout=None, stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class TestRipgrepNoneStdout:
    """Regression tests for the AttributeError: 'NoneType' has no attribute 'splitlines'."""

    def test_none_stdout_returns_empty_not_crash(
        self, backend: OptimizedFilesystemBackend, tmp_path: Path
    ) -> None:
        """proc.stdout=None should return an empty dict, not raise AttributeError."""
        fake_proc = _FakeCompletedProcess(returncode=0, stdout=None)

        with patch.object(subprocess, "run", return_value=fake_proc):
            result, truncated = backend._rg_impl("some_pattern", tmp_path, None)

        assert result == {}
        assert isinstance(result, dict)

    def test_none_stdout_no_match_returncode(
        self, backend: OptimizedFilesystemBackend, tmp_path: Path
    ) -> None:
        """proc.stdout=None with returncode=1 (no match) should also return empty dict."""
        fake_proc = _FakeCompletedProcess(returncode=1, stdout=None)

        with patch.object(subprocess, "run", return_value=fake_proc):
            result, truncated = backend._rg_impl("some_pattern", tmp_path, None)

        assert result == {}

    def test_empty_string_stdout_still_works(
        self, backend: OptimizedFilesystemBackend, tmp_path: Path
    ) -> None:
        """proc.stdout='' (empty string, normal no-match case) should return empty dict."""
        fake_proc = _FakeCompletedProcess(returncode=1, stdout="")

        with patch.object(subprocess, "run", return_value=fake_proc):
            result, truncated = backend._rg_impl("some_pattern", tmp_path, None)

        assert result == {}

    def test_valid_stdout_still_parsed(
        self, backend: OptimizedFilesystemBackend, tmp_path: Path
    ) -> None:
        """Normal JSON stdout should still be parsed correctly."""
        # Create a test file with content
        test_file = tmp_path / "example.py"
        test_file.write_text("hello world\n", encoding="utf-8")

        # Simulate ripgrep JSON output for a match
        rg_json_line = (
            '{"type":"match","data":{"path":{"text":"example.py"},'
            '"line_number":1,"lines":{"text":"hello world\\n"}}}'
        )
        fake_proc = _FakeCompletedProcess(returncode=0, stdout=rg_json_line)

        with patch.object(subprocess, "run", return_value=fake_proc):
            result, truncated = backend._rg_impl("hello", tmp_path, None)

        # Should have one match
        assert len(result) == 1
        # The key is the file path, value is list of (line_num, line_text)
        for file_path, matches in result.items():
            assert "example.py" in file_path
            assert matches[0][0] == 1  # line number
            assert "hello world" in matches[0][1]  # line text
"""Wrapper improvements on OptimizedFilesystemBackend (read/edit/glob/grep).

These are pure backend-method overrides — the deepagents filesystem tools call
``backend.read/edit/glob/grep``, so improving the backend improves the tools
without touching the package. Each test pins one wrapper.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from novacode_cli.backends.filesystem import OptimizedFilesystemBackend


@pytest.fixture
def backend(tmp_path: Path) -> OptimizedFilesystemBackend:
    return OptimizedFilesystemBackend(str(tmp_path))


# -- read: non-utf-8 recovery -------------------------------------------------


def test_read_recovers_non_utf8_file(backend: OptimizedFilesystemBackend, tmp_path: Path) -> None:
    (tmp_path / "latin.txt").write_bytes("café — naïve\nsecond".encode("cp1252"))
    result = backend.read("latin.txt")
    assert result.error is None
    assert "second" in result.file_data["content"]


def test_read_utf8_unaffected(backend: OptimizedFilesystemBackend, tmp_path: Path) -> None:
    (tmp_path / "u.txt").write_text("hello\nworld\n", encoding="utf-8")
    result = backend.read("u.txt")
    assert result.error is None
    assert result.file_data["content"] == "hello\nworld\n"


# -- edit: failure hints ------------------------------------------------------


def test_edit_hint_on_whitespace_drift(
    backend: OptimizedFilesystemBackend, tmp_path: Path
) -> None:
    (tmp_path / "code.py").write_text("    def foo():\n        return 1\n", encoding="utf-8")
    res = backend.edit("code.py", "def  foo():", "def bar():")  # two spaces: no exact match
    assert res.error is not None
    assert "Hint:" in res.error
    assert "line 1" in res.error


def test_edit_hint_on_ambiguous_match(
    backend: OptimizedFilesystemBackend, tmp_path: Path
) -> None:
    (tmp_path / "d.py").write_text("x=1\nx=1\n", encoding="utf-8")
    res = backend.edit("d.py", "x=1", "x=2")
    assert res.error is not None
    assert "replace_all=True" in res.error


def test_edit_success_path_unchanged(
    backend: OptimizedFilesystemBackend, tmp_path: Path
) -> None:
    f = tmp_path / "ok.py"
    f.write_text("alpha\nbeta\n", encoding="utf-8")
    res = backend.edit("ok.py", "beta", "gamma")
    assert res.error is None
    assert f.read_text() == "alpha\ngamma\n"


# -- glob: prune + newest-first ----------------------------------------------


def test_glob_prunes_vendored_dirs_and_sorts_newest_first(
    backend: OptimizedFilesystemBackend, tmp_path: Path
) -> None:
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "junk.py").write_text("x")
    old = tmp_path / "old.py"
    new = tmp_path / "new.py"
    old.write_text("x")
    new.write_text("x")
    os.utime(old, (1, 1))
    os.utime(new, (10**9, 10**9))

    result = backend.glob("**/*.py")
    names = [Path(m["path"]).name for m in (result.matches or [])]
    assert "junk.py" not in names  # vendored dir pruned
    assert names.index("new.py") < names.index("old.py")  # newest first


# -- grep: smart-case ---------------------------------------------------------


def test_grep_lowercase_is_case_insensitive(
    backend: OptimizedFilesystemBackend, tmp_path: Path
) -> None:
    (tmp_path / "s.txt").write_text("Hello WORLD\nhello there\n", encoding="utf-8")
    result = backend.grep("hello", path="s.txt")  # lower-case -> matches both
    assert len(result.matches or []) == 2


def test_grep_uppercase_stays_case_sensitive(
    backend: OptimizedFilesystemBackend, tmp_path: Path
) -> None:
    (tmp_path / "s.txt").write_text("Hello WORLD\nhello there\n", encoding="utf-8")
    result = backend.grep("Hello", path="s.txt")  # has upper-case -> exact case
    assert len(result.matches or []) == 1

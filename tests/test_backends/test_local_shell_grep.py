"""OptimizedLocalShellBackend pairs Nova's guarded grep with local execute.

Regression for the AttributeError "'NoneType' object has no attribute
'splitlines'": in local mode the composite default backend was a plain
deepagents ``LocalShellBackend`` whose ``_ripgrep_search`` lacks the Windows
None-stdout guard, so a workspace grep crashed. The subclass inherits Nova's
guarded (and non-hanging) grep while keeping ``execute``.
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING
from unittest.mock import patch

from deepagents.backends.local_shell import LocalShellBackend

from novacode_cli.backends import OptimizedFilesystemBackend, OptimizedLocalShellBackend

if TYPE_CHECKING:
    from pathlib import Path


class _FakeProc:
    """Mimics subprocess.CompletedProcess with stdout=None."""

    def __init__(self, returncode: int = 0, stdout: object = None, stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _backend(tmp_path: Path) -> OptimizedLocalShellBackend:
    return OptimizedLocalShellBackend(root_dir=str(tmp_path), virtual_mode=False)


def test_grep_uses_optimized_not_deepagents_base():
    # grep / _ripgrep_search must resolve to Nova's guarded versions via the MRO.
    assert OptimizedLocalShellBackend.grep is OptimizedFilesystemBackend.grep
    assert OptimizedLocalShellBackend._ripgrep_search is OptimizedFilesystemBackend._ripgrep_search


def test_search_overrides_match_installed_deepagents_contract():
    """The overrides must return the shape the INSTALLED parent grep() unpacks.

    deepagents changed this in 0.7.0 (dict -> (dict, truncated)) and pyproject
    allows both (>=0.6.8). Returning only the new shape under 0.6.x made the
    parent call .items() on a tuple — "'tuple' object has no attribute 'items'"
    on every literal grep. Pin the adaptation to the parent's real signature.
    """
    import inspect

    from deepagents.backends.filesystem import FilesystemBackend

    import novacode_cli.backends.filesystem as fsmod

    rg_v2 = "max_count" in inspect.signature(FilesystemBackend._ripgrep_search).parameters
    py_v2 = "max_count" in inspect.signature(FilesystemBackend._python_search).parameters
    assert fsmod._PARENT_RG_V2 is rg_v2
    assert fsmod._PARENT_PY_V2 is py_v2

    # And the override's arity must accept however the parent calls it.
    params = inspect.signature(FilesystemBackend._ripgrep_search).parameters
    ours = inspect.signature(fsmod.OptimizedFilesystemBackend._ripgrep_search).parameters
    for name in params:
        assert name in ours, f"parent passes {name!r} but our override lacks it"


def test_grep_returns_matches_under_installed_contract(tmp_path: Path):
    """End-to-end literal grep through the parent's grep() — the path that broke."""
    (tmp_path / "a.py").write_text("hello world\n", encoding="utf-8")
    backend = _backend(tmp_path)
    result = backend.grep("hello", path=".")
    assert result.error is None
    assert len(result.matches) == 1


def test_none_stdout_does_not_crash(tmp_path: Path):
    backend = _backend(tmp_path)
    with patch.object(subprocess, "run", return_value=_FakeProc(returncode=0, stdout=None)):
        result, _truncated = backend._rg_impl("some_pattern", tmp_path, None)
    assert result == {}


def test_still_supports_local_execute(tmp_path: Path):
    backend = _backend(tmp_path)
    # The whole reason the default backend is LocalShellBackend: the execute tool.
    assert isinstance(backend, LocalShellBackend)
    assert hasattr(backend, "execute")

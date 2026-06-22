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


def test_none_stdout_does_not_crash(tmp_path: Path):
    backend = _backend(tmp_path)
    with patch.object(subprocess, "run", return_value=_FakeProc(returncode=0, stdout=None)):
        result = backend._ripgrep_search("some_pattern", tmp_path, None)
    assert result == {}


def test_still_supports_local_execute(tmp_path: Path):
    backend = _backend(tmp_path)
    # The whole reason the default backend is LocalShellBackend: the execute tool.
    assert isinstance(backend, LocalShellBackend)
    assert hasattr(backend, "execute")

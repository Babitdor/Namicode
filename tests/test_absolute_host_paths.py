"""Real absolute host paths reach the filesystem tools.

Pins the reported bug: a file in a *sibling* project was unreachable —

    Windows absolute paths are not supported:
    B:/Summer Project 2026/ai-job-search/docs/CV.pdf

for reads *and* writes. Paths inside the workspace were rewritten to virtual
form and worked; one directory over was refused outright, with a message that
blamed the drive letter rather than the real rule.

Nova now takes real paths the way Claude Code does: the path is passed through,
and access is gated by the approval policy (``write_file``/``edit_file`` default
to ``ask``; system/secret globs are denied) rather than by refusing to name the
file. These tests cover both halves — validation must accept the path, and the
backend must actually serve it, since either alone silently looks like it works.
"""

from __future__ import annotations

import pathlib

import pytest


@pytest.fixture
def outside(tmp_path) -> pathlib.Path:
    """A directory outside the workspace, shaped like the reported case."""
    d = tmp_path / "ai-job-search" / "docs"
    d.mkdir(parents=True)
    (d / "CV.txt").write_text("PDF-CONTENT", encoding="utf-8")
    return d


def _validate():
    from novacode_cli.utils.backend_patches import apply_filesystem_host_path_patch

    apply_filesystem_host_path_patch()
    import deepagents.middleware.filesystem as fsmod

    return fsmod.validate_path


# ── validation ──────────────────────────────────────────────────────────────


def test_outside_file_is_accepted(outside):
    """The reported failure: reading a sibling project's file."""
    host = str(outside / "CV.txt").replace("\\", "/")
    assert _validate()(host) == host


def test_new_file_outside_is_accepted(outside):
    """write_file creates files — requiring existence would block every write."""
    host = str(outside / "notes.md").replace("\\", "/")
    assert _validate()(host) == host


def test_path_in_a_nonexistent_directory_still_fails(outside):
    """A typo has no real parent, so it gets the stock validator's error."""
    host = str(outside / "no_such_dir" / "x.md").replace("\\", "/")
    with pytest.raises(ValueError, match="Windows absolute|not supported"):
        _validate()(host)


def test_virtual_paths_are_untouched():
    assert _validate()("/skills/x/SKILL.md") == "/skills/x/SKILL.md"


def test_traversal_is_still_rejected():
    """Passing host paths through must not open a traversal hole."""
    with pytest.raises(ValueError):
        _validate()("../../etc/passwd")


def test_workspace_paths_still_become_virtual():
    """The existing rewrite must keep working — every route depends on it."""
    from novacode_cli.config.config import settings

    ws = str(settings.get_workspace_root()).replace("\\", "/")
    assert _validate()(f"{ws}/README.md") == "/README.md"


# ── backend resolution ──────────────────────────────────────────────────────


def test_drive_roots_cover_the_workspace_drive():
    import os

    from novacode_cli.agents.core_agent import _host_drive_roots
    from novacode_cli.config.config import settings

    roots = _host_drive_roots(settings.get_workspace_root())
    assert roots, "no filesystem roots to mount"
    if os.name == "nt":
        anchor = pathlib.Path(settings.get_workspace_root()).anchor.replace("\\", "/")
        assert any(r.rstrip("/").lower() == anchor.rstrip("/").lower() for r in roots)
    else:
        assert roots == ["/"]


def test_backend_reads_and_writes_a_real_outside_path(outside):
    """Validation alone is not enough — the bytes have to move."""
    from deepagents.backends.composite import CompositeBackend
    from deepagents.backends.filesystem import FilesystemBackend

    host = str(outside / "CV.txt").replace("\\", "/")
    drive = host.split("/")[0] + "/" if ":" in host.split("/")[0] else "/"

    cb = CompositeBackend(
        default=FilesystemBackend(root_dir=str(outside.parent), virtual_mode=True),
        routes={drive: FilesystemBackend(root_dir=drive, virtual_mode=True)},
    )

    backend, key = cb._get_backend_and_key(host)
    assert "PDF-CONTENT" in str(getattr(backend.read(key), "file_data", ""))

    new_host = str(outside / "out.md").replace("\\", "/")
    wbackend, wkey = cb._get_backend_and_key(new_host)
    wbackend.write(wkey, "written by nova")
    assert (outside / "out.md").read_text(encoding="utf-8") == "written by nova"

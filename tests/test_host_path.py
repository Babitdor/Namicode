"""Tests for host-path → virtual-path normalization and the validate_path patch.

The agent constantly passes real host absolute paths to file tools; deepagents'
``validate_path`` rejects them ("Windows absolute paths are not supported").
These verify the normalization helper and that the monkey-patch makes such paths
work end-to-end while leaving genuinely-invalid paths erroring.
"""

import pytest

from novacode_cli.integrations.host_path import host_path_to_virtual

WIN_ROOT = "B:/Summer Project 2026/Nova-Code/nova-code-cli"


# ── pure helper ──────────────────────────────────────────────────────────
def test_windows_forward_slash_inside_project():
    p = WIN_ROOT + "/novacode_cli/prompts/plan_agent.jinja"
    assert host_path_to_virtual(p, WIN_ROOT) == "/novacode_cli/prompts/plan_agent.jinja"


def test_windows_backslash_and_case_insensitive():
    p = "b:\\Summer Project 2026\\Nova-Code\\nova-code-cli\\novacode_cli\\main.py"
    # Case-insensitive match only applies on Windows hosts.
    import os
    expected = "/novacode_cli/main.py" if os.name == "nt" else p
    assert host_path_to_virtual(p, WIN_ROOT) == expected


def test_root_itself_maps_to_slash():
    assert host_path_to_virtual(WIN_ROOT, WIN_ROOT) == "/"


def test_already_virtual_unchanged():
    assert host_path_to_virtual("/novacode_cli/x.py", WIN_ROOT) == "/novacode_cli/x.py"


def test_relative_unchanged():
    assert host_path_to_virtual("novacode_cli/x.py", WIN_ROOT) == "novacode_cli/x.py"


def test_out_of_project_absolute_unchanged():
    assert host_path_to_virtual("C:/Windows/system32/notepad.exe", WIN_ROOT) == (
        "C:/Windows/system32/notepad.exe"
    )


def test_posix_host_path_inside_project():
    root = "/home/user/project"
    assert host_path_to_virtual(root + "/src/app.py", root) == "/src/app.py"


def test_empty_and_none_inputs():
    assert host_path_to_virtual("", WIN_ROOT) == ""
    assert host_path_to_virtual("/x", "") == "/x"


# ── the validate_path monkey-patch (the actual fix) ──────────────────────
def test_patch_makes_host_path_validate(monkeypatch, tmp_path):
    pytest.importorskip("deepagents.middleware.filesystem")
    import deepagents.middleware.filesystem as fsmod

    # Point the patch's notion of the project root at tmp_path.
    from novacode_cli.config import config as cfg
    monkeypatch.setattr(cfg.settings, "project_root", tmp_path, raising=False)

    original = fsmod.validate_path
    try:
        # Apply our patch freshly (reset the module-level idempotency guard).
        import novacode_cli.utils.backend_patches as bp
        monkeypatch.setattr(bp, "_fs_host_path_patched", False, raising=False)
        bp.apply_filesystem_host_path_patch()

        host_path = str(tmp_path / "novacode_cli" / "prompts" / "plan_agent.jinja")
        # Before the patch this raised ValueError; now it normalizes to a virtual path.
        result = fsmod.validate_path(host_path)
        assert result == "/novacode_cli/prompts/plan_agent.jinja"

        # A host path OUTSIDE the project still raises (helpful error preserved).
        with pytest.raises(ValueError):
            fsmod.validate_path("Q:/somewhere/else/file.txt")
    finally:
        fsmod.validate_path = original

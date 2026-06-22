"""Tests for RefreshingSkillsMiddleware mid-session skill refresh."""

from __future__ import annotations

import os
import shutil
import time

from novacode_cli.backends import OptimizedFilesystemBackend as FilesystemBackend
from novacode_cli.skills.refreshing_middleware import RefreshingSkillsMiddleware


def _write_skill(skills_dir, name, desc="does things") -> None:  # noqa: ANN001
    sk = skills_dir / name
    sk.mkdir(parents=True, exist_ok=True)
    (sk / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {desc}\n---\n\n# {name}\n", encoding="utf-8"
    )


def _make(skills_dir):  # noqa: ANN001, ANN202
    backend = FilesystemBackend(root_dir=str(skills_dir), virtual_mode=True)
    return RefreshingSkillsMiddleware(backend=backend, sources=["."], watch_dirs=[skills_dir])


def test_skills_changed_first_call_then_stable(tmp_path):  # noqa: ANN001
    _write_skill(tmp_path, "alpha")
    mw = _make(tmp_path)
    assert mw._skills_changed() is True  # first call establishes the baseline
    assert mw._skills_changed() is False  # nothing changed since


def test_skills_changed_detects_add(tmp_path):  # noqa: ANN001
    _write_skill(tmp_path, "alpha")
    mw = _make(tmp_path)
    mw._skills_changed()  # baseline
    _write_skill(tmp_path, "beta")
    assert mw._skills_changed() is True


def test_skills_changed_detects_remove(tmp_path):  # noqa: ANN001
    _write_skill(tmp_path, "alpha")
    _write_skill(tmp_path, "beta")
    mw = _make(tmp_path)
    mw._skills_changed()  # baseline
    shutil.rmtree(tmp_path / "beta")
    assert mw._skills_changed() is True


def test_skills_changed_detects_edit(tmp_path):  # noqa: ANN001
    _write_skill(tmp_path, "alpha", desc="v1")
    mw = _make(tmp_path)
    mw._skills_changed()  # baseline
    p = tmp_path / "alpha" / "SKILL.md"
    p.write_text(p.read_text(encoding="utf-8").replace("v1", "v2"), encoding="utf-8")
    future = time.time() + 10
    os.utime(p, (future, future))  # ensure a distinct mtime
    assert mw._skills_changed() is True


def test_before_agent_defers_when_unchanged(tmp_path):  # noqa: ANN001
    _write_skill(tmp_path, "alpha")
    mw = _make(tmp_path)
    upd1 = mw.before_agent({}, None, None)
    assert upd1 is not None
    assert "alpha" in {s["name"] for s in upd1["skills_metadata"]}
    state = {"skills_metadata": upd1["skills_metadata"]}
    assert mw.before_agent(state, None, None) is None  # deferred, no reload


def test_before_agent_refreshes_after_new_skill(tmp_path):  # noqa: ANN001
    _write_skill(tmp_path, "alpha")
    mw = _make(tmp_path)
    upd1 = mw.before_agent({}, None, None)
    state = {"skills_metadata": upd1["skills_metadata"]}
    _write_skill(tmp_path, "beta")
    upd2 = mw.before_agent(state, None, None)
    assert upd2 is not None
    assert {s["name"] for s in upd2["skills_metadata"]} == {"alpha", "beta"}


async def test_abefore_agent_refreshes_after_new_skill(tmp_path):  # noqa: ANN001
    _write_skill(tmp_path, "alpha")
    mw = _make(tmp_path)
    upd1 = await mw.abefore_agent({}, None, None)
    state = {"skills_metadata": upd1["skills_metadata"]}
    _write_skill(tmp_path, "beta")
    upd2 = await mw.abefore_agent(state, None, None)
    assert "beta" in {s["name"] for s in upd2["skills_metadata"]}

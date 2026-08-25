"""Tests for Phase 1 — skill versioning + rollback safety.

Covers the versioning module directly and the new skill_manage actions
(history / rollback) plus soft-delete recoverability.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from novacode_cli.skills import versioning
from novacode_cli.tools.skill_tools import skill_manage

# Reuse the Settings/_generate_skill harness from the skill_manage tests.
from tests.test_skill_manage_tool import skill_env, _FakeSettings  # noqa: F401


def _write_skill(base: Path, name: str, body: str) -> Path:
    d = base / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(
        f'---\nname: {name}\ndescription: "x"\n---\n\n{body}\n', encoding="utf-8"
    )
    return d


# ── versioning module ────────────────────────────────────────────────────────


class TestVersioningModule:
    def test_snapshot_then_list(self, tmp_path):
        d = _write_skill(tmp_path / "skills", "s", "v1 body")
        ver = versioning.snapshot(d, reason="create")
        assert ver is not None
        versions = versioning.list_versions(d)
        assert len(versions) == 1
        assert versions[0]["reason"] == "create"

    def test_snapshot_none_when_no_skill_md(self, tmp_path):
        d = tmp_path / "skills" / "empty"
        d.mkdir(parents=True)
        assert versioning.snapshot(d, reason="create") is None

    def test_restore_latest(self, tmp_path):
        d = _write_skill(tmp_path / "skills", "s", "original")
        versioning.snapshot(d, reason="create")
        (d / "SKILL.md").write_text("changed", encoding="utf-8")
        ok, _ = versioning.restore(d)
        assert ok
        assert "original" in (d / "SKILL.md").read_text(encoding="utf-8")

    def test_restore_is_itself_reversible(self, tmp_path):
        # restore() snapshots the current state first (pre-rollback).
        d = _write_skill(tmp_path / "skills", "s", "original")
        versioning.snapshot(d, reason="create")
        (d / "SKILL.md").write_text("changed", encoding="utf-8")
        versioning.restore(d)
        reasons = [v["reason"] for v in versioning.list_versions(d)]
        assert "pre-rollback" in reasons

    def test_restore_specific_version(self, tmp_path):
        d = _write_skill(tmp_path / "skills", "s", "A")
        v1 = versioning.snapshot(d, reason="create")
        (d / "SKILL.md").write_text("B", encoding="utf-8")
        versioning.snapshot(d, reason="edit")
        (d / "SKILL.md").write_text("C", encoding="utf-8")
        ok, _ = versioning.restore(d, version=v1)
        assert ok
        content = (d / "SKILL.md").read_text(encoding="utf-8")
        assert "A" in content and "B" not in content and "C" not in content

    def test_rapid_snapshots_get_distinct_versions(self, tmp_path):
        """Back-to-back snapshots must not collide on the same id.

        Version ids were a bare timestamp, and the clock is coarse enough
        (notably on Windows) that two quick snapshots produced the SAME id — the
        second overwrote the first, so restoring the earlier version silently
        returned the later content. This made restore tests fail ~50% of runs.
        """
        d = _write_skill(tmp_path / "skills", "s", "v0")
        ids = []
        for i in range(8):
            (d / "SKILL.md").write_text(f"v{i}", encoding="utf-8")
            ids.append(versioning.snapshot(d, reason=f"edit{i}"))

        assert len(set(ids)) == len(ids), f"duplicate version ids: {ids}"
        # Sortable: creation order must survive as lexicographic order.
        assert ids == sorted(ids)
        assert len(versioning.list_versions(d)) == len(ids)

    def test_each_rapid_version_restores_its_own_content(self, tmp_path):
        d = _write_skill(tmp_path / "skills", "s", "v0")
        made = []
        for i in range(5):
            (d / "SKILL.md").write_text(f"content-{i}", encoding="utf-8")
            made.append((versioning.snapshot(d, reason=f"e{i}"), f"content-{i}"))

        for version, expected in made:
            ok, _ = versioning.restore(d, version=version)
            assert ok
            assert (d / "SKILL.md").read_text(encoding="utf-8") == expected

    def test_restore_no_history(self, tmp_path):
        d = _write_skill(tmp_path / "skills", "s", "x")
        ok, msg = versioning.restore(d)
        assert not ok and "no version history" in msg

    def test_archive_moves_outside_skills_root(self, tmp_path):
        skills_root = tmp_path / "skills"
        d = _write_skill(skills_root, "s", "x")
        dest = versioning.archive_skill(d)
        assert dest is not None
        assert not d.exists()
        assert dest.exists()
        # Archive lives outside the skills root so it is never listed.
        assert skills_root not in dest.parents


# ── skill_manage integration ─────────────────────────────────────────────────


def _run(action: str, **kw) -> str:
    return asyncio.run(skill_manage.ainvoke({"action": action, **kw}))


class TestSkillManageVersioning:
    def test_patch_creates_snapshot(self, skill_env):
        _run("create", name="vs", description="trigger")  # stub body has "Step 1."
        _run("patch", name="vs", old="Step 1.", new="Step 2.")
        d = skill_env["user"] / "vs"
        reasons = [v["reason"] for v in versioning.list_versions(d)]
        assert "create" in reasons and "patch" in reasons

    def test_rollback_restores_previous(self, skill_env):
        _run("create", name="vs", description="trigger")
        _run("patch", name="vs", old="Step 1.", new="Step 2.")
        result = _run("rollback", name="vs")
        assert "Rolled back" in result
        content = (skill_env["user"] / "vs" / "SKILL.md").read_text(encoding="utf-8")
        assert "Step 1." in content and "Step 2." not in content

    def test_history_lists_versions(self, skill_env):
        _run("create", name="vs", description="trigger")
        _run("edit", name="vs", body="new body")
        out = _run("history", name="vs")
        assert "Version history" in out
        assert "create" in out and "edit" in out

    def test_delete_is_soft_and_recoverable(self, skill_env):
        _run("create", name="vs", description="trigger")
        result = _run("delete", name="vs")
        assert "Archived" in result
        assert not (skill_env["user"] / "vs").exists()
        # Archive dir is the sibling of the skills root.
        archive_root = skill_env["user"].parent / "skills-archive"
        assert archive_root.exists()
        assert any(archive_root.iterdir())

    def test_cannot_rollback_bundled(self, skill_env):
        _write_skill(skill_env["claude"], "bundled", "x")
        versioning.snapshot(skill_env["claude"] / "bundled", reason="create")
        result = _run("rollback", name="bundled")
        assert "bundled skill" in result and "cannot" in result

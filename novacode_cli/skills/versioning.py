"""Skill versioning + rollback safety.

Every mutation of a skill (create / patch / edit / refine) snapshots the prior
``SKILL.md`` first, so a buggy or ineffective change can be reverted instantly.
Deletes are *soft* — the skill directory is moved to a sibling archive rather
than removed — so it, too, is recoverable.

Layout::

    <skills_root>/<name>/SKILL.md
    <skills_root>/<name>/.history/<version>.md      # snapshots
    <skills_root>/<name>/.history/manifest.json     # version log
    <skills_root>/../skills-archive/<name>-<ts>/    # soft-deleted skills

The ``.history`` directory lives *inside* the skill dir (it has no ``SKILL.md``
so the skill lister ignores it, and the supporting-file loader skips dot-dirs).
The archive lives *outside* the skills root so archived skills are never listed.
"""

from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("nova.skills.versioning")

_HISTORY_DIR = ".history"
_MANIFEST = "manifest.json"
_ARCHIVE_DIRNAME = "skills-archive"


def _now_version() -> str:
    """A sortable, collision-resistant version id."""
    return datetime.now().strftime("%Y%m%dT%H%M%S_%f")


def _manifest_path(skill_dir: Path) -> Path:
    return skill_dir / _HISTORY_DIR / _MANIFEST


def _read_manifest(skill_dir: Path) -> dict:
    path = _manifest_path(skill_dir)
    if not path.exists():
        return {"versions": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("versions"), list):
            return data
    except (json.JSONDecodeError, OSError):
        pass
    return {"versions": []}


def _write_manifest(skill_dir: Path, data: dict) -> None:
    path = _manifest_path(skill_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def snapshot(skill_dir: Path, reason: str, *, source: str = "agent") -> str | None:
    """Snapshot the current ``SKILL.md`` before it is overwritten.

    Returns the new version id, or ``None`` if there was nothing to snapshot
    (no SKILL.md yet) or the write failed. Best-effort — never raises.
    """
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        return None
    try:
        version = _now_version()
        hist = skill_dir / _HISTORY_DIR
        hist.mkdir(parents=True, exist_ok=True)
        shutil.copy2(skill_md, hist / f"{version}.md")

        data = _read_manifest(skill_dir)
        data["versions"].append(
            {
                "id": version,
                "file": f"{version}.md",
                "reason": reason,
                "source": source,
                "ts": datetime.now().timestamp(),
            }
        )
        _write_manifest(skill_dir, data)
        return version
    except OSError:
        logger.debug("Could not snapshot skill at %s", skill_dir, exc_info=True)
        return None


def list_versions(skill_dir: Path) -> list[dict]:
    """Return the version history (newest last) for a skill."""
    return _read_manifest(skill_dir).get("versions", [])


def restore(skill_dir: Path, version: str | None = None) -> tuple[bool, str]:
    """Restore a skill's ``SKILL.md`` from a snapshot.

    Snapshots the *current* state first (reason ``pre-rollback``) so the
    rollback is itself reversible, then restores either the named ``version``
    or the most recent snapshot.

    Returns ``(ok, message)``.
    """
    versions = list_versions(skill_dir)
    if not versions:
        return False, "no version history to roll back to"

    if version is None:
        target = versions[-1]
    else:
        target = next((v for v in versions if v["id"] == version), None)
        if target is None:
            return False, f"version '{version}' not found"

    snap_file = skill_dir / _HISTORY_DIR / target["file"]
    if not snap_file.exists():
        return False, f"snapshot file for '{target['id']}' is missing"

    try:
        snapshot(skill_dir, reason="pre-rollback", source="rollback")
        shutil.copy2(snap_file, skill_dir / "SKILL.md")
        return True, f"restored version {target['id']} ({target.get('reason', '')})"
    except OSError as exc:
        return False, f"restore failed: {exc}"


def archive_skill(skill_dir: Path) -> Path | None:
    """Soft-delete: move the skill dir to a sibling archive. Recoverable.

    The archive lives at ``<skills_root>/../skills-archive/`` so archived
    skills are outside any skills source and never listed. Returns the archive
    path, or ``None`` on failure.
    """
    skills_root = skill_dir.parent
    archive_root = skills_root.parent / _ARCHIVE_DIRNAME
    try:
        archive_root.mkdir(parents=True, exist_ok=True)
        dest = archive_root / f"{skill_dir.name}-{_now_version()}"
        shutil.move(str(skill_dir), str(dest))
        return dest
    except OSError:
        logger.debug("Could not archive skill %s", skill_dir, exc_info=True)
        return None


__all__ = ["snapshot", "list_versions", "restore", "archive_skill"]

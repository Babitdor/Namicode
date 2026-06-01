"""File recovery system: snapshots files before destructive operations.

Files are saved to ~/.nova/trash/<session_id>/ with a manifest.json index.
Use /restore to interactively pick and recover any snapshot.
"""

from __future__ import annotations

import json
import re
import shlex
import shutil
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

_TRASH_ROOT = Path.home() / ".nova" / "trash"
_MAX_SNAPSHOT_BYTES = 10 * 1024 * 1024  # 10 MB — skip larger files

REASON_LABELS = {
    "rm-command": "deleted (rm)",
    "write_file": "overwritten",
    "edit_file": "edited",
}


@dataclass
class SnapshotEntry:
    id: str
    original_path: str          # relative to workspace_root (or absolute if outside)
    snapshot_file: str          # filename inside session trash dir
    reason: str                 # "rm-command", "write_file", "edit_file"
    timestamp: str              # ISO 8601
    command: str | None = None  # shell command that triggered the snapshot (for rm)


class FileRecoveryManager:
    """Snapshots files before destructive operations and restores them on demand."""

    def __init__(self, session_id: str, workspace_root: Path) -> None:
        self.session_id = session_id
        self.workspace_root = workspace_root.resolve()
        self.session_dir = _TRASH_ROOT / session_id
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self._manifest_path = self.session_dir / "manifest.json"
        self._manifest: list[SnapshotEntry] = self._load_manifest()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def snapshot(
        self,
        file_path: Path | str,
        reason: str,
        command: str | None = None,
    ) -> bool:
        """Copy *file_path* into the trash dir.

        Returns True if the snapshot was created, False otherwise
        (file doesn't exist, too large, or an error occurred).
        """
        path = Path(file_path)
        if not path.is_absolute():
            path = (self.workspace_root / path).resolve()

        if not path.exists():
            return False

        # Skip very large files/dirs
        if path.is_file():
            try:
                if path.stat().st_size > _MAX_SNAPSHOT_BYTES:
                    return False
            except OSError:
                return False

        try:
            entry = self._write_snapshot(path, reason, command)
            self._manifest.append(entry)
            self._save_manifest()
            return True
        except Exception:
            return False

    def snapshot_from_content(
        self,
        file_path: str,
        content: str,
        reason: str,
    ) -> bool:
        """Snapshot using already-read content (avoids a second disk read).

        Used by FileOpTracker which already has before_content in memory.
        Returns True on success.
        """
        if not content:
            return False
        try:
            snapshot_name = self._make_snapshot_name(Path(file_path).name)
            dest = self.session_dir / snapshot_name
            dest.write_text(content, encoding="utf-8")

            rel = self._relative(file_path)
            entry = SnapshotEntry(
                id=str(uuid.uuid4())[:8],
                original_path=rel,
                snapshot_file=snapshot_name,
                reason=reason,
                timestamp=datetime.now().isoformat(timespec="seconds"),
            )
            self._manifest.append(entry)
            self._save_manifest()
            return True
        except Exception:
            return False

    def list_snapshots(self, include_past_sessions: bool = True) -> list[tuple[str, SnapshotEntry]]:
        """Return list of (session_id, entry) pairs, newest first.

        When *include_past_sessions* is True, also reads the last 3 other
        sessions from the trash root so the user can recover across restarts.
        """
        results: list[tuple[str, SnapshotEntry]] = [
            (self.session_id, e) for e in reversed(self._manifest)
        ]

        if include_past_sessions and _TRASH_ROOT.exists():
            other_sessions = sorted(
                (d for d in _TRASH_ROOT.iterdir() if d.is_dir() and d.name != self.session_id),
                key=lambda d: d.stat().st_mtime,
                reverse=True,
            )[:3]
            for session_dir in other_sessions:
                manifest_path = session_dir / "manifest.json"
                if manifest_path.exists():
                    try:
                        entries = _load_manifest_file(manifest_path)
                        results.extend((session_dir.name, e) for e in reversed(entries))
                    except Exception:
                        pass

        return results

    def restore(self, entry: SnapshotEntry, session_id: str | None = None) -> bool:
        """Copy *entry*'s snapshot back to its original path.

        Returns True on success.
        """
        trash_dir = _TRASH_ROOT / (session_id or self.session_id)
        snapshot_path = trash_dir / entry.snapshot_file
        if not snapshot_path.exists():
            return False

        target = Path(entry.original_path)
        if not target.is_absolute():
            target = self.workspace_root / target

        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(snapshot_path, target)
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _write_snapshot(
        self, path: Path, reason: str, command: str | None
    ) -> SnapshotEntry:
        snapshot_name = self._make_snapshot_name(path.name)
        dest = self.session_dir / snapshot_name

        if path.is_dir():
            shutil.make_archive(str(dest), "zip", path)
            snapshot_name = snapshot_name + ".zip"
        else:
            shutil.copy2(path, dest)

        rel = self._relative(str(path))
        return SnapshotEntry(
            id=str(uuid.uuid4())[:8],
            original_path=rel,
            snapshot_file=snapshot_name,
            reason=reason,
            timestamp=datetime.now().isoformat(timespec="seconds"),
            command=command,
        )

    def _make_snapshot_name(self, original_name: str) -> str:
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        uid = str(uuid.uuid4())[:4]
        return f"{ts}-{uid}_{original_name}"

    def _relative(self, path_str: str) -> str:
        """Return path relative to workspace_root if possible, else absolute."""
        try:
            return str(Path(path_str).resolve().relative_to(self.workspace_root))
        except ValueError:
            return str(Path(path_str).resolve())

    def _load_manifest(self) -> list[SnapshotEntry]:
        return _load_manifest_file(self._manifest_path)

    def _save_manifest(self) -> None:
        data = [asdict(e) for e in self._manifest]
        self._manifest_path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _load_manifest_file(path: Path) -> list[SnapshotEntry]:
    if not path.exists():
        return []
    try:
        data: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))
        return [SnapshotEntry(**d) for d in data]
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Session-level singleton
# ---------------------------------------------------------------------------

_manager: FileRecoveryManager | None = None


def get_recovery_manager(
    session_id: str | None = None,
    workspace_root: Path | None = None,
) -> FileRecoveryManager | None:
    """Return the session recovery manager, creating it on first call.

    Call with *session_id* and *workspace_root* once at session start to
    initialize. Subsequent calls (no args) return the existing instance.
    """
    global _manager
    if _manager is None:
        if session_id is None or workspace_root is None:
            return None
        _manager = FileRecoveryManager(session_id, workspace_root)
    return _manager


# ---------------------------------------------------------------------------
# Shell command helpers
# ---------------------------------------------------------------------------

def extract_rm_targets(command: str, workspace_root: Path) -> list[Path]:
    """Parse file paths from a shell rm command.

    Handles common forms: rm file, rm -f file, rm -rf dir, rm *.py
    Returns only paths that currently exist on disk.
    """
    try:
        parts = shlex.split(command)
    except ValueError:
        return []

    # Find the rm token (could be /bin/rm, sudo rm, etc.)
    rm_idx = next(
        (i for i, p in enumerate(parts) if re.search(r"\brm$", p)),
        None,
    )
    if rm_idx is None:
        return []

    # Everything after rm that doesn't start with - is a target
    raw_targets = []
    skip_next = False
    for part in parts[rm_idx + 1 :]:
        if skip_next:
            skip_next = False
            continue
        if part == "--":
            continue
        if part.startswith("-"):
            # Some flags take an argument (none common for rm, but be safe)
            continue
        raw_targets.append(part)

    result: list[Path] = []
    for t in raw_targets:
        if "*" in t or "?" in t or "[" in t:
            # Glob expand relative to workspace
            for match in workspace_root.glob(t):
                if match.exists():
                    result.append(match)
        else:
            candidate = Path(t) if Path(t).is_absolute() else workspace_root / t
            if candidate.exists():
                result.append(candidate)

    return result


# ---------------------------------------------------------------------------
# Agent-callable tools
# ---------------------------------------------------------------------------

def list_trash(path_filter: str | None = None) -> dict:
    """List file snapshots available for recovery.

    Shows files that were deleted or overwritten by the agent during this
    session (and recent past sessions). Use this to discover what can be
    restored before calling restore_file.

    Args:
        path_filter: Optional substring to filter results by path
                     (e.g. "src/", ".py", "utils"). Default: show all.

    Returns:
        Dictionary with:
        - success: bool
        - snapshots: list of {index, original_path, reason, timestamp, session_id}
        - total: number of snapshots found
    """
    mgr = get_recovery_manager()
    if mgr is None:
        return {"success": False, "error": "Recovery manager not initialized", "snapshots": [], "total": 0}

    raw = mgr.list_snapshots(include_past_sessions=True)

    results = []
    for i, (session_id, entry) in enumerate(raw, 1):
        if path_filter and path_filter not in entry.original_path:
            continue
        results.append({
            "index": i,
            "original_path": entry.original_path,
            "reason": REASON_LABELS.get(entry.reason, entry.reason),
            "timestamp": entry.timestamp,
            "session_id": session_id,
            "snapshot_id": entry.id,
        })

    return {"success": True, "snapshots": results, "total": len(results)}


def restore_file(original_path: str) -> dict:
    """Restore a file from the snapshot trash to its original location.

    Recovers the most recent snapshot for the given path. The file will be
    written back to where it was before the agent deleted or overwrote it.

    Call list_trash() first if you are unsure what snapshots exist.

    Args:
        original_path: The original file path to restore (relative or absolute).
                       Partial matches work — e.g. "utils.py" matches
                       "NovaCode_cli/utils.py".

    Returns:
        Dictionary with:
        - success: bool
        - restored_path: the path the file was written to (on success)
        - error: description of failure (on failure)
    """
    mgr = get_recovery_manager()
    if mgr is None:
        return {"success": False, "error": "Recovery manager not initialized"}

    snapshots = mgr.list_snapshots(include_past_sessions=True)

    # Find the most recent snapshot matching the path
    for session_id, entry in snapshots:
        if original_path in entry.original_path or entry.original_path.endswith(original_path):
            ok = mgr.restore(entry, session_id=session_id)
            if ok:
                return {"success": True, "restored_path": entry.original_path}
            else:
                return {
                    "success": False,
                    "error": f"Snapshot file missing from trash for '{entry.original_path}'",
                }

    return {
        "success": False,
        "error": f"No snapshot found matching '{original_path}'. Call list_trash() to see available snapshots.",
    }

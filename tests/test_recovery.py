"""Tests for recovery.py — file recovery system."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from novacode_cli.recovery import (
    FileRecoveryManager,
    SnapshotEntry,
    _load_manifest_file,
    extract_rm_targets,
    get_recovery_manager,
)


class TestLoadManifestFile:
    """_load_manifest_file: loads SnapshotEntry list from JSON."""

    def test_missing_file_returns_empty(self, tmp_path):
        assert _load_manifest_file(tmp_path / "nonexistent.json") == []

    def test_valid_manifest(self, tmp_path):
        entries = [
            {"id": "abc123", "original_path": "src/main.py", "snapshot_file": "ts-uid_main.py", "reason": "write_file", "timestamp": "2026-01-01T00:00:00"},
        ]
        manifest = tmp_path / "manifest.json"
        manifest.write_text(json.dumps(entries))
        result = _load_manifest_file(manifest)
        assert len(result) == 1
        assert result[0].id == "abc123"
        assert result[0].original_path == "src/main.py"

    def test_corrupted_json_returns_empty(self, tmp_path):
        manifest = tmp_path / "manifest.json"
        manifest.write_text("not json")
        assert _load_manifest_file(manifest) == []

    def test_empty_list(self, tmp_path):
        manifest = tmp_path / "manifest.json"
        manifest.write_text("[]")
        assert _load_manifest_file(manifest) == []


class TestExtractRmTargets:
    """extract_rm_targets: parse file paths from rm commands."""

    def test_simple_file(self, tmp_path):
        target = tmp_path / "test.txt"
        target.write_text("hello")
        result = extract_rm_targets(f"rm {target}", tmp_path)
        assert len(result) == 1
        assert result[0] == target

    def test_rm_with_flags(self, tmp_path):
        target = tmp_path / "test.txt"
        target.write_text("hello")
        result = extract_rm_targets(f"rm -rf {target}", tmp_path)
        assert len(result) == 1
        assert result[0] == target

    def test_glob_expansion(self, tmp_path):
        (tmp_path / "a.py").write_text("a")
        (tmp_path / "b.py").write_text("b")
        result = extract_rm_targets("rm *.py", tmp_path)
        assert len(result) == 2

    def test_no_rm_command_returns_empty(self, tmp_path):
        result = extract_rm_targets("echo hello", tmp_path)
        assert result == []

    def test_non_existent_file_skipped(self, tmp_path):
        result = extract_rm_targets("rm nonexistent.txt", tmp_path)
        assert result == []

    def test_malformed_command_returns_empty(self, tmp_path):
        result = extract_rm_targets("rm 'unclosed", tmp_path)
        assert result == []


class TestFileRecoveryManager:
    """FileRecoveryManager: snapshot, list, restore."""

    @pytest.fixture(autouse=True)
    def _setup(self, tmp_path, monkeypatch):
        import novacode_cli.recovery as rec
        rec._manager = None
        # Isolate trash to tmp_path so tests don't collide
        monkeypatch.setattr(rec, "_TRASH_ROOT", tmp_path / ".nova" / "trash")

    def test_snapshot_file(self, tmp_path):
        workspace = tmp_path / "project"
        workspace.mkdir()
        target = workspace / "main.py"
        target.write_text("print('hello')")

        mgr = FileRecoveryManager("snap-file", workspace)
        assert mgr.snapshot(target, reason="write_file") is True

        entries = mgr.list_snapshots(include_past_sessions=False)
        assert len(entries) == 1
        assert entries[0][1].original_path == "main.py"

    def test_snapshot_nonexistent_file(self, tmp_path):
        workspace = tmp_path / "project"
        workspace.mkdir()
        mgr = FileRecoveryManager("snap-nonexist", workspace)
        assert mgr.snapshot(workspace / "nonexistent.py", reason="write_file") is False

    def test_snapshot_from_content(self, tmp_path):
        workspace = tmp_path / "project"
        workspace.mkdir()
        mgr = FileRecoveryManager("snap-content", workspace)
        assert mgr.snapshot_from_content("src/main.py", "print('hello')", reason="write_file") is True

        entries = mgr.list_snapshots(include_past_sessions=False)
        assert len(entries) == 1
        # Path is stored as absolute since it's not under workspace_root
        assert "src/main.py" in entries[0][1].original_path

    def test_snapshot_from_empty_content(self, tmp_path):
        workspace = tmp_path / "project"
        workspace.mkdir()
        mgr = FileRecoveryManager("snap-empty", workspace)
        assert mgr.snapshot_from_content("src/main.py", "", reason="write_file") is False

    def test_restore_snapshot(self, tmp_path):
        workspace = tmp_path / "project"
        workspace.mkdir()
        target = workspace / "main.py"
        target.write_text("original content")

        mgr = FileRecoveryManager("test-restore", workspace)
        mgr.snapshot(target, reason="write_file")

        # Overwrite the file
        target.write_text("new content")

        # Restore from snapshot
        entries = mgr.list_snapshots(include_past_sessions=False)
        assert mgr.restore(entries[0][1]) is True
        assert target.read_text() == "original content"

    def test_restore_missing_snapshot(self, tmp_path):
        workspace = tmp_path / "project"
        workspace.mkdir()
        mgr = FileRecoveryManager("restore-miss", workspace)
        entry = SnapshotEntry(
            id="test", original_path="main.py", snapshot_file="nonexistent",
            reason="write_file", timestamp="2026-01-01T00:00:00",
        )
        assert mgr.restore(entry) is False

    def test_list_snapshots_multiple(self, tmp_path):
        workspace = tmp_path / "project"
        workspace.mkdir()
        (workspace / "a.py").write_text("a")
        (workspace / "b.py").write_text("b")

        mgr = FileRecoveryManager("list-multi", workspace)
        mgr.snapshot(workspace / "a.py", reason="write_file")
        mgr.snapshot(workspace / "b.py", reason="edit_file")

        entries = mgr.list_snapshots(include_past_sessions=False)
        assert len(entries) == 2

    def test_manifest_persists_across_instances(self, tmp_path):
        workspace = tmp_path / "project"
        workspace.mkdir()
        target = workspace / "main.py"
        target.write_text("content")

        mgr1 = FileRecoveryManager("test-persist", workspace)
        mgr1.snapshot(target, reason="write_file")

        # New manager with same session should load existing manifest
        mgr2 = FileRecoveryManager("test-persist", workspace)
        entries = mgr2.list_snapshots(include_past_sessions=False)
        assert len(entries) == 1


class TestGetRecoveryManager:
    """get_recovery_manager: session-level singleton."""

    def test_returns_none_before_init(self):
        # Reset the global
        import novacode_cli.recovery as rec
        rec._manager = None
        assert get_recovery_manager() is None

    def test_creates_on_first_call(self, tmp_path):
        import novacode_cli.recovery as rec
        rec._manager = None
        mgr = get_recovery_manager("test-session", tmp_path)
        assert mgr is not None
        assert mgr.session_id == "test-session"

    def test_returns_same_instance(self, tmp_path):
        import novacode_cli.recovery as rec
        rec._manager = None
        mgr1 = get_recovery_manager("test-session", tmp_path)
        mgr2 = get_recovery_manager()
        assert mgr1 is mgr2

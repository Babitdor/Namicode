"""Tests for FileTrackerMiddleware's read-before-edit gate.

The gate prevents edits to files the agent hasn't seen, but a file the agent
*wrote* this session is known content too — gating it falsely rejected the very
common write_file→edit_file pattern. These lock in the relaxed behavior.
"""

from __future__ import annotations

import types

from novacode_cli.tracking.file_tracker import (
    FileTrackerMiddleware,
    get_session_tracker,
    reset_session_tracker,
)


def _req(name: str, args: dict):
    return types.SimpleNamespace(tool_call={"name": name, "args": args, "id": "tc1"})


def _edit(path: str):
    return _req("edit_file", {"file_path": path, "old_string": "a", "new_string": "b"})


def test_edit_on_unseen_file_is_rejected_as_error():
    reset_session_tracker()
    mw = FileTrackerMiddleware()
    rejection = mw._check_edit_allowed(_edit("/unseen.py"))
    assert rejection is not None
    # Surfaced as an error so the UI shows a failed edit, not a silent no-diff ✓.
    assert getattr(rejection, "status", None) == "error"


def test_edit_after_read_is_allowed():
    reset_session_tracker()
    mw = FileTrackerMiddleware()
    get_session_tracker().record_read("/bar.py", "content")
    assert mw._check_edit_allowed(_edit("/bar.py")) is None


def test_edit_after_write_is_allowed():
    # The regression: writing a file then editing it must not be rejected.
    reset_session_tracker()
    mw = FileTrackerMiddleware()
    get_session_tracker().record_write("/foo.py", "new content", operation="write")
    assert mw._check_edit_allowed(_edit("/foo.py")) is None


def test_gate_disabled_allows_everything():
    reset_session_tracker()
    mw = FileTrackerMiddleware(enforce_read_before_edit=False)
    assert mw._check_edit_allowed(_edit("/whatever.py")) is None


if __name__ == "__main__":
    test_edit_on_unseen_file_is_rejected_as_error()
    test_edit_after_read_is_allowed()
    test_edit_after_write_is_allowed()
    test_gate_disabled_allows_everything()
    print("ALL TESTS PASSED")

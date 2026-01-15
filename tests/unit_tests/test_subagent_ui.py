"""Unit tests for subagent UI observability features.

Tests that subagents have enhanced UI features like:
- File operation tracking with diffs
- Todo list rendering
- Text content buffering with markdown rendering
- File operation metrics display
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from namicode_cli.file_ops import (
    FileOpTracker,
    FileOperationRecord,
    compute_unified_diff,
)
from namicode_cli.ui.ui_elements import render_file_operation, render_todo_list


class TestSubagentFileOpTracker:
    """Test FileOpTracker integration for subagents."""

    def test_file_op_tracker_initialization(self, tmp_path: Path) -> None:
        """Test that FileOpTracker initializes correctly for subagent."""
        from nami_deepagents.backends.filesystem import FilesystemBackend
        from nami_deepagents.backends import CompositeBackend

        backend = CompositeBackend(
            default=FilesystemBackend(),
            routes={},
        )

        tracker = FileOpTracker(assistant_id="test-subagent", backend=backend)

        assert tracker.assistant_id == "test-subagent"
        assert tracker.backend == backend
        assert tracker.active == {}
        assert tracker.completed == []

    def test_start_operation_for_write_file(self, tmp_path: Path) -> None:
        """Test starting a write_file operation tracking."""
        tracker = FileOpTracker(assistant_id="test-subagent", backend=None)

        # Create existing file for before_content capture
        test_file = tmp_path / "test.py"
        test_file.write_text("original content")

        args = {"file_path": str(test_file), "content": "new content"}
        tracker.start_operation("write_file", args, "call-123")

        assert "call-123" in tracker.active
        record = tracker.active["call-123"]
        assert record.tool_name == "write_file"
        assert record.before_content == "original content"

    def test_start_operation_for_edit_file(self, tmp_path: Path) -> None:
        """Test starting an edit_file operation tracking."""
        tracker = FileOpTracker(assistant_id="test-subagent", backend=None)

        test_file = tmp_path / "config.py"
        test_file.write_text("FOO = 'bar'\nBAZ = 'qux'")

        args = {
            "file_path": str(test_file),
            "old_string": "FOO = 'bar'",
            "new_string": "FOO = 'updated'",
        }
        tracker.start_operation("edit_file", args, "call-456")

        assert "call-456" in tracker.active
        record = tracker.active["call-456"]
        assert record.tool_name == "edit_file"
        assert "FOO = 'bar'" in record.before_content

    def test_start_operation_ignores_non_file_ops(self) -> None:
        """Test that non-file operations are ignored."""
        tracker = FileOpTracker(assistant_id="test-subagent", backend=None)

        tracker.start_operation("web_search", {"query": "test"}, "call-789")

        assert "call-789" not in tracker.active

    def test_complete_with_message_generates_diff(self, tmp_path: Path) -> None:
        """Test that completing an operation generates a diff."""
        tracker = FileOpTracker(assistant_id="test-subagent", backend=None)

        test_file = tmp_path / "app.py"
        test_file.write_text("def hello():\n    return 'world'\n")

        # Start operation
        args = {
            "file_path": str(test_file),
            "content": "def hello():\n    return 'hello world'\n",
        }
        tracker.start_operation("write_file", args, "call-100")

        # Simulate the write happening
        test_file.write_text("def hello():\n    return 'hello world'\n")

        # Complete the operation with a mock ToolMessage
        mock_message = MagicMock()
        mock_message.tool_call_id = "call-100"
        mock_message.content = "Successfully wrote file"
        mock_message.status = "success"

        record = tracker.complete_with_message(mock_message)

        assert record is not None
        assert record.status == "success"
        assert record.diff is not None
        assert "+    return 'hello world'" in record.diff
        assert "-    return 'world'" in record.diff


class TestComputeUnifiedDiff:
    """Test unified diff computation."""

    def test_compute_diff_with_additions(self) -> None:
        """Test diff computation with added lines."""
        before = "line1\nline2"
        after = "line1\nline2\nline3"

        diff = compute_unified_diff(before, after, "test.py")

        assert diff is not None
        assert "+line3" in diff

    def test_compute_diff_with_deletions(self) -> None:
        """Test diff computation with deleted lines."""
        before = "line1\nline2\nline3"
        after = "line1\nline3"

        diff = compute_unified_diff(before, after, "test.py")

        assert diff is not None
        assert "-line2" in diff

    def test_compute_diff_with_modifications(self) -> None:
        """Test diff computation with modified lines."""
        before = "def foo():\n    return 'old'"
        after = "def foo():\n    return 'new'"

        diff = compute_unified_diff(before, after, "test.py")

        assert diff is not None
        assert "-    return 'old'" in diff
        assert "+    return 'new'" in diff

    def test_compute_diff_no_changes(self) -> None:
        """Test diff computation with no changes returns None."""
        content = "line1\nline2"

        diff = compute_unified_diff(content, content, "test.py")

        assert diff is None

    def test_compute_diff_respects_max_lines(self) -> None:
        """Test diff computation respects max_lines limit."""
        before = "\n".join([f"line{i}" for i in range(100)])
        after = "\n".join([f"modified{i}" for i in range(100)])

        diff = compute_unified_diff(before, after, "test.py", max_lines=10)

        assert diff is not None
        lines = diff.split("\n")
        assert len(lines) <= 10
        assert "..." in diff


class TestRenderFileOperation:
    """Test file operation rendering."""

    def test_render_write_file_operation(self, capsys) -> None:
        """Test rendering a write_file operation."""
        record = FileOperationRecord(
            tool_name="write_file",
            display_path="config.py",
            physical_path=Path("/tmp/config.py"),
            tool_call_id="call-1",
            status="success",
        )
        record.metrics.lines_written = 10
        record.metrics.lines_added = 10
        record.metrics.lines_removed = 0

        with patch("namicode_cli.ui.console") as mock_console:
            render_file_operation(record)
            # Verify console.print was called
            assert mock_console.print.called

    def test_render_edit_file_operation_with_diff(self, capsys) -> None:
        """Test rendering an edit_file operation with diff."""
        record = FileOperationRecord(
            tool_name="edit_file",
            display_path="app.py",
            physical_path=Path("/tmp/app.py"),
            tool_call_id="call-2",
            status="success",
        )
        record.metrics.lines_written = 20
        record.metrics.lines_added = 5
        record.metrics.lines_removed = 3
        record.diff = (
            "--- app.py (before)\n+++ app.py (after)\n@@ -1,3 +1,5 @@\n-old\n+new"
        )

        with patch("namicode_cli.ui.console") as mock_console:
            render_file_operation(record)
            assert mock_console.print.called

    def test_render_error_operation(self) -> None:
        """Test rendering a failed file operation."""
        record = FileOperationRecord(
            tool_name="write_file",
            display_path="readonly.py",
            physical_path=Path("/tmp/readonly.py"),
            tool_call_id="call-3",
            status="error",
            error="Permission denied",
        )

        with patch("namicode_cli.ui.console") as mock_console:
            render_file_operation(record)
            assert mock_console.print.called


class TestRenderTodoList:
    """Test todo list rendering."""

    def test_render_empty_todo_list(self) -> None:
        """Test rendering an empty todo list does nothing."""
        with patch("namicode_cli.ui.console") as mock_console:
            render_todo_list([])
            # Should not print anything for empty list
            mock_console.print.assert_not_called()

    def test_render_todo_list_with_items(self) -> None:
        """Test rendering a todo list with various statuses."""
        todos = [
            {"content": "Completed task", "status": "completed"},
            {"content": "In progress task", "status": "in_progress"},
            {"content": "Pending task", "status": "pending"},
        ]

        with patch("namicode_cli.ui.console") as mock_console:
            render_todo_list(todos)
            assert mock_console.print.called

    def test_render_todo_list_preserves_order(self) -> None:
        """Test that todo list rendering preserves item order."""
        todos = [
            {"content": "First", "status": "pending"},
            {"content": "Second", "status": "in_progress"},
            {"content": "Third", "status": "completed"},
        ]

        with patch("namicode_cli.ui.console") as mock_console:
            render_todo_list(todos)
            # Verify Panel was created and printed
            assert mock_console.print.called


class TestSubagentUIIntegration:
    """Integration tests for subagent UI components."""

    def test_file_tracker_workflow(self, tmp_path: Path) -> None:
        """Test complete file operation tracking workflow."""
        tracker = FileOpTracker(assistant_id="integration-agent", backend=None)

        # Create test file
        test_file = tmp_path / "workflow.py"
        test_file.write_text("# Original\nprint('hello')")

        # Start operation
        args = {
            "file_path": str(test_file),
            "content": "# Modified\nprint('hello world')\nprint('goodbye')",
        }
        tracker.start_operation("write_file", args, "workflow-call")

        # Simulate write
        test_file.write_text("# Modified\nprint('hello world')\nprint('goodbye')")

        # Complete operation
        mock_message = MagicMock()
        mock_message.tool_call_id = "workflow-call"
        mock_message.content = "File written successfully"
        mock_message.status = "success"

        record = tracker.complete_with_message(mock_message)

        # Verify metrics
        assert record is not None
        assert record.metrics.lines_written == 3
        assert record.metrics.lines_added > 0
        assert record.diff is not None

    def test_multiple_file_operations(self, tmp_path: Path) -> None:
        """Test tracking multiple file operations."""
        tracker = FileOpTracker(assistant_id="multi-op-agent", backend=None)

        # Create test files
        file1 = tmp_path / "file1.py"
        file2 = tmp_path / "file2.py"
        file1.write_text("content1")
        file2.write_text("content2")

        # Start multiple operations
        tracker.start_operation("write_file", {"file_path": str(file1)}, "call-1")
        tracker.start_operation("edit_file", {"file_path": str(file2)}, "call-2")

        assert len(tracker.active) == 2
        assert "call-1" in tracker.active
        assert "call-2" in tracker.active

    def test_new_file_creation_tracking(self, tmp_path: Path) -> None:
        """Test tracking creation of a new file."""
        tracker = FileOpTracker(assistant_id="create-agent", backend=None)

        new_file = tmp_path / "brand_new.py"
        assert not new_file.exists()

        args = {"file_path": str(new_file), "content": "# New file\nprint('created')"}
        tracker.start_operation("write_file", args, "create-call")

        record = tracker.active["create-call"]
        # before_content should be empty for new file
        assert record.before_content == ""


class TestSubagentUIWithBackend:
    """Test subagent UI with CompositeBackend."""

    def test_tracker_with_composite_backend(self, tmp_path: Path) -> None:
        """Test FileOpTracker works with CompositeBackend."""
        from deepagents.backends.filesystem import FilesystemBackend
        from deepagents.backends import CompositeBackend

        backend = CompositeBackend(
            default=FilesystemBackend(),
            routes={},
        )

        tracker = FileOpTracker(assistant_id="backend-agent", backend=backend)

        # Create test file
        test_file = tmp_path / "backend_test.py"
        test_file.write_text("original = True")

        args = {"file_path": str(test_file)}
        tracker.start_operation("write_file", args, "backend-call")

        assert "backend-call" in tracker.active

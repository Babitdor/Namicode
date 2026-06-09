"""Tests for novacode_cli.plans — plan persistence as markdown."""

import pytest

from novacode_cli.plans import todos_to_markdown


class TestTodosToMarkdown:
    """Tests for todos_to_markdown()."""

    def test_empty_list_returns_header_only(self):
        result = todos_to_markdown([])
        assert result.startswith("# Plan")
        assert "## Tasks" in result
        # No task list items
        assert "- [" not in result

    def test_pending_todo_renders_unchecked(self):
        result = todos_to_markdown([{"content": "Do something", "status": "pending"}])
        assert "- [ ] Do something" in result

    def test_completed_todo_renders_checked(self):
        result = todos_to_markdown([{"content": "Done task", "status": "completed"}])
        assert "- [x] Done task" in result

    def test_in_progress_todo_renders_dash(self):
        result = todos_to_markdown([{"content": "In progress", "status": "in_progress"}])
        assert "- [-] In progress" in result

    def test_unknown_status_renders_unchecked(self):
        result = todos_to_markdown([{"content": "Weird status", "status": "unknown"}])
        assert "- [ ] Weird status" in result

    def test_depends_on_appears_as_suffix(self):
        result = todos_to_markdown([
            {"content": "Task A", "status": "pending", "depends_on": ["Task B"]}
        ])
        assert "depends on: Task B" in result

    def test_multiple_dependencies(self):
        result = todos_to_markdown([
            {"content": "Task", "status": "pending", "depends_on": ["A", "B"]}
        ])
        assert "depends on: A, B" in result

    def test_subtask_is_indented(self):
        result = todos_to_markdown([
            {
                "content": "Parent",
                "status": "pending",
                "subtasks": [
                    {"content": "Child", "status": "completed"}
                ]
            }
        ])
        assert "- [ ] Parent" in result
        assert "  - [x] Child" in result

    def test_nested_subtasks(self):
        result = todos_to_markdown([
            {
                "content": "Level 1",
                "status": "pending",
                "subtasks": [
                    {
                        "content": "Level 2",
                        "status": "in_progress",
                        "subtasks": [
                            {"content": "Level 3", "status": "pending"}
                        ]
                    }
                ]
            }
        ])
        assert "- [ ] Level 1" in result
        assert "  - [-] Level 2" in result
        assert "    - [ ] Level 3" in result

    def test_multiple_todos_all_rendered(self):
        result = todos_to_markdown([
            {"content": "First", "status": "pending"},
            {"content": "Second", "status": "completed"},
        ])
        assert "- [ ] First" in result
        assert "- [x] Second" in result

    def test_todo_without_status_field_defaults_to_pending(self):
        result = todos_to_markdown([{"content": "No status"}])
        assert "- [ ] No status" in result

    def test_no_depends_on_does_not_add_suffix(self):
        result = todos_to_markdown([{"content": "Alone", "status": "pending"}])
        assert "depends on" not in result
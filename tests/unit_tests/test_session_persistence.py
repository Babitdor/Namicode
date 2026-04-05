"""Tests for session persistence module."""

import tempfile
from datetime import UTC
from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from novacode_cli.session.session_persistence import (
    SessionManager,
    SessionMeta,
)
from novacode_cli.session.session_restore import (
    build_session_summary_message,
    format_session_age,
    format_session_summary,
    restore_session,
    validate_session_compatibility,
)


class TestSessionMeta:
    """Test SessionMeta dataclass."""

    def test_create_session_meta(self) -> None:
        """Test creating a SessionMeta instance."""
        meta = SessionMeta(
            session_id="test-session-id",
            thread_id="test-thread-id",
            created_at="2025-01-01T00:00:00+00:00",
            last_active="2025-01-01T01:00:00+00:00",
            project_root="/path/to/project",
            repo_hash="abc123",
            Nova_md_checksum="def456",
            model_name="gpt-4",
            assistant_id="test-agent",
            message_count=10,
        )
        assert meta.session_id == "test-session-id"
        assert meta.message_count == 10

    def test_to_dict(self) -> None:
        """Test converting SessionMeta to dict."""
        meta = SessionMeta(
            session_id="test-id",
            thread_id="thread-id",
            created_at="2025-01-01T00:00:00+00:00",
            last_active="2025-01-01T01:00:00+00:00",
            project_root=None,
            repo_hash=None,
            Nova_md_checksum=None,
            model_name=None,
            assistant_id="agent",
        )
        d = meta.to_dict()
        assert d["session_id"] == "test-id"
        assert d["thread_id"] == "thread-id"
        assert d["assistant_id"] == "agent"

    def test_from_dict(self) -> None:
        """Test creating SessionMeta from dict."""
        data = {
            "session_id": "test-id",
            "thread_id": "thread-id",
            "created_at": "2025-01-01T00:00:00+00:00",
            "last_active": "2025-01-01T01:00:00+00:00",
            "project_root": "/path",
            "repo_hash": "abc",
            "Nova_md_checksum": "def",
            "model_name": "claude-3",
            "assistant_id": "agent",
            "message_count": 5,
        }
        meta = SessionMeta.from_dict(data)
        assert meta.session_id == "test-id"
        assert meta.message_count == 5


class TestSessionManager:
    """Test SessionManager class."""

    def test_init_creates_directory(self) -> None:
        """Test that initialization creates sessions directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sessions_dir = Path(tmpdir) / "sessions"
            manager = SessionManager(sessions_dir=sessions_dir)
            assert sessions_dir.exists()

    def test_save_and_load_session(self) -> None:
        """Test saving and loading a session."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sessions_dir = Path(tmpdir) / "sessions"
            manager = SessionManager(sessions_dir=sessions_dir)

            # Create test messages
            messages = [
                HumanMessage(content="Hello"),
                AIMessage(content="Hi there!"),
            ]

            # Save session
            session_path = manager.save_session(
                session_id="test-session",
                thread_id="test-thread",
                messages=messages,
                assistant_id="test-agent",
                model_name="gpt-4",
            )
            assert session_path.exists()
            assert (session_path / "meta.json").exists()
            assert (session_path / "conversation.jsonl").exists()

            # Load session
            session_data = manager.load_session("test-session")
            assert session_data is not None
            assert session_data.meta.session_id == "test-session"
            assert session_data.meta.thread_id == "test-thread"
            assert len(session_data.messages) == 2

    def test_save_session_with_todos(self) -> None:
        """Test saving session with todos."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sessions_dir = Path(tmpdir) / "sessions"
            manager = SessionManager(sessions_dir=sessions_dir)

            todos = [
                {"content": "Task 1", "status": "completed"},
                {"content": "Task 2", "status": "pending"},
            ]

            manager.save_session(
                session_id="test-session",
                thread_id="test-thread",
                messages=[HumanMessage(content="Hello")],
                assistant_id="test-agent",
                todos=todos,
            )

            session_data = manager.load_session("test-session")
            assert session_data is not None
            assert session_data.todos == todos

    def test_list_sessions(self) -> None:
        """Test listing sessions."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sessions_dir = Path(tmpdir) / "sessions"
            manager = SessionManager(sessions_dir=sessions_dir)

            # Create multiple sessions
            for i in range(3):
                manager.save_session(
                    session_id=f"session-{i}",
                    thread_id=f"thread-{i}",
                    messages=[HumanMessage(content=f"Message {i}")],
                    assistant_id="test-agent",
                )

            sessions = manager.list_sessions()
            assert len(sessions) == 3

    def test_list_sessions_with_limit(self) -> None:
        """Test listing sessions with limit."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sessions_dir = Path(tmpdir) / "sessions"
            manager = SessionManager(sessions_dir=sessions_dir)

            # Create 5 sessions
            for i in range(5):
                manager.save_session(
                    session_id=f"session-{i}",
                    thread_id=f"thread-{i}",
                    messages=[HumanMessage(content=f"Message {i}")],
                    assistant_id="test-agent",
                )

            sessions = manager.list_sessions(limit=3)
            assert len(sessions) == 3

    def test_get_latest_session(self) -> None:
        """Test getting the latest session."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sessions_dir = Path(tmpdir) / "sessions"
            manager = SessionManager(sessions_dir=sessions_dir)

            # Create sessions
            manager.save_session(
                session_id="old-session",
                thread_id="thread-1",
                messages=[HumanMessage(content="Old")],
                assistant_id="test-agent",
            )
            manager.save_session(
                session_id="new-session",
                thread_id="thread-2",
                messages=[HumanMessage(content="New")],
                assistant_id="test-agent",
            )

            latest = manager.get_latest_session()
            assert latest is not None
            assert latest.session_id == "new-session"

    def test_delete_session(self) -> None:
        """Test deleting a session."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sessions_dir = Path(tmpdir) / "sessions"
            manager = SessionManager(sessions_dir=sessions_dir)

            manager.save_session(
                session_id="test-session",
                thread_id="test-thread",
                messages=[HumanMessage(content="Hello")],
                assistant_id="test-agent",
            )

            assert manager.delete_session("test-session") is True
            assert manager.load_session("test-session") is None

    def test_delete_nonexistent_session(self) -> None:
        """Test deleting a nonexistent session returns False."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sessions_dir = Path(tmpdir) / "sessions"
            manager = SessionManager(sessions_dir=sessions_dir)
            assert manager.delete_session("nonexistent") is False

    def test_load_nonexistent_session(self) -> None:
        """Test loading a nonexistent session returns None."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sessions_dir = Path(tmpdir) / "sessions"
            manager = SessionManager(sessions_dir=sessions_dir)
            assert manager.load_session("nonexistent") is None


class TestMessageSerialization:
    """Test message serialization/deserialization."""

    def test_serialize_human_message(self) -> None:
        """Test serializing HumanMessage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sessions_dir = Path(tmpdir) / "sessions"
            manager = SessionManager(sessions_dir=sessions_dir)

            msg = HumanMessage(content="Hello world")
            serialized = manager._serialize_message(msg)

            assert serialized["type"] == "HumanMessage"
            assert serialized["content"] == "Hello world"

    def test_serialize_ai_message_with_tool_calls(self) -> None:
        """Test serializing AIMessage with tool calls."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sessions_dir = Path(tmpdir) / "sessions"
            manager = SessionManager(sessions_dir=sessions_dir)

            msg = AIMessage(
                content="Let me help",
                tool_calls=[{"name": "read_file", "args": {"path": "test.py"}, "id": "call_1"}],
            )
            serialized = manager._serialize_message(msg)

            assert serialized["type"] == "AIMessage"
            assert len(serialized["tool_calls"]) == 1
            assert serialized["tool_calls"][0]["name"] == "read_file"

    def test_serialize_tool_message(self) -> None:
        """Test serializing ToolMessage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sessions_dir = Path(tmpdir) / "sessions"
            manager = SessionManager(sessions_dir=sessions_dir)

            msg = ToolMessage(content="File contents", tool_call_id="call_1", name="read_file")
            serialized = manager._serialize_message(msg)

            assert serialized["type"] == "ToolMessage"
            assert serialized["tool_call_id"] == "call_1"
            assert serialized["name"] == "read_file"

    def test_deserialize_human_message(self) -> None:
        """Test deserializing to HumanMessage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sessions_dir = Path(tmpdir) / "sessions"
            manager = SessionManager(sessions_dir=sessions_dir)

            data = {"type": "HumanMessage", "content": "Hello"}
            msg = manager._deserialize_message(data)

            assert isinstance(msg, HumanMessage)
            assert msg.content == "Hello"

    def test_deserialize_unknown_type_returns_none(self) -> None:
        """Test deserializing unknown type returns None."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sessions_dir = Path(tmpdir) / "sessions"
            manager = SessionManager(sessions_dir=sessions_dir)

            data = {"type": "UnknownMessage", "content": "Hello"}
            msg = manager._deserialize_message(data)

            assert msg is None


class TestSessionRestore:
    """Test session restoration functions."""

    def test_format_session_age_just_now(self) -> None:
        """Test formatting age for recent timestamp."""
        from datetime import datetime

        now = datetime.now(UTC).isoformat()
        result = format_session_age(now)
        assert result == "just now"

    def test_format_session_age_invalid(self) -> None:
        """Test formatting age for invalid timestamp."""
        result = format_session_age("invalid-timestamp")
        assert result == "unknown"

    def test_format_session_summary(self) -> None:
        """Test formatting session summary."""
        meta = SessionMeta(
            session_id="abc12345-1234-1234-1234-123456789012",
            thread_id="thread-id",
            created_at="2025-01-01T00:00:00+00:00",
            last_active="2025-01-01T00:00:00+00:00",
            project_root="/path/to/project",
            repo_hash=None,
            Nova_md_checksum=None,
            model_name="gpt-4",
            assistant_id="agent",
            message_count=5,
        )
        summary = format_session_summary(meta)
        assert "abc12345" in summary
        assert "project" in summary
        assert "gpt-4" in summary
        assert "5 messages" in summary

    def test_build_session_summary_message_empty(self) -> None:
        """Test building summary for empty messages."""
        result = build_session_summary_message([])
        assert result == "No previous conversation."

    def test_build_session_summary_message_with_messages(self) -> None:
        """Test building summary with messages."""
        messages = [
            HumanMessage(content="Hello"),
            AIMessage(content="Hi there!"),
        ]
        result = build_session_summary_message(messages)
        assert "2 messages" in result
        assert "1 user" in result
        assert "1 assistant" in result


class TestValidateSessionCompatibility:
    """Test session compatibility validation."""

    def test_validate_compatible_session(self) -> None:
        """Test validating a compatible session."""
        meta = SessionMeta(
            session_id="test",
            thread_id="thread",
            created_at="2025-01-01T00:00:00+00:00",
            last_active="2025-01-01T00:00:00+00:00",
            project_root=None,
            repo_hash=None,
            Nova_md_checksum=None,
            model_name="gpt-4",
            assistant_id="agent",
        )
        is_valid, warnings = validate_session_compatibility(meta)
        assert is_valid is True
        assert len(warnings) == 0

    def test_validate_different_project_warning(self) -> None:
        """Test warning for different project root."""
        with tempfile.TemporaryDirectory() as tmpdir:
            current_root = Path(tmpdir)
            meta = SessionMeta(
                session_id="test",
                thread_id="thread",
                created_at="2025-01-01T00:00:00+00:00",
                last_active="2025-01-01T00:00:00+00:00",
                project_root="/different/path",
                repo_hash=None,
                Nova_md_checksum=None,
                model_name="gpt-4",
                assistant_id="agent",
            )
            is_valid, warnings = validate_session_compatibility(meta, current_root)
            assert is_valid is True  # Still valid, just warning
            assert len(warnings) > 0
            assert "different project" in warnings[0]


class TestRestoreSession:
    """Test restore_session function."""

    def test_restore_nonexistent_session(self) -> None:
        """Test restoring a nonexistent session returns None."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sessions_dir = Path(tmpdir) / "sessions"
            manager = SessionManager(sessions_dir=sessions_dir)

            result = restore_session(manager, "nonexistent")
            assert result is None

    def test_restore_latest_session(self) -> None:
        """Test restoring the latest session."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sessions_dir = Path(tmpdir) / "sessions"
            project_root = Path(tmpdir) / "project"
            project_root.mkdir()
            manager = SessionManager(sessions_dir=sessions_dir)

            # Create a session with project_root
            manager.save_session(
                session_id="test-session",
                thread_id="test-thread",
                messages=[HumanMessage(content="Hello")],
                assistant_id="test-agent",
                project_root=project_root,
            )

            result = restore_session(manager, project_root=project_root)
            assert result is not None
            session_data, warnings = result
            assert session_data.meta.session_id == "test-session"

    def test_restore_specific_session(self) -> None:
        """Test restoring a specific session by ID."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sessions_dir = Path(tmpdir) / "sessions"
            manager = SessionManager(sessions_dir=sessions_dir)

            # Create multiple sessions
            manager.save_session(
                session_id="session-1",
                thread_id="thread-1",
                messages=[HumanMessage(content="First")],
                assistant_id="test-agent",
            )
            manager.save_session(
                session_id="session-2",
                thread_id="thread-2",
                messages=[HumanMessage(content="Second")],
                assistant_id="test-agent",
            )

            result = restore_session(manager, "session-1")
            assert result is not None
            session_data, warnings = result
            assert session_data.meta.session_id == "session-1"

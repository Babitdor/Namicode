"""Session persistence for namicode-cli.

This module provides functionality to save and restore CLI sessions,
including conversation history, todos, and tool state.
"""

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)


@dataclass
class SessionMeta:
    """Metadata for a saved session.

    Attributes:
        session_id: Unique identifier for the session
        thread_id: LangGraph thread ID for checkpointer
        created_at: ISO timestamp when session was created
        last_active: ISO timestamp of last activity
        project_root: Path to project root (if in a git project)
        repo_hash: Hash of git HEAD for compatibility checking
        nami_md_checksum: Checksum of NAMI.md for change detection
        model_name: Name of the model used
        assistant_id: Agent identifier
        message_count: Number of messages in conversation
        current_task: Current task description
        task_status: Task status - 'active', 'blocked', or 'complete'
        blocked_reason: Reason for blockage if task_status is 'blocked'
        next_step_hint: Optional hint for what to do next
    """

    session_id: str
    thread_id: str
    created_at: str
    last_active: str
    project_root: str | None
    repo_hash: str | None
    nami_md_checksum: str | None
    model_name: str | None
    assistant_id: str
    message_count: int = 0
    current_task: str | None = None
    task_status: str = "active"  # active | blocked | complete
    blocked_reason: str | None = None
    next_step_hint: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SessionMeta":
        """Create from dictionary with backward compatibility."""
        # Provide defaults for new fields to support old sessions
        defaults = {
            "current_task": None,
            "task_status": "active",
            "blocked_reason": None,
            "next_step_hint": None,
        }
        # Merge defaults with provided data (data takes precedence)
        merged = {**defaults, **data}
        return cls(**merged)


@dataclass
class SessionData:
    """Complete session data for save/restore.

    Attributes:
        meta: Session metadata
        messages: Conversation messages
        todos: Todo list state
        tool_state: Last tool outputs and env info
        memory: Declarative memory.md content
        workspace_state: Last known workspace state (git + filesystem)
    """

    meta: SessionMeta
    messages: list[BaseMessage] = field(default_factory=list)
    todos: list[dict] | None = None
    tool_state: dict | None = None
    memory: str | None = None
    workspace_state: dict | None = None


class SessionManager:
    """Manages session persistence for the CLI.

    Sessions are stored in ~/.nami/sessions/<session_id>/ with:
    - meta.json: Session metadata
    - conversation.jsonl: Ordered messages
    - todos.json: Task list state
    - tool_state.json: Last tool outputs
    """

    def __init__(self, sessions_dir: Path | None = None) -> None:
        """Initialize session manager.

        Args:
            sessions_dir: Directory to store sessions. Defaults to ~/.nami/sessions/
        """
        self.sessions_dir = sessions_dir or Path.home() / ".nami" / "sessions"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

    def save_session(
        self,
        session_id: str,
        thread_id: str,
        messages: list[BaseMessage],
        assistant_id: str,
        *,
        todos: list[dict] | None = None,
        tool_state: dict | None = None,
        model_name: str | None = None,
        project_root: Path | None = None,
        current_task: str | None = None,
        task_status: str = "active",
        blocked_reason: str | None = None,
        next_step_hint: str | None = None,
        memory: str | None = None,
        workspace_state: dict | None = None,
    ) -> Path:
        """Save a session to disk.

        Args:
            session_id: Unique session identifier
            thread_id: LangGraph thread ID
            messages: Conversation messages to save
            assistant_id: Agent identifier
            todos: Optional todo list state
            tool_state: Optional tool state
            model_name: Name of the model being used
            project_root: Path to project root (for repo hash)

        Returns:
            Path to the session directory
        """
        session_dir = self.sessions_dir / session_id
        session_dir.mkdir(parents=True, exist_ok=True)

        now = datetime.now(timezone.utc).isoformat()

        # Load existing meta to preserve created_at
        meta_path = session_dir / "meta.json"
        if meta_path.exists():
            with open(meta_path) as f:
                existing_meta = json.load(f)
            created_at = existing_meta.get("created_at", now)
        else:
            created_at = now

        # Compute hashes
        repo_hash = self._compute_repo_hash(project_root) if project_root else None
        nami_md_checksum = (
            self._compute_nami_md_checksum(project_root) if project_root else None
        )

        # Create metadata
        meta = SessionMeta(
            session_id=session_id,
            thread_id=thread_id,
            created_at=created_at,
            last_active=now,
            project_root=str(project_root) if project_root else None,
            repo_hash=repo_hash,
            nami_md_checksum=nami_md_checksum,
            model_name=model_name,
            assistant_id=assistant_id,
            message_count=len(messages),
            current_task=current_task,
            task_status=task_status,
            blocked_reason=blocked_reason,
            next_step_hint=next_step_hint,
        )

        # Save metadata
        with open(meta_path, "w") as f:
            json.dump(meta.to_dict(), f, indent=2)

        # Split messages into recent and archive
        recent_messages, archive_messages = self._split_messages(
            messages, recent_limit=8
        )

        # Save recent messages (for context)
        recent_path = session_dir / "recent.jsonl"
        with open(recent_path, "w", encoding="utf-8") as f:
            for msg in recent_messages:
                f.write(json.dumps(self._serialize_message(msg)) + "\n")

        # Save archive messages (full history, not injected into context)
        archive_path = session_dir / "archive.jsonl"
        with open(archive_path, "w", encoding="utf-8") as f:
            for msg in archive_messages:
                f.write(json.dumps(self._serialize_message(msg)) + "\n")

        # Also save full conversation for backward compatibility (deprecated)
        conversation_path = session_dir / "conversation.jsonl"
        with open(conversation_path, "w", encoding="utf-8") as f:
            for msg in messages:
                f.write(json.dumps(self._serialize_message(msg)) + "\n")

        # Save todos if provided
        if todos is not None:
            todos_path = session_dir / "todos.json"
            with open(todos_path, "w") as f:
                json.dump(todos, f, indent=2)

        # Save tool state if provided
        if tool_state is not None:
            tool_state_path = session_dir / "tool_state.json"
            with open(tool_state_path, "w") as f:
                json.dump(tool_state, f, indent=2)

        # Save memory.md if provided
        if memory is not None:
            memory_path = session_dir / "memory.md"
            with open(memory_path, "w", encoding="utf-8") as f:
                f.write(memory)

        # Save workspace state if provided
        if workspace_state is not None:
            workspace_path = session_dir / "workspace_state.json"
            with open(workspace_path, "w") as f:
                json.dump(workspace_state, f, indent=2)

        return session_dir

    def load_session(self, session_id: str) -> SessionData | None:
        """Load a session from disk.

        Args:
            session_id: Session identifier to load

        Returns:
            SessionData if found, None otherwise
        """
        session_dir = self.sessions_dir / session_id
        if not session_dir.exists():
            return None

        # Load metadata
        meta_path = session_dir / "meta.json"
        if not meta_path.exists():
            return None

        try:
            with open(meta_path) as f:
                meta = SessionMeta.from_dict(json.load(f))
        except (json.JSONDecodeError, TypeError, KeyError):
            return None

        # Load messages - prioritize recent.jsonl + archive.jsonl
        # Fall back to conversation.jsonl for backward compatibility
        messages: list[BaseMessage] = []
        recent_path = session_dir / "recent.jsonl"
        archive_path = session_dir / "archive.jsonl"
        conversation_path = session_dir / "conversation.jsonl"

        if recent_path.exists() or archive_path.exists():
            # New format: load from archive + recent
            # Load archive first (older messages)
            if archive_path.exists():
                try:
                    with open(archive_path, encoding="utf-8") as f:
                        for line in f:
                            if line.strip():
                                msg = self._deserialize_message(json.loads(line))
                                if msg:
                                    messages.append(msg)
                except (json.JSONDecodeError, TypeError):
                    pass

            # Then load recent messages (newer messages)
            if recent_path.exists():
                try:
                    with open(recent_path, encoding="utf-8") as f:
                        for line in f:
                            if line.strip():
                                msg = self._deserialize_message(json.loads(line))
                                if msg:
                                    messages.append(msg)
                except (json.JSONDecodeError, TypeError):
                    pass
        elif conversation_path.exists():
            # Old format: load from single conversation file
            try:
                with open(conversation_path, encoding="utf-8") as f:
                    for line in f:
                        if line.strip():
                            msg = self._deserialize_message(json.loads(line))
                            if msg:
                                messages.append(msg)
            except (json.JSONDecodeError, TypeError):
                pass

        # Load todos
        todos: list[dict] | None = None
        todos_path = session_dir / "todos.json"
        if todos_path.exists():
            try:
                with open(todos_path) as f:
                    todos = json.load(f)
            except json.JSONDecodeError:
                pass

        # Load tool state
        tool_state: dict | None = None
        tool_state_path = session_dir / "tool_state.json"
        if tool_state_path.exists():
            try:
                with open(tool_state_path) as f:
                    tool_state = json.load(f)
            except json.JSONDecodeError:
                pass

        # Load memory.md
        memory: str | None = None
        memory_path = session_dir / "memory.md"
        if memory_path.exists():
            try:
                with open(memory_path, encoding="utf-8") as f:
                    memory = f.read()
            except OSError:
                pass

        # Load workspace state
        workspace_state: dict | None = None
        workspace_path = session_dir / "workspace_state.json"
        if workspace_path.exists():
            try:
                with open(workspace_path) as f:
                    workspace_state = json.load(f)
            except json.JSONDecodeError:
                pass

        return SessionData(
            meta=meta,
            messages=messages,
            todos=todos,
            tool_state=tool_state,
            memory=memory,
            workspace_state=workspace_state,
        )

    def list_sessions(self, limit: int = 10) -> list[SessionMeta]:
        """List available sessions, sorted by last_active (most recent first).

        Args:
            limit: Maximum number of sessions to return

        Returns:
            List of SessionMeta objects
        """
        sessions: list[SessionMeta] = []

        if not self.sessions_dir.exists():
            return sessions

        for session_dir in self.sessions_dir.iterdir():
            if not session_dir.is_dir():
                continue

            meta_path = session_dir / "meta.json"
            if not meta_path.exists():
                continue

            try:
                with open(meta_path) as f:
                    meta = SessionMeta.from_dict(json.load(f))
                    sessions.append(meta)
            except (json.JSONDecodeError, TypeError, KeyError):
                continue

        # Sort by last_active descending
        sessions.sort(key=lambda s: s.last_active, reverse=True)

        return sessions[:limit]

    def get_latest_session(
        self, project_root: Path | None = None
    ) -> SessionMeta | None:
        """Get the most recent session, optionally filtered by project.

        Args:
            project_root: If provided, only return sessions from this project

        Returns:
            Most recent SessionMeta or None
        """
        sessions = self.list_sessions(limit=100)

        if project_root:
            project_str = str(project_root)
            sessions = [s for s in sessions if s.project_root == project_str]

        return sessions[0] if sessions else None

    def load_recent_messages(self, session_id: str) -> list[BaseMessage]:
        """Load only recent messages from a session (for prompt construction).

        Args:
            session_id: Session identifier

        Returns:
            List of recent messages (empty list if not found)
        """
        session_dir = self.sessions_dir / session_id
        recent_path = session_dir / "recent.jsonl"

        if not recent_path.exists():
            # Fallback to loading from conversation.jsonl and taking last N
            conversation_path = session_dir / "conversation.jsonl"
            if conversation_path.exists():
                all_messages = []
                try:
                    with open(conversation_path, encoding="utf-8") as f:
                        for line in f:
                            if line.strip():
                                msg = self._deserialize_message(json.loads(line))
                                if msg:
                                    all_messages.append(msg)
                except (json.JSONDecodeError, TypeError):
                    return []
                # Return last 8 messages
                return all_messages[-8:] if len(all_messages) > 8 else all_messages
            return []

        # Load from recent.jsonl
        recent_messages: list[BaseMessage] = []
        try:
            with open(recent_path, encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        msg = self._deserialize_message(json.loads(line))
                        if msg:
                            recent_messages.append(msg)
        except (json.JSONDecodeError, TypeError):
            return []

        return recent_messages

    def delete_session(self, session_id: str) -> bool:
        """Delete a session from disk.

        Args:
            session_id: Session identifier to delete

        Returns:
            True if deleted, False if not found
        """
        session_dir = self.sessions_dir / session_id
        if not session_dir.exists():
            return False

        import shutil

        shutil.rmtree(session_dir)
        return True

    def _serialize_message(self, msg: BaseMessage) -> dict[str, Any]:
        """Serialize a LangChain message to JSON-serializable dict.

        Args:
            msg: Message to serialize

        Returns:
            Dictionary representation
        """
        data: dict[str, Any] = {
            "type": msg.__class__.__name__,
            "content": msg.content,
        }

        # Handle additional_kwargs (tool calls, etc.)
        if hasattr(msg, "additional_kwargs") and msg.additional_kwargs:
            # Filter out non-serializable items
            serializable_kwargs = {}
            for k, v in msg.additional_kwargs.items():
                try:
                    json.dumps(v)
                    serializable_kwargs[k] = v
                except (TypeError, ValueError):
                    pass
            if serializable_kwargs:
                data["additional_kwargs"] = serializable_kwargs

        # Handle tool calls for AIMessage
        if isinstance(msg, AIMessage) and hasattr(msg, "tool_calls") and msg.tool_calls:
            data["tool_calls"] = [
                {
                    "name": tc.get("name", ""),
                    "args": tc.get("args", {}),
                    "id": tc.get("id", ""),
                }
                for tc in msg.tool_calls
            ]

        # Handle ToolMessage specifics
        if isinstance(msg, ToolMessage):
            data["tool_call_id"] = msg.tool_call_id
            if hasattr(msg, "name"):
                data["name"] = msg.name

        # Handle response_metadata if present
        if hasattr(msg, "response_metadata") and msg.response_metadata:
            # Only serialize safe metadata
            safe_metadata = {}
            for k, v in msg.response_metadata.items():
                try:
                    json.dumps(v)
                    safe_metadata[k] = v
                except (TypeError, ValueError):
                    pass
            if safe_metadata:
                data["response_metadata"] = safe_metadata

        return data

    def _deserialize_message(self, data: dict[str, Any]) -> BaseMessage | None:
        """Deserialize JSON dict back to LangChain message.

        Args:
            data: Dictionary to deserialize

        Returns:
            LangChain message or None if invalid
        """
        msg_type = data.get("type")
        content = data.get("content", "")
        additional_kwargs = data.get("additional_kwargs", {})

        if msg_type == "HumanMessage":
            return HumanMessage(content=content, additional_kwargs=additional_kwargs)

        if msg_type == "AIMessage":
            tool_calls = data.get("tool_calls", [])
            response_metadata = data.get("response_metadata", {})
            return AIMessage(
                content=content,
                additional_kwargs=additional_kwargs,
                tool_calls=tool_calls,
                response_metadata=response_metadata,
            )

        if msg_type == "SystemMessage":
            return SystemMessage(content=content, additional_kwargs=additional_kwargs)

        if msg_type == "ToolMessage":
            tool_call_id = data.get("tool_call_id", "")
            name = data.get("name")
            return ToolMessage(
                content=content,
                tool_call_id=tool_call_id,
                name=name,
                additional_kwargs=additional_kwargs,
            )

        # Unknown message type - skip
        return None

    def _split_messages(
        self,
        messages: list[BaseMessage],
        recent_limit: int = 8,
    ) -> tuple[list[BaseMessage], list[BaseMessage]]:
        """Split messages into recent (for context) and archive (for storage).

        Args:
            messages: All messages to split
            recent_limit: Number of recent messages to keep (default 8)

        Returns:
            Tuple of (recent_messages, archive_messages)
        """
        if len(messages) <= recent_limit:
            return messages, []

        # Keep last N messages as recent
        return messages[-recent_limit:], messages[:-recent_limit]

    def _compute_repo_hash(self, project_root: Path) -> str | None:
        """Compute hash of git HEAD for compatibility checking.

        Args:
            project_root: Path to the git repository root

        Returns:
            Short hash of HEAD or None if not a git repo
        """
        git_head = project_root / ".git" / "HEAD"
        if not git_head.exists():
            return None

        try:
            head_content = git_head.read_text().strip()

            # If HEAD is a ref, read the actual commit
            if head_content.startswith("ref:"):
                ref_path = project_root / ".git" / head_content[5:].strip()
                if ref_path.exists():
                    head_content = ref_path.read_text().strip()

            return hashlib.sha256(head_content.encode()).hexdigest()[:12]
        except OSError:
            return None

    def _compute_nami_md_checksum(self, project_root: Path) -> str | None:
        """Compute checksum of NAMI.md for change detection.

        Args:
            project_root: Path to the project root

        Returns:
            MD5 checksum of NAMI.md or None if not found
        """
        # Check both NAMI.md and .nami/agent.md
        nami_md_paths = [
            project_root / "NAMI.md",
            project_root / ".nami" / "NAMI.md",
        ]

        for path in nami_md_paths:
            if path.exists():
                try:
                    content = path.read_bytes()
                    return hashlib.md5(content).hexdigest()[:12]
                except OSError:
                    continue

        return None

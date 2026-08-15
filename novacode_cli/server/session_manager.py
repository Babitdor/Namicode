"""In-memory session lifecycle manager.

Each session holds:
- A unique session ID
- Creation timestamp
- The agent instance and its config
- A cancellation event (for cancelling in-progress runs)

Sessions are stored in a plain dict. This is suitable for single-process
deployment. For multi-process or persistent storage, replace this module
with a database-backed implementation.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any


class SessionInfo:
    """Holds the state for one agent session."""

    def __init__(
        self,
        session_id: str,
        agent: Any,
        config: dict[str, Any],
    ) -> None:
        self.session_id = session_id
        self.created_at = time.time()
        self.agent = agent
        self.config = config
        # Set when a run is in progress; cleared when done or cancelled
        self._cancel_event: asyncio.Event | None = None

    @property
    def cancel_event(self) -> asyncio.Event | None:
        return self._cancel_event

    def set_cancel_event(self, event: asyncio.Event) -> None:
        self._cancel_event = event

    def clear_cancel_event(self) -> None:
        self._cancel_event = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "created_at": self.created_at,
            "age_seconds": int(time.time() - self.created_at),
        }


class SessionManager:
    """Manages agent session lifecycle with in-memory storage."""

    def __init__(self) -> None:
        self._sessions: dict[str, SessionInfo] = {}

    def create_session(self, agent: Any, config: dict[str, Any]) -> SessionInfo:
        """Create a new session and return it."""
        session_id = uuid.uuid4().hex[:12]
        info = SessionInfo(session_id=session_id, agent=agent, config=config)
        self._sessions[session_id] = info
        return info

    def get_session(self, session_id: str) -> SessionInfo | None:
        """Look up a session by ID."""
        return self._sessions.get(session_id)

    def delete_session(self, session_id: str) -> bool:
        """Remove a session. Returns True if it existed."""
        info = self._sessions.pop(session_id, None)
        if info is not None:
            # Cancel any in-progress run
            cancel = info.cancel_event
            if cancel is not None and not cancel.is_set():
                cancel.set()
            return True
        return False

    def list_sessions(self) -> list[dict[str, Any]]:
        """Return a summary of all active sessions."""
        return [s.to_dict() for s in self._sessions.values()]

    @property
    def active_count(self) -> int:
        return len(self._sessions)

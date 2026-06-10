"""In-terminal notification state slice.

Owns the notification deque and provides CRUD methods. Hook dispatch
(when a notification should fire a webhook or log event) is the
responsibility of SessionState, not this slice.
"""

from __future__ import annotations

import uuid
from collections import deque
from typing import Any


class NotificationState:
    """Bounded queue of in-terminal notifications.

    All CRUD operations are safe to call from any thread — the deque
    append/pop operations are atomic at the C level.
    """

    def __init__(self) -> None:
        from novacode_cli.states.Session import Notification

        self.notifications: deque[Notification] = deque(maxlen=100)

    # -- CRUD ------------------------------------------------------------------

    def add(
        self,
        level: str,
        title: str,
        message: str,
        source: str,
        *,
        action_id: str | None = None,
        action_type: str | None = None,
    ) -> str:
        """Create and store a notification. Returns id. Does NOT fire hooks.

        When *action_id* is set the notification represents a *pending approval*
        — the agent is blocked waiting for the user to approve/reject via the
        corresponding key in ``SessionState._pending_approvals``.
        """
        from novacode_cli.states.Session import Notification

        n = Notification(
            id=uuid.uuid4().hex[:8],
            level=level,
            title=title,
            message=message,
            source=source,
            action_id=action_id,
            action_type=action_type,
        )
        self.notifications.appendleft(n)
        return n.id

    def dismiss(self, notification_id: str) -> bool:
        """Mark a notification as dismissed. Returns True if found."""
        for n in self.notifications:
            if n.id == notification_id:
                n.dismissed = True
                return True
        return False

    def clear(self) -> int:
        """Drop all notifications. Returns how many were removed."""
        count = len(self.notifications)
        self.notifications.clear()
        return count

    def unread_count(self) -> int:
        """Number of non-dismissed notifications."""
        return sum(1 for n in self.notifications if not n.dismissed)
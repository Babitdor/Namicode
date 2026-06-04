"""Multi-domain session state for the Nova CLI.

SessionState is a composite container backed by 5 focused state slices.
Callers continue to access SessionState fields directly — no changes needed.
"""

from novacode_cli.states.Session import (
    BackgroundRalphTask,
    Notification,
    RalphTaskStatus,
    SessionState,
)
from novacode_cli.states.slices import (
    AgentRuntimeState,
    BackgroundTaskState,
    NotificationState,
    RemoteBridgeState,
    UISettings,
)

__all__ = [
    "SessionState",
    "Notification",
    "BackgroundRalphTask",
    "RalphTaskStatus",
    "UISettings",
    "AgentRuntimeState",
    "RemoteBridgeState",
    "BackgroundTaskState",
    "NotificationState",
]
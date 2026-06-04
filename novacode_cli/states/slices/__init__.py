"""Domain-specific state slices extracted from SessionState."""

from novacode_cli.states.slices.ui_settings import UISettings
from novacode_cli.states.slices.agent_runtime import AgentRuntimeState
from novacode_cli.states.slices.remote_bridge import RemoteBridgeState
from novacode_cli.states.slices.background_tasks import BackgroundTaskState
from novacode_cli.states.slices.notifications import NotificationState

__all__ = [
    "UISettings",
    "AgentRuntimeState",
    "RemoteBridgeState",
    "BackgroundTaskState",
    "NotificationState",
]
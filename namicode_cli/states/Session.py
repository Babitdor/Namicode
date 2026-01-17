from pathlib import Path
import uuid


class SessionState:
    """Holds mutable session state (auto-approve mode, etc)."""

    def __init__(self, auto_approve: bool = False, no_splash: bool = False) -> None:
        self.auto_approve = auto_approve
        self.no_splash = no_splash
        self.exit_hint_until: float | None = None
        self.exit_hint_handle = None
        self.thread_id = str(uuid.uuid4())
        # Session persistence fields
        self.session_id: str | None = None
        self.is_continued: bool = False
        self.todos: list[dict] | None = None
        # Plan mode fields
        self.plan_mode_enabled: bool = False
        self.pending_plan_exit: bool = False  # Flag for deferred plan exit with approval
        self.pending_plan_mode_sync: bool = False  # Flag to sync plan mode to agent state

    def toggle_auto_approve(self) -> bool:
        """Toggle auto-approve and return new state."""
        self.auto_approve = not self.auto_approve
        return self.auto_approve

    def toggle_plan_mode(self) -> bool:
        """Toggle plan mode and return new state."""
        self.plan_mode_enabled = not self.plan_mode_enabled
        return self.plan_mode_enabled



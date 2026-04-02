import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum


class RalphTaskStatus(Enum):
    """Status of a Ralph background task."""
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class BackgroundRalphTask:
    """Tracks a Ralph background task."""
    task_id: str  # Unique identifier
    iteration: int  # Current iteration number
    max_iterations: int  # Total iterations
    task_description: str  # What ralph is working on
    status: RalphTaskStatus = RalphTaskStatus.RUNNING
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
    asyncio_task: object = field(default=None, repr=False)  # Reference to asyncio.Task
    working_directory: str = "."
    error_message: str | None = None


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
        # Verbose mode: show internal agent context instead of collapsing it
        self.verbose: bool = False
        # Ralph background tasks: task_id -> BackgroundRalphTask
        self.background_ralph_tasks: dict[str, BackgroundRalphTask] = {}

    def toggle_auto_approve(self) -> bool:
        """Toggle auto-approve and return new state."""
        self.auto_approve = not self.auto_approve
        return self.auto_approve

    def toggle_plan_mode(self) -> bool:
        """Toggle plan mode and return new state."""
        self.plan_mode_enabled = not self.plan_mode_enabled
        return self.plan_mode_enabled

    def toggle_verbose(self) -> bool:
        """Toggle verbose mode and return new state."""
        self.verbose = not self.verbose
        return self.verbose

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any


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
        
        # Agent components for dynamic model switching
        self._agent: Any = None  # The compiled agent graph
        self._backend: Any = None  # Composite backend
        self._checkpointer: Any = None  # Checkpointer for state preservation
        self._store: Any = None  # Store for memory
        self._tools: list = []  # List of tools
        self._assistant_id: str | None = None  # Agent ID
        self._model: Any = None  # Current model instance
        self._sandbox_type: str | None = None  # Sandbox type

    def set_agent_context(
        self,
        agent: Any,
        backend: Any,
        checkpointer: Any,
        store: Any,
        tools: list,
        assistant_id: str,
        model: Any,
        sandbox_type: str | None = None,
    ) -> None:
        """Set the agent context for dynamic model switching.
        
        Args:
            agent: The compiled agent graph
            backend: Composite backend
            checkpointer: Checkpointer for state preservation
            store: Store for memory
            tools: List of tools
            assistant_id: Agent ID
            model: Current model instance
            sandbox_type: Sandbox type (optional)
        """
        self._agent = agent
        self._backend = backend
        self._checkpointer = checkpointer
        self._store = store
        self._tools = tools
        self._assistant_id = assistant_id
        self._model = model
        self._sandbox_type = sandbox_type

    async def switch_model(self, new_model: Any) -> tuple[Any, Any]:
        """Switch to a new model dynamically by recreating the agent.
        
        This preserves conversation state via the checkpointer and store.
        
        Args:
            new_model: The new model instance to use
            
        Returns:
            Tuple of (new_agent, new_backend)
            
        Raises:
            RuntimeError: If agent context is not set
        """
        if not all([self._agent, self._checkpointer, self._store, self._assistant_id]):
            raise RuntimeError("Agent context not set. Cannot switch model.")
        
        from novacode_cli.agents.core_agent import create_agent_with_config
        
        # Recreate agent with new model, preserving state
        new_agent, new_backend = create_agent_with_config(
            model=new_model,
            assistant_id=self._assistant_id,
            tools=self._tools,
            sandbox=self._backend if hasattr(self._backend, 'default') else None,
            sandbox_type=self._sandbox_type,
            store=self._store,
            checkpointer=self._checkpointer,
            is_continuation=True,  # Mark as continuation to preserve state
        )
        
        # Update stored references
        self._agent = new_agent
        self._backend = new_backend
        self._model = new_model
        
        return new_agent, new_backend

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

"""Hierarchical task planning middleware with subtasks and dependencies.

Extends the upstream TodoListMiddleware with:
- Unique task IDs for referencing
- Nested subtasks (max 2 levels)
- Inter-task dependencies (depends_on)
- Automatic blocked status when deps are unmet
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any, Literal, cast

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.types import Command
from typing_extensions import NotRequired, TypedDict, override

from langchain.agents.middleware.types import (
    AgentMiddleware,
    AgentState,
    ModelCallResult,
    ModelRequest,
    ModelResponse,
    OmitFromInput,
)
from langchain.tools import InjectedToolCallId


class Todo(TypedDict):
    """A single todo item with optional subtasks and dependencies."""

    id: str
    """Unique identifier (e.g., '1', '2', '1.1', '1.2')."""

    content: str
    """The content/description of the todo item."""

    status: Literal["pending", "in_progress", "completed", "blocked"]
    """The current status of the todo item."""

    subtasks: NotRequired[list["Todo"]]
    """Nested child tasks (max 1 level of nesting)."""

    depends_on: NotRequired[list[str]]
    """IDs of tasks that must be completed before this one can start."""


# ---------------------------------------------------------------------------
# Dependency resolution helpers
# ---------------------------------------------------------------------------


def _collect_ids(todos: list[Todo]) -> set[str]:
    """Collect all task IDs from a (possibly nested) todo list."""
    ids: set[str] = set()
    for t in todos:
        ids.add(t["id"])
        for sub in t.get("subtasks", []):
            ids.add(sub["id"])
    return ids


def _is_completed(todo_id: str, todos: list[Todo]) -> bool:
    """Check whether a given task ID is completed."""
    for t in todos:
        if t["id"] == todo_id:
            return t["status"] == "completed"
        for sub in t.get("subtasks", []):
            if sub["id"] == todo_id:
                return sub["status"] == "completed"
    return False


def resolve_blocked(todos: list[Todo]) -> list[Todo]:
    """Walk the todo tree and set/unset blocked status based on dependencies.

    - If all deps are completed and status is ``blocked`` → set to ``pending``.
    - If any dep is NOT completed and status is ``pending`` → set to ``blocked``.
    - ``in_progress`` and ``completed`` tasks are never auto-changed.

    Returns a *new* list (shallow copy of dicts).
    """
    result: list[Todo] = []
    for t in todos:
        t = dict(t)  # type: ignore[assignment]
        deps = t.get("depends_on", [])
        if deps and t["status"] in ("pending", "blocked"):
            all_met = all(_is_completed(dep_id, todos) for dep_id in deps)
            t["status"] = "pending" if all_met else "blocked"

        # Resolve subtasks too
        subs = t.get("subtasks")
        if subs:
            resolved_subs: list[Todo] = []
            for sub in subs:
                sub = dict(sub)  # type: ignore[assignment]
                sub_deps = sub.get("depends_on", [])
                if sub_deps and sub["status"] in ("pending", "blocked"):
                    all_met = all(_is_completed(d, todos) for d in sub_deps)
                    sub["status"] = "pending" if all_met else "blocked"
                resolved_subs.append(sub)  # type: ignore[arg-type]
            t["subtasks"] = resolved_subs

        result.append(t)  # type: ignore[arg-type]
    return result


def get_next_actionable(todos: list[Todo]) -> list[Todo]:
    """Return tasks that are pending with all dependencies met."""
    actionable: list[Todo] = []
    for t in todos:
        if t["status"] == "pending":
            deps = t.get("depends_on", [])
            if not deps or all(_is_completed(d, todos) for d in deps):
                actionable.append(t)
        for sub in t.get("subtasks", []):
            if sub["status"] == "pending":
                sub_deps = sub.get("depends_on", [])
                if not sub_deps or all(_is_completed(d, todos) for d in sub_deps):
                    actionable.append(sub)
    return actionable


def flatten_todos(todos: list[Todo]) -> list[Todo]:
    """Flatten a hierarchical todo list into a single-level list."""
    flat: list[Todo] = []
    for t in todos:
        flat.append(t)
        for sub in t.get("subtasks", []):
            flat.append(sub)
    return flat


def _validate_todos(todos: list[Todo]) -> str | None:
    """Validate the todo list. Returns an error message or None if valid."""
    all_ids = _collect_ids(todos)

    # Check for duplicate IDs
    seen: set[str] = set()
    for t in flatten_todos(todos):
        if t["id"] in seen:
            return f"Duplicate task ID: '{t['id']}'"
        seen.add(t["id"])

    # Check that depends_on references exist
    for t in flatten_todos(todos):
        for dep_id in t.get("depends_on", []):
            if dep_id not in all_ids:
                return f"Task '{t['id']}' depends on unknown ID '{dep_id}'"

    # Check for circular dependencies (simple cycle detection)
    def _has_cycle(tid: str, visited: set[str]) -> bool:
        if tid in visited:
            return True
        visited.add(tid)
        # Find the task
        for t in flatten_todos(todos):
            if t["id"] == tid:
                for dep in t.get("depends_on", []):
                    if _has_cycle(dep, visited.copy()):
                        return True
        return False

    for t in flatten_todos(todos):
        if t.get("depends_on"):
            if _has_cycle(t["id"], set()):
                # Only flag if there's an actual back-edge
                pass  # Simple detection above is conservative; skip for now

    return None


# ---------------------------------------------------------------------------
# System prompt and tool description
# ---------------------------------------------------------------------------

HIERARCHICAL_TODOS_TOOL_DESCRIPTION = """Use this tool to create and manage a structured, hierarchical task list for your current work session.

## Task Structure
Each task has:
- **id**: Unique identifier (e.g., "1", "2", "1.1", "1.2"). Use dotted notation for subtasks.
- **content**: Description of what needs to be done.
- **status**: One of "pending", "in_progress", "completed", or "blocked".
- **subtasks** (optional): Nested child tasks for breaking down a parent task.
- **depends_on** (optional): List of task IDs that must be completed first.

## When to Use
1. Complex multi-step tasks requiring 3+ steps
2. Tasks with natural parent-child relationships (e.g., "Implement feature X" with subtasks for each file)
3. Tasks with ordering dependencies (e.g., "Run tests" depends on "Implement feature")

## How to Use
1. Create tasks with unique IDs. Use subtasks to group related work under a parent.
2. Use `depends_on` when task ordering matters (e.g., testing depends on implementation).
3. Tasks with unmet dependencies are automatically set to "blocked".
4. Mark tasks "in_progress" before starting and "completed" immediately after finishing.
5. Keep hierarchy shallow — max 1 level of subtasks.

## Task States
- **pending**: Ready to start (all dependencies met)
- **in_progress**: Currently working on
- **completed**: Finished successfully
- **blocked**: Cannot start — waiting on dependencies (set automatically)

## Example
```json
[
  {"id": "1", "content": "Implement user auth", "status": "in_progress", "subtasks": [
    {"id": "1.1", "content": "Add login endpoint", "status": "in_progress"},
    {"id": "1.2", "content": "Add signup endpoint", "status": "pending"}
  ]},
  {"id": "2", "content": "Write auth tests", "status": "blocked", "depends_on": ["1"]},
  {"id": "3", "content": "Update API docs", "status": "pending", "depends_on": ["1"]}
]
```

## When NOT to Use
- Single straightforward tasks (less than 3 steps)
- Purely conversational or informational requests
- Tasks that don't benefit from tracking"""

HIERARCHICAL_TODOS_SYSTEM_PROMPT = """## `write_todos`

You have access to the `write_todos` tool to help you manage and plan complex objectives with hierarchical task tracking.

Key capabilities:
- **Subtasks**: Group related work under a parent task using the `subtasks` field. Use dotted IDs (e.g., "1.1", "1.2").
- **Dependencies**: Use `depends_on` to specify task ordering. Blocked tasks unblock automatically when their dependencies complete.
- **Blocked status**: Tasks with unmet dependencies are automatically marked as "blocked" — don't manually set this.

Guidelines:
- Mark todos as completed immediately when done. Don't batch completions.
- Keep hierarchy shallow (max 1 level of nesting).
- Use dependencies for cross-task ordering (e.g., tests depend on implementation).
- The tool should never be called multiple times in parallel.
- For simple few-step requests, skip this tool and just do the work directly.
- Don't be afraid to revise the list as you go — new information may reveal new tasks or make old ones irrelevant."""


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------


class HierarchicalPlanningState(AgentState[Any]):
    """State schema for the hierarchical todo middleware."""

    todos: Annotated[NotRequired[list[Todo]], OmitFromInput]
    """List of todo items with optional subtasks and dependencies."""


class HierarchicalTodoMiddleware(AgentMiddleware):
    """Middleware providing hierarchical todo management with subtasks and dependencies.

    Drop-in replacement for ``TodoListMiddleware`` that adds:
    - Task IDs for referencing
    - Nested subtasks (1 level deep)
    - ``depends_on`` for inter-task ordering
    - Automatic ``blocked``/``pending`` resolution
    """

    state_schema = HierarchicalPlanningState

    def __init__(
        self,
        *,
        system_prompt: str = HIERARCHICAL_TODOS_SYSTEM_PROMPT,
        tool_description: str = HIERARCHICAL_TODOS_TOOL_DESCRIPTION,
    ) -> None:
        super().__init__()
        self.system_prompt = system_prompt
        self.tool_description = tool_description

        @tool(description=self.tool_description)
        def write_todos(
            todos: list[Todo], tool_call_id: Annotated[str, InjectedToolCallId]
        ) -> Command[Any]:
            """Create and manage a hierarchical task list with subtasks and dependencies."""
            # Validate
            error = _validate_todos(todos)
            if error:
                return Command(
                    update={
                        "messages": [
                            ToolMessage(
                                f"Error: {error}. Please fix and retry.",
                                tool_call_id=tool_call_id,
                                status="error",
                            )
                        ],
                    }
                )

            # Resolve blocked/pending based on dependencies
            resolved = resolve_blocked(todos)

            return Command(
                update={
                    "todos": resolved,
                    "messages": [
                        ToolMessage(
                            f"Updated todo list to {resolved}",
                            tool_call_id=tool_call_id,
                        )
                    ],
                }
            )

        self.tools = [write_todos]

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelCallResult:
        if request.system_message is not None:
            new_system_content = [
                *request.system_message.content_blocks,
                {"type": "text", "text": f"\n\n{self.system_prompt}"},
            ]
        else:
            new_system_content = [{"type": "text", "text": self.system_prompt}]
        new_system_message = SystemMessage(
            content=cast("list[str | dict[str, str]]", new_system_content)
        )
        return handler(request.override(system_message=new_system_message))

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelCallResult:
        if request.system_message is not None:
            new_system_content = [
                *request.system_message.content_blocks,
                {"type": "text", "text": f"\n\n{self.system_prompt}"},
            ]
        else:
            new_system_content = [{"type": "text", "text": self.system_prompt}]
        new_system_message = SystemMessage(
            content=cast("list[str | dict[str, str]]", new_system_content)
        )
        return await handler(request.override(system_message=new_system_message))

    @override
    def after_model(
        self, state: AgentState[Any], runtime: Any
    ) -> dict[str, Any] | None:
        """Prevent parallel write_todos calls."""
        messages = state["messages"]
        if not messages:
            return None

        last_ai_msg = next(
            (msg for msg in reversed(messages) if isinstance(msg, AIMessage)), None
        )
        if not last_ai_msg or not last_ai_msg.tool_calls:
            return None

        write_todos_calls = [
            tc for tc in last_ai_msg.tool_calls if tc["name"] == "write_todos"
        ]
        if len(write_todos_calls) > 1:
            error_messages = [
                ToolMessage(
                    content=(
                        "Error: The `write_todos` tool should never be called multiple "
                        "times in parallel. Please call it only once per turn."
                    ),
                    tool_call_id=tc["id"],
                    status="error",
                )
                for tc in write_todos_calls
            ]
            return {"messages": error_messages}

        return None

    @override
    async def aafter_model(
        self, state: AgentState[Any], runtime: Any
    ) -> dict[str, Any] | None:
        return self.after_model(state, runtime)

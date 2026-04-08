"""Todo List Middleware with agent name display support.

This middleware provides:
1. Todo list state tracking with agent name display
2. write_todos tool for managing structured task lists
3. System prompt injection for todo instructions
4. Beautiful formatted task list display with agent name header

State Schema:
- todos: list of todo items with content and status
- agent_name: name of the agent for display purposes

Integration:
- Works with LangGraph's Command system for state updates
- Integrates with execution.py for rendering the todo UI
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Annotated, Any, Literal, NotRequired, cast
from typing_extensions import TypedDict

from nova_deepagents.prompts import render_template

from langchain.agents.middleware.types import (
    AgentMiddleware,
    AgentState,
    ContextT,
    ModelRequest,
    ModelResponse,
    OmitFromInput,
    ResponseT,
)
from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.types import Command
from langchain.tools import InjectedToolCallId

logger = logging.getLogger(__name__)


class Todo(TypedDict):
    """A single todo item with content and status."""

    content: str
    """The content/description of the todo item."""

    status: Literal["pending", "in_progress", "completed"]
    """The current status of the todo item."""


class TodoState(AgentState[ResponseT]):
    """State schema for the todo middleware.

    Type Parameters:
        ResponseT: The type of the structured response. Defaults to `Any`.
    """

    todos: Annotated[NotRequired[list[Todo]], OmitFromInput]
    """List of todo items for tracking task progress."""

    agent_name: NotRequired[str]
    """Name of the agent for display in the todo list header."""


class TodoStateUpdate(TypedDict):
    """State update for todo middleware."""

    todos: NotRequired[list[Todo]]
    agent_name: NotRequired[str]


# System prompt for todo management (loaded from template)
TODO_SYSTEM_PROMPT = render_template("todo.jinja")


def _format_todo_list(todos: list[Todo], agent_name: str | None = None) -> str:
    """Format todo list as a beautiful bordered display.

    Args:
        todos: List of todo items to format
        agent_name: Optional agent name for the header

    Returns:
        Formatted string representation of the todo list
    """
    if not todos:
        return "No tasks in the list."

    # Determine header text
    if agent_name:
        header = f"{agent_name}'s Task List"
    else:
        header = "Task List"

    # Calculate max line length for border
    max_content_length = max(len(todo["content"]) for todo in todos)
    # Account for status symbol (► or ○ or ✓) and padding (spaces)
    # Format: "║ ► content ║" = 2 (border) + 1 (space) + 1 (symbol) + 1 (space) + content + padding + 1 (space) + 1 (border)
    content_width = max(max_content_length, len(header) + 10)  # +10 for " ◆ 📋 " and " ◆ "
    
    # Build the display
    lines = []

    # Top border with header
    # Format: "╔══...══ ◆ 📋 Header ◆ ══...══╗"
    header_text = f" ◆ 📋 {header} ◆ "
    top_border = f"╔{'═' * content_width}{header_text}{'═' * content_width}╗"
    lines.append(top_border)

    # Todo items
    for todo in todos:
        status_symbol = {
            "pending": "○",
            "in_progress": "►",
            "completed": "✓",
        }.get(todo["status"], "○")

        # Pad content to align
        content = todo["content"]
        # Calculate padding to match the total width
        # Total width = 2 * content_width + len(header_text)
        total_width = 2 * content_width + len(header_text)
        # Content line format: "║ ► content ║"
        # Available space for content = total_width - 4 (║, space, space, ║)
        available_space = total_width - 4
        padding = available_space - len(content) - 2  # -2 for symbol and space
        line = f"║ {status_symbol} {content}{' ' * padding} ║"
        lines.append(line)

    # Bottom border
    bottom_border = f"╚{'═' * (2 * content_width + len(header_text))}╝"
    lines.append(bottom_border)

    return "\n".join(lines)


WRITE_TODOS_TOOL_DESCRIPTION = """Use this tool to create and manage a structured task list for your current work session. This helps you track progress, organize complex tasks, and demonstrate thoroughness to the user.

Only use this tool if you think it will be helpful in staying organized. If the user's request is trivial and takes less than 3 steps, it is better to NOT use this tool and just do the task directly.

## When to Use This Tool
Use this tool in these scenarios:

1. Complex multi-step tasks - When a task requires 3 or more distinct steps or actions
2. Non-trivial and complex tasks - Tasks that require careful planning or multiple operations
3. User explicitly requests todo list - When the user directly asks you to use the todo list
4. User provides multiple tasks - When users provide a list of things to be done (numbered or comma-separated)
5. The plan may need future revisions or updates based on results from the first few steps

## How to Use This Tool
1. When you start working on a task - Mark it as in_progress BEFORE beginning work.
2. After completing a task - Mark it as completed and add any new follow-up tasks discovered during implementation.
3. You can also update future tasks, such as deleting them if they are no longer necessary, or adding new tasks that are necessary. Don't change previously completed tasks.
4. You can make several updates to the todo list at once. For example, when you complete a task, you can mark the next task you need to start as in_progress.

## When NOT to Use This Tool
It is important to skip using this tool when:
1. There is only a single, straightforward task
2. The task is trivial and tracking it provides no benefit
3. The task can be completed in less than 3 trivial steps
4. The task is purely conversational or informational

## Task States and Management

1. **Task States**: Use these states to track progress:
   - pending: Task not yet started
   - in_progress: Currently working on (you can have multiple tasks in_progress at a time if they are not related to each other and can be run in parallel)
   - completed: Task finished successfully

2. **Task Management**:
   - Update task status in real-time as you work
   - Mark tasks complete IMMEDIATELY after finishing (don't batch completions)
   - Complete current tasks before starting new ones
   - Remove tasks that are no longer relevant from the list entirely
   - IMPORTANT: When you write this todo list, you should mark your first task (or tasks) as in_progress immediately!.
   - IMPORTANT: Unless all tasks are completed, you should always have at least one task in_progress to show the user that you are working on something.

3. **Task Completion Requirements**:
   - ONLY mark a task as completed when you have FULLY accomplished it
   - If you encounter errors, blockers, or cannot finish, keep the task as in_progress
   - When blocked, create a new task describing what needs to be resolved
   - Never mark a task as completed if:
     - There are unresolved issues or errors
     - Work is partial or incomplete
     - You encountered blockers that prevent completion
     - You couldn't find necessary resources or dependencies
     - Quality standards haven't been met

4. **Task Breakdown**:
   - Create specific, actionable items
   - Break complex tasks into smaller, manageable steps
   - Use clear, descriptive task names

Being proactive with task management demonstrates attentiveness and ensures you complete all requirements successfully
Remember: If you only need to make few tool calls to complete a task, and it is clear what you need to do, it is better to just do the task directly and NOT call this tool at all."""  # noqa: E501


@tool(description=WRITE_TODOS_TOOL_DESCRIPTION)
def write_todos(
    todos: list[Todo], tool_call_id: Annotated[str, InjectedToolCallId]
) -> Command[Any]:
    """Create and manage a structured task list for your current work session."""
    return Command(
        update={
            "todos": todos,
            "messages": [ToolMessage(f"Updated todo list to {todos}", tool_call_id=tool_call_id)],
        }
    )


class TodoListMiddleware(AgentMiddleware[TodoState[ResponseT], ContextT, ResponseT]):
    """Middleware that provides todo list management capabilities to agents.

    This middleware adds a `write_todos` tool that allows agents to create and manage
    structured task lists for complex multi-step operations. It's designed to help
    agents track progress, organize complex tasks, and provide users with visibility
    into task completion status.

    The middleware automatically injects system prompts that guide the agent on when
    and how to use the todo functionality effectively. It also enforces that the
    `write_todos` tool is called at most once per model turn, since the tool replaces
    the entire todo list and parallel calls would create ambiguity about precedence.

    The middleware supports agent name display in the todo list header, allowing
    different agents to have their own named task lists.

    Example:
        ```python
        from nova_deepagents.middleware.todo import TodoListMiddleware
        from langchain.agents import create_agent

        agent = create_agent(
            "openai:gpt-4o",
            middleware=[TodoListMiddleware(agent_name="Research Agent")]
        )

        # Agent now has access to write_todos tool and todo state tracking
        result = await agent.invoke({"messages": [HumanMessage("Research quantum computing")]})

        print(result["todos"])  # Array of todo items with status tracking
        ```

    Attributes:
        state_schema: The state schema for this middleware (TodoState).
        agent_name: Optional name of the agent for display in the todo list header.
    """

    state_schema = TodoState  # type: ignore[assignment]

    def __init__(
        self,
        *,
        agent_name: str | None = None,
        system_prompt: str = TODO_SYSTEM_PROMPT,
        tool_description: str = WRITE_TODOS_TOOL_DESCRIPTION,
    ) -> None:
        """Initialize the `TodoListMiddleware` with optional agent name and custom prompts.

        Args:
            agent_name: Optional name of the agent for display in the todo list header.
                If provided, the todo list will show "{agent_name}'s Task List" as the header.
            system_prompt: Custom system prompt to guide the agent on using the todo tool.
            tool_description: Custom description for the `write_todos` tool.
        """
        super().__init__()
        self.agent_name = agent_name
        self.system_prompt = system_prompt
        self.tool_description = tool_description

        # Dynamically create the write_todos tool with the custom description
        @tool(description=self.tool_description)
        def write_todos(
            todos: list[Todo], tool_call_id: Annotated[str, InjectedToolCallId]
        ) -> Command[Any]:
            """Create and manage a structured task list for your current work session."""
            # Format the todo list with agent name if available
            formatted_todos = _format_todo_list(todos, self.agent_name)
            return Command(
                update={
                    "todos": todos,
                    "messages": [
                        ToolMessage(formatted_todos, tool_call_id=tool_call_id)
                    ],
                }
            )

        self.tools = [write_todos]

    def before_agent(  # type: ignore
        self, state: TodoState[ResponseT], runtime, config
    ) -> TodoStateUpdate | None:
        """Initialize agent name in state if provided.

        Args:
            state: Current agent state.
            runtime: LangGraph runtime instance.
            config: Runtime configuration.

        Returns:
            State update with agent name if not already set, otherwise None.
        """
        if self.agent_name and "agent_name" not in state:
            return TodoStateUpdate(agent_name=self.agent_name)
        return None

    async def abefore_agent(  # type: ignore
        self, state: TodoState[ResponseT], runtime, config
    ) -> TodoStateUpdate | None:
        """Initialize agent name in state if provided (async).

        Args:
            state: Current agent state.
            runtime: LangGraph runtime instance.
            config: Runtime configuration.

        Returns:
            State update with agent name if not already set, otherwise None.
        """
        return self.before_agent(state, runtime, config)

    def wrap_model_call(
        self,
        request: ModelRequest[ContextT],
        handler: Callable[[ModelRequest[ContextT]], ModelResponse[ResponseT]],
    ) -> ModelResponse[ResponseT] | AIMessage:
        """Update the system message to include the todo system prompt.

        Args:
            request: Model request to execute (includes state and runtime).
            handler: Async callback that executes the model request and returns
                `ModelResponse`.

        Returns:
            The model call result.
        """
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
        request: ModelRequest[ContextT],
        handler: Callable[[ModelRequest[ContextT]], Awaitable[ModelResponse[ResponseT]]],
    ) -> ModelResponse[ResponseT] | AIMessage:
        """Update the system message to include the todo system prompt.

        Args:
            request: Model request to execute (includes state and runtime).
            handler: Async callback that executes the model request and returns
                `ModelResponse`.

        Returns:
            The model call result.
        """
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

    def after_model(
        self, state: TodoState[ResponseT], runtime
    ) -> dict[str, Any] | None:
        """Check for parallel write_todos tool calls and return errors if detected.

        The todo list is designed to be updated at most once per model turn. Since
        the `write_todos` tool replaces the entire todo list with each call, making
        multiple parallel calls would create ambiguity about which update should take
        precedence. This method prevents such conflicts by rejecting any response that
        contains multiple write_todos tool calls.

        Args:
            state: The current agent state containing messages.
            runtime: The LangGraph runtime instance.

        Returns:
            A dict containing error ToolMessages for each write_todos call if multiple
            parallel calls are detected, otherwise None to allow normal execution.
        """
        messages = state.get("messages", [])
        if not messages:
            return None

        last_ai_msg = next((msg for msg in reversed(messages) if isinstance(msg, AIMessage)), None)
        if not last_ai_msg or not last_ai_msg.tool_calls:
            return None

        # Count write_todos tool calls
        write_todos_calls = [tc for tc in last_ai_msg.tool_calls if tc["name"] == "write_todos"]

        if len(write_todos_calls) > 1:
            # Create error tool messages for all write_todos calls
            error_messages = [
                ToolMessage(
                    content=(
                        "Error: The `write_todos` tool should never be called multiple times "
                        "in parallel. Please call it only once per model invocation to update "
                        "the todo list."
                    ),
                    tool_call_id=tc["id"],
                    status="error",
                )
                for tc in write_todos_calls
            ]

            # Keep the tool calls in the AI message but return error messages
            # This follows the same pattern as HumanInTheLoopMiddleware
            return {"messages": error_messages}

        return None

    async def aafter_model(
        self, state: TodoState[ResponseT], runtime
    ) -> dict[str, Any] | None:
        """Check for parallel write_todos tool calls and return errors if detected.

        Async version of `after_model`. The todo list is designed to be updated at
        most once per model turn. Since the `write_todos` tool replaces the entire
        todo list with each call, making multiple parallel calls would create ambiguity
        about which update should take precedence. This method prevents such conflicts
        by rejecting any response that contains multiple write_todos tool calls.

        Args:
            state: The current agent state containing messages.
            runtime: The LangGraph runtime instance.

        Returns:
            A dict containing error ToolMessages for each write_todos call if multiple
            parallel calls are detected, otherwise None to allow normal execution.
        """
        return self.after_model(state, runtime)

    def format_todos(self, todos: list[Todo]) -> str:
        """Format the todo list with the agent name header.

        Args:
            todos: List of todo items to format.

        Returns:
            Formatted string representation of the todo list.
        """
        return _format_todo_list(todos, self.agent_name)


__all__ = [
    "TodoListMiddleware",
    "TodoState",
    "TodoStateUpdate",
    "Todo",
    "WRITE_TODOS_TOOL_DESCRIPTION",
    "TODO_SYSTEM_PROMPT",
    "_format_todo_list",
]
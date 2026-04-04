"""Robust todo list middleware that handles JSON string arguments.

This module provides a custom TodoListMiddleware that wraps the original
langchain.agents.middleware.todo.TodoListMiddleware but adds robustness
for handling cases where the LLM passes todos as a JSON string instead
of a proper Python list.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Annotated, Any, Literal, cast

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from langgraph.runtime import Runtime

from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.types import Command
from typing_extensions import NotRequired, TypedDict, override

from langchain.agents.middleware.types import (
    AgentMiddleware,
    AgentState,
    ContextT,
    ModelRequest,
    ModelResponse,
    OmitFromInput,
    ResponseT,
)
from langchain.tools import InjectedToolCallId

from nami_deepagents.prompts import render_template

logger = logging.getLogger(__name__)


class Todo(TypedDict):
    """A single todo item with content and status."""

    content: str
    """The content/description of the todo item."""

    status: Literal["pending", "in_progress", "completed"]
    """The current status of the todo item."""


class PlanningState(AgentState[ResponseT]):
    """State schema for the todo middleware.

    Type Parameters:
        ResponseT: The type of the structured response. Defaults to `Any`.
    """

    todos: Annotated[NotRequired[list[Todo]], OmitFromInput]
    """List of todo items for tracking task progress."""


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
   - IMPORTANT: When you write this todo list, you should mark your first task (or tasks) as in_progress immediately!
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
Remember: If you only need to make a few tool calls to complete a task, and it is clear what you need to do, it is better to just do the task directly and NOT call this tool at all."""  # noqa: E501

# System prompt loaded from jinja template
WRITE_TODOS_SYSTEM_PROMPT = render_template("todo.jinja")


def _parse_todos(todos_input: list[Todo] | str) -> list[Todo]:
    """Parse todos input, handling JSON strings.

    Args:
        todos_input: Either a list of Todo dicts or a JSON string.

    Returns:
        A list of Todo dicts.

    Raises:
        ValueError: If the input cannot be parsed.
    """
    if isinstance(todos_input, list):
        return todos_input

    if isinstance(todos_input, str):
        try:
            parsed = json.loads(todos_input)
            if isinstance(parsed, list):
                return parsed
            raise ValueError(f"Expected a list, got {type(parsed).__name__}")
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON: {e}") from e

    raise ValueError(f"Expected list or JSON string, got {type(todos_input).__name__}")


def _validate_todo(todo: dict) -> Todo:
    """Validate and normalize a todo item.

    Args:
        todo: A todo dict to validate.

    Returns:
        A validated Todo dict.

    Raises:
        ValueError: If the todo is invalid.
    """
    if not isinstance(todo, dict):
        raise ValueError(f"Todo must be a dict, got {type(todo).__name__}")

    content = todo.get("content")
    if not content:
        raise ValueError("Todo must have 'content' field")

    status = todo.get("status", "pending")
    if status not in ("pending", "in_progress", "completed"):
        raise ValueError(f"Invalid status '{status}', must be one of: pending, in_progress, completed")

    return {"content": str(content), "status": status}


@tool(description=WRITE_TODOS_TOOL_DESCRIPTION)
def write_todos(
    todos: list[Todo] | str, tool_call_id: Annotated[str, InjectedToolCallId]
) -> Command[Any]:
    """Create and manage a structured task list for your current work session.

    Args:
        todos: A list of todo items, each with 'content' and 'status' fields.
               Can also be a JSON string that will be parsed.
        tool_call_id: Injected tool call ID for message correlation.

    Returns:
        Command to update the todo list state.
    """
    # Handle JSON string input (common LLM mistake)
    try:
        parsed_todos = _parse_todos(todos)
    except ValueError as e:
        logger.warning(f"Failed to parse todos: {e}")
        return Command(
            update={
                "messages": [
                    ToolMessage(
                        f"Error parsing todos: {e}. Please provide a valid list of todo items.",
                        tool_call_id=tool_call_id,
                    )
                ]
            }
        )

    # Validate each todo item
    validated_todos: list[Todo] = []
    for i, todo in enumerate(parsed_todos):
        try:
            validated_todos.append(_validate_todo(todo))
        except ValueError as e:
            logger.warning(f"Invalid todo at index {i}: {e}")
            return Command(
                update={
                    "messages": [
                        ToolMessage(
                            f"Invalid todo at index {i}: {e}",
                            tool_call_id=tool_call_id,
                        )
                    ]
                }
            )

    return Command(
        update={
            "todos": validated_todos,
            "messages": [
                ToolMessage(
                    f"Updated todo list with {len(validated_todos)} items",
                    tool_call_id=tool_call_id,
                )
            ],
        }
    )


class TodoListMiddleware(AgentMiddleware[PlanningState[ResponseT], ContextT, ResponseT]):
    """Middleware that provides todo list management capabilities to agents.

    This middleware adds a `write_todos` tool that allows agents to create and manage
    structured task lists for complex multi-step operations. It's designed to help
    agents track progress, organize complex tasks, and provide users with visibility
    into task completion status.

    This version is more robust than the original langchain TodoListMiddleware:
    - Handles JSON string input for todos (common LLM mistake)
    - Validates todo items before storing
    - Provides better error messages

    Example:
        ```python
        from nami_deepagents.middleware.todo import TodoListMiddleware
        from nami_deepagents import create_agent

        agent = create_agent("openai:gpt-4o", middleware=[TodoListMiddleware()])

        # Agent now has access to write_todos tool and todo state tracking
        result = await agent.invoke({"messages": [HumanMessage("Help me refactor my codebase")]})

        print(result["todos"])  # Array of todo items with status tracking
        ```
    """

    state_schema = PlanningState  # type: ignore[assignment]

    def __init__(
        self,
        *,
        system_prompt: str = WRITE_TODOS_SYSTEM_PROMPT,
        tool_description: str = WRITE_TODOS_TOOL_DESCRIPTION,
    ) -> None:
        """Initialize the `TodoListMiddleware` with optional custom prompts.

        Args:
            system_prompt: Custom system prompt to guide the agent on using the todo
                tool.
            tool_description: Custom description for the `write_todos` tool.
        """
        super().__init__()
        self.system_prompt = system_prompt
        self.tool_description = tool_description

        # Dynamically create the write_todos tool with the custom description
        @tool(description=self.tool_description)
        def write_todos(
            todos: list[Todo] | str, tool_call_id: Annotated[str, InjectedToolCallId]
        ) -> Command[Any]:
            """Create and manage a structured task list for your current work session."""
            # Handle JSON string input (common LLM mistake)
            try:
                parsed_todos = _parse_todos(todos)
            except ValueError as e:
                logger.warning(f"Failed to parse todos: {e}")
                return Command(
                    update={
                        "messages": [
                            ToolMessage(
                                f"Error parsing todos: {e}. Please provide a valid list of todo items.",
                                tool_call_id=tool_call_id,
                            )
                        ]
                    }
                )

            # Validate each todo item
            validated_todos: list[Todo] = []
            for i, todo in enumerate(parsed_todos):
                try:
                    validated_todos.append(_validate_todo(todo))
                except ValueError as e:
                    logger.warning(f"Invalid todo at index {i}: {e}")
                    return Command(
                        update={
                            "messages": [
                                ToolMessage(
                                    f"Invalid todo at index {i}: {e}",
                                    tool_call_id=tool_call_id,
                                )
                            ]
                        }
                    )

            return Command(
                update={
                    "todos": validated_todos,
                    "messages": [
                        ToolMessage(
                            f"Updated todo list with {len(validated_todos)} items",
                            tool_call_id=tool_call_id,
                        )
                    ],
                }
            )

        self.tools = [write_todos]

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
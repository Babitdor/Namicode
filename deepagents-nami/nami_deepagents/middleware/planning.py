"""Plan Mode Middleware for enhanced planning and question-asking capabilities.

This middleware provides:
1. Plan mode state tracking (enabled/disabled)
2. ask_question tool for both structured (multiple choice) and open-ended questions
3. System prompt injection for planning instructions when enabled
4. Complexity detection to suggest plan mode activation

State Schema:
- plan_mode_enabled: bool - Whether plan mode is currently active
- pending_question: dict | None - Question awaiting user response

Tool Schema (ask_question):
- question: str - The question to ask the user
- question_type: "structured" | "open_ended" - Type of question
- options: list[str] | None - Options for structured questions (required if structured)
- context: str | None - Additional context about why asking

Integration:
- Uses LangGraph Command(interrupt=...) for HITL question flow
- Integrates with execution.py for rendering question UI
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Annotated, Literal, NotRequired, TypedDict

from langchain.agents.middleware.types import (
    AgentMiddleware,
    AgentState,
    ModelRequest,
    ModelResponse,
    PrivateStateAttr,
)
from langchain_core.tools import StructuredTool
from langchain.tools import BaseTool
from langgraph.types import interrupt

logger = logging.getLogger(__name__)

# Question types
QuestionType = Literal["structured", "open_ended"]


class QuestionRequest(TypedDict):
    """Schema for a question request from the agent."""

    question: str
    question_type: QuestionType
    options: NotRequired[list[str]]  # Required if question_type == "structured"
    context: NotRequired[str]  # Why the agent is asking


class QuestionResponse(TypedDict):
    """Schema for user's response to a question."""

    answer: str
    selected_index: NotRequired[int]  # For structured questions


class PlanModeState(AgentState):
    """State schema for plan mode middleware."""

    plan_mode_enabled: NotRequired[Annotated[bool, PrivateStateAttr]]
    """Whether plan mode is currently active."""

    pending_question: NotRequired[Annotated[QuestionRequest | None, PrivateStateAttr]]
    """Question currently awaiting user response."""


class PlanModeStateUpdate(TypedDict):
    """State update for plan mode middleware."""

    plan_mode_enabled: NotRequired[bool]
    pending_question: NotRequired[QuestionRequest | None]


# System prompt for plan mode (injected when enabled)
PLAN_MODE_SYSTEM_PROMPT = """
## Plan Mode (ACTIVE) - PLANNING ONLY

You are currently in **Plan Mode**. This is a PLANNING-ONLY phase.

### CRITICAL RULES:
1. **DO NOT EXECUTE** - You must ONLY create a plan, not execute it
2. **NO FILE OPERATIONS** - Do not write, edit, or create any files
3. **NO CODE CHANGES** - Do not implement any code yet
4. **PLAN FIRST** - Create your plan using the `write_todos` tool

### Your Task in Plan Mode:
1. **Analyze** the user's request thoroughly
2. **Decompose** the task into clear, actionable steps
3. **Identify** dependencies, constraints, and potential issues
4. **Create a plan** using `write_todos` with all steps needed
5. **Call `exit_plan_mode`** to submit the plan for user approval

### Plan Structure (use write_todos):
- Break complex tasks into small, verifiable steps
- Each todo should be a single, clear action
- Order todos by dependency (what must happen first)
- Include verification steps (e.g., "Test the changes")

### After Planning:
Once you create the plan with `write_todos`, you MUST call `exit_plan_mode` to submit
your plan for user approval. The user will review and approve before you execute.

**REMEMBER: In Plan Mode, you are a PLANNER, not an EXECUTOR.**
**ALWAYS call `exit_plan_mode` when your plan is ready.**
"""

# System prompt for ask_question tool (always included)
ASK_QUESTION_SYSTEM_PROMPT = """
## Question Tool Available

You have access to `ask_question` to get clarification from the user:

- **Structured questions**: Multiple choice with predefined options
- **Open-ended questions**: Free-form text response

Use this when:
- Requirements are ambiguous or incomplete
- Multiple valid approaches exist and user preference matters
- You need specific information (API keys locations, deployment targets)
- Confirming understanding before significant changes

The user will see your question and respond directly.
"""


def _exit_plan_mode() -> str:
    """Exit plan mode and submit the plan for user approval.

    Call this tool when you have finished creating your plan using write_todos.
    The user will review your plan and decide whether to approve it.

    Returns:
        The user's decision: "approved" or "rejected".
    """
    # Use LangGraph's interrupt to pause execution and get user approval
    response = interrupt({
        "type": "plan_approval",
        "message": "Plan is ready for review",
    })

    # Return the user's decision
    if isinstance(response, dict):
        if response.get("approved"):
            return "Plan approved. You may now execute the plan."
        else:
            return "Plan rejected. Please revise the plan based on user feedback."
    return str(response)


def _create_exit_plan_mode_tool() -> BaseTool:
    """Create the exit_plan_mode tool."""
    return StructuredTool.from_function(
        name="exit_plan_mode",
        func=_exit_plan_mode,
        description=(
            "Exit plan mode and submit your plan for user approval. "
            "Call this after creating your plan with write_todos. "
            "The user will review and approve or reject the plan."
        ),
    )


def _ask_question(
    question: str,
    question_type: QuestionType = "open_ended",
    options: list[str] | None = None,
    context: str | None = None,
) -> str:
    """Ask the user a question and wait for their response.

    Use this tool when you need clarification or user input before proceeding.
    The execution will pause until the user responds.

    Args:
        question: The question to ask the user.
        question_type: Either "structured" (multiple choice) or "open_ended" (free text).
        options: List of options for structured questions. Required if question_type is "structured".
        context: Optional explanation of why you're asking this question.

    Returns:
        The user's response as a string.
    """
    if question_type == "structured" and not options:
        return "Error: 'options' is required for structured questions."

    if question_type == "structured" and options and len(options) < 2:
        return "Error: Structured questions need at least 2 options."

    # Create the question request
    question_request: QuestionRequest = {
        "question": question,
        "question_type": question_type,
    }
    if options:
        question_request["options"] = options
    if context:
        question_request["context"] = context

    # Use LangGraph's interrupt to pause execution and get user input
    # The execution loop will handle displaying the question and getting the response
    response = interrupt({
        "type": "question",
        "request": question_request,
    })

    # Return the user's answer
    if isinstance(response, dict) and "answer" in response:
        return response["answer"]
    return str(response)


def _create_ask_question_tool() -> BaseTool:
    """Create the ask_question tool."""
    return StructuredTool.from_function(
        name="ask_question",
        func=_ask_question,
        description=(
            "Ask the user a question when you need clarification or input. "
            "Use 'structured' for multiple choice, 'open_ended' for free text. "
            "Execution pauses until the user responds."
        ),
    )


class PlanModeMiddleware(AgentMiddleware):
    """Middleware for plan mode and question-asking capabilities.

    This middleware:
    1. Tracks plan mode state (enabled/disabled)
    2. Provides the ask_question tool for agent-initiated questions
    3. Injects planning instructions when plan mode is enabled
    4. Supports both structured (multiple choice) and open-ended questions

    Args:
        enabled_by_default: Whether plan mode starts enabled (default: False).
        include_system_prompt: Whether to inject system prompt instructions.
    """

    state_schema = PlanModeState

    def __init__(
        self,
        enabled_by_default: bool = False,
        include_system_prompt: bool = True,
    ) -> None:
        super().__init__()
        self.enabled_by_default = enabled_by_default
        self.include_system_prompt = include_system_prompt
        self._ask_question_tool = _create_ask_question_tool()
        self._exit_plan_mode_tool = _create_exit_plan_mode_tool()

    @property
    def tools(self) -> list[BaseTool]:
        """Return tools provided by this middleware."""
        return [self._ask_question_tool, self._exit_plan_mode_tool]

    def before_agent(  # type: ignore
        self, state: PlanModeState, runtime, config
    ) -> PlanModeStateUpdate | None:
        """Initialize plan mode state if not present."""
        if "plan_mode_enabled" not in state:
            return PlanModeStateUpdate(
                plan_mode_enabled=self.enabled_by_default,
                pending_question=None,
            )
        return None

    async def abefore_agent(  # type: ignore
        self, state: PlanModeState, runtime, config
    ) -> PlanModeStateUpdate | None:
        """Initialize plan mode state if not present (async)."""
        return self.before_agent(state, runtime, config)

    def modify_request(self, request: ModelRequest) -> ModelRequest:
        """Inject plan mode instructions into a model request's system prompt.

        Args:
            request: Model request to modify

        Returns:
            New model request with plan mode documentation injected into system prompt
        """
        if not self.include_system_prompt:
            return request

        system_prompt = request.system_prompt or ""

        # Always include ask_question tool instructions
        system_prompt += "\n\n" + ASK_QUESTION_SYSTEM_PROMPT

        # Add plan mode instructions if enabled
        plan_mode_enabled = request.state.get("plan_mode_enabled", False)
        if plan_mode_enabled:
            system_prompt += "\n\n" + PLAN_MODE_SYSTEM_PROMPT

        return request.override(system_prompt=system_prompt)

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        """Inject plan mode instructions into the system prompt."""
        modified_request = self.modify_request(request)
        return handler(modified_request)

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        """Inject plan mode instructions into the system prompt (async)."""
        modified_request = self.modify_request(request)
        return await handler(modified_request)


__all__ = [
    "PlanModeMiddleware",
    "PlanModeState",
    "PlanModeStateUpdate",
    "QuestionRequest",
    "QuestionResponse",
    "QuestionType",
]

"""Middleware that provides the ask_question tool to agents.

This is a lightweight, always-on middleware that lets any agent pause execution
and ask the user a question — independently of plan mode.

Provides:
- ``ask_question`` tool: structured (multiple-choice) questions only
- System prompt snippet describing when to use the tool

Integration:
- Uses LangGraph's ``interrupt()`` for the HITL pause/resume cycle
- The execution loop in ``NovaCode_cli/ui/execution.py`` handles the UI side
"""

from __future__ import annotations

from typing import Any, NotRequired, TypedDict

from langchain.agents.middleware.types import (
    AgentMiddleware,
    AgentState,
    ModelRequest,
    ModelResponse,
)
from langchain_core.tools import BaseTool, StructuredTool
from langgraph.types import interrupt

from nova_deepagents.prompts import render_template

# Context tracking for middleware optimization
try:
    from novacode_cli.utils.context_tracking import track_context, track_context_async
    CONTEXT_TRACKING_AVAILABLE = True
except ImportError:
    CONTEXT_TRACKING_AVAILABLE = False
    # Fallback: create no-op decorators
    def track_context(name):
        def decorator(func):
            return func
        return decorator
    def track_context_async(name):
        def decorator(func):
            return func
        return decorator

# ---------------------------------------------------------------------------
# Types (also imported by planning.py so they stay in one canonical place)
# ---------------------------------------------------------------------------


class OptionDict(TypedDict, total=False):
    """Rich option object the LLM may pass instead of a plain string."""

    label: str
    value: str
    description: str


class QuestionRequest(TypedDict):
    """Schema for a question request from the agent."""

    question: str
    options: list[str]  # Required: at least 2 options for structured questions
    question_type: NotRequired[str]  # "structured" for multiple-choice questions
    context: NotRequired[str]  # Why the agent is asking


class QuestionResponse(TypedDict):
    """Schema for the user's response to a question."""

    answer: str
    selected_index: NotRequired[int]  # Index of selected option


# ---------------------------------------------------------------------------
# System-prompt snippet (injected by AskQuestionMiddleware)
# ---------------------------------------------------------------------------

ASK_QUESTION_SYSTEM_PROMPT = render_template("ask_question.jinja")


# ---------------------------------------------------------------------------
# Tool implementation
# ---------------------------------------------------------------------------


def _normalize_options(
    raw: list[str | dict[str, Any]],
) -> tuple[list[str], dict[str, str]]:
    """Normalise options to display strings and build a label→value mapping.

    Accepts either plain strings or dicts with ``label`` / ``value`` /
    ``description`` keys (the richer format the LLM sometimes produces).

    Returns:
        display_options: list of strings shown in the menu.
        value_map: maps each display string back to its intended return value
            (identity mapping for plain strings; ``value`` field for dicts).
    """
    display_options: list[str] = []
    value_map: dict[str, str] = {}
    for opt in raw:
        if isinstance(opt, dict):
            label = str(opt.get("label") or opt.get("value") or opt)
            description = opt.get("description", "")
            display = f"{label} — {description}" if description else label
            return_value = str(opt.get("value") or label)
        else:
            display = str(opt)
            return_value = str(opt)
        display_options.append(display)
        value_map[display] = return_value
    return display_options, value_map


def _ask_question(
    question: str,
    options: list[str | dict[str, Any]],
    context: str | None = None,
) -> str:
    """Ask the user a multiple-choice question and wait for their response.

    Use this tool when you need clarification or user input before proceeding.
    The execution will pause until the user responds.

    IMPORTANT: This tool ONLY accepts structured (multiple-choice) questions.
    You MUST provide at least 2 options for the user to choose from.
    An "Other" option is automatically added for free-form input if needed.

    Args:
        question: The question to ask the user.
        options: List of options for the user to choose from. Each option may be a plain
            string or a dict with ``label``, ``value``, and optional ``description`` keys.
            At least 2 options are required.
        context: Optional explanation of why you're asking this question.

    Returns:
        The user's selected option as a string.
    """
    if not options or len(options) < 2:
        return "Error: At least 2 options are required for ask_question. Provide multiple choices for the user."

    # Normalise to display strings; keep a mapping back to intended values
    display_options, value_map = _normalize_options(options)

    question_request: QuestionRequest = {
        "question": question,
        "options": display_options,
        "question_type": "structured",  # Always structured for ask_question tool
    }
    if context:
        question_request["context"] = context

    # LangGraph interrupt — pauses the graph and hands control back to the CLI
    response = interrupt(
        {
            "type": "question",
            "request": question_request,
        }
    )

    raw_answer = (
        response["answer"]
        if isinstance(response, dict) and "answer" in response
        else str(response)
    )
    # Return the intended value (e.g. "portfolio") not just the display label
    return value_map.get(raw_answer, raw_answer)


def _create_ask_question_tool() -> BaseTool:
    """Create the ask_question StructuredTool."""
    return StructuredTool.from_function(
        name="ask_question",
        func=_ask_question,
        description=(
            "Ask the user a multiple-choice question when you need clarification before proceeding. "
            "IMPORTANT: This tool ONLY accepts structured (multiple-choice) questions. "
            "You MUST provide at least 2 options for the user to choose from. "
            "Use this tool sparingly: only when you genuinely need information you cannot determine from context. "
            "Never ask questions you can answer yourself from the available context. "
            "Execution pauses until the user responds."
        ),
    )


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------


class AskQuestionMiddleware(AgentMiddleware[AgentState, Any]):
    """Lightweight middleware that gives agents the ability to ask the user questions.

    This is decoupled from plan mode so that any agent — regardless of whether
    plan mode is enabled — can pause and ask for clarification.

    Provides:
    - ``ask_question`` tool (structured multiple-choice questions only)
    - ``ASK_QUESTION_SYSTEM_PROMPT`` injected into the system prompt

    Usage::

        agent_middleware = [
            AskQuestionMiddleware(),
            PlanModeMiddleware(enabled_by_default=False),
            ...
        ]
    """

    def __init__(self, *, include_system_prompt: bool = True) -> None:
        super().__init__()
        self.include_system_prompt = include_system_prompt
        self._ask_question_tool = _create_ask_question_tool()
        self.tools = [self._ask_question_tool]

    def modify_request(self, request: ModelRequest) -> ModelRequest:
        """Inject ASK_QUESTION_SYSTEM_PROMPT into the system prompt."""
        if not self.include_system_prompt:
            return request
        system_prompt = (
            (request.system_prompt or "") + "\n\n" + ASK_QUESTION_SYSTEM_PROMPT
        )
        return request.override(system_prompt=system_prompt)  # type: ignore

    @track_context("AskQuestionMiddleware")
    def wrap_model_call(self, request: ModelRequest, handler) -> ModelResponse:
        return handler(self.modify_request(request))

    @track_context_async("AskQuestionMiddleware")
    async def awrap_model_call(self, request: ModelRequest, handler) -> ModelResponse:
        return await handler(self.modify_request(request))


__all__ = [
    "AskQuestionMiddleware",
    "ASK_QUESTION_SYSTEM_PROMPT",
    "OptionDict",
    "QuestionRequest",
    "QuestionResponse",
]

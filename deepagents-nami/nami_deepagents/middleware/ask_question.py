"""Middleware that provides the ask_question tool to agents.

This is a lightweight, always-on middleware that lets any agent pause execution
and ask the user a question — independently of plan mode.

Provides:
- ``ask_question`` tool: structured (multiple-choice) or open-ended questions
- System prompt snippet describing when to use the tool

Integration:
- Uses LangGraph's ``interrupt()`` for the HITL pause/resume cycle
- The execution loop in ``namicode_cli/ui/execution.py`` handles the UI side
"""

from __future__ import annotations

from typing import Any, Literal, NotRequired, TypedDict

from langchain.agents.middleware.types import (
    AgentMiddleware,
    AgentState,
    ModelRequest,
    ModelResponse,
)
from langchain_core.tools import BaseTool, StructuredTool
from langgraph.types import interrupt

# ---------------------------------------------------------------------------
# Types (also imported by planning.py so they stay in one canonical place)
# ---------------------------------------------------------------------------

QuestionType = Literal["structured", "open_ended"]


class OptionDict(TypedDict, total=False):
    """Rich option object the LLM may pass instead of a plain string."""

    label: str
    value: str
    description: str


class QuestionRequest(TypedDict):
    """Schema for a question request from the agent."""

    question: str
    question_type: QuestionType
    options: NotRequired[list[str]]  # Required if question_type == "structured"
    context: NotRequired[str]  # Why the agent is asking


class QuestionResponse(TypedDict):
    """Schema for the user's response to a question."""

    answer: str
    selected_index: NotRequired[int]  # For structured questions only


# ---------------------------------------------------------------------------
# System-prompt snippet (injected by AskQuestionMiddleware)
# ---------------------------------------------------------------------------

ASK_QUESTION_SYSTEM_PROMPT = """
## ask_question Tool

Use `ask_question` to pause and get clarification before proceeding. **Prefer asking over guessing** — a short question saves costly rework.

**Ask when:**
- The request is ambiguous or has multiple interpretations
- Multiple valid approaches exist and user preference matters
- Key information is missing (target, constraints, environment)
- You are about to make a hard-to-reverse decision

**Do NOT ask when:**
- The answer is obvious from context
- It's a trivial implementation detail the user doesn't care about

**Question types:**
- `structured` — multiple choice (use when there are clear alternatives)
- `open_ended` — free text (use for open-ended or unknown answers)

The user will see your question and respond directly before you continue.

For structured questions, options may be plain strings **or** rich dicts:
```json
{"label": "Portfolio site", "value": "portfolio", "description": "Showcase your work"}
```
The `value` field is returned to you after the user picks an option.
"""


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
    question_type: QuestionType = "open_ended",
    options: list[str | dict[str, Any]] | None = None,
    context: str | None = None,
) -> str:
    """Ask the user a question and wait for their response.

    Use this tool when you need clarification or user input before proceeding.
    The execution will pause until the user responds.

    Args:
        question: The question to ask the user.
        question_type: Either "structured" (multiple choice) or "open_ended" (free text).
        options: List of options for structured questions. Each option may be a plain
            string or a dict with ``label``, ``value``, and optional ``description`` keys.
            Required if question_type is "structured".
        context: Optional explanation of why you're asking this question.

    Returns:
        The user's response as a string.
    """
    if question_type == "structured" and not options:
        return "Error: 'options' is required for structured questions."

    if question_type == "structured" and options and len(options) < 2:
        return "Error: Structured questions need at least 2 options."

    # Normalise to display strings; keep a mapping back to intended values
    value_map: dict[str, str] = {}
    display_options: list[str] | None = None
    if options:
        display_options, value_map = _normalize_options(options)

    question_request: QuestionRequest = {
        "question": question,
        "question_type": question_type,
    }
    if display_options:
        question_request["options"] = display_options
    if context:
        question_request["context"] = context

    # LangGraph interrupt — pauses the graph and hands control back to the CLI
    response = interrupt(
        {
            "type": "question",
            "request": question_request,
        }
    )

    raw_answer = response["answer"] if isinstance(response, dict) and "answer" in response else str(response)
    # Return the intended value (e.g. "portfolio") not just the display label
    return value_map.get(raw_answer, raw_answer)


def _create_ask_question_tool() -> BaseTool:
    """Create the ask_question StructuredTool."""
    return StructuredTool.from_function(
        name="ask_question",
        func=_ask_question,
        description=(
            "Ask the user a question when you need clarification or input. "
            "Use 'structured' for multiple choice, 'open_ended' for free text. "
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
    - ``ask_question`` tool (structured or open-ended)
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

    @property
    def tools(self) -> list[BaseTool]:
        """Return the ask_question tool."""
        return [self._ask_question_tool]

    def modify_request(self, request: ModelRequest) -> ModelRequest:
        """Inject ASK_QUESTION_SYSTEM_PROMPT into the system prompt."""
        if not self.include_system_prompt:
            return request
        system_prompt = (request.system_prompt or "") + "\n\n" + ASK_QUESTION_SYSTEM_PROMPT
        return request.override(system_prompt=system_prompt)

    def wrap_model_call(self, request: ModelRequest, handler) -> ModelResponse:
        return handler(self.modify_request(request))

    async def awrap_model_call(self, request: ModelRequest, handler) -> ModelResponse:
        return await handler(self.modify_request(request))


__all__ = [
    "AskQuestionMiddleware",
    "ASK_QUESTION_SYSTEM_PROMPT",
    "OptionDict",
    "QuestionRequest",
    "QuestionResponse",
    "QuestionType",
]

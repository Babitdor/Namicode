"""Plan Mode Middleware for enhanced planning and question-asking capabilities.

This middleware provides:
1. Plan mode state tracking (enabled/disabled)
2. ask_question tool for both structured (multiple choice) and open-ended questions
3. System prompt injection for planning instructions when enabled
4. Complexity detection to suggest plan mode activation
5. Hard enforcement - blocking modifying tools when in plan mode

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

import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Question types
QuestionType = Literal["structured", "open_ended"]

# Tools that are BLOCKED when in plan mode
BLOCKED_TOOLS_IN_PLAN_MODE = {
    # File modifying tools
    "write_file",
    "edit_file",
    # Shell execution
    "execute_bash",
    "execute",
    # Server management
    "start_dev_server",
    "stop_server",
    # Test execution
    "run_tests",
    # Browser automation (modifies external state)
    "browser_click",
    "browser_type",
    "browser_fill_form",
    "browser_upload",
    # Git operations (modifies repo)
    "git_branch",  # create/delete branches
    "git_stash",  # push/pop stashes
}

# Tools that are ALLOWED in plan mode (read-only)
ALLOWED_TOOLS_IN_PLAN_MODE = {
    # File reading
    "read_file",
    "ls",
    "glob",
    "grep",
    # Git read operations
    "git_status",
    "git_log",
    "git_diff",
    "git_blame",
    # Web search/fetch
    "web_search",
    "duckduckgo_search",
    "docs_search",
    "fetch_url",
    "http_request",
    # Semantic search
    "semantic_search",
    "find_similar_code",
    "find_function",
    # Browser read operations
    "browser_navigate",
    "browser_screenshot",
    "browser_query",
    "browser_get_content",
    "browser_get_url",
    # Planning and questions
    "write_todos",
    "ask_question",
    "exit_plan_mode",
    "task",  # Subagent delegation
    # Code quality (read-only)
    "lint_code",
    "check_types",
    # Package info
    "package_info",
}

# Complexity detection constants
COMPLEXITY_KEYWORDS = {
    # Feature implementation keywords
    "implement",
    "create",
    "build",
    "develop",
    "add feature",
    "develop feature",
    "integrate",
    "extend",
    "new module",
    "new component",
    "architecture",
    # Refactoring keywords
    "refactor",
    "restructure",
    "reorganize",
    "rewrite",
    "migrate",
    # Multi-step keywords
    "then",
    "next",
    "after that",
    "afterwards",
    "following",
    "finally",
    "step by step",
    "first",
    "second",
    "third",
    "last",
    # Complex task indicators
    "multiple files",
    "several files",
    "across modules",
    "coordinate",
    "and then",
    "also",
    "additionally",
    "furthermore",
    # Implementation complexity
    "design",
    "structure",
    "pattern",
    "algorithm",
    "optimize",
}

STEP_INDICATORS = {" and ", ", then", " next ", " first ", " then ", " finally ", " after that "}


@dataclass
class ComplexityResult:
    """Result of complexity analysis."""

    should_plan: bool
    reason: str
    score: float  # 0.0 to 1.0
    factors: list[str]  # List of detected complexity factors


def analyze_complexity(message: str) -> ComplexityResult:
    """Analyze user message for complexity to suggest planning.

    Uses multiple heuristics:
    1. Keyword detection (implement, refactor, etc.)
    2. Step count threshold (count conjunctions)
    3. File scope analysis (detect file mentions)
    4. Task length (word count)

    Args:
        message: User's request message

    Returns:
        ComplexityResult with should_plan boolean and reason
    """
    message_lower = message.lower()
    factors = []
    score = 0.0

    # 1. Keyword detection (weight: 0.3 per keyword, max 0.6)
    matched_keywords = []
    for keyword in COMPLEXITY_KEYWORDS:
        if keyword in message_lower:
            matched_keywords.append(keyword)

    if matched_keywords:
        factors.append(f"Keywords: {', '.join(matched_keywords[:3])}")
        score += min(0.6, len(matched_keywords) * 0.2)

    # 2. Step count threshold (weight: 0.15 per step, max 0.5)
    step_count = 0
    for indicator in STEP_INDICATORS:
        step_count += message_lower.count(indicator)

    if step_count >= 2:
        factors.append(f"Multiple steps detected ({step_count} step indicators)")
        score += min(0.5, step_count * 0.15)

    # 3. File scope analysis (weight: 0.1 per file, max 0.4)
    # Match patterns like "file.py", "module.ts", "component.jsx"
    file_pattern = r"\b[\w\-]+\.(py|js|ts|jsx|tsx|go|rs|java|cpp|c|h|md|json|yaml|yml|toml)\b"
    file_mentions = re.findall(file_pattern, message, re.IGNORECASE)

    if len(file_mentions) >= 2:
        factors.append(f"Multiple files mentioned ({len(file_mentions)} files)")
        score += min(0.4, len(file_mentions) * 0.1)

    # 4. Word count (weight: 0.001 per word, max 0.3)
    word_count = len(message.split())
    if word_count >= 30:
        factors.append(f"Long request ({word_count} words)")
        score += min(0.3, word_count / 100)

    # 5. Conjunction count (weight: 0.05 per conjunction, max 0.2)
    conjunction_count = sum(1 for word in message_lower.split() if word in {"and", "or", "but"})
    if conjunction_count >= 2:
        factors.append(f"Multiple conjunctions ({conjunction_count})")
        score += min(0.2, conjunction_count * 0.05)

    # Determine if planning should be suggested
    # Lower threshold: score >= 0.25 OR multiple factors
    should_plan = score >= 0.25 or len(factors) >= 2

    reason = f"Complexity score: {score:.2f}. " + "; ".join(factors) if factors else "Task appears simple"

    return ComplexityResult(
        should_plan=should_plan,
        reason=reason,
        score=score,
        factors=factors,
    )


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

### BLOCKED TOOLS (not available in plan mode):
The following tools are BLOCKED because they modify state:
- write_file, edit_file (file modifications)
- execute_bash, execute (shell commands)
- start_dev_server, stop_server (server management)
- run_tests (test execution)
- git_branch, git_stash (git state modifications)

### ALLOWED TOOLS (read-only):
- read_file, ls, glob, grep (file operations)
- git_status, git_log, git_diff, git_blame (git read operations)
- web_search, http_request, fetch_url (information gathering)
- ask_question, write_todos, exit_plan_mode (planning tools)
- task (subagent delegation)

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
    response = interrupt(
        {
            "type": "plan_approval",
            "message": "Plan is ready for review",
        }
    )

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
    response = interrupt(
        {
            "type": "question",
            "request": question_request,
        }
    )

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
    5. Blocks modifying tools when in plan mode (hard enforcement)

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

    def wrap_tool_call(
        self,
        request,  # ToolCallRequest
        handler: Callable,
    ):
        """Wrap tool calls to block modifying tools in plan mode.

        When plan mode is enabled, this intercepts tool calls and blocks
        tools that modify state (write_file, edit_file, execute_bash, etc.).

        Args:
            request: Tool call request containing tool name and arguments
            handler: Function to execute the tool call

        Returns:
            Tool execution result or error message if blocked
        """
        # Get tool name from request
        tool_name = getattr(request, "tool", getattr(request, "name", None))
        if tool_name is None:
            # Try different attribute names
            if hasattr(request, "tool_call"):
                tool_name = getattr(request.tool_call, "name", None)
            elif hasattr(request, "args"):
                # ToolCallRequest might have different structure
                tool_name = getattr(request, "tool_name", None)

        # Get plan mode state from request
        plan_mode_enabled = False
        if hasattr(request, "state"):
            plan_mode_enabled = request.state.get("plan_mode_enabled", False)

        # Block modifying tools in plan mode
        if plan_mode_enabled and tool_name and tool_name in BLOCKED_TOOLS_IN_PLAN_MODE:
            logger.warning(f"Tool '{tool_name}' blocked in plan mode. Exit plan mode first or use ask_question to clarify.")
            from langchain_core.messages import ToolMessage
            from uuid import uuid4

            return ToolMessage(
                content=f"Tool '{tool_name}' is blocked in plan mode. "
                f"Plan mode is for planning only, not execution. "
                f"Please either:\n"
                f"1. Create a plan with write_todos and call exit_plan_mode, or\n"
                f"2. Ask a clarifying question with ask_question",
                tool_call_id=str(uuid4()),
            )

        # Tool allowed - proceed with execution
        return handler(request)

    async def awrap_tool_call(
        self,
        request,  # ToolCallRequest
        handler: Callable,
    ):
        """Async version of wrap_tool_call."""
        # Get tool name from request
        tool_name = getattr(request, "tool", getattr(request, "name", None))
        if tool_name is None:
            if hasattr(request, "tool_call"):
                tool_name = getattr(request.tool_call, "name", None)
            elif hasattr(request, "args"):
                tool_name = getattr(request, "tool_name", None)

        # Get plan mode state from request
        plan_mode_enabled = False
        if hasattr(request, "state"):
            plan_mode_enabled = request.state.get("plan_mode_enabled", False)

        # Block modifying tools in plan mode
        if plan_mode_enabled and tool_name and tool_name in BLOCKED_TOOLS_IN_PLAN_MODE:
            logger.warning(f"Tool '{tool_name}' blocked in plan mode. Exit plan mode first or use ask_question to clarify.")
            from langchain_core.messages import ToolMessage
            from uuid import uuid4

            return ToolMessage(
                content=f"Tool '{tool_name}' is blocked in plan mode. "
                f"Plan mode is for planning only, not execution. "
                f"Please either:\n"
                f"1. Create a plan with write_todos and call exit_plan_mode, or\n"
                f"2. Ask a clarifying question with ask_question",
                tool_call_id=str(uuid4()),
            )

        # Tool allowed - proceed with execution
        return await handler(request)

    # Legacy method name for backwards compatibility
    def filter_tools(
        self,
        tools: list[BaseTool],
        state: PlanModeState,
    ) -> list[BaseTool]:
        """Filter tools based on plan mode state (legacy method).

        NOTE: This method filters tools at the tool list level.
        For runtime blocking based on state, use wrap_tool_call instead.

        Args:
            tools: List of all available tools
            state: Current agent state

        Returns:
            Filtered list of tools (blocked tools removed if in plan mode)
        """
        plan_mode_enabled = state.get("plan_mode_enabled", self.enabled_by_default)

        if not plan_mode_enabled:
            return tools

        filtered_tools = []
        blocked_count = 0

        for tool in tools:
            tool_name = getattr(tool, "name", getattr(tool, "__name__", str(tool)))

            if tool_name in BLOCKED_TOOLS_IN_PLAN_MODE:
                blocked_count += 1
                logger.debug(f"Blocked tool in plan mode: {tool_name}")
            else:
                filtered_tools.append(tool)

        if blocked_count > 0:
            logger.info(f"Plan mode: blocked {blocked_count} modifying tools, {len(filtered_tools)} read-only tools available")

        return filtered_tools


__all__ = [
    "PlanModeMiddleware",
    "PlanModeState",
    "PlanModeStateUpdate",
    "QuestionRequest",
    "QuestionResponse",
    "QuestionType",
    "ComplexityResult",
    "analyze_complexity",
    "BLOCKED_TOOLS_IN_PLAN_MODE",
    "ALLOWED_TOOLS_IN_PLAN_MODE",
]

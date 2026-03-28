"""Plan Mode Middleware for structured planning with user approval.

This middleware provides:
1. Plan mode state tracking (enabled/disabled)
2. exit_plan_mode tool to submit a plan for user approval
3. System prompt injection for planning instructions when enabled
4. Complexity detection to suggest plan mode activation
5. Hard enforcement - blocking modifying tools when in plan mode

Note: The ask_question tool and its system prompt are provided by
``AskQuestionMiddleware`` (ask_question.py), which should appear earlier in the
middleware chain so the tool is registered before this middleware's blocklist runs.

State Schema:
- plan_mode_enabled: bool - Whether plan mode is currently active
- pending_question: dict | None - Question awaiting user response

Integration:
- Uses LangGraph interrupt() for the plan approval flow
- Integrates with execution.py for rendering the approval UI
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Annotated, NotRequired, TypedDict

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

from nami_deepagents.middleware.ask_question import (
    QuestionRequest,
    QuestionResponse,
    QuestionType,
)

logger = logging.getLogger(__name__)


def _is_plan_file_path(file_path: str) -> bool:
    """Return True if the path targets a plan file, which is allowed in plan mode."""
    import os

    normalized = file_path.replace("\\", "/").lower()
    basename = os.path.basename(normalized)
    return (
        ".nami/plans/" in normalized
        or normalized.endswith("plan.md")
        or basename.startswith("plan")
    )


# Tools that are BLOCKED when in plan mode
BLOCKED_TOOLS_IN_PLAN_MODE = {
    # File modifying tools
    "write_file",
    "edit_file",
    # Shell execution
    "shell",
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
2. **NO CODE CHANGES** - Do not implement any code yet
3. **PLAN FIRST** - Research the task, write a plan file, then call `exit_plan_mode`

### FILE OPERATIONS in Plan Mode:
- **BLOCKED**: `write_file` for source code, configs, or any non-plan files
- **BLOCKED**: `edit_file` (always blocked in plan mode)
- **ALLOWED**: `write_file` to create or update a plan file:
  - Preferred path: `.nami/plans/plan.md`
  - Any file whose name starts with `plan` or ends with `plan.md`
- Write your plan to `.nami/plans/plan.md` so the user can review it in their editor
- After writing the plan file, call `exit_plan_mode` to request approval

### BLOCKED TOOLS (not available in plan mode):
The following tools are BLOCKED because they modify state:
- edit_file (file modifications)
- shell, execute_bash, execute (shell commands)
- start_dev_server, stop_server (server management)
- run_tests (test execution)
- git_branch, git_stash (git state modifications)

### ALLOWED TOOLS:
- read_file, ls, glob, grep (file reading)
- write_file **only to `.nami/plans/plan.md`** (plan writing)
- git_status, git_log, git_diff, git_blame (git read operations)
- web_search, http_request, fetch_url (information gathering)
- ask_question, write_todos, exit_plan_mode (planning tools)
- task (subagent delegation)

### Your Task in Plan Mode:
1. **Analyze** the user's request thoroughly (read files, search code)
2. **Decompose** the task into clear, actionable steps
3. **Write your plan** to `.nami/plans/plan.md` using `write_file`
4. **Call `exit_plan_mode`** to submit the plan for user approval

### Plan File Format (write to .nami/plans/plan.md):
```markdown
# Plan: <short title>

## Context
<why this change is needed>

## Steps
- [ ] Step 1: ...
- [ ] Step 2: ...
- [ ] Step 3: ...

## Files to Modify
- `path/to/file.py` — what changes
```

### After Planning:
Once you write the plan file, you MUST call `exit_plan_mode` to submit
your plan for user approval. The user will review and approve before you execute.

**REMEMBER: In Plan Mode, you are a PLANNER, not an EXECUTOR.**
**ALWAYS write `.nami/plans/plan.md` and call `exit_plan_mode` when your plan is ready.**
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


class PlanModeMiddleware(AgentMiddleware):
    """Middleware for structured plan-mode with user approval.

    This middleware:
    1. Tracks plan mode state (enabled/disabled)
    2. Provides the exit_plan_mode tool to submit a plan for approval
    3. Injects planning instructions when plan mode is enabled
    4. Blocks modifying tools when in plan mode (hard enforcement)

    The ask_question tool is provided by AskQuestionMiddleware, which should
    appear earlier in the middleware chain.

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
        self._exit_plan_mode_tool = _create_exit_plan_mode_tool()

    @property
    def tools(self) -> list[BaseTool]:
        """Return tools provided by this middleware."""
        return [self._exit_plan_mode_tool]

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
        # Get tool name from request — ToolCallRequest.tool_call is a dict
        # with keys "name", "args", "id"
        tool_call = getattr(request, "tool_call", None)
        if isinstance(tool_call, dict):
            tool_name = tool_call.get("name")
        else:
            tool_name = getattr(tool_call, "name", None)

        # Get plan mode state from request
        plan_mode_enabled = False
        if hasattr(request, "state"):
            state = request.state
            if isinstance(state, dict):
                plan_mode_enabled = state.get("plan_mode_enabled", False)

        # Block modifying tools in plan mode
        if plan_mode_enabled and tool_name and tool_name in BLOCKED_TOOLS_IN_PLAN_MODE:
            # Allow write_file when writing to a plan file (.nami/plans/ or plan*.md)
            if tool_name == "write_file":
                args = tool_call.get("args", {}) if isinstance(tool_call, dict) else {}
                file_path = str(args.get("file_path", ""))
                if _is_plan_file_path(file_path):
                    return handler(request)

            logger.warning(f"Tool '{tool_name}' blocked in plan mode. Exit plan mode first or use ask_question to clarify.")
            from langchain_core.messages import ToolMessage

            return ToolMessage(
                content=f"Tool '{tool_name}' is blocked in plan mode. "
                f"Plan mode is for planning only, not execution. "
                f"Please either:\n"
                f"1. Create a plan with write_todos and call exit_plan_mode, or\n"
                f"2. Ask a clarifying question with ask_question",
                tool_call_id=tool_call.get("id", "") if isinstance(tool_call, dict) else str(getattr(tool_call, "id", "")),
            )

        # Tool allowed - proceed with execution
        return handler(request)

    async def awrap_tool_call(
        self,
        request,  # ToolCallRequest
        handler: Callable,
    ):
        """Async version of wrap_tool_call."""
        # Get tool name from request — ToolCallRequest.tool_call is a dict
        tool_call = getattr(request, "tool_call", None)
        if isinstance(tool_call, dict):
            tool_name = tool_call.get("name")
        else:
            tool_name = getattr(tool_call, "name", None)

        # Get plan mode state from request
        plan_mode_enabled = False
        if hasattr(request, "state"):
            state = request.state
            if isinstance(state, dict):
                plan_mode_enabled = state.get("plan_mode_enabled", False)

        # Block modifying tools in plan mode
        if plan_mode_enabled and tool_name and tool_name in BLOCKED_TOOLS_IN_PLAN_MODE:
            # Allow write_file when writing to a plan file (.nami/plans/ or plan*.md)
            if tool_name == "write_file":
                args = tool_call.get("args", {}) if isinstance(tool_call, dict) else {}
                file_path = str(args.get("file_path", ""))
                if _is_plan_file_path(file_path):
                    return await handler(request)

            logger.warning(f"Tool '{tool_name}' blocked in plan mode. Exit plan mode first or use ask_question to clarify.")
            from langchain_core.messages import ToolMessage

            return ToolMessage(
                content=f"Tool '{tool_name}' is blocked in plan mode. "
                f"Plan mode is for planning only, not execution. "
                f"Please either:\n"
                f"1. Create a plan with write_todos and call exit_plan_mode, or\n"
                f"2. Ask a clarifying question with ask_question",
                tool_call_id=tool_call.get("id", "") if isinstance(tool_call, dict) else str(getattr(tool_call, "id", "")),
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

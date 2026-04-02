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


class PlanModeState(AgentState):
    """State schema for plan mode middleware."""

    plan_mode_enabled: NotRequired[bool]
    """Whether plan mode is currently active.

    NOTE: Must be a plain (non-private) field so it can be read/written
    externally via agent.aget_state / agent.aupdate_state. Using PrivateStateAttr
    (OmitFromSchema) causes aupdate_state to silently drop the value.
    """

    pending_question: NotRequired[Annotated[QuestionRequest | None, PrivateStateAttr]]
    """Question currently awaiting user response."""


class PlanModeStateUpdate(TypedDict):
    """State update for plan mode middleware."""

    plan_mode_enabled: NotRequired[bool]
    pending_question: NotRequired[QuestionRequest | None]


# System prompt for plan mode (injected when enabled)
PLAN_MODE_SYSTEM_PROMPT = """
<system>
**PLAN MODE ACTIVATED**

You are now in structured planning mode. Your goal is to design a clear, executable solution
WITHOUT implementing it yet. Think deeply, explore thoroughly, then present a concrete plan
for user approval before execution begins.
</system>

<principles>
- **Be specific** - Vague plans cannot be executed well
- **Be practical** - Plans should be executable by a developer
- **Be complete** - Don't leave gaps that require guessing
- **Be realistic** - Consider actual complexity and edge cases
- **Be aware** - Understand why each step is necessary
</principles>

<workflow>
1. **Investigate** - Explore the codebase thoroughly using read-only tools
2. **Analyze** - Understand current behavior, dependencies, and implications
3. **Design** - Develop clear strategy for change
4. **Document** - Write the plan in a structured format
5. **Submit** - Call exit_plan_mode when ready for approval
</workflow>

<investigation_checklist>
Before designing, make sure you understand:
- Which files/components are involved and their current responsibilities
- How components interact (imports, data flow, function calls)
- Existing patterns, naming conventions, and architectural decisions
- Dependencies and potential breaking changes
- Test coverage and integration points
- Edge cases and error handling patterns

Ask clarifying questions if requirements are ambiguous.
</investigation_checklist>


Write a clear, structured plan.

Include:

## Goal
What we are trying to achieve.

## Context
Key findings from investigation.

## Approach
High-level strategy and reasoning.

## Steps
Numbered, actionable steps.

For each step:
- What to change
- Where to change it
- Why it’s needed

Include code snippets where helpful, but only when necessary.

## Verification
How to confirm the solution works.

## Risks
Potential issues and how to mitigate them.
<constraints>
- Do not write or modify actual project files
- Do not run commands
- Do not simulate execution
</constraints>

<quality_bar>
A good plan:
- Is specific and unambiguous
- Can be executed without guesswork
- Reflects real understanding of the codebase
- Avoids unnecessary complexity
</quality_bar>

Optionally, the plan may be written to `.nami/plans/plan.md` if the environment requires it.

<plan_structure>
## Goal - What problem are we solving?
## Analysis - Key findings from investigation
## Strategy - Overall approach and why it's best
## Implementation Steps - Numbered, specific changes
## Testing & Verification - How to confirm it works
## Risks & Mitigation - Issues and solutions
## Rollback Plan - How to safely undo if needed
</plan_structure>

<tools_available>
INVESTIGATION (read-only): read_file, ls, glob, grep, git_status, git_log, git_diff
DOCUMENTATION: write_file (.nami/plans/plan.md only), exit_plan_mode
BLOCKED: All modifications, execution, git writes
</tools_available>
"""


def _exit_plan_mode() -> str:
    """Exit plan mode and submit the plan for user approval.

    Call this tool when you have finished creating your plan.
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


def _submit_complexity_decision(
    task: str,
    should_plan: bool,
    reasoning: str,
) -> str:
    """Submit your decision on whether this task needs planning.

    You evaluate the task using YOUR own judgment, not predefined rules.
    This tool lets you decide whether to enable plan mode.

    Args:
        task: The user's task description
        should_plan: Your decision (True = enable plan mode, False = execute directly)
        reasoning: Explain your decision in your own words

    Returns:
        Confirmation of your decision
    """
    decision = "PLAN MODE ENABLED" if should_plan else "DIRECT EXECUTION"
    return f"""{decision}

Task: {task}
Reasoning: {reasoning}

You may now {'create a detailed plan' if should_plan else 'proceed with execution'}."""


def _create_exit_plan_mode_tool() -> BaseTool:
    """Create the exit_plan_mode tool."""
    return StructuredTool.from_function(
        name="exit_plan_mode",
        func=_exit_plan_mode,
        description=(
            "Exit plan mode and submit your plan for user approval. "
            "Call this after creating your plan. "
            "The user will review and approve or reject the plan."
        ),
    )


def _create_complexity_decision_tool() -> BaseTool:
    """Create the tool for agent to submit its own complexity decision."""
    return StructuredTool.from_function(
        name="decide_complexity",
        func=_submit_complexity_decision,
        description=(
            "Submit YOUR decision on whether a task needs planning mode. "
            "You decide what makes something complex - no predefined rules. "
            "Use your own judgment based on task scope, interdependencies, and risk."
        ),
    )


class PlanModeMiddleware(AgentMiddleware):
    """Middleware for structured plan-mode with agent-decided complexity.

    This middleware:
    1. Tracks plan mode state (enabled/disabled)
    2. Provides tools for plan decision-making:
       - decide_complexity: Agent decides if planning is needed (your own judgment)
       - exit_plan_mode: Submit plan for user approval
    3. Injects planning instructions when plan mode is enabled
    4. Blocks modifying tools when in plan mode (hard enforcement)

    Key difference: The agent decides what makes something complex.
    No predefined keywords or heuristics - full agent autonomy.

    The ask_question tool is provided by AskQuestionMiddleware, which should
    appear earlier in the middleware chain.

    Control Flow:
    - Agent receives user request
    - Agent calls decide_complexity with own reasoning
    - Agent enables/disables plan mode based on its judgment
    - If planning enabled: Agent creates detailed plan
    - Agent calls exit_plan_mode to submit plan for approval
    - User approves/rejects plan
    - Agent executes approved plan

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
        self._complexity_decision_tool = _create_complexity_decision_tool()
        self._exit_plan_mode_tool = _create_exit_plan_mode_tool()
        self.tools = [self._complexity_decision_tool, self._exit_plan_mode_tool]

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


__all__ = [
    "PlanModeMiddleware",
    "PlanModeState",
    "PlanModeStateUpdate",
    "QuestionRequest",
    "QuestionResponse",
    "QuestionType",
    "BLOCKED_TOOLS_IN_PLAN_MODE",
    "ALLOWED_TOOLS_IN_PLAN_MODE",
]

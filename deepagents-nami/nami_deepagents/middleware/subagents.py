"""Middleware for providing subagents to an agent via a `task` tool."""

from collections.abc import Awaitable, Callable, Sequence
from typing import Any, NotRequired, TypedDict, cast

from langchain.agents import create_agent
from langchain.agents.middleware import InterruptOnConfig
from langchain.agents.middleware.types import (
    AgentMiddleware,
    ModelRequest,
    ModelResponse,
)
from langchain.tools import BaseTool, ToolRuntime
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, ToolMessage
from langchain_core.runnables import Runnable
from langchain_core.tools import StructuredTool
from langgraph.types import Command


class SubAgent(TypedDict):
    """Specification for an agent.

    When specifying custom agents, the `default_middleware` from `SubAgentMiddleware`
    will be applied first, followed by any `middleware` specified in this spec.
    To use only custom middleware without the defaults, pass `default_middleware=[]`
    to `SubAgentMiddleware`.
    """

    name: str
    """The name of the agent."""

    description: str
    """The description of the agent."""

    system_prompt: str
    """The system prompt to use for the agent."""

    tools: Sequence[BaseTool | Callable | dict[str, Any]]
    """The tools to use for the agent."""

    model: NotRequired[str | BaseChatModel]
    """The model for the agent. Defaults to `default_model`."""

    middleware: NotRequired[list[AgentMiddleware]]
    """Additional middleware to append after `default_middleware`."""

    interrupt_on: NotRequired[dict[str, bool | InterruptOnConfig]]
    """The tool configs to use for the agent."""

    color: NotRequired[str]
    """The color for this agent's output (hex code like '#ef4444' or color name)."""


class CompiledSubAgent(TypedDict):
    """A pre-compiled agent spec."""

    name: str
    """The name of the agent."""

    description: str
    """The description of the agent."""

    runnable: Runnable
    """The Runnable to use for the agent."""

    color: NotRequired[str]
    """The color for this agent's output (hex code like '#ef4444' or color name)."""


# Global registry for subagent colors (name -> color)
_subagent_colors: dict[str, str] = {}


def get_subagent_color(name: str) -> str:
    """Get the color for a subagent by name.

    Args:
        name: The name of the subagent.

    Returns:
        The color string (hex or name). Returns gray (#888888) if not set.
    """
    return _subagent_colors.get(name, "#888888")


def set_subagent_color(name: str, color: str) -> None:
    """Set the color for a subagent.

    Args:
        name: The name of the subagent.
        color: The color string (hex code like '#ef4444' or color name).
    """
    _subagent_colors[name] = color


def get_all_subagent_colors() -> dict[str, str]:
    """Get all registered subagent colors.

    Returns:
        Dictionary mapping subagent names to their colors.
    """
    return _subagent_colors.copy()


def clear_subagent_colors() -> None:
    """Clear all registered subagent colors."""
    _subagent_colors.clear()


DEFAULT_SUBAGENT_PROMPT = "In order to complete the objective that the user asks of you, you have access to a number of standard tools."

# State keys that should be excluded when passing state to subagents
_EXCLUDED_STATE_KEYS = ("messages", "todos")

# Maximum content length for subagent response truncation
_MAX_SUBAGENT_CONTENT_LENGTH = 2000

TASK_TOOL_DESCRIPTION = """Launch an ephemeral subagent to handle complex, multi-step independent tasks with isolated context windows.

Available agent types and the tools they have access to:
{available_agents}

When using the Task tool, you must specify a subagent_type parameter to select which agent type to use.

## Usage notes:
1. Launch multiple agents concurrently whenever possible, to maximize performance; to do that, use a single message with multiple tool uses
2. When the agent is done, it will return a single message back to you. The result returned by the agent is not visible to the user. To show the user the result, you should send a text message back to the user with a concise summary of the result.
3. Each agent invocation is stateless. You will not be able to send additional messages to the agent, nor will the agent be able to communicate with you outside of its final report. Therefore, your prompt should contain a highly detailed task description for the agent to perform autonomously and you should specify exactly what information the agent should return back to you in its final and only message to you.
4. The agent's outputs should generally be trusted
5. Clearly tell the agent whether you expect it to create content, perform analysis, or just do research (search, file reads, web fetches, etc.), since it is not aware of the user's intent
6. If the agent description mentions that it should be used proactively, then you should try your best to use it without the user having to ask for it first. Use your judgement.
7. When only the general-purpose agent is provided, you should use it for all tasks. It is great for isolating context and token usage, and completing specific, complex tasks, as it has all the same capabilities as the main agent.

### Example usage of the general-purpose agent:

<example_agent_descriptions>
"general-purpose": use this agent for general purpose tasks, it has access to all tools as the main agent.
</example_agent_descriptions>

<example>
User: "I want to conduct research on the accomplishments of Lebron James, Michael Jordan, and Kobe Bryant, and then compare them."
Assistant: *Uses the task tool in parallel to conduct isolated research on each of the three players*
Assistant: *Synthesizes the results of the three isolated research tasks and responds to the User*
<commentary>
Research is a complex, multi-step task in it of itself.
The research of each individual player is not dependent on the research of the other players.
The assistant uses the task tool to break down the complex objective into three isolated tasks.
Each research task only needs to worry about context and tokens about one player, then returns synthesized information about each player as the Tool Result.
This means each research task can dive deep and spend tokens and context deeply researching each player, but the final result is synthesized information, and saves us tokens in the long run when comparing the players to each other.
</commentary>
</example>

<example>
User: "Analyze a single large code repository for security vulnerabilities and generate a report."
Assistant: *Launches a single `task` subagent for the repository analysis*
Assistant: *Receives report and integrates results into final summary*
<commentary>
Subagent is used to isolate a large, context-heavy task, even though there is only one. This prevents the main thread from being overloaded with details.
If the user then asks followup questions, we have a concise report to reference instead of the entire history of analysis and tool calls, which is good and saves us time and money.
</commentary>
</example>

<example>
User: "Schedule two meetings for me and prepare agendas for each."
Assistant: *Calls the task tool in parallel to launch two `task` subagents (one per meeting) to prepare agendas*
Assistant: *Returns final schedules and agendas*
<commentary>
Tasks are simple individually, but subagents help silo agenda preparation.
Each subagent only needs to worry about the agenda for one meeting.
</commentary>
</example>

<example>
User: "I want to order a pizza from Dominos, order a burger from McDonald's, and order a salad from Subway."
Assistant: *Calls tools directly in parallel to order a pizza from Dominos, a burger from McDonald's, and a salad from Subway*
<commentary>
The assistant did not use the task tool because the objective is super simple and clear and only requires a few trivial tool calls.
It is better to just complete the task directly and NOT use the `task`tool.
</commentary>
</example>

### Example usage with custom agents:

<example_agent_descriptions>
"content-reviewer": use this agent after you are done creating significant content or documents
"greeting-responder": use this agent when to respond to user greetings with a friendly joke
"research-analyst": use this agent to conduct thorough research on complex topics
</example_agent_description>

<example>
user: "Please write a function that checks if a number is prime"
assistant: Sure let me write a function that checks if a number is prime
assistant: First let me use the Write tool to write a function that checks if a number is prime
assistant: I'm going to use the Write tool to write the following code:
<code>
function isPrime(n) {{
  if (n <= 1) return false
  for (let i = 2; i * i <= n; i++) {{
    if (n % i === 0) return false
  }}
  return true
}}
</code>
<commentary>
Since significant content was created and the task was completed, now use the content-reviewer agent to review the work
</commentary>
assistant: Now let me use the content-reviewer agent to review the code
assistant: Uses the Task tool to launch with the content-reviewer agent
</example>

<example>
user: "Can you help me research the environmental impact of different renewable energy sources and create a comprehensive report?"
<commentary>
This is a complex research task that would benefit from using the research-analyst agent to conduct thorough analysis
</commentary>
assistant: I'll help you research the environmental impact of renewable energy sources. Let me use the research-analyst agent to conduct comprehensive research on this topic.
assistant: Uses the Task tool to launch with the research-analyst agent, providing detailed instructions about what research to conduct and what format the report should take
</example>

<example>
user: "Hello"
<commentary>
Since the user is greeting, use the greeting-responder agent to respond with a friendly joke
</commentary>
assistant: "I'm going to use the Task tool to launch with the greeting-responder agent"
</example>"""  # noqa: E501

TASK_SYSTEM_PROMPT = """## `task` (subagent spawner)

You have access to a `task` tool to launch short-lived subagents that handle isolated tasks. These agents are ephemeral — they live only for the duration of the task and return a single result.

**Default stance: lean toward delegation.** If a task has 3+ steps, involves multiple files, or matches a specialist agent's domain, delegate it rather than doing it inline. The cost of spawning a subagent is low; chaining dozens of intermediate tool calls in the main thread is expensive and degrades response quality.

When to use the task tool (strongly prefer these):
- **Codebase exploration**: Any research task requiring 3+ searches or 3+ file reads — use a subagent instead of chaining glob/grep/read yourself
- **Complex multi-step work**: Bug diagnosis, feature implementation, test writing, security audit — anything with 5+ steps
- **Parallel independent tasks**: Two or more tasks that don't share state — spawn them simultaneously
- **Context isolation**: Research that would flood the main thread with intermediate results
- **Specialist work**: When a named specialist agent covers the domain exactly

Subagent lifecycle:
1. **Spawn** → Provide clear role, complete context, and exact expected output format
2. **Run** → The subagent completes the task autonomously
3. **Return** → The subagent provides a single structured result
4. **Reconcile** → You integrate the result and synthesize the final response

When NOT to use the task tool:
- The task is completable in 1–2 tool calls (simple lookup, reading one file, one-line fix)
- You already have all needed context in the current conversation
- Steps are sequentially dependent and can't be parallelized

## Critical parallelism rule
**Whenever you have independent steps — always spawn them in parallel.** This is non-negotiable. Parallel subagents complete in the same wall time as one, saving the user significant time.

Correct: spawn all independent subagents in a single `task` batch call.
Wrong: spawn one, wait for it, spawn the next.

Subagents are highly capable and will produce thorough, well-structured results. Trust them with complex work."""  # noqa: E501


DEFAULT_GENERAL_PURPOSE_DESCRIPTION = "General-purpose agent for researching complex questions, searching for files and content, and executing multi-step tasks. When you are searching for a keyword or file and are not confident that you will find the right match in the first few tries use this agent to perform the search for you. This agent has access to all tools as the main agent."  # noqa: E501

# Read-only exploration agent
EXPLORE_AGENT_PROMPT = """You are a read-only code exploration agent. Your role is to investigate, analyze, and explain code without making any changes.

## Your Capabilities (Read-Only)
- `read_file` - Read file contents with pagination
- `ls` / `glob` / `grep` - Find and search files
- `git_status` / `git_log` / `git_diff` / `git_blame` - Version control inspection
- `web_search` / `fetch_url` / `docs_search` - Web research
- `ask_question` - Clarify requirements

## Your Limitations (STRICT)
You CANNOT use: `write_file`, `edit_file`, `shell`, `execute`, `start_dev_server`, `stop_server`, `run_tests`, `git_branch`, `git_stash`, or any tool that modifies files or system state.

## Your Workflow
1. **Understand the goal**: What does the user want to know?
2. **Explore systematically**: Start broad, then narrow
3. **Read relevant files**: Use pagination for large files
4. **Trace connections**: Follow imports and dependencies
5. **Provide clear findings**: Explain what you found with evidence

## Output Guidelines
- Be thorough but focused
- Use code blocks for file paths, function signatures, snippets
- Include line numbers when referencing code
- Summarize key findings at the end
"""

EXPLORE_AGENT_TOOLS = [
    "read_file",
    "ls",
    "glob",
    "grep",
    "git_status",
    "git_log",
    "git_diff",
    "git_blame",
    "web_search",
    "fetch_url",
    "docs_search",
    "package_info",
]

EXPLORE_AGENT_DESCRIPTION = "Read-only exploration agent for researching codebases, understanding architecture, and analyzing code. Cannot modify files or execute shell commands."

# Read-only planning agent
PLAN_AGENT_PROMPT = """You are a read-only planning agent. Your role is to analyze requirements, investigate the codebase, and create detailed implementation plans without making any changes.

## Your Mission
1. Understand what the user wants to accomplish
2. Investigate relevant parts of the codebase
3. Create a detailed, actionable plan
4. Output the plan clearly

## Your Capabilities (Read-Only)
- `read_file` - Read file contents with pagination
- `ls` / `glob` / `grep` - Find and search files
- `git_status` / `git_log` / `git_diff` - Version control
- `web_search` / `fetch_url` / `docs_search` - Research
- `ask_question` - Clarify requirements

## Your Limitations (STRICT)
You CANNOT use: `write_file`, `edit_file`, `shell`, `execute`, `run_tests`, or any tool that changes system state.

## Plan Format
```markdown
# Plan: [Task Title]

## Context
[Problem explanation and why this change is needed]

## Approach
[Chosen strategy and tradeoffs]

## Implementation Steps
### 1. [Action] — `path/to/file.py`
**What:** [Specific change]
**Why:** [Reason]
**How:**
- [sub-step a]
- [sub-step b]

## Files Changed
| File | Change | Notes |

## Verification
- [ ] [How to verify]

## Risks & Rollback
- [Risk] — mitigation: [How to avoid/recover]
```

## Quality Standards
- Every step names specific files and line numbers
- Code sketches show before AND after
- Verification has runnable commands
"""

PLAN_AGENT_TOOLS = [
    "read_file",
    "ls",
    "glob",
    "grep",
    "git_status",
    "git_log",
    "git_diff",
    "git_blame",
    "web_search",
    "fetch_url",
    "docs_search",
    "package_info",
    "ask_question",
]

PLAN_AGENT_DESCRIPTION = "Read-only planning agent for analyzing requirements and creating implementation plans. Cannot modify files or execute commands."

# Verification agent - can write temp scripts but not modify project files
VERIFICATION_AGENT_PROMPT = """You are a verification agent. Your role is to verify implementations by writing and running tests, including temporary/ephemeral scripts.

## Your Workflow
1. **Understand what to verify**: What was implemented? What should it do?
2. **Create verification tests**: Write temporary test scripts
3. **Run tests**: Execute your verification scripts
4. **Report results**: Clear pass/fail with evidence

## Your Capabilities
### Execution
- `shell` / `execute` - Run shell commands and test scripts
- `run_tests` - Run the project's test suite

### Code Quality
- `lint_code` - Lint verification scripts
- `check_types` - Type-check verification scripts

### Inspection (Read-Only)
- `read_file` - Read project files and temp scripts
- `ls` / `glob` / `grep` - Find files
- `git_status` / `git_diff` - Check changes
- `package_info` - Inspect dependencies

## Your Restrictions
1. **NEVER modify existing project files** - Only create temporary scripts
2. **Temp scripts go in `/tmp/`, `.test_files/`, or similar ephemeral locations**
3. **Clean up after yourself** - Remove temp scripts when done

## Verification Patterns

### Unit Test
```bash
cat > /tmp/test_feature.py << 'EOF'
import pytest
from project.module import function_under_test

def test_feature_success():
    assert function_under_test(valid_input) == expected_output
EOF
python -m pytest /tmp/test_feature.py -v
```

### Output Format
```
## Verification Results
### Test: [Name]
- **Status**: PASS / FAIL
- **Evidence**: [Output/error]
- **Location**: [Temp file if applicable]

### Summary
- Total: X | Passed: Y | Failed: Z
```
"""

VERIFICATION_AGENT_TOOLS = [
    "shell",
    "run_tests",
    "lint_code",
    "check_types",
    "read_file",
    "ls",
    "glob",
    "grep",
    "git_status",
    "git_diff",
    "package_info",
    "ask_question",
]

VERIFICATION_AGENT_DESCRIPTION = "Verification and testing agent. Can write temporary scripts and run tests to verify implementation. Cannot modify existing project files."


def _get_subagents(
    *,
    default_model: str | BaseChatModel,
    default_tools: Sequence[BaseTool | Callable | dict[str, Any]],
    default_middleware: list[AgentMiddleware] | None,
    _default_interrupt_on: (
        dict[str, bool | InterruptOnConfig] | None
    ),  # Deprecated: subagents auto-approve
    subagents: list[SubAgent | CompiledSubAgent],
    general_purpose_agent: bool,
    explore_agent: bool = True,
    plan_agent: bool = True,
    verification_agent: bool = True,
) -> tuple[dict[str, Any], list[str]]:
    """Create subagent instances from specifications.

    Args:
        default_model: Default model for subagents that don't specify one.
        default_tools: Default tools for subagents that don't specify tools.
        default_middleware: Middleware to apply to all subagents. If `None`,
            no default middleware is applied.
        _default_interrupt_on: Deprecated - subagents always auto-approve. Kept for API compatibility.
        subagents: List of agent specifications or pre-compiled agents.
        general_purpose_agent: Whether to include a general-purpose subagent.
        explore_agent: Whether to include a read-only exploration agent.
        plan_agent: Whether to include a read-only planning agent.
        verification_agent: Whether to include a verification/testing agent.

    Returns:
        Tuple of (agent_dict, description_list) where agent_dict maps agent names
        to runnable instances and description_list contains formatted descriptions.
    """
    # Use empty list if None (no default middleware)
    default_subagent_middleware = default_middleware or []

    agents: dict[str, Any] = {}
    subagent_descriptions = []

    # Helper to filter tools by name
    def _filter_tools(tool_names: list[str]) -> list:
        name_set = set(tool_names)
        return [t for t in default_tools if getattr(t, "name", None) in name_set]

    # Create general-purpose agent if enabled
    # NOTE: Subagents never have HITL middleware - they auto-approve all operations
    # The main agent handles user approvals; subagents execute autonomously
    if general_purpose_agent:
        general_purpose_subagent = create_agent(
            default_model,
            system_prompt=DEFAULT_SUBAGENT_PROMPT,
            tools=list(default_tools),
            middleware=[*default_subagent_middleware],  # No HITL for subagents
        )
        agents["general-purpose"] = general_purpose_subagent
        subagent_descriptions.append(
            f"- general-purpose: {DEFAULT_GENERAL_PURPOSE_DESCRIPTION}"
        )
        # Register default color for general-purpose agent
        set_subagent_color("general-purpose", "#30c3f0")  # Default cyan/blue

    # Create explore agent if enabled
    if explore_agent:
        explore_subagent = create_agent(
            default_model,
            system_prompt=EXPLORE_AGENT_PROMPT,
            tools=_filter_tools(EXPLORE_AGENT_TOOLS),
            middleware=[*default_subagent_middleware],
        )
        agents["explore"] = explore_subagent
        subagent_descriptions.append(f"- explore: {EXPLORE_AGENT_DESCRIPTION}")
        set_subagent_color("explore", "#10b981")  # Green

    # Create plan agent if enabled
    if plan_agent:
        plan_subagent = create_agent(
            default_model,
            system_prompt=PLAN_AGENT_PROMPT,
            tools=_filter_tools(PLAN_AGENT_TOOLS),
            middleware=[*default_subagent_middleware],
        )
        agents["plan"] = plan_subagent
        subagent_descriptions.append(f"- plan: {PLAN_AGENT_DESCRIPTION}")
        set_subagent_color("plan", "#8b5cf6")  # Purple

    # Create verification agent if enabled
    if verification_agent:
        verification_subagent = create_agent(
            default_model,
            system_prompt=VERIFICATION_AGENT_PROMPT,
            tools=_filter_tools(VERIFICATION_AGENT_TOOLS),
            middleware=[*default_subagent_middleware],
        )
        agents["verification"] = verification_subagent
        subagent_descriptions.append(
            f"- verification: {VERIFICATION_AGENT_DESCRIPTION}"
        )
        set_subagent_color("verification", "#f59e0b")  # Amber

    # Process custom subagents
    for agent_ in subagents:
        subagent_descriptions.append(f"- {agent_['name']}: {agent_['description']}")
        # Register color if provided
        if "color" in agent_:
            set_subagent_color(agent_["name"], agent_["color"])
        if "runnable" in agent_:
            custom_agent = cast("CompiledSubAgent", agent_)
            agents[custom_agent["name"]] = custom_agent["runnable"]
            continue
        _tools = agent_.get("tools", list(default_tools))

        subagent_model = agent_.get("model", default_model)

        # NOTE: Subagents never have HITL middleware - they auto-approve all operations
        _middleware = (
            [*default_subagent_middleware, *agent_["middleware"]]
            if "middleware" in agent_
            else [*default_subagent_middleware]
        )
        # interrupt_on config is ignored for subagents - they always auto-approve

        agents[agent_["name"]] = create_agent(
            subagent_model,
            system_prompt=agent_["system_prompt"],
            tools=_tools,
            middleware=_middleware,
        )
    return agents, subagent_descriptions


def _create_task_tool(
    *,
    default_model: str | BaseChatModel,
    default_tools: Sequence[BaseTool | Callable | dict[str, Any]],
    default_middleware: list[AgentMiddleware] | None,
    default_interrupt_on: (
        dict[str, bool | InterruptOnConfig] | None
    ),  # Deprecated: subagents auto-approve
    subagents: list[SubAgent | CompiledSubAgent],
    general_purpose_agent: bool,
    explore_agent: bool = True,
    plan_agent: bool = True,
    verification_agent: bool = True,
    task_description: str | None = None,
) -> BaseTool:
    """Create a task tool for invoking subagents.

    Args:
        default_model: Default model for subagents.
        default_tools: Default tools for subagents.
        default_middleware: Middleware to apply to all subagents.
        default_interrupt_on: Deprecated - subagents always auto-approve. Kept for API compatibility.
        subagents: List of subagent specifications.
        general_purpose_agent: Whether to include general-purpose agent.
        explore_agent: Whether to include a read-only exploration agent.
        plan_agent: Whether to include a read-only planning agent.
        verification_agent: Whether to include a verification/testing agent.
        task_description: Custom description for the task tool. If `None`,
            uses default template. Supports `{available_agents}` placeholder.

    Returns:
        A StructuredTool that can invoke subagents by type.
    """
    subagent_graphs, subagent_descriptions = _get_subagents(
        default_model=default_model,
        default_tools=default_tools,
        default_middleware=default_middleware,
        _default_interrupt_on=default_interrupt_on,  # Deprecated: subagents auto-approve
        subagents=subagents,
        general_purpose_agent=general_purpose_agent,
        explore_agent=explore_agent,
        plan_agent=plan_agent,
        verification_agent=verification_agent,
    )
    subagent_description_str = "\n".join(subagent_descriptions)

    def _return_command_with_state_update(result: dict, tool_call_id: str) -> Command:
        """Return a Command with state update and ToolMessage from subagent result.

        Handles edge cases:
        - Empty messages list
        - Last message not being AIMessage (could be ToolMessage)
        - AIMessage with empty text (reasoning-only, tool-calls-only)
        - Missing messages key

        Args:
            result: The subagent result dict containing messages and state.
            tool_call_id: The tool call ID for the ToolMessage.

        Returns:
            Command with state update and ToolMessage.
        """
        state_update = {
            k: v for k, v in result.items() if k not in _EXCLUDED_STATE_KEYS
        }

        # Extract messages safely
        messages = result.get("messages", [])

        # Find the last AIMessage (not ToolMessage, HumanMessage, etc.)
        # The subagent should end with an AIMessage containing its final response
        last_ai_message = None
        for msg in reversed(messages):
            if hasattr(msg, "type") and msg.type == "ai":
                last_ai_message = msg
                break

        if last_ai_message is not None:
            # Extract text from AIMessage
            # .text property concatenates all text blocks, ignoring reasoning/tool blocks
            text_content = last_ai_message.text

            # If text is empty but content_blocks exist, try to extract from them
            # This handles cases like reasoning-only responses or empty content
            if not text_content and hasattr(last_ai_message, "content_blocks"):
                text_parts = [
                    block.get("text", "")
                    for block in last_ai_message.content_blocks
                    if block.get("type") == "text"
                ]
                text_content = " ".join(text_parts)

            # If still empty, check for tool_calls as a fallback indicator
            if not text_content:
                # Check if there were tool calls but no text response
                if (
                    hasattr(last_ai_message, "tool_calls")
                    and last_ai_message.tool_calls
                ):
                    text_content = (
                        "[Subagent made tool calls but provided no text response]"
                    )
                else:
                    text_content = "[Subagent returned empty response]"
        elif messages:
            # Fallback: use last message if no AIMessage found
            # This could happen if subagent ended with a ToolMessage
            last_message = messages[-1]
            if hasattr(last_message, "type") and last_message.type == "tool":
                # Last message is a ToolMessage - extract its content
                text_content = getattr(last_message, "content", str(last_message))
                # Only use if content is meaningful
                if isinstance(text_content, str) and text_content:
                    text_content = text_content[:1000]  # Truncate large tool results
                else:
                    text_content = "[Subagent completed but returned no summary]"
            else:
                # Try to get text from any message type
                text_content = getattr(last_message, "text", str(last_message))
                if not text_content or text_content == str(last_message):
                    text_content = "[Subagent completed but returned no summary]"
        else:
            # No messages at all - return error message
            text_content = "[Subagent completed but returned no response]"

        return Command(
            update={
                **state_update,
                "messages": [ToolMessage(text_content, tool_call_id=tool_call_id)],
            }
        )

    def _validate_and_prepare_state(
        subagent_type: str, description: str, runtime: ToolRuntime
    ) -> tuple[Runnable, dict]:
        """Prepare state for invocation."""
        subagent = subagent_graphs[subagent_type]
        # Create a new state dict to avoid mutating the original
        subagent_state = {
            k: v for k, v in runtime.state.items() if k not in _EXCLUDED_STATE_KEYS
        }
        subagent_state["messages"] = [HumanMessage(content=description)]
        return subagent, subagent_state

    # Use custom description if provided, otherwise use default template
    if task_description is None:
        task_description = TASK_TOOL_DESCRIPTION.format(
            available_agents=subagent_description_str
        )
    elif "{available_agents}" in task_description:
        # If custom description has placeholder, format with agent descriptions
        task_description = task_description.format(
            available_agents=subagent_description_str
        )

    def task(
        description: str,
        subagent_type: str,
        runtime: ToolRuntime,
    ) -> str | Command:
        if subagent_type not in subagent_graphs:
            allowed_types = ", ".join([f"`{k}`" for k in subagent_graphs])
            return f"We cannot invoke subagent {subagent_type} because it does not exist, the only allowed types are {allowed_types}"
        subagent, subagent_state = _validate_and_prepare_state(
            subagent_type, description, runtime
        )
        result = subagent.invoke(subagent_state)
        if not runtime.tool_call_id:
            value_error_msg = "Tool call ID is required for subagent invocation"
            raise ValueError(value_error_msg)
        return _return_command_with_state_update(result, runtime.tool_call_id)

    async def atask(
        description: str,
        subagent_type: str,
        runtime: ToolRuntime,
    ) -> str | Command:
        if subagent_type not in subagent_graphs:
            allowed_types = ", ".join([f"`{k}`" for k in subagent_graphs])
            return f"We cannot invoke subagent {subagent_type} because it does not exist, the only allowed types are {allowed_types}"
        subagent, subagent_state = _validate_and_prepare_state(
            subagent_type, description, runtime
        )
        result = await subagent.ainvoke(subagent_state)
        if not runtime.tool_call_id:
            value_error_msg = "Tool call ID is required for subagent invocation"
            raise ValueError(value_error_msg)
        return _return_command_with_state_update(result, runtime.tool_call_id)

    return StructuredTool.from_function(
        name="task",
        func=task,
        coroutine=atask,
        description=task_description,
        tags=["nami:subagent"],
    )


class SubAgentMiddleware(AgentMiddleware):
    """Middleware for providing subagents to an agent via a `task` tool.

    This  middleware adds a `task` tool to the agent that can be used to invoke subagents.
    Subagents are useful for handling complex tasks that require multiple steps, or tasks
    that require a lot of context to resolve.

    A chief benefit of subagents is that they can handle multi-step tasks, and then return
    a clean, concise response to the main agent.

    Subagents are also great for different domains of expertise that require a narrower
    subset of tools and focus.

    This middleware comes with a default general-purpose subagent that can be used to
    handle the same tasks as the main agent, but with isolated context.

    Built-in specialized agents:
    - `explore`: Read-only exploration agent for researching codebases
    - `plan`: Read-only planning agent for creating implementation plans
    - `verification`: Testing agent that can write temp scripts but not modify project files

    Args:
        default_model: The model to use for subagents.
            Can be a LanguageModelLike or a dict for init_chat_model.
        default_tools: The tools to use for the default general-purpose subagent.
        default_middleware: Default middleware to apply to all subagents. If `None` (default),
            no default middleware is applied. Pass a list to specify custom middleware.
        default_interrupt_on: The tool configs to use for the default general-purpose subagent. These
            are also the fallback for any subagents that don't specify their own tool configs.
        subagents: A list of additional subagents to provide to the agent.
        system_prompt: Full system prompt override. When provided, completely replaces
            the agent's system prompt.
        general_purpose_agent: Whether to include the general-purpose agent. Defaults to `True`.
        explore_agent: Whether to include a read-only exploration agent. Defaults to `False`.
        plan_agent: Whether to include a read-only planning agent. Defaults to `False`.
        verification_agent: Whether to include a verification/testing agent. Defaults to `False`.
        task_description: Custom description for the task tool. If `None`, uses the
            default description template.

    Example:
        ```python
        from langchain.agents.middleware.subagents import SubAgentMiddleware
        from langchain.agents import create_agent

        # Basic usage with defaults (no default middleware)
        agent = create_agent(
            "openai:gpt-4o",
            middleware=[
                SubAgentMiddleware(
                    default_model="openai:gpt-4o",
                    subagents=[],
                )
            ],
        )

        # Add custom middleware to subagents
        agent = create_agent(
            "openai:gpt-4o",
            middleware=[
                SubAgentMiddleware(
                    default_model="openai:gpt-4o",
                    default_middleware=[TodoListMiddleware()],
                    subagents=[],
                )
            ],
        )

        # Enable built-in specialized agents
        agent = create_agent(
            "openai:gpt-4o",
            middleware=[
                SubAgentMiddleware(
                    default_model="openai:gpt-4o",
                    explore_agent=True,
                    plan_agent=True,
                    verification_agent=True,
                )
            ],
        )
        ```
    """

    def __init__(
        self,
        *,
        default_model: str | BaseChatModel,
        default_tools: Sequence[BaseTool | Callable | dict[str, Any]] | None = None,
        default_middleware: list[AgentMiddleware] | None = None,
        default_interrupt_on: dict[str, bool | InterruptOnConfig] | None = None,
        subagents: list[SubAgent | CompiledSubAgent] | None = None,
        system_prompt: str | None = TASK_SYSTEM_PROMPT,
        general_purpose_agent: bool = True,
        explore_agent: bool = True,
        plan_agent: bool = True,
        verification_agent: bool = True,
        task_description: str | None = None,
    ) -> None:
        """Initialize the SubAgentMiddleware."""
        super().__init__()
        self.system_prompt = system_prompt
        task_tool = _create_task_tool(
            default_model=default_model,
            default_tools=default_tools or [],
            default_middleware=default_middleware,
            default_interrupt_on=default_interrupt_on,
            subagents=subagents or [],
            general_purpose_agent=general_purpose_agent,
            explore_agent=explore_agent,
            plan_agent=plan_agent,
            verification_agent=verification_agent,
            task_description=task_description,
        )
        self.tools = [task_tool]

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        """Update the system prompt to include instructions on using subagents."""
        if self.system_prompt is not None:
            system_prompt = (
                request.system_prompt + "\n\n" + self.system_prompt
                if request.system_prompt
                else self.system_prompt
            )
            return handler(request.override(system_prompt=system_prompt))
        return handler(request)

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        """(async) Update the system prompt to include instructions on using subagents."""
        if self.system_prompt is not None:
            system_prompt = (
                request.system_prompt + "\n\n" + self.system_prompt
                if request.system_prompt
                else self.system_prompt
            )
            return await handler(request.override(system_prompt=system_prompt))  # type: ignore
        return await handler(request)

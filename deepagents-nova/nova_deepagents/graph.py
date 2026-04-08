"""Nova_deepagents come with planning, filesystem, and subagents."""

from collections.abc import Callable, Sequence
from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import (
    HumanInTheLoopMiddleware,
    InterruptOnConfig,
)
from langchain.agents.middleware import ContextEditingMiddleware, ClearToolUsesEdit
from langchain.agents.middleware import ModelRetryMiddleware, ToolRetryMiddleware
from langgraph.errors import GraphInterrupt
from langchain.agents.middleware.summarization import SummarizationMiddleware
from langchain.agents.middleware.types import AgentMiddleware
from langchain.agents.structured_output import ResponseFormat
from langchain.chat_models import init_chat_model
from langchain_anthropic import ChatAnthropic
from langchain_anthropic.middleware import AnthropicPromptCachingMiddleware
from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool
from langgraph.cache.base import BaseCache
from langgraph.graph.state import CompiledStateGraph
from langgraph.store.base import BaseStore
from langgraph.types import Checkpointer
from pathlib import Path
from nova_deepagents.backends import StateBackend
from nova_deepagents.backends.protocol import BackendFactory, BackendProtocol
from nova_deepagents.middleware.filesystem import FilesystemMiddleware
from nova_deepagents.middleware.memory import MemoryMiddleware
from nova_deepagents.middleware.patch_tool_calls import PatchToolCallsMiddleware
from nova_deepagents.middleware.skills import SkillsMiddleware
from nova_deepagents.middleware.ask_question import AskQuestionMiddleware
from nova_deepagents.middleware.planning import PlanModeMiddleware
from nova_deepagents.middleware.skills import SkillsMiddleware
from nova_deepagents.middleware.subagents import (
    CompiledSubAgent,
    SubAgent,
    SubAgentMiddleware,
)
from nova_deepagents.middleware.shared_memory import SharedMemoryMiddleware
from nova_deepagents.middleware.todo import TodoListMiddleware
from nova_deepagents.middleware.async_subagents import AsyncSubAgent, AsyncSubAgentMiddleware

BASE_AGENT_PROMPT = """You are Nova, an AI assistant that helps users accomplish tasks using tools. You respond with text and tool calls. The user can see your responses and tool outputs in real time.

## Core Behavior

- Be concise and direct. Don't over-explain unless asked.
- NEVER add unnecessary preamble (\"Sure!\", \"Great question!\", \"I'll now...\").
- Don't say \"I'll now do X\" — just do it.
- If the request is ambiguous, ask questions before acting.
- If asked how to approach something, explain first, then act.

## Professional Objectivity

- Prioritize accuracy over validating the user's beliefs
- Disagree respectfully when the user is incorrect
- Avoid unnecessary superlatives, praise, or emotional validation

## Doing Tasks

When the user asks you to do something:

1. **Understand first** — read relevant files, check existing patterns. Quick but thorough — gather enough evidence to start, then iterate.
2. **Act** — implement the solution. Work quickly but accurately.
3. **Verify** — check your work against what was asked, not against your own output. Your first attempt is rarely correct — iterate.

Keep working until the task is fully complete. Don't stop partway and explain what you would do — just do it. Only yield back to the user when the task is done or you're genuinely blocked.

**When things go wrong:**
- If something fails repeatedly, stop and analyze *why* — don't keep retrying the same approach.
- If you're blocked, tell the user what's wrong and ask for guidance.

## Progress Updates

For longer tasks, provide brief progress updates at reasonable intervals — a concise sentence recapping what you've done and what's next."""  # noqa: E501
"""Default system prompt appended to every Deep Agent.

When a caller passes `system_prompt` to `create_deep_agent`, the custom prompt
is prepended and this base prompt is appended. When `system_prompt` is `None`,
this is used as the sole system prompt.
"""


def _reraise_graph_interrupt(exc: Exception) -> str:
    """Re-raise GraphInterrupt so LangGraph handles it; format other exceptions as strings."""
    if isinstance(exc, GraphInterrupt):
        raise exc
    return f"Tool failed with {type(exc).__name__}: {exc}"


def get_default_model() -> ChatAnthropic:
    """Get the default model for deep agents.

    Returns:
        `ChatAnthropic` instance configured with Claude Sonnet 4.5.
    """
    return ChatAnthropic(
        model_name="claude-sonnet-4-5-20250929",
        max_tokens=200000,  # type: ignore
    )


def create_deep_agent(
    model: str | BaseChatModel | None = None,
    tools: Sequence[BaseTool | Callable | dict[str, Any]] | None = None,
    *,
    system_prompt: str | None = None,
    middleware: Sequence[AgentMiddleware] = (),
    subagents: list[SubAgent | CompiledSubAgent | AsyncSubAgent] | None = None,
    skills: list[str] | None = None,
    memory: list[str] | None = None,
    response_format: ResponseFormat | None = None,
    context_schema: type[Any] | None = None,
    checkpointer: Checkpointer | None = None,
    store: BaseStore | None = None,
    backend: BackendProtocol | BackendFactory | None = None,
    interrupt_on: dict[str, bool | InterruptOnConfig] | None = None,
    debug: bool = False,
    name: str | None = None,
    cache: BaseCache | None = None,
) -> CompiledStateGraph:
    """Create a deep agent.

    This agent will by default have access to a tool to write todos (`write_todos`),
    seven file and execution tools: `ls`, `read_file`, `write_file`, `edit_file`, `glob`, `grep`, `execute`,
    and a tool to call subagents.

    The `execute` tool allows running shell commands if the backend implements `SandboxBackendProtocol`.
    For non-sandbox backends, the `execute` tool will return an error message.

    Args:
        model: The model to use. Defaults to `claude-sonnet-4-5-20250929`.
        tools: The tools the agent should have access to.
        system_prompt: The additional instructions the agent should have. Will go in
            the system prompt.
        middleware: Additional middleware to apply after standard middleware.
        subagents: The subagents to use.

            Each subagent should be a `dict` with the following keys:

            - `name`
            - `description` (used by the main agent to decide whether to call the sub agent)
            - `prompt` (used as the system prompt in the subagent)
            - (optional) `tools`
            - (optional) `model` (either a `LanguageModelLike` instance or `dict` settings)
            - (optional) `middleware` (list of `AgentMiddleware`)
        skills: Optional list of skill source paths (e.g., `["/skills/user/", "/skills/project/"]`).

            Paths must be specified using POSIX conventions (forward slashes) and are relative
            to the backend's root. When using `StateBackend` (default), provide skill files via
            `invoke(files={...})`. With `FilesystemBackend`, skills are loaded from disk relative
            to the backend's `root_dir`. Later sources override earlier ones for skills with the
            same name (last one wins).
        memory: Optional list of memory file paths (`AGENTS.md` files) to load
            (e.g., `["/memory/AGENTS.md"]`). Display names are automatically derived from paths.
            Memory is loaded at agent startup and added into the system prompt.
        response_format: A structured output response format to use for the agent.
        context_schema: The schema of the deep agent.
        checkpointer: Optional `Checkpointer` for persisting agent state between runs.
        store: Optional store for persistent storage (required if backend uses `StoreBackend`).
        backend: Optional backend for file storage and execution.

            Pass either a `Backend` instance or a callable factory like `lambda rt: StateBackend(rt)`.
            For execution support, use a backend that implements `SandboxBackendProtocol`.
        interrupt_on: Mapping of tool names to interrupt configs.
        debug: Whether to enable debug mode. Passed through to `create_agent`.
        name: The name of the agent. Passed through to `create_agent`.
        cache: The cache to use for the agent. Passed through to `create_agent`.

    Returns:
        A configured deep agent.
    """
    if model is None:
        model = get_default_model()
    elif isinstance(model, str):
        model = init_chat_model(model)

    if (
        model.profile is not None
        and isinstance(model.profile, dict)
        and "max_input_tokens" in model.profile
        and isinstance(model.profile["max_input_tokens"], int)
    ):
        trigger = ("fraction", 0.85)
        keep = ("fraction", 0.25)
        trim_tokens_to_summarize: int | None = int(
            model.profile["max_input_tokens"] * 0.70
        )
    else:
        trigger = ("tokens", 40000)
        keep = ("tokens", 12000)
        trim_tokens_to_summarize = 35000

    # Build middleware stack for subagents (includes skills if provided)
    # Note: SharedMemoryMiddleware is added to enable cross-agent memory sharing
    # between main agent and subagents. All subagents use author_id="subagent"
    # for attribution (main agent uses "main-agent").
    # Note: TodoListMiddleware is added individually for each subagent with their specific name
    # in SubAgentMiddleware._get_subagents() to show unique agent names in todo lists.
    subagent_middleware: list[AgentMiddleware] = [
        SharedMemoryMiddleware(author_id="subagent"),
    ]

    backend = backend if backend is not None else (lambda rt: StateBackend(rt))

    if memory is not None:
        subagent_middleware.append(MemoryMiddleware(backend=backend, sources=memory))
    if skills is not None:
        subagent_middleware.append(SkillsMiddleware(backend=backend, sources=skills))
    subagent_middleware.extend(
        [
            FilesystemMiddleware(backend=backend),
            ToolRetryMiddleware(
                max_retries=2,
                backoff_factor=2.0,
                initial_delay=1.0,
                retry_on=lambda e: not isinstance(e, GraphInterrupt),
                on_failure=_reraise_graph_interrupt,
            ),
            ContextEditingMiddleware(edits=[ClearToolUsesEdit(trigger=60000, keep=5)]),
            ModelRetryMiddleware(max_retries=3, backoff_factor=2.0, initial_delay=1.0),
            SummarizationMiddleware(
                model=model,
                trigger=trigger,
                keep=keep,
                trim_tokens_to_summarize=trim_tokens_to_summarize,
            ),
            AnthropicPromptCachingMiddleware(unsupported_model_behavior="ignore"),
            PatchToolCallsMiddleware(),
        ]
    )

    # Separate inline subagents from async subagents
    # AsyncSubAgent entries are identified by their async-subagent fields (graph_id)
    # and are routed into AsyncSubAgentMiddleware instead of SubAgentMiddleware
    inline_subagents: list[SubAgent | CompiledSubAgent] = []
    async_subagents: list[AsyncSubAgent] = []
    for spec in subagents or []:
        if "graph_id" in spec:
            # Then spec is an AsyncSubAgent
            async_subagents.append(spec)  # type: ignore[arg-type]
        else:
            # SubAgent or CompiledSubAgent - use as-is
            inline_subagents.append(spec)  # type: ignore[arg-type]

    # Build main agent middleware stack
    # Use the provided name for the agent's todo list, or default to "Deep Agent"
    agent_display_name = name if name else "Deep Agent"
    deepagent_middleware: list[AgentMiddleware] = [
        TodoListMiddleware(agent_name=agent_display_name), # type: ignore
    ]
    if memory is not None:
        deepagent_middleware.append(MemoryMiddleware(backend=backend, sources=memory))
    if skills is not None:
        deepagent_middleware.append(SkillsMiddleware(backend=backend, sources=skills))
    deepagent_middleware.extend(
        [
            FilesystemMiddleware(backend=backend),
            AskQuestionMiddleware(),
            PlanModeMiddleware(enabled_by_default=False),
            ToolRetryMiddleware(
                max_retries=2,
                backoff_factor=2.0,
                initial_delay=1.0,
                retry_on=lambda e: not isinstance(e, GraphInterrupt),
                on_failure=_reraise_graph_interrupt,
            ),
            SubAgentMiddleware(
                default_model=model,
                default_tools=tools,
                subagents=inline_subagents,
                default_middleware=subagent_middleware,
                default_interrupt_on=interrupt_on,
                general_purpose_agent=True,
            ),
            ContextEditingMiddleware(edits=[ClearToolUsesEdit(trigger=60000, keep=5)]),
            ModelRetryMiddleware(max_retries=3, backoff_factor=2.0, initial_delay=1.0),
            SummarizationMiddleware(
                model=model,
                trigger=trigger,
                keep=keep,
                trim_tokens_to_summarize=trim_tokens_to_summarize,
            ),
            AnthropicPromptCachingMiddleware(unsupported_model_behavior="ignore"),
            PatchToolCallsMiddleware(),
        ]
    )

    if async_subagents:
        # Async here means that we run these subagents in a non-blocking manner.
        # Currently this supports agents deployed via LangSmith deployments.
        deepagent_middleware.append(AsyncSubAgentMiddleware(async_subagents=async_subagents))
    if middleware:
        deepagent_middleware.extend(middleware)
    if interrupt_on is not None:
        deepagent_middleware.append(HumanInTheLoopMiddleware(interrupt_on=interrupt_on))

    return create_agent(
        model,
        system_prompt=(
            system_prompt + "\n\n" + BASE_AGENT_PROMPT
            if system_prompt
            else BASE_AGENT_PROMPT
        ),
        tools=tools,
        middleware=deepagent_middleware,
        response_format=response_format,
        context_schema=context_schema,
        checkpointer=checkpointer,
        store=store,
        debug=debug,
        name=name,
        cache=cache,
    ).with_config({"recursion_limit": 1000})

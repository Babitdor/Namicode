import os
from pathlib import Path

from nami_deepagents import create_deep_agent
from nami_deepagents.backends import CompositeBackend
from nami_deepagents.backends.filesystem import FilesystemBackend
from nami_deepagents.backends.sandbox import SandboxBackendProtocol
from langgraph.store.memory import InMemoryStore
from langchain.tools import BaseTool
from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.pregel import Pregel
from namicode_cli.shell import ShellMiddleware
from nami_deepagents.middleware import SkillsMiddleware, MemoryMiddleware
import os
from namicode_cli.config.config import (
    config,
)
from namicode_cli.agents.core_agent import _add_interrupt_on
from namicode_cli.shell import ShellMiddleware
from namicode_cli.mcp import get_shared_mcp_middleware
from namicode_cli.memory.shared_memory import SharedMemoryMiddleware
from namicode_cli.tracking.file_tracker import (
    FileTrackerMiddleware,
    get_session_tracker,
)
from namicode_cli.tracking.tracing import (
    is_tracing_enabled,
    get_tracing_config,
)
from namicode_cli.config.config import Settings


def create_subagent(
    agent_name: str,
    model: str | BaseChatModel,
    tools: list[BaseTool],
    *,
    sandbox: SandboxBackendProtocol | None = None,
    sandbox_type: str | None = None,
    auto_approve: bool = False,
    settings: Settings,
    checkpointer: InMemorySaver | None = None,
    store: InMemoryStore | None = None,
) -> tuple[Pregel, CompositeBackend]:
    """Create and configure an agent with the specified model and tools.

    Args:
        agent_name: Name of the agent to create
        model: LLM model to use
        tools: Additional tools to provide to agent
        backend: Optional composite backend for execution
        settings: Settings object for configuration
        store: Optional InMemoryStore. If None and use_shared_store is True,
               uses the module-level shared store from agent.py.
        use_shared_store: If True and store is None, use the shared store.
               Set to False to create an isolated store.

    Returns:
        2-tuple of (graph, backend)
    """
    skill_sources = []
    memory_sources = []
    agent_location = settings.find_agent(agent_name=agent_name)

    if not agent_location:
        return f"Error: Agent '{agent_name}' not found."  # type: ignore

    agent_dir, scope = agent_location
    agent_md_path = agent_dir / "agent.md"

    try:
        system_prompt = agent_md_path.read_text(encoding="utf-8")
    except Exception as e:
        return f"Error reading agent configuration: {e}"  # type: ignore

    # NAMI.md Project memory
    project_memory = settings.get_project_agent_md_paths()
    memory_sources.append(str(project_memory))

    # Setup tracing if LangSmith is configured
    tracing_enabled = False
    if is_tracing_enabled():
        tracing_enabled = True
        tracing_config = get_tracing_config()
        # console.print(
        #     f"[dim]LangSmith tracing enabled: {tracing_config.project_name}[/dim]"
        # )
    else:
        # Try to auto-configure from environment
        from namicode_cli.tracking.tracing import auto_configure

        config_result = auto_configure()
        if config_result.is_configured():
            tracing_enabled = True
            # console.print(
            #     f"[dim]LangSmith tracing enabled: {config_result.project_name}[/dim]"
            # )

    # Wrap model for OpenAI tracing if enabled and model is a ChatOpenAI instance
    wrapped_model = model
    if tracing_enabled and hasattr(model, "_model"):  # Check if it's a LangChain model
        try:
            from langchain_openai import ChatOpenAI

            if isinstance(model, ChatOpenAI):
                from namicode_cli.tracking.tracing import (
                    wrap_openai_client as _wrap_openai,
                )

                wrapped_model = _wrap_openai(model)
        except ImportError:
            pass

    # Skills directory - global (shared across all agents at ~/.nami/skills/)
    skills_dir = settings.ensure_user_skills_dir()
    skill_sources.append(str(skills_dir))
    # Project-level skills directories (if in a project)
    # Supports both .claude/skills/ and .nami/skills/
    project_skills_dirs = settings.get_project_skills_dirs()
    skill_sources.append(str(project_skills_dirs))
    # Use shared MCP middleware to avoid reconnecting for each subagent
    mcp_middleware = get_shared_mcp_middleware()

    # CONDITIONAL SETUP: Local vs Remote Sandbox
    if sandbox is None:
        # ========== LOCAL MODE ==========
        # Backend: Local filesystem for code (no virtual routes)
        backend = FilesystemBackend()  # Current working directory

    else:
        # ========== REMOTE SANDBOX MODE ==========
        # Backend: Remote sandbox for code (no /memories/ route needed with filesystem-based memory)
        backend = sandbox
        # Middleware: FileTrackerMiddleware, AgentMemoryMiddleware, SkillsMiddleware, MCPMiddleware, SharedMemoryMiddleware, ShellToolMiddleware
        # FileTrackerMiddleware MUST be first to track all file operations and enforce read-before-edit

    # Middleware: FileTrackerMiddleware, AgentMemoryMiddleware, SkillsMiddleware, MCPMiddleware, SharedMemoryMiddleware, ShellToolMiddleware
    # FileTrackerMiddleware uses shared session tracker so subagents inherit file read state from main agent
    subagent_middleware = [
        FileTrackerMiddleware(
            enforce_read_before_edit=True,
            truncate_results=True,
            include_system_prompt=True,
            tracker=get_session_tracker(),  # Share tracker with main agent
        ),
        MemoryMiddleware(backend=FilesystemBackend(), sources=memory_sources),
        SkillsMiddleware(backend=FilesystemBackend(), sources=skill_sources),
        mcp_middleware,
        SharedMemoryMiddleware(author_id=f"subagent:{agent_name}"),
        ShellMiddleware(
            workspace_root=str(Path.cwd()),
            env=dict(os.environ),
        ),
    ]

    enhanced_prompt = f"""{system_prompt}

---

## Subagent Context

You are being invoked as a subagent ('{agent_name}') to handle a specific task.
Your response will be returned to the main assistant.

Guidelines:
- Focus on the specific task at hand
- Provide clear, actionable responses
- Keep your response concise but comprehensive
- You have FULL access to all tools: filesystem (read, write, edit, glob, grep), shell commands, web search, HTTP requests, dev servers, and test runner
- You have access to the SAME skills as the main agent - check the Skills System section below for available skills
- If a skill is relevant to your task, read the SKILL.md file for detailed instructions
- Return a synthesized summary rather than raw data
- Do NOT ask for confirmation - execute tools directly

### Shared Memory
You have access to shared memory tools (write_memory, read_memory, list_memories) that persist across all agents.
Use these to share findings with the main agent or read context from previous conversations.
Your writes will be attributed as 'subagent:{agent_name}'."""

    composite_backend = CompositeBackend(
        default=backend,
        routes={},
    )
    final_checkpointer = checkpointer if checkpointer is not None else InMemorySaver()

    if auto_approve:
        # No interrupts - all tools run automatically
        interrupt_on = {}
    else:
        # Full HITL for destructive operations
        interrupt_on = _add_interrupt_on()

    subagent = create_deep_agent(
        name=agent_name,
        model=wrapped_model,
        system_prompt=enhanced_prompt,
        tools=tools,
        checkpointer=final_checkpointer,
        backend=composite_backend,  # type: ignore
        middleware=subagent_middleware,
        store=store,
        interrupt_on=interrupt_on,  # type: ignore
    ).with_config(
        config  # type: ignore
    )

    return subagent, composite_backend

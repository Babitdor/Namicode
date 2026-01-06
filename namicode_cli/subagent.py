import os
from pathlib import Path

from nami_deepagents import create_deep_agent
from nami_deepagents.backends import CompositeBackend
from nami_deepagents.backends.filesystem import FilesystemBackend
from langgraph.store.memory import InMemoryStore
from langchain.tools import BaseTool
from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.pregel import Pregel
from namicode_cli.shell import ShellMiddleware
from namicode_cli.skills.middleware import SkillsMiddleware
import os
from namicode_cli.agent_memory import AgentMemoryMiddleware
from namicode_cli.config import (
    config,
    console,
)
from namicode_cli.agent import _add_interrupt_on
from namicode_cli.shell import ShellMiddleware
from namicode_cli.skills import SkillsMiddleware
from namicode_cli.mcp import MCPMiddleware
from namicode_cli.tracing import (
    is_tracing_enabled,
    get_tracing_config,
)
from namicode_cli.config import Settings


def create_subagent(
    agent_name: str,
    model: str | BaseChatModel,
    tools: list[BaseTool],
    backend: CompositeBackend | None = None,
    *,
    settings: Settings,
) -> tuple[Pregel, CompositeBackend]:
    """Create and configure an agent with the specified model and tools.

    Args:
        agent_name: Name of the agent to create
        model: LLM model to use
        tools: Additional tools to provide to agent
        backend: Optional composite backend for execution
        settings: Settings object for configuration

    Returns:
        2-tuple of (graph, backend)
    """
    agent_location = settings.find_agent(agent_name=agent_name)

    if not agent_location:
        return f"Error: Agent '{agent_name}' not found."  # type: ignore

    agent_dir, scope = agent_location
    agent_md_path = agent_dir / "agent.md"

    try:
        system_prompt = agent_md_path.read_text(encoding="utf-8")
    except Exception as e:
        return f"Error reading agent configuration: {e}"  # type: ignore

    # Setup MemoryStore for agent conversations
    subagent_store = InMemoryStore()

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
        from namicode_cli.tracing import auto_configure

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
                from namicode_cli.tracing import wrap_openai_client as _wrap_openai

                wrapped_model = _wrap_openai(model)
        except ImportError:
            pass

    # Skills directory - global (shared across all agents at ~/.nami/skills/)
    skills_dir = settings.ensure_user_skills_dir()

    # Project-level skills directories (if in a project)
    # Supports both .claude/skills/ and .nami/skills/
    project_skills_dirs = settings.get_project_skills_dirs()

    # Create MCP middleware once (shared across modes for cleanup)
    mcp_middleware = MCPMiddleware()

    # CONDITIONAL SETUP: Local vs Remote Sandbox
    if backend is None:
        # ========== LOCAL MODE ==========
        # Backend: Local filesystem for code (no virtual routes)
        subagent_backend = CompositeBackend(
            default=FilesystemBackend(),  # Current working directory
            routes={},  # No virtualization - use real paths
        )
    else:
        subagent_backend = backend

    # Middleware: AgentMemoryMiddleware, SkillsMiddleware, MCPMiddleware, ShellToolMiddleware
    subagent_middleware = [
        AgentMemoryMiddleware(settings=settings, assistant_id=agent_name),
        SkillsMiddleware(
            skills_dir=skills_dir,
            assistant_id=agent_name,
            project_skills_dirs=project_skills_dirs,
        ),
        mcp_middleware,
        ShellMiddleware(
            workspace_root=str(Path.cwd()),
            env=dict(os.environ),
        ),
        # FIX 4: Add AgentMemoryMiddleware if needed
        # AgentMemoryMiddleware()  # Uncomment if this middleware is needed
    ]

    enhanced_prompt = f"""{system_prompt}

---

## Subagent Context

You are being invoked as an isolated subagent to handle a specific task.
Your response will be returned to the main assistant.

Guidelines:
- Focus on the specific task at hand
- Provide clear, actionable responses
- Keep your response concise but comprehensive
- You have FULL access to all tools: filesystem (read, write, edit, glob, grep), shell commands, web search, HTTP requests, dev servers, and test runner
- You have access to the SAME skills as the main agent - check the Skills System section below for available skills
- If a skill is relevant to your task, read the SKILL.md file for detailed instructions
- Return a synthesized summary rather than raw data
- Do NOT ask for confirmation - execute tools directly"""

    interrupt_on = _add_interrupt_on()

    subagent = create_deep_agent(
        model=wrapped_model,
        system_prompt=enhanced_prompt,
        tools=tools,
        checkpointer=InMemorySaver(),
        backend=subagent_backend,  # type: ignore
        middleware=subagent_middleware,
        store=subagent_store,
        interrupt_on=interrupt_on,  # type: ignore
    ).with_config(
        config  # type: ignore
    )

    return subagent, subagent_backend

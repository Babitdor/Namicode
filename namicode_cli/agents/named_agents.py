from langchain.tools import BaseTool
from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.pregel import Pregel
from langgraph.store.memory import InMemoryStore
from nami_deepagents.backends import CompositeBackend
from nami_deepagents.backends.filesystem import FilesystemBackend
from nami_deepagents.backends.sandbox import SandboxBackendProtocol

from namicode_cli.config.config import Settings


# ── Legacy single-agent path (kept for compatibility / sandbox use) ─────────

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
    """Create a single subagent on demand.

    Named agents are now dispatched via the main agent's task tool
    (SubAgentMiddleware). This function is kept for legacy/sandbox use cases
    where a standalone subagent graph is needed outside that flow.
    """
    from namicode_cli.agents.core_agent import create_agent_with_config

    agent_location = settings.find_agent(agent_name=agent_name)
    if not agent_location:
        return f"Error: Agent '{agent_name}' not found."  # type: ignore

    agent_dir, _scope = agent_location
    try:
        system_prompt = (agent_dir / "agent.md").read_text(encoding="utf-8")
    except Exception as e:
        return f"Error reading agent configuration: {e}"  # type: ignore

    backend: SandboxBackendProtocol | FilesystemBackend
    if sandbox is None:
        backend = FilesystemBackend()
    else:
        backend = sandbox

    composite_backend = CompositeBackend(default=backend, routes={})

    agent, _ = create_agent_with_config(
        model,
        agent_name,
        tools,
        sandbox=sandbox,
        sandbox_type=sandbox_type,
        system_prompt=system_prompt,
        auto_approve=auto_approve,
        store=store,
        checkpointer=checkpointer or InMemorySaver(),
    )

    return agent, composite_backend

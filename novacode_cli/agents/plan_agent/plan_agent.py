"""Plan-mode agent factory.

Creates an agent with PlanModeMiddleware (blocks write/execute tools outside
.nova/plans/ until exit_plan_mode is approved) and the plan_agent.jinja system
prompt that enforces the clarify → investigate → write plan → exit_plan_mode workflow.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool
from langgraph.pregel import Pregel

from langchain.agents.middleware import ModelRetryMiddleware

from novacode_cli.agents.plan_agent.plan_mode_middleware import PlanModeMiddleware
from novacode_cli.bootstrap.steering import SteeringMiddleware
from novacode_cli.config.plan_mode import (
    BLOCKED_TOOLS_DISPLAY,
    RESTRICTED_WRITE_TOOLS_DISPLAY,
)
from novacode_cli.hitl.interrupts import get_interrupt_configs
from novacode_cli.config.config import settings
from novacode_cli.prompts import render_template

# Type imports
from langgraph.checkpoint.memory import InMemorySaver
from deepagents.backends import CompositeBackend
from deepagents.backends.filesystem import FilesystemBackend
from deepagents.backends.protocol import BackendProtocol, SandboxBackendProtocol

__all__ = ["create_plan_agent_with_config", "get_plan_agent_system_prompt"]


def get_plan_agent_system_prompt(
    sandbox_type: str | None = None,
) -> str:
    """Get the system prompt for the plan-mode agent.

    Args:
        sandbox_type: Type of sandbox provider ("modal", "runloop", "daytona").
                     If None, agent is operating in local mode.

    Returns:
        The system prompt string for plan mode
    """

    if sandbox_type:
        from novacode_cli.integrations.sandbox_factory import get_default_working_dir

        working_dir = get_default_working_dir(sandbox_type)
    else:
        # In local mode with virtual_mode=True, the FilesystemBackend maps
        # virtual paths (starting with /) to the workspace root directory.
        # The LLM must use virtual paths like /file.txt, not Windows absolute
        # paths like B:\path\file.txt, because FilesystemMiddleware.validate_path
        # rejects Windows paths.
        working_dir = "/"

    return render_template(
        "plan_agent.jinja",
        working_dir=working_dir,
        blocked_tools=BLOCKED_TOOLS_DISPLAY,
        restricted_write_tools=RESTRICTED_WRITE_TOOLS_DISPLAY,
    )


def create_plan_agent_with_config(
    model: str | BaseChatModel,
    assistant_id: str,
    tools: list[BaseTool],
    *,
    sandbox: SandboxBackendProtocol | None = None,
    sandbox_type: str | None = None,
    system_prompt: str | None = None,
    auto_approve: bool = False,
    steering_instructions: list | None = None,
    checkpointer: Any = None,
    store: Any = None,
) -> tuple[Pregel, CompositeBackend]:
    """Create and configure a plan-mode agent with the specified model and tools.

    This creates an agent optimized for complex tasks that benefit from
    structured planning before execution. The agent includes:

    - AskQuestionMiddleware: For asking structured questions
    - PlanModeMiddleware: For plan creation and approval workflow
    - SkillsMiddleware: For loading skills from user/project directories

    Args:
        model: LLM model to use
        assistant_id: Agent identifier for memory storage
        tools: Additional tools to provide to agent
        sandbox: Optional sandbox backend for remote execution.
        sandbox_type: Type of sandbox provider ("modal", "runloop", "daytona")
        system_prompt: Optional custom system prompt
        auto_approve: If True, skip human-in-the-loop approvals
        checkpointer: Conversation checkpointer to share with the core agent so
            plan mode SEES the prior conversation (and persists across restarts).
            When None, a private in-memory checkpointer is used (no continuity).
        store: Durable KV store to share with the core agent (memory/learning).

    Returns:
        2-tuple of (graph, backend)
    """
    # Lazy import for tracing (speeds up startup)
    from novacode_cli.tracking.tracing import is_tracing_enabled, get_tracing_config

    tracing_enabled = False

    if is_tracing_enabled():
        tracing_enabled = True
        get_tracing_config()  # side-effect: registers config
    else:
        # Try to auto-configure from environment
        from novacode_cli.tracking.tracing import auto_configure

        config_result = auto_configure()
        if config_result.is_configured():
            tracing_enabled = True

    # Wrap model for OpenAI tracing if enabled and model is a ChatOpenAI instance
    wrapped_model = model
    if tracing_enabled and hasattr(model, "_model"):
        try:
            from langchain_openai import ChatOpenAI

            if isinstance(model, ChatOpenAI):
                from novacode_cli.tracking.tracing import (
                    wrap_openai_client as _wrap_openai,
                )

                wrapped_model = _wrap_openai(model)
        except ImportError:
            pass

    # Determine workspace root for path containment
    workspace_root = settings.project_root or Path.cwd()

    # Skills directory - global (shared across all agents at ~/.nova/skills/)
    skills_dir = settings.ensure_user_skills_dir()
    # Project-level skills directories (if in a project)
    project_skills_dirs = settings.get_project_skills_dirs()

    # Build skill sources using virtual path prefixes that match CompositeBackend routes.
    skill_sources: list[str] = ["/skills/"]
    for i, _p in enumerate(project_skills_dirs):
        skill_sources.append(f"/project-skills-{i}/")

    # CONDITIONAL SETUP: Local vs Remote Sandbox
    if sandbox is None:
        # ========== LOCAL MODE ==========
        # Backend: Local filesystem for code with virtual path semantics.
        # virtual_mode=True maps virtual paths (starting with /) to the workspace root,
        # and rejects Windows absolute paths (B:\...) and path traversal (..).
        _default_backend = FilesystemBackend(
            root_dir=str(workspace_root),
            virtual_mode=True,
        )

    else:
        # ========== REMOTE SANDBOX MODE ==========
        # Backend: Remote sandbox for code execution
        _default_backend = sandbox

    # ------------------------------------------------------------------
    # Build CompositeBackend with routes per deepagents 0.5.6 docs:
    # https://docs.langchain.com/oss/python/deepagents/backends#compositebackend-router
    #
    # SkillsMiddleware receives the same backend as create_deep_agent
    # and calls backend.ls(source_path) for each source. When source_path
    # is "/skills/", CompositeBackend routes it to the FilesystemBackend
    # rooted at ~/.nova/skills/.
    # ------------------------------------------------------------------

    _skills_backend = FilesystemBackend(
        root_dir=str(skills_dir),
        virtual_mode=True,
    )

    _routes: dict[str, BackendProtocol] = {  # type: ignore[name-defined]
        "/skills/": _skills_backend,
    }

    # Add project-level skills routes (each gets its own FilesystemBackend)
    for i, proj_skills_dir in enumerate(project_skills_dirs):
        _proj_backend = FilesystemBackend(
            root_dir=str(proj_skills_dir),
            virtual_mode=True,
        )
        _routes[f"/project-skills-{i}/"] = _proj_backend

    # Add /memories/ route for agent directory (~/.nova/<agent>/).
    # Per deepagents docs, /memories/ is the canonical route for persistent
    # agent memory. This allows the agent's read_file tool to access
    # memory files (Nova.md, CLAUDE.md) via virtual paths like
    # /memories/Nova.md. AgentMemoryMiddleware reads these files directly
    # from the filesystem at startup, but the /memories/ route enables
    # the agent to re-read them during execution.
    agent_dir = settings.get_agent_dir(assistant_id)
    if agent_dir:
        _agent_backend = FilesystemBackend(
            root_dir=str(agent_dir),
            virtual_mode=True,
        )
        _routes["/memories/"] = _agent_backend

    # Add /.nova/plans/ route for plan files.
    # This allows the plan agent to write and read plan files via virtual paths
    # like /.nova/plans/plan-refactor.md. The FilesystemBackend maps these
    # to {workspace_root}/.nova/plans/ on disk.
    _plans_dir = workspace_root / ".nova" / "plans"
    _plans_dir.mkdir(parents=True, exist_ok=True)
    _plans_backend = FilesystemBackend(
        root_dir=str(_plans_dir),
        virtual_mode=True,
    )
    _routes["/.nova/plans/"] = _plans_backend

    # Add /project-memory/ route for project-level memory files.
    # This allows the plan agent to read project memory (NOVA.md, CLAUDE.md)
    # via virtual paths like /project-memory/NOVA.md.
    _project_nova_dir = workspace_root / ".nova"
    _project_nova_dir.mkdir(parents=True, exist_ok=True)
    _project_memory_backend = FilesystemBackend(
        root_dir=str(_project_nova_dir),
        virtual_mode=True,
    )
    _routes["/project-memory/"] = _project_memory_backend

    composite_backend = CompositeBackend(
        default=_default_backend,
        routes=_routes,
    )

    # Get the system prompt (sandbox-aware)
    if system_prompt is None:
        system_prompt = get_plan_agent_system_prompt(sandbox_type=sandbox_type)

    if auto_approve:
        interrupt_on = {}
    else:
        interrupt_on = get_interrupt_configs()

    # Import create_deep_agent here to avoid circular imports
    from deepagents.graph import create_deep_agent

    # Share the core agent's checkpointer + thread so plan mode continues from
    # the existing conversation (with the core agent OR a prior plan turn) and
    # survives restarts. Fall back to a private in-memory saver only when no
    # shared checkpointer is provided (e.g. standalone/tests).
    plan_checkpointer = checkpointer if checkpointer is not None else InMemorySaver()

    agent = create_deep_agent(
        name=assistant_id,
        model=wrapped_model,
        skills=skill_sources,
        system_prompt=system_prompt,
        tools=tools,
        checkpointer=plan_checkpointer,
        backend=composite_backend,
        store=store,
        interrupt_on=interrupt_on,  # type: ignore
        subagents=[],  # Plan agents don't use subagents by default
        middleware=[
            # Retry transient model failures (rate limits / 429, timeouts,
            # network blips) with exponential backoff before erroring out.
            ModelRetryMiddleware(
                max_retries=3,
                backoff_factor=2.0,
                initial_delay=1.0,
            ),
            PlanModeMiddleware(workspace_root=workspace_root),
            # Keep the SHARED session list reference even when empty — using
            # `or []` would swap in a fresh list and break live steering, since
            # the list is usually empty at plan-agent creation time.
            SteeringMiddleware(
                instructions=(
                    steering_instructions if steering_instructions is not None else []
                )
            ),
        ],
    )

    return agent, composite_backend

"""Agent management and creation for the CLI.

This module handles the creation, configuration, and management of LangGraph
deep agents for the Nova-Code CLI. It provides:

- Agent creation with custom system prompts and tool configurations
- Management of agent profiles (global and project-specific)
- Integration with middleware components (memory, skills, MCP, shell)
- Support for multiple backends (local filesystem and sandboxes)
- Agent memory management and persistence

Key Components:
- create_agent_with_config(): Create a fully configured deep agent
- list_agents(): Display available agent profiles
- reset_agent(): Reset an agent to default configuration
- Agent profiles stored in ~/.Nova/agents/<name>/agent.md

The agent is built using LangGraph's Pregel architecture with:
- Planning capability via write_todos tool
- Subagent delegation via task tool
- File system access via CompositeBackend
- Middleware for memory, skills, MCP, and shell execution
- Checkpointing for conversation state persistence
"""

import os
import shutil
import time
from pathlib import Path

from langchain.agents.middleware import (
    InterruptOnConfig,
)
from langchain.agents.middleware.types import AgentState
from langchain.messages import ToolCall
from langchain.tools import BaseTool
from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.pregel import Pregel
from langgraph.runtime import Runtime
from langgraph.store.memory import InMemoryStore
from nova_deepagents import create_deep_agent
from nova_deepagents.backends import CompositeBackend
from nova_deepagents.backends.filesystem import FilesystemBackend
from nova_deepagents.backends.sandbox import SandboxBackendProtocol
from nova_deepagents.middleware.subagents import SubAgent

from novacode_cli.agents.default_subagents.subagents import retrieve_core_subagents
from novacode_cli.agents.default_subagents.async_subagents import retrieve_async_subagents
from novacode_cli.config.config import (
    COLORS,
    config,
    console,
    get_default_coding_instructions,
    parse_agent_color,
    set_agent_color,
    settings,
)
from novacode_cli.integrations.sandbox_factory import get_default_working_dir
from novacode_cli.prompts import render_template

# Lazy imports for heavy dependencies (imported inside functions to speed up startup)
# - novacode_cli.mcp (MCP middleware)
# - novacode_cli.memory.agent_memory (Memory middleware)
# - novacode_cli.shell (Shell middleware)
# - novacode_cli.tracking.file_tracker (File tracker)
# - novacode_cli.tracking.tool_limits_middleware (Tool limits)
# - novacode_cli.tracking.tracing (Tracing)

# Module-level shared store for agent/subagent memory sharing
_shared_store: InMemoryStore | None = None
_store_lock_initialized = False


def get_shared_store() -> InMemoryStore:
    """Get or create the shared InMemoryStore for agent/subagent communication.

    Returns:
        Shared InMemoryStore instance
    """
    global _shared_store, _store_lock_initialized
    if _shared_store is None:
        _shared_store = InMemoryStore()
        _store_lock_initialized = True
    return _shared_store


def reset_shared_store() -> None:
    """Reset the shared store, shared memory, file tracker, and tool limits (useful for new sessions)."""
    global _shared_store, _store_lock_initialized
    _shared_store = None
    _store_lock_initialized = False
    # Also reset the shared memory store
    from nova_deepagents.middleware.shared_memory import reset_shared_memory_store
    reset_shared_memory_store()
    # Also reset the file tracker for the new session
    from novacode_cli.tracking.file_tracker import reset_session_tracker
    reset_session_tracker()
    # Also reset the tool limits circuit breaker
    from novacode_cli.tracking.tool_limits_middleware import reset_tool_limits
    reset_tool_limits()


def _extract_agent_description(agent_md_content: str) -> str:
    """Extract a description from agent.md content.

    Looks for the first substantial line of content (ignoring headers and blank lines).

    Args:
        agent_md_content: The content of the agent.md file

    Returns:
        A brief description extracted from the file, or a default message
    """
    lines = agent_md_content.strip().split("\n")

    for line in lines[:10]:  # Check first 10 lines
        line = line.strip()
        # Skip empty lines, headers, and very short lines
        if line and not line.startswith("#") and len(line) > 30:
            # Truncate if too long
            if len(line) > 150:
                return line[:147] + "..."
            return line

    # Fallback: return a generic description
    return "Agent with custom system prompt and tools"


# Cache for named subagents with TTL to avoid repeated filesystem reads
_named_subagents_cache: dict[str, tuple[float, list[SubAgent]]] = {}
_NAMED_SUBAGENTS_CACHE_TTL = 60.0  # seconds


def build_named_subagents(
    assistant_id: str,
    tools: list[BaseTool],
) -> list[SubAgent]:
    """Build SubAgent specifications from all available named agents.

    Reads all agents from both global (~/.Nova/agents/) and project (.Nova/agents/)
    directories, excluding the current main agent, and converts them into SubAgent
    specifications that can be passed to SubAgentMiddleware.

    Uses a cache with TTL to avoid repeated filesystem reads on agent restarts.

    Args:
        assistant_id: The name of the current main agent (to exclude from subagents)
        tools: The list of tools to provide to each subagent

    Returns:
        List of SubAgent specifications ready for SubAgentMiddleware
    """
    from novacode_cli.config.config import settings

    # Check cache first
    now = time.time()
    cache_key = assistant_id
    if cache_key in _named_subagents_cache:
        cached_time, cached_value = _named_subagents_cache[cache_key]
        if now - cached_time < _NAMED_SUBAGENTS_CACHE_TTL:
            return cached_value

    subagents: list[SubAgent] = []
    all_agents = settings.get_all_agents()

    for agent_name, agent_dir, scope in all_agents:
        # Skip the current main agent
        if agent_name == assistant_id:
            continue

        agent_md_path = agent_dir / "agent.md"

        # Skip if agent.md doesn't exist
        if not agent_md_path.exists():
            console.print(
                f"[dim yellow]Warning: Skipping agent '{agent_name}' - no agent.md file[/dim yellow]"
            )
            continue

        try:
            system_prompt = agent_md_path.read_text(encoding="utf-8")
        except Exception as e:
            console.print(
                f"[dim yellow]Warning: Could not read agent.md for '{agent_name}': {e}[/dim yellow]"
            )
            continue

        # Extract description from the agent.md content
        description = _extract_agent_description(system_prompt)

        # Parse and register agent color from YAML frontmatter
        agent_color = parse_agent_color(agent_md_path)
        if agent_color:
            set_agent_color(agent_name, agent_color)

        # Create SubAgent specification
        subagent: SubAgent = {
            "name": agent_name,
            "description": f"[{scope}] {description}",
            "system_prompt": system_prompt,
            "tools": tools,  # Same tools as main agent
            # model and middleware will use defaults from SubAgentMiddleware
        }

        # Add color to subagent if available
        if agent_color:
            subagent["color"] = agent_color  # type: ignore

        subagents.append(subagent)

    # Cache the result
    _named_subagents_cache[cache_key] = (now, subagents)

    return subagents


def list_agents() -> None:
    """List all available agents with detailed information."""
    agents = settings.get_all_agents()

    if not agents:
        console.print(
            f"\n[bold {COLORS['primary']}]📋 Available Agents[/bold {COLORS['primary']}]\n"
        )
        console.print("[yellow]No agents found.[/yellow]")
        console.print(
            "[dim]Agents will be created in ~/.Nova/agents/ when you first use them.[/dim]",
            style=COLORS["dim"],
        )
        return

    console.print(
        f"\n[bold {COLORS['primary']}]📋 Available Agents[/bold {COLORS['primary']}]\n"
    )

    for agent_name, agent_path, scope in sorted(agents, key=lambda x: (x[2], x[0])):
        # Display scope badge
        scope_badge = "🌐" if scope == "global" else "📁"
        scope_color = COLORS["accent"] if scope == "global" else COLORS["success"]

        # Agent name with icon and scope
        console.print(
            f"  {scope_badge} [bold {COLORS['primary']}]{agent_name}[/bold {COLORS['primary']}] "
            f"[dim]([{scope_color}]{scope}[/{scope_color}])[/dim]"
        )

        # Agent path
        relative_path = (
            agent_path.relative_to(Path.home())
            if agent_path.is_relative_to(Path.home())
            else agent_path
        )
        console.print(f"    [dim]Path: ~/{relative_path}[/dim]")

        # Check for agent.md existence and show summary
        agent_md = agent_path / "agent.md"
        if agent_md.exists():
            content = agent_md.read_text(encoding="utf-8")
            # Extract first line or first sentence as description
            lines = content.strip().split("\n")
            desc = ""
            for line in lines[:3]:  # Check first 3 lines
                line = line.strip()
                if line and not line.startswith("#") and len(line) > 20:
                    desc = line[:80] + "..." if len(line) > 80 else line
                    break
            if desc:
                console.print(f"    [dim]{desc}[/dim]")
        else:
            console.print("    [yellow]⚠️  (incomplete - no agent.md)[/yellow]")

        console.print()

    console.print(f"[dim]Total: {len(agents)} agent(s)[/dim]")
    console.print()


def reset_agent(agent_name: str, source_agent: str | None = None) -> None:
    """Reset an agent to default or copy from another agent."""
    agents_root = settings.get_agents_root_dir()
    agent_dir = agents_root / agent_name

    if source_agent:
        source_dir = agents_root / source_agent
        source_md = source_dir / "agent.md"

        if not source_md.exists():
            console.print(
                f"[bold red]Error:[/bold red] Source agent '{source_agent}' not found "
                "or has no agent.md"
            )
            return

        source_content = source_md.read_text(encoding="utf-8")
        action_desc = f"contents of agent '{source_agent}'"
    else:
        source_content = get_default_coding_instructions()
        action_desc = "default"

    if agent_dir.exists():
        shutil.rmtree(agent_dir)
        console.print(
            f"Removed existing agent directory: {agent_dir}", style=COLORS["tool"]
        )

    agent_dir.mkdir(parents=True, exist_ok=True)
    agent_md = agent_dir / "agent.md"
    agent_md.write_text(source_content, encoding="utf-8")

    console.print(
        f"✓ Agent '{agent_name}' reset to {action_desc}", style=COLORS["primary"]
    )
    console.print(f"Location: {agent_dir}\n", style=COLORS["dim"])


def get_system_prompt(assistant_id: str, sandbox_type: str | None = None) -> str:
    """Get the base system prompt for the agent.

    Args:
        assistant_id: The agent identifier for path references
        sandbox_type: Type of sandbox provider ("modal", "runloop", "daytona").
                     If None, agent is operating in local mode.

    Returns:
        The system prompt string (without Nova.md content)
    """
    agent_dir_path = f"~/.Nova/{assistant_id}"

    if sandbox_type:
        working_dir = get_default_working_dir(sandbox_type)
    else:
        working_dir = str(Path.cwd())

    return render_template(
        "core_agent_system.jinja",
        working_dir=working_dir,
        sandbox_type=sandbox_type,
        skills_directory=agent_dir_path,
    )


def _format_write_file_description(
    tool_call: ToolCall, _state: AgentState, _runtime: Runtime
) -> str:
    """Format write_file tool call for approval prompt."""
    args = tool_call["args"]
    file_path = args.get("file_path", "unknown")
    content = args.get("content", "")

    # Handle case where content might be a dict instead of string
    if isinstance(content, dict):
        # If content is structured, try to extract the actual content
        content_str = content.get("text", str(content))
    else:
        content_str = str(content) if content is not None else ""

    action = "Overwrite" if Path(file_path).exists() else "Create"
    line_count = len(content_str.splitlines())

    return f"File: {file_path}\nAction: {action} file\nLines: {line_count}"


def _format_edit_file_description(
    tool_call: ToolCall, _state: AgentState, _runtime: Runtime
) -> str:
    """Format edit_file tool call for approval prompt."""
    args = tool_call["args"]
    file_path = args.get("file_path", "unknown")
    replace_all = bool(args.get("replace_all", False))

    return (
        f"File: {file_path}\n"
        f"Action: Replace text ({'all occurrences' if replace_all else 'single occurrence'})"
    )


def _format_web_search_description(
    tool_call: ToolCall, _state: AgentState, _runtime: Runtime
) -> str:
    """Format web_search tool call for approval prompt."""
    args = tool_call["args"]
    query = args.get("query", "unknown")
    max_results = args.get("max_results", 5)

    return f"Query: {query}\nMax results: {max_results}\n\n⚠️  This will use Tavily API credits"


def _format_fetch_url_description(
    tool_call: ToolCall, _state: AgentState, _runtime: Runtime
) -> str:
    """Format fetch_url tool call for approval prompt."""
    args = tool_call["args"]
    url = args.get("url", "unknown")
    timeout = args.get("timeout", 30)

    return f"URL: {url}\nTimeout: {timeout}s\n\n⚠️  Will fetch and convert web content to markdown"


def _format_task_description(
    tool_call: ToolCall, _state: AgentState, _runtime: Runtime
) -> str:
    """Format task (subagent) tool call for approval prompt.

    The task tool signature is: task(description: str, subagent_type: str)
    The description contains all instructions that will be sent to the subagent.
    """
    args = tool_call["args"]
    description = args.get("description", "unknown")
    subagent_type = args.get("subagent_type", "unknown")

    # Truncate description if too long for display
    description_preview = description
    if len(description) > 500:
        description_preview = description[:500] + "..."

    return (
        f"Subagent Type: {subagent_type}\n\n"
        f"Task Instructions:\n"
        f"{'─' * 40}\n"
        f"{description_preview}\n"
        f"{'─' * 40}\n\n"
        f"⚠️  Subagent will have access to file operations and shell commands"
    )


def _format_shell_description(
    tool_call: ToolCall, _state: AgentState, _runtime: Runtime
) -> str:
    """Format shell tool call for approval prompt."""
    args = tool_call["args"]
    command = args.get("command", "N/A")
    return f"Shell Command: {command}\nWorking Directory: {Path.cwd()}"


def _format_execute_description(
    tool_call: ToolCall, _state: AgentState, _runtime: Runtime
) -> str:
    """Format execute tool call for approval prompt."""
    args = tool_call["args"]
    command = args.get("command", "N/A")
    return f"Execute Command: {command}\nLocation: Remote Sandbox"


def _format_run_tests_description(
    tool_call: ToolCall, _state: AgentState, _runtime: Runtime
) -> str:
    """Format run_tests tool call for approval prompt."""
    args = tool_call["args"]
    command = args.get("command", "")
    working_dir = args.get("working_dir", ".")
    timeout = args.get("timeout", 300)

    command_display = command if command else "(auto-detect framework)"
    return (
        f"Test Command: {command_display}\n"
        f"Working Directory: {working_dir}\n"
        f"Timeout: {timeout}s\n\n"
        "⚠️  Will execute tests and stream output in real-time"
    )


def _format_start_dev_server_description(
    tool_call: ToolCall, _state: AgentState, _runtime: Runtime
) -> str:
    """Format start_dev_server tool call for approval prompt."""
    args = tool_call["args"]
    command = args.get("command", "unknown")
    name = args.get("name", "dev-server")
    port = args.get("port", "auto")
    working_dir = args.get("working_dir", ".")
    auto_open_browser = args.get("auto_open_browser", True)

    return (
        f"Server Command: {command}\n"
        f"Name: {name}\n"
        f"Port: {port if port else 'auto-detect'}\n"
        f"Working Directory: {working_dir}\n"
        f"Auto-open browser: {'Yes' if auto_open_browser else 'No'}\n\n"
        "⚠️  Will start a background process (killed on CLI exit)"
    )


def _add_interrupt_on() -> dict[str, InterruptOnConfig]:
    """Configure human-in-the-loop interrupt_on settings for destructive tools."""
    shell_interrupt_config: InterruptOnConfig = {
        "allowed_decisions": ["approve", "reject"],
        "description": _format_shell_description,  # type: ignore
    }

    execute_interrupt_config: InterruptOnConfig = {
        "allowed_decisions": ["approve", "reject"],
        "description": _format_execute_description,  # type: ignore
    }

    write_file_interrupt_config: InterruptOnConfig = {
        "allowed_decisions": ["approve", "reject"],
        "description": _format_write_file_description,  # type: ignore
    }

    edit_file_interrupt_config: InterruptOnConfig = {
        "allowed_decisions": ["approve", "reject"],
        "description": _format_edit_file_description,  # type: ignore
    }

    web_search_interrupt_config: InterruptOnConfig = {
        "allowed_decisions": ["approve", "reject"],
        "description": _format_web_search_description,  # type: ignore
    }

    fetch_url_interrupt_config: InterruptOnConfig = {
        "allowed_decisions": ["approve", "reject"],
        "description": _format_fetch_url_description,  # type: ignore
    }

    # Subagent delegation (task tool) runs without HITL approval —
    # subagents are controlled, stateless agents, not destructive operations.

    run_tests_interrupt_config: InterruptOnConfig = {
        "allowed_decisions": ["approve", "reject"],
        "description": _format_run_tests_description,  # type: ignore
    }

    start_dev_server_interrupt_config: InterruptOnConfig = {
        "allowed_decisions": ["approve", "reject"],
        "description": _format_start_dev_server_description,  # type: ignore
    }

    return {
        "shell": shell_interrupt_config,
        "execute": execute_interrupt_config,
        "write_file": write_file_interrupt_config,
        "edit_file": edit_file_interrupt_config,
        "web_search": web_search_interrupt_config,
        "fetch_url": fetch_url_interrupt_config,
        "run_tests": run_tests_interrupt_config,
        "start_dev_server": start_dev_server_interrupt_config,
    }


def create_agent_with_config(
    model: str | BaseChatModel,
    assistant_id: str,
    tools: list[BaseTool],
    *,
    sandbox: SandboxBackendProtocol | None = None,
    sandbox_type: str | None = None,
    system_prompt: str | None = None,
    auto_approve: bool = False,
    store: InMemoryStore | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
    is_continuation: bool = False,
) -> tuple[Pregel, CompositeBackend]:
    """Create and configure an agent with the specified model and tools.

    Args:
        model: LLM model to use
        assistant_id: Agent identifier for memory storage
        tools: Additional tools to provide to agent
        sandbox: Optional sandbox backend for remote execution (e.g., ModalBackend).
                 If None, uses local filesystem + shell.
        sandbox_type: Type of sandbox provider ("modal", "runloop", "daytona")
        store: Optional InMemoryStore. If None and use_shared_store is True,
               uses a module-level shared store that subagents can also access.
        is_continuation: If True, skip project memory paths (Nova.md/CLAUDE.md)
               from AgentMemoryMiddleware since they're already in the continuation prompt.

    Returns:
        2-tuple of (graph, backend)
    """
    # Lazy import for tracing (speeds up startup)
    from novacode_cli.tracking.tracing import is_tracing_enabled, get_tracing_config

    tracing_enabled = False
    skill_sources = []
    Nova_SubAgent: list[SubAgent] = []

    if is_tracing_enabled():
        tracing_enabled = True
        tracing_config = get_tracing_config()
        # console.print(
        #     f"[dim]LangSmith tracing enabled: {tracing_config.project_name}[/dim]"
        # )
    else:
        # Try to auto-configure from environment
        from novacode_cli.tracking.tracing import auto_configure

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
                from novacode_cli.tracking.tracing import (
                    wrap_openai_client as _wrap_openai,
                )

                wrapped_model = _wrap_openai(model)
        except ImportError:
            pass

    # Skills directory - global (shared across all agents at ~/.Nova/skills/)
    skills_dir = settings.ensure_user_skills_dir()
    skill_sources.append(str(skills_dir))
    # Project-level skills directories (if in a project)
    # Supports both .claude/skills/ and .Nova/skills/
    project_skills_dirs = settings.get_project_skills_dirs()
    # Extend with each path as a string (not str(list) which would be wrong)
    skill_sources.extend(str(p) for p in project_skills_dirs)

    # Determine workspace root for path containment
    workspace_root = settings.project_root or Path.cwd()

    # Build list of allowed directories for filesystem access
    # This includes the workspace root plus user directories like skills, memory, etc.
    allowed_prefixes = [str(workspace_root)]
    
    # Add user skills directory (~/.Nova/skills/)
    if skills_dir:
        allowed_prefixes.append(str(skills_dir))
    
    # Add project skills directories
    for skills_path in project_skills_dirs:
        allowed_prefixes.append(str(skills_path))
    
    # Add user agent directory (~/.Nova/<agent>/) for memory files
    agent_dir = settings.get_agent_dir(assistant_id)
    if agent_dir:
        allowed_prefixes.append(str(agent_dir))

    # CONDITIONAL SETUP: Local vs Remote Sandbox
    if sandbox is None:
        # ========== LOCAL MODE ==========
        # Backend: Local filesystem for code with path containment to allowed directories
        # This prevents the agent from writing outside allowed directories
        backend = FilesystemBackend(
            root_dir=str(workspace_root),
            virtual_mode=False,  # Use real filesystem paths
            allowed_prefixes=allowed_prefixes,  # Allow workspace + user directories # type: ignore
        )

    else:
        # ========== REMOTE SANDBOX MODE ==========
        # Backend: Remote sandbox for code (no /memories/ route needed with filesystem-based memory)
        backend = sandbox
        # FileTrackerMiddleware MUST be first to track all file operations and enforce read-before-edit

    # Lazy imports for middleware (speeds up startup)
    from novacode_cli.mcp import get_shared_mcp_middleware
    from novacode_cli.memory.agent_memory import AgentMemoryMiddleware
    from nova_deepagents.middleware.shared_memory import SharedMemoryMiddleware
    from novacode_cli.shell import ShellMiddleware
    from novacode_cli.tracking.file_tracker import FileTrackerMiddleware
    from novacode_cli.tracking.tool_limits_middleware import ToolLimitsMiddleware

    # Use shared MCP middleware (singleton pattern avoids reconnecting for subagents)
    mcp_middleware = get_shared_mcp_middleware()

    agent_middleware = [
        FileTrackerMiddleware(
            enforce_read_before_edit=True,
            truncate_results=True,
            include_system_prompt=True,
        ),
        ToolLimitsMiddleware(),  # Prevent infinite tool calling loops
        mcp_middleware,
        SharedMemoryMiddleware(author_id="main-agent"),
        ShellMiddleware(
            workspace_root=str(workspace_root),
            env=dict(os.environ),
            backend=backend,  # Pass sandbox backend for remote execution
        ),
        AgentMemoryMiddleware(
            settings=settings,
            assistant_id=assistant_id,
            skip_project_memory=is_continuation,
            backend=backend,  # Pass sandbox backend for reading memory files
        ),
    ]
    # Load pre-defined default and user defined subagents
    Nova_SubAgent.extend(retrieve_core_subagents(tools=tools))  # type: ignore
    Nova_SubAgent.extend(build_named_subagents(assistant_id=assistant_id, tools=tools))  # type: ignore
    
    # Load async subagents (run on remote LangGraph servers in background)
    async_subagents = retrieve_async_subagents()

    # Get the system prompt (sandbox-aware and with skills)
    if system_prompt is None:
        system_prompt = get_system_prompt(
            assistant_id=assistant_id, sandbox_type=sandbox_type
        )

    if auto_approve:
        # No interrupts - all tools run automatically
        interrupt_on = {}
    else:
        # Full HITL for destructive operations
        interrupt_on = _add_interrupt_on()

    composite_backend = CompositeBackend(
        default=backend,
        routes={},
    )

    # Pass named_subagents directly to create_deep_agent
    # It will create the SubAgentMiddleware internally
    # Use provided checkpointer or fallback to InMemorySaver
    final_checkpointer = checkpointer if checkpointer is not None else InMemorySaver()
    agent = create_deep_agent(
        name=assistant_id,
        model=wrapped_model,
        skills=skill_sources,
        system_prompt=system_prompt,
        tools=tools,
        checkpointer=final_checkpointer,
        backend=composite_backend,  # type: ignore
        middleware=agent_middleware,
        store=store,
        interrupt_on=interrupt_on,  # type: ignore
        subagents=Nova_SubAgent + async_subagents,  # type: ignore
    ).with_config(
        config  # type: ignore
    )

    return agent, composite_backend  # type: ignore


async def get_agent_plan_mode_state(agent: Pregel, thread_id: str) -> bool:
    """Get current plan mode state from agent.

    Args:
        agent: The agent instance.
        thread_id: Current thread ID.

    Returns:
        True if plan mode is enabled, False otherwise.
    """
    config = {"configurable": {"thread_id": thread_id}}
    state = await agent.aget_state(config)  # type: ignore
    return state.values.get("plan_mode_enabled", False)


async def set_agent_plan_mode_state(
    agent: Pregel, thread_id: str, enabled: bool
) -> None:
    """Set plan mode state in agent.

    Args:
        agent: The agent instance.
        thread_id: Current thread ID.
        enabled: Whether to enable plan mode.
    """
    config = {"configurable": {"thread_id": thread_id}}
    await agent.aupdate_state(
        config=config,  # type: ignore
        values={"plan_mode_enabled": enabled},
    )

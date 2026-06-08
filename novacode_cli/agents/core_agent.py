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
- Agent profiles stored in ~/.nova/agents/<name>/agent.md

The agent is built using LangGraph's Pregel architecture with:
- Planning capability via write_todos tool
- Subagent delegation via task tool
- File system access via CompositeBackend
- Middleware for memory, skills, MCP, and shell execution
- Checkpointing for conversation state persistence
"""

import os
import re
import shutil
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

# ── Patch deepagents validate_path to accept Windows paths ──────────────────
# The deepagents FilesystemMiddleware rejects Windows absolute paths (e.g.
# B:\...), but LLMs running on Windows sometimes produce them.  Convert
# Windows paths to be relative to the workspace root before validation.
import deepagents.backends.utils as _dab_utils

_original_validate = _dab_utils.validate_path


def _patched_validate_path(path: str, allowed_prefixes=None) -> str:
    """Normalize Windows absolute paths before delegating to the real validator."""
    # If the LLM produces a Windows absolute path, resolve it relative to the
    # workspace root (cwd) so the virtual filesystem backend can map it.
    m = re.match(r"^[a-zA-Z]:[/\\]", path)
    if m:
        try:
            workspace = Path.cwd()
            abs_path = Path(path)
            rel = abs_path.relative_to(workspace)
            path = "/" + rel.as_posix()
        except ValueError:
            # Not under workspace — strip drive and hope for the best
            stripped = path[m.end() :].replace("\\", "/")
            path = f"/{stripped}"
    return _original_validate(path, allowed_prefixes=allowed_prefixes)


_dab_utils.validate_path = _patched_validate_path
# ────────────────────────────────────────────────────────────────────────────

# ── Patch deepagents string replacement to tolerate a UTF-8 BOM ─────────────
# edit_file matches the model's `old_string` against the file content read in
# text mode. On Windows, files authored by some editors carry a leading UTF-8
# BOM (U+FEFF) that the read keeps but the model's `old_string` never includes,
# so the very first edit of such a file fails with "string not found" — what
# looks like an inexplicable whitespace/encoding mismatch. Stripping a leading
# BOM from the content before matching is semantically safe (the BOM is not real
# text) and fixes those edits. Patched at every import site since the symbol is
# bound by-name at module load.
_BOM = "﻿"  # U+FEFF byte-order mark
_original_psr = _dab_utils.perform_string_replacement


def _patched_perform_string_replacement(content, old_string, new_string, replace_all=False):  # noqa: ANN001, ANN201, FBT002
    if content.startswith(_BOM) and not old_string.startswith(_BOM):
        content = content.lstrip(_BOM)
    return _original_psr(content, old_string, new_string, replace_all)


_dab_utils.perform_string_replacement = _patched_perform_string_replacement
for _mod_name in (
    "deepagents.backends.filesystem",
    "deepagents.backends.state",
):
    try:
        _m = __import__(_mod_name, fromlist=["perform_string_replacement"])
        if hasattr(_m, "perform_string_replacement"):
            _m.perform_string_replacement = _patched_perform_string_replacement
    except Exception:  # noqa: BLE001 - best-effort; never block import
        pass
# ────────────────────────────────────────────────────────────────────────────

from langchain.tools import BaseTool
from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.pregel import Pregel
from langgraph.store.base import BaseStore
from deepagents import create_deep_agent
from deepagents.backends import CompositeBackend
from deepagents.backends.filesystem import FilesystemBackend
from deepagents.backends.protocol import BackendProtocol, SandboxBackendProtocol
from deepagents.backends.store import StoreBackend
from deepagents.middleware.subagents import SubAgent

from novacode_cli.agents.default_subagents.subagents import retrieve_core_subagents
from novacode_cli.agents.default_subagents.async_subagents import (
    retrieve_async_subagents,
)
from novacode_cli.config.config import (
    COLORS,
    boot_status,
    config,
    console,
    get_default_coding_instructions,
    set_agent_color,
    settings,
)
from novacode_cli.hitl.interrupts import get_interrupt_configs
from novacode_cli.integrations.sandbox_factory import get_default_working_dir
from novacode_cli.prompts import render_template


def get_shared_store() -> "BaseStore":
    """Get the shared, durable store for agent/subagent memory sharing.

    Backed by SQLite at ``~/.nova/store.db`` so structured memory written via
    the store survives restarts (see :mod:`novacode_cli.memory.store`). All
    agents and subagents in a process share this one instance.

    Returns:
        The shared durable store (falls back to in-memory if SQLite is
        unavailable).
    """
    from novacode_cli.memory.store import get_durable_store

    return get_durable_store()  # type: ignore


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

    Reads all agents from both global (~/.nova/agents/) and project (.nova/agents/)
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

    # Collect valid candidates (path existence check is fast, no I/O for content yet)
    candidates: list[tuple[str, Path, str, Path]] = []
    for agent_name, agent_dir, scope in all_agents:
        if agent_name == assistant_id:
            continue
        agent_md_path = agent_dir / "agent.md"
        if not agent_md_path.exists():
            console.print(
                f"[dim yellow]Warning: Skipping agent '{agent_name}' - no agent.md file[/dim yellow]"
            )
            continue
        candidates.append((agent_name, agent_dir, scope, agent_md_path))

    def _read_agent(
        args: tuple[str, Path, str, Path],
    ) -> tuple[str, Path, str, str] | None:
        """Read agent.md content in a worker thread. Returns None on error."""
        agent_name, agent_dir, scope, agent_md_path = args
        try:
            return (
                agent_name,
                agent_dir,
                scope,
                agent_md_path.read_text(encoding="utf-8"),
            )
        except Exception as e:
            console.print(
                f"[dim yellow]Warning: Could not read agent.md for '{agent_name}': {e}[/dim yellow]"
            )
            return None

    def _parse_color_from_content(content: str) -> str | None:
        """Extract color from YAML frontmatter without re-reading the file."""
        match = re.match(r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL)
        if not match:
            return None
        for line in match.group(1).split("\n"):
            kv = re.match(r"^color:\s*(.+)$", line.strip())
            if kv:
                return kv.group(1).strip().strip('"').strip("'")
        return None

    # Read all agent files in parallel
    max_workers = min(len(candidates), 8) if candidates else 1
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        read_results = list(executor.map(_read_agent, candidates))

    for result in read_results:
        if result is None:
            continue
        agent_name, agent_dir, scope, system_prompt = result

        description = _extract_agent_description(system_prompt)

        # Parse color directly from already-loaded content (avoids second read)
        agent_color = _parse_color_from_content(system_prompt)
        if agent_color:
            set_agent_color(agent_name, agent_color)

        subagent: SubAgent = {
            "name": agent_name,
            "description": f"[{scope}] {description}",
            "system_prompt": system_prompt,
            "tools": tools,
        }
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
            "[dim]Agents will be created in ~/.nova/agents/ when you first use them.[/dim]",
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


def _get_shell_platform_info(sandbox_type: str | None) -> dict:
    """Return shell/platform metadata for the current execution environment.

    Sandbox environments are always Linux regardless of the host OS.
    For local execution the real OS is detected so the LLM never uses
    bash syntax on Windows or PowerShell syntax on macOS/Linux.

    Returns a dict with keys:
        platform    – "windows" | "macos" | "linux"
        shell_name  – "PowerShell" | "zsh" | "bash"
        path_sep    – "\\\\" | "/"
        shell_notes – list of platform-specific shell rules (strings)
    """
    import platform as _platform

    if sandbox_type:
        # All supported sandbox providers (Modal, Runloop, Daytona) are Linux
        return {
            "platform": "linux",
            "shell_name": "bash",
            "path_sep": "/",
            "shell_notes": [
                "Use `bash` syntax — the sandbox is a Linux environment.",
                "Chain commands with `&&`.",
                "Use forward slashes in all paths.",
            ],
        }

    system = _platform.system().lower()

    if system == "windows":
        return {
            "platform": "windows",
            "shell_name": "PowerShell",
            "path_sep": "\\",
            "shell_notes": [
                "The user is on **Windows** — always use PowerShell syntax, NEVER bash.",
                "Use `;` to chain commands (not `&&`, which is unreliable in older PowerShell).",
                "Use `$env:VAR` for environment variables, not `$VAR` or `export VAR=`.",
                "Use backslashes in Windows paths, or wrap paths in double quotes.",
                "Do NOT use `rm -rf`, `cat`, `chmod`, `sudo`, `which`, or any Unix-only commands.",
                "Use `Get-ChildItem` instead of `ls`/`find`; `Select-String` instead of `grep`.",
                "Use `Remove-Item -Recurse -Force` instead of `rm -rf`.",
            ],
        }

    if system == "darwin":
        return {
            "platform": "macos",
            "shell_name": "zsh",
            "path_sep": "/",
            "shell_notes": [
                "The user is on **macOS** — the default shell is `zsh`.",
                "Chain commands with `&&`.",
                "Use forward slashes in all paths.",
                "Prefer `brew` for package management when available.",
            ],
        }

    return {
        "platform": "linux",
        "shell_name": "bash",
        "path_sep": "/",
        "shell_notes": [
            "The user is on **Linux** — use `bash` syntax.",
            "Chain commands with `&&`.",
            "Use forward slashes in all paths.",
        ],
    }


def get_system_prompt(assistant_id: str, sandbox_type: str | None = None) -> str:
    """Get the base system prompt for the agent.

    Args:
        assistant_id: The agent identifier for path references
        sandbox_type: Type of sandbox provider ("modal", "runloop", "daytona").
                     If None, agent is operating in local mode.

    Returns:
        The system prompt string (without NOVA.md content)
    """
    agent_dir_path = f"~/.nova/{assistant_id}"

    if sandbox_type:
        working_dir = get_default_working_dir(sandbox_type)
    else:
        # In local mode with virtual_mode=True, the FilesystemBackend maps
        # virtual paths (starting with /) to the workspace root directory.
        # The LLM must use virtual paths like /file.txt, not Windows absolute
        # paths like B:\path\file.txt, because FilesystemMiddleware.validate_path
        # rejects Windows paths with:
        #   "Windows absolute paths are not supported: B:\... Please use virtual
        #    paths starting with / (e.g., /workspace/file.txt)"
        # Since root_dir == workspace_root, the virtual path "/" maps to the
        # project root, so we present "/" as the working directory.
        working_dir = "/"

    has_tavily = getattr(settings, "has_tavily", False)
    has_graph = getattr(settings, "has_graph", False)
    shell_info = _get_shell_platform_info(sandbox_type)

    return render_template(
        "core_agent_system.jinja",
        working_dir=working_dir,
        sandbox_type=sandbox_type,
        skills_directory=agent_dir_path,
        has_tavily=has_tavily,
        has_graph=has_graph,
        **shell_info,
    )


def _harden_subagent_specs(specs: list) -> list:
    """Return resilient, unattended copies of the subagent specs.

    Returns a NEW list of NEW spec dicts — it must NOT mutate the inputs, because
    ``build_named_subagents``/``retrieve_core_subagents`` hand back **cached**
    spec dicts that are reused across every ``create_agent_with_config`` call
    (the session agent, then /init's dedicated agent, …). Mutating them in place
    accumulated a fresh ``ModelRetryMiddleware`` per call, so the 2nd build saw
    two retry middleware with the same ``.name`` and langchain aborted with
    "Please remove duplicate middleware instances" (this is what made /init fall
    back to the shared agent).

    For each dict spec that isn't a compiled/remote subagent (``runnable``/``url``):

    - **Clear ``interrupt_on``** — a HITL interrupt raised inside a subagent
      bubbles out of the ``task`` tool as an unresolvable ``GraphInterrupt`` and
      crashes the turn (see the comment in :func:`create_agent_with_config`). The
      main agent stays the sole HITL boundary; dispatched subagents never prompt.
    - **Prepend a fresh ``ModelRetryMiddleware``** — deepagents gives subagents
      only ``[TodoList, Filesystem, Summarization, PatchToolCalls] + skills +
      spec["middleware"]``, i.e. **no retry**, while the main agent has one. So a
      transient provider 5xx/429/timeout during a subagent's model call would
      otherwise kill it (this is what broke /init's semantic-extraction
      subagents — the chunk fragment never got written). A fresh instance per
      build; skipped if the spec already carries a retry middleware.
    """
    from langchain.agents.middleware import ModelRetryMiddleware

    out: list = []
    for spec in specs:
        if not isinstance(spec, dict) or "runnable" in spec or "url" in spec:
            out.append(spec)  # compiled/remote subagents own their own config
            continue
        existing = list(spec.get("middleware") or [])
        new_spec = dict(spec)  # copy — never mutate the (possibly cached) original
        new_spec["interrupt_on"] = {}
        has_retry = any(type(m).__name__ == "ModelRetryMiddleware" for m in existing)
        new_spec["middleware"] = (
            existing
            if has_retry
            else [
                ModelRetryMiddleware(
                    max_retries=3, backoff_factor=2.0, initial_delay=1.0
                ),
                *existing,
            ]
        )
        out.append(new_spec)
    return out


def _seed_summarization_profile(model: object, model_name: str) -> None:
    """Seed ``model.profile['max_input_tokens']`` so deepagents' built-in
    ``SummarizationMiddleware`` triggers on OUR context budget.

    deepagents auto-computes the summarization trigger from the model profile:
    with a profile exposing ``max_input_tokens`` it summarizes at 85% of the
    window (keeping the last ~10%); WITHOUT one it falls back to a fixed
    170k-token trigger — which never fires for local/Ollama models whose real
    window is far smaller (the model just overflows). Seeding the profile from
    the same window Nova uses for ``/context`` ties the summarization trigger to
    the displayed ctx %.

    No-op when the model already exposes a profile (cloud models often ship one)
    or isn't a chat-model instance. Never raises — it's a pure optimization.
    """
    try:
        if (
            not isinstance(model, BaseChatModel)
            or getattr(model, "profile", None) is not None
        ):
            return
        from novacode_cli.context import ContextManager

        window = ContextManager(model_name).window_size()
        if window and window > 0:
            model.profile = {"max_input_tokens": int(window)}  # type: ignore[assignment]
    except Exception:  # noqa: BLE001 - never block agent build on a profile hint
        __import__("logging").getLogger(__name__).debug(
            "Could not seed model profile for summarization", exc_info=True
        )


def create_agent_with_config(
    model: str | BaseChatModel,
    assistant_id: str,
    tools: list[BaseTool],
    *,
    sandbox: SandboxBackendProtocol | None = None,
    sandbox_type: str | None = None,
    system_prompt: str | None = None,
    auto_approve: bool = False,
    store: BaseStore | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
    is_continuation: bool = False,
    steering_instructions: list | None = None,
) -> tuple[Pregel, CompositeBackend]:
    """Create and configure an agent with the specified model and tools.

    Args:
        model: LLM model to use
        assistant_id: Agent identifier for memory storage
        tools: Additional tools to provide to agent
        sandbox: Optional sandbox backend for remote execution (e.g., ModalBackend).
                 If None, uses local filesystem + shell.
        sandbox_type: Type of sandbox provider ("modal", "runloop", "daytona")
        store: Optional durable store (BaseStore). If None, the caller is
               expected to pass the shared store from get_shared_store() so
               subagents can also access it.
        is_continuation: If True, skip project memory paths (NOVA.md/CLAUDE.md)
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

    # Skills directory - global (shared across all agents at ~/.nova/skills/)
    skills_dir = settings.ensure_user_skills_dir()
    # Global Claude Code skills directory (~/.claude/skills/)
    claude_skills_dir = settings.get_global_claude_skills_dir()
    # Project-level skills directories (if in a project)
    # Supports both .claude/skills/ and .nova/skills/
    project_skills_dirs = settings.get_project_skills_dirs()

    # Build skill sources using virtual path prefixes that match CompositeBackend routes.
    # This ensures SkillsMiddleware.ls("/skills/") routes to the FilesystemBackend
    # instead of the default backend (which may fail outside graph context).
    skill_sources.append("/skills/")
    if claude_skills_dir.exists():
        skill_sources.append("/claude-skills/")
    for i, _p in enumerate(project_skills_dirs):
        skill_sources.append(f"/project-skills-{i}/")

    # Determine workspace root for path containment
    workspace_root = settings.project_root or Path.cwd()

    # Build list of allowed directories for filesystem access
    # This includes the workspace root plus user directories like skills, memory, etc.
    allowed_prefixes = [str(workspace_root)]

    # Add user skills directory (~/.nova/skills/)
    if skills_dir:
        allowed_prefixes.append(str(skills_dir))

    # Add global Claude Code skills directory (~/.claude/skills/)
    if claude_skills_dir.exists():
        allowed_prefixes.append(str(claude_skills_dir))

    # Add project skills directories
    for skills_path in project_skills_dirs:
        allowed_prefixes.append(str(skills_path))

    # Add user agent directory (~/.nova/<agent>/) for memory files
    agent_dir = settings.get_agent_dir(assistant_id)
    if agent_dir:
        allowed_prefixes.append(str(agent_dir))
        # Auto-create simple memory structure on first use so the agent has
        # a memory file to read/write without needing the
        # create_memory_structure tool (which is no longer registered in the
        # default toolset).
        _agent_md = agent_dir / "agent.md"
        if not _agent_md.exists():
            agent_dir.mkdir(parents=True, exist_ok=True)
            _agent_md.write_text(
                """# Agent Memory

This file stores your preferences and context that persist across sessions.

## Communication Style
- [Your preferred communication style]

## Coding Preferences
- [Your coding preferences]

## Project Context
- [Project-specific notes]

## Workflows
- [Common workflows you use]
""",
                encoding="utf-8",
            )

        # Ensure the Nova learning memory tiers (USER.md / MEMORY.md) exist so
        # the learning middleware has files to read/write during review cycles.
        try:
            from novacode_cli.hermes.memory_tiers import ensure_memory_tiers

            ensure_memory_tiers(agent_dir)
        except Exception:  # noqa: BLE001
            console.print("[dim]⚠ Failed to ensure Nova memory tiers[/dim]")

    # CONDITIONAL SETUP: Local vs Remote Sandbox
    if sandbox is None:
        # ========== LOCAL MODE ==========
        # Backend: Local filesystem for code with path containment to allowed directories
        # This prevents the agent from writing outside allowed directories
        _default_backend = FilesystemBackend(
            root_dir=str(workspace_root),
            virtual_mode=True,
        )

    else:
        # ========== REMOTE SANDBOX MODE ==========
        # Backend: Remote sandbox for code execution.
        # Wrap it so the agent's `/`-rooted *virtual* project paths (e.g.
        # `/novacode_cli/x`) map to the sandbox **working directory** (e.g.
        # `/workspace/novacode_cli/x`) for file ops. Without this, file reads
        # hit the container root and 404, even though `execute` runs in the
        # workdir — see novacode_cli/integrations/workdir_backend.py.
        from novacode_cli.integrations.workdir_backend import WorkdirSandboxBackend

        _sandbox_workdir = None
        if sandbox_type:
            try:
                _sandbox_workdir = get_default_working_dir(sandbox_type)
            except Exception:  # noqa: BLE001
                _sandbox_workdir = None
        if _sandbox_workdir is None:
            _sandbox_workdir = getattr(sandbox, "_workdir", None) or "/workspace"
        _default_backend = WorkdirSandboxBackend(sandbox, workdir=_sandbox_workdir)  # type: ignore

    # ------------------------------------------------------------------
    # Build CompositeBackend with routes per deepagents 0.5.6 docs:
    # https://docs.langchain.com/oss/python/deepagents/backends#compositebackend-router
    #
    # CompositeBackend routes file operations to different backends based
    # on path prefix. SkillsMiddleware receives the same backend as
    # create_deep_agent and calls backend.ls(source_path) for each source.
    # When source_path is "/skills/", CompositeBackend routes it to the
    # FilesystemBackend rooted at ~/.nova/skills/.
    #
    # Canonical pattern (from deepagents docs and examples):
    #   skill_backend = FilesystemBackend(root_dir=SKILLS_DIR, virtual_mode=True)
    #   backend = CompositeBackend(
    #       default=StateBackend(),
    #       routes={
    #           "/memories/": StoreBackend(),
    #           "/skills/": skill_backend,
    #       },
    #   )
    #   create_deep_agent(backend=backend, skills=["/skills/"], ...)
    # ------------------------------------------------------------------

    _skills_backend = FilesystemBackend(
        root_dir=str(skills_dir),
        virtual_mode=True,
    )

    _routes: dict[str, BackendProtocol] = {  # type: ignore[name-defined]
        "/skills/": _skills_backend,
    }

    # Add global Claude Code skills route (~/.claude/skills/)
    if claude_skills_dir.exists():
        _claude_skills_backend = FilesystemBackend(
            root_dir=str(claude_skills_dir),
            virtual_mode=True,
        )
        _routes["/claude-skills/"] = _claude_skills_backend

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
    # memory files (NOVA.md, CLAUDE.md) via virtual paths like
    # /memories/NOVA.md. AgentMemoryMiddleware reads these files directly
    # from the filesystem at startup, but the /memories/ route enables
    # the agent to re-read them during execution.
    if agent_dir:
        _agent_backend = FilesystemBackend(
            root_dir=str(agent_dir),
            virtual_mode=True,
        )
        _routes["/memories/"] = _agent_backend
        # Nova memory tier routes — point to the same agent directory
        # but are used solely for USER.md and MEMORY.md access.
        _routes["/user-memory/"] = _agent_backend
        _routes["/session-memory/"] = _agent_backend

    # /store/ route → StoreBackend (persistent, cross-thread).
    #
    # Unlike /memories/ (which is backed by a FilesystemBackend so
    # AgentMemoryMiddleware can read agent.md directly from disk), /store/
    # stores files in LangGraph's durable Store (SQLite at ~/.nova/store.db).
    # Data written here survives agent restarts, thread switches, and is
    # shared across subagents.
    #
    # The namespace is scoped by (assistant_id, "store") so different agents
    # have isolated storage.  Use this for cross-session data that the agent
    # wants to keep — preference records, accumulated facts, etc.
    if store is not None:
        _ns = assistant_id  # captured in closure for namespace factory
        _store_backend = StoreBackend(
            store=store,
            namespace=lambda rt: (_ns, "store"),  # type: ignore[union-attr]
        )
        _routes["/store/"] = _store_backend

    # Add /.nova/plans/ route for plan files.
    # This allows the agent to write and read plan files via virtual paths
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
    # This allows the agent to read/write project memory (NOVA.md, CLAUDE.md)
    # via virtual paths like /project-memory/NOVA.md. The FilesystemBackend
    # maps these to {workspace_root}/.nova/ on disk.
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

    # Lazy imports for middleware (speeds up startup)
    from langchain.agents.middleware import ModelRetryMiddleware
    from novacode_cli.bootstrap import BootstrapMiddleware, GraphContextMiddleware
    from novacode_cli.bootstrap.steering import SteeringMiddleware
    from novacode_cli.hermes.middleware import NovaLearningMiddleware
    from novacode_cli.memory.agent_memory import AgentMemoryMiddleware
    from novacode_cli.security.middleware import SecurityMiddleware
    from novacode_cli.shell import ShellMiddleware
    from novacode_cli.tracking.file_tracker import FileTrackerMiddleware

    # Check whether MCP servers are configured before instantiating the middleware.
    # MCPMiddleware calls list_servers() (a JSON file read) on every model turn, so
    # skipping it entirely when there are no servers saves ~4 file reads per call.
    _has_mcp = False
    try:
        from novacode_cli.mcp.config import MCPConfig as _MCPConfig

        _has_mcp = bool(_MCPConfig().load())
    except Exception:
        pass

    _model_name = (
        model
        if isinstance(model, str)
        else getattr(model, "model_name", getattr(model, "model", "unknown"))
    )
    agent_middleware = [
        # Retry transient model failures (rate limits / 429, timeouts, network
        # blips) with exponential backoff before surfacing an error to the user.
        ModelRetryMiddleware(
            max_retries=3,
            backoff_factor=2.0,
            initial_delay=1.0,
        ),
        # Nova — autonomous learning middleware that tracks tool usage,
        # triggers periodic review cycles, and manages memory tiers.
        # Positioned after ModelRetryMiddleware so retried tool calls don't
        # inflate the counter, but before other middleware so learning data
        # is collected for all downstream operations.
        NovaLearningMiddleware(
            store=store,  # type: ignore
            skills_dir=skills_dir,
            agent_dir=agent_dir,
        ),
        # Screen URL-bearing tool args for deceptive Unicode / spoofed domains
        # (warn + sanitize) before the tool runs. Early in the stack so the
        # cleaned args flow to every downstream middleware and the tool itself.
        SecurityMiddleware(),
        BootstrapMiddleware(workspace_root=str(workspace_root)),
        GraphContextMiddleware(workspace_root=str(workspace_root)),
        # Connect to the session's shared steering list so /steer AND live
        # mid-run steering (TUI) reach the model — the middleware reads this
        # list on every model call, so appends made while the agent is working
        # take effect on its next step.
        SteeringMiddleware(instructions=steering_instructions),
        FileTrackerMiddleware(
            enforce_read_before_edit=True,
            truncate_results=True,
            include_system_prompt=True,
        ),
        ShellMiddleware(
            workspace_root=str(workspace_root),
            env=dict(os.environ),
            backend=composite_backend,  # Route through CompositeBackend for /skills/ etc.
            # When in a sandbox, show the in-sandbox working dir (e.g. /workspace)
            # in the tool description instead of the host path.
            sandbox_working_dir=(
                get_default_working_dir(sandbox_type) if sandbox_type else None
            ),
        ),
        AgentMemoryMiddleware(
            settings=settings,
            assistant_id=assistant_id,
            # Always load project memory (NOVA.md/CLAUDE.md) into <project_memory>,
            # even on resume. It's standing project config that must be present in
            # the system prompt EVERY turn (and hot-reloaded). The continuation
            # prompt no longer carries NOVA.md, so there's nothing to duplicate —
            # and unlike a seeded message, the system-prompt copy survives
            # summarization/compaction.
            skip_project_memory=False,
            backend=composite_backend,  # Route through CompositeBackend for /memories/ etc.
        ),
    ]

    # Plugin middleware injection — discover and inject user-enabled plugins
    # from installed pip packages that register "nova.plugins" entry points.
    # Plugins sit after the built-in middleware assembly but before the optional
    # MCP middleware so slot-based positioning remains predictable regardless of
    # whether MCP is configured on this machine.
    _plugin_specs: list = []
    try:
        from novacode_cli.plugins.loader import (
            discover_enabled_plugins,
            merge_plugin_middleware,
            merge_plugin_tools,
        )

        _plugin_specs = discover_enabled_plugins()
        if _plugin_specs:
            merge_plugin_middleware(agent_middleware, _plugin_specs)
            merge_plugin_tools(tools, _plugin_specs)
            # Surface lifecycle hooks if any plugins registered them
            for _pkg_name, _spec in _plugin_specs:
                _hooks = _spec.get("hooks") or {}
                _before = _hooks.get("before_agent_setup")
                if _before:
                    try:
                        import asyncio

                        asyncio.create_task(_before())
                    except Exception:
                        logger = __import__("logging").getLogger("nova.plugins")
                        logger.exception(
                            "Plugin '%s' before_agent_setup hook failed", _pkg_name
                        )
    except Exception:
        pass

    # MCP middleware: only add when servers are actually configured.
    # Insert after GraphContext (index 3 now that ModelRetryMiddleware leads the
    # stack) so MCP tools keep their original position relative to the others.
    if _has_mcp:
        from novacode_cli.mcp import get_shared_mcp_middleware

        mcp_middleware = get_shared_mcp_middleware()
        # Eagerly discover MCP tools BEFORE building the agent graph.
        # create_deep_agent collects each middleware's ``.tools`` at construction
        # time (langchain factory: ``[t for m in middleware for t in m.tools]``),
        # so lazy discovery would leave ``mcp_middleware.tools`` empty and the
        # MCP tools (serena, playwright, …) would never be registered or callable.
        if not mcp_middleware._tools_discovered:
            try:
                boot_status("mcp: connecting to servers…")
                mcp_middleware._discover_tools_sync()
            except Exception as exc:  # noqa: BLE001
                boot_status(
                    f"mcp: discovery did not complete ({type(exc).__name__})", "warn"
                )
        agent_middleware.insert(3, mcp_middleware)

    # NOTE: automatic context-window summarization is provided by
    # create_deep_agent's built-in SummarizationMiddleware (part of its tail
    # stack) — do NOT add another here or agent creation fails with
    # "duplicate middleware instances".

    # Load pre-defined default and user defined subagents
    Nova_SubAgent.extend(retrieve_core_subagents(tools=tools))  # type: ignore
    Nova_SubAgent.extend(build_named_subagents(assistant_id=assistant_id, tools=tools))  # type: ignore

    # Plugin subagents — delegate agents contributed by enabled plugins. Added
    # after the built-ins so they go through the same _harden_subagent_specs pass
    # below (retry + no nested HITL) and can be dispatched via the `task` tool.
    if _plugin_specs:
        try:
            from novacode_cli.plugins.loader import merge_plugin_subagents

            merge_plugin_subagents(Nova_SubAgent, _plugin_specs)  # type: ignore
        except Exception:  # noqa: BLE001
            __import__("logging").getLogger("nova.plugins").exception(
                "Failed to merge plugin subagents"
            )

    # Own the general-purpose subagent instead of letting create_deep_agent
    # auto-inject it. The auto-injected one inherits the main `interrupt_on` and
    # gets NO retry middleware, so it (a) can crash the turn on a nested HITL
    # interrupt and (b) dies on a transient provider 5xx. /init delegates its
    # semantic-extraction chunks to general-purpose, so this is exactly the
    # subagent that was failing. Providing our own spec (the documented override)
    # routes it through _harden_subagent_specs below — retry + no nested HITL —
    # while deepagents still builds its base middleware stack. The stock
    # GENERAL_PURPOSE_SUBAGENT system prompt is used (we forgo the harness-profile
    # prompt overlay, which is an acceptable trade for resilience).
    from deepagents.middleware.subagents import GENERAL_PURPOSE_SUBAGENT

    if not any(
        isinstance(s, dict) and s.get("name") == "general-purpose"
        for s in Nova_SubAgent
    ):
        Nova_SubAgent.append({**GENERAL_PURPOSE_SUBAGENT, "tools": tools})  # type: ignore

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
        interrupt_on = get_interrupt_configs()

    # Subagents run UNATTENDED — the main agent is the sole HITL boundary.
    #
    # Why: create_deep_agent propagates the main `interrupt_on` to every
    # declarative subagent (deepagents.graph). But a subagent is invoked via
    # `subagent.ainvoke()` inside the `task` tool, so a HITL interrupt raised
    # INSIDE a subagent surfaces as a GraphInterrupt EXCEPTION bubbling out of
    # the parent agent's stream — it never appears as a top-level
    # `__interrupt__` event, so the approve/auto-approve path in run_agent_stream
    # never sees it and the whole turn crashes (this is what broke /init's
    # semantic-extraction and NOVA.md-authoring subagents, and would break any
    # /research subagent that writes a file). Nested HITL is unresolvable in this
    # architecture, so we explicitly clear `interrupt_on` on each declarative
    # subagent. The main agent still gates its own destructive tools; subagents
    # it dispatches do not independently prompt. Compiled/remote subagents own
    # their own approval config and are left untouched.
    #
    # The same pass also gives each subagent a ModelRetryMiddleware (which they
    # otherwise lack entirely) so a transient provider 5xx/429 no longer kills a
    # subagent mid-run — see _harden_subagent_specs. Returns fresh copies (never
    # mutates the cached specs, which would accumulate middleware across builds).
    Nova_SubAgent = _harden_subagent_specs(Nova_SubAgent)

    # Make deepagents' built-in SummarizationMiddleware actually fire on OUR
    # context budget (see _seed_summarization_profile).
    _seed_summarization_profile(wrapped_model, _model_name)

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
        backend=composite_backend,
        middleware=agent_middleware,
        store=store,
        interrupt_on=interrupt_on,  # type: ignore
        subagents=Nova_SubAgent + async_subagents,  # type: ignore
    ).with_config(
        config  # type: ignore
    )

    # Plugin after_agent_setup hooks — call any registered lifecycle hooks
    # now that the agent graph is fully built.
    try:
        from novacode_cli.plugins.loader import discover_enabled_plugins

        for _pkg_name, _spec in discover_enabled_plugins():
            _hooks = _spec.get("hooks") or {}
            _after = _hooks.get("after_agent_setup")
            if _after:
                try:
                    import asyncio

                    asyncio.create_task(_after(agent))  # type: ignore
                except Exception:
                    _log = __import__("logging").getLogger("nova.plugins")
                    _log.exception(
                        "Plugin '%s' after_agent_setup hook failed", _pkg_name
                    )
    except Exception:
        pass

    return agent, composite_backend

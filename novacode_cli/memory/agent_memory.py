"""Middleware for loading agent-specific long-term memory into the system prompt."""

import contextlib
import os
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TypedDict, cast

try:
    from typing import NotRequired
except ImportError:
    from typing import NotRequired

from langchain.agents.middleware.types import (
    AgentMiddleware,
    AgentState,
    ModelRequest,
    ModelResponse,
)

# from langgraph.runtime import Runtime
from novacode_cli.config.config import Settings
from novacode_cli.prompts import render_template

# Maximum characters to inject per memory source (~3,000 tokens at 4 chars/token).
# Prevents unbounded prompt growth from large CLAUDE.md / Nova.md files.
MAX_MEMORY_CHARS = 12_000
_MEMORY_TRUNCATION_NOTICE = "\n\n... [memory truncated — use read_file for full content]"


class AgentMemoryState(AgentState):
    """State for the agent memory middleware."""

    user_memory: NotRequired[str]
    """Personal preferences from ~/.Nova/{agent}/ (applies everywhere)."""

    project_memory: NotRequired[str]
    """Project-specific context (combined from all found memory files)."""


class AgentMemoryStateUpdate(TypedDict):
    """A state update for the agent memory middleware."""

    user_memory: NotRequired[str]
    """Personal preferences from ~/.Nova/{agent}/ (applies everywhere)."""

    project_memory: NotRequired[str]
    """Project-specific context (combined from all found memory files)."""


# Long-term Memory Documentation
# Note: Claude Code loads CLAUDE.md files hierarchically and combines them (not precedence-based):
# - Loads recursively from cwd up to (but not including) root directory
# - Multiple files are combined hierarchically: enterprise → project → user
# - Both [project-root]/CLAUDE.md and [project-root]/.claude/CLAUDE.md are loaded if both exist
# - Files higher in hierarchy load first, providing foundation for more specific memories
# We follow that pattern for Nova CLI
# Long-term memory system prompt is loaded from: NovaCode_cli/prompts/longterm_memory.jinja


DEFAULT_MEMORY_SNIPPET = """<user_memory>
{user_memory}
</user_memory>

<project_memory>
{project_memory}
</project_memory>"""


class AgentMemoryMiddleware(AgentMiddleware):
    """Middleware for loading agent-specific long-term memory.

    This middleware loads the agent's long-term memory from files (CLAUDE.md,
    Nova.md) and injects them into the system prompt. Memory is loaded once
    at the start of the conversation and stored in state.

    Supports loading from multiple project memory files and combining them.
    """

    state_schema = AgentMemoryState

    def __init__(
        self,
        *,
        settings: Settings,
        assistant_id: str,
        system_prompt_template: str | None = None,
        skip_project_memory: bool = False,
    ) -> None:
        """Initialize the agent memory middleware.

        Args:
            settings: Global settings instance with project detection and paths.
            assistant_id: The agent identifier.
            system_prompt_template: Optional custom template for injecting
                agent memory into system prompt.
            skip_project_memory: If True, skip loading project memory files
                (Nova.md/CLAUDE.md). Use on session continuation to avoid
                duplicate context.
        """
        self.settings = settings
        self.assistant_id = assistant_id
        self.skip_project_memory = skip_project_memory

        # User paths
        self.agent_dir = settings.get_agent_dir(assistant_id)
        # Store both display path (with ~) and absolute path for file operations
        self.agent_dir_display = f"~/.Nova/{assistant_id}"
        self.agent_dir_absolute = str(self.agent_dir)

        # Project paths (from settings)
        self.project_root = settings.project_root

        self.system_prompt_template = system_prompt_template or DEFAULT_MEMORY_SNIPPET

        # Track which project memory files were loaded (for display in prompt)
        self.loaded_project_memory_sources: list[str] = []

        # Track file modification times for hot-reloading
        self._last_mtimes: dict[str, float] = {}

        # Cache for loaded memory content
        self._cached_user_memory: str | None = None
        self._cached_project_memory: str | None = None

    def _get_file_mtime(self, path: Path) -> float | None:
        """Get modification time for a file, or None if it doesn't exist."""
        try:
            return path.stat().st_mtime
        except OSError:
            return None

    def _files_changed(self, paths: list[Path]) -> bool:
        """Check if any files have been modified since last load."""
        for path in paths:
            current_mtime = self._get_file_mtime(path)
            if current_mtime is not None:
                last_mtime = self._last_mtimes.get(str(path))
                if last_mtime is None or current_mtime > last_mtime:
                    return True
        return False

    def _record_mtimes(self, paths: list[Path]) -> None:
        """Record modification times for all paths."""
        for path in paths:
            mtime = self._get_file_mtime(path)
            if mtime is not None:
                self._last_mtimes[str(path)] = mtime

    def before_agent(  # type: ignore
        self,
        state: AgentMemoryState,
        # runtime: Runtime,
    ) -> AgentMemoryStateUpdate:
        """Load agent memory from file before agent execution.

        Loads both user agent.md and project-specific memory files if available.
        Project memory is combined from multiple sources (CLAUDE.md, Nova.md).

        Hot-reload: Automatically reloads memory files when they change on disk.
        Tracks modification times and reloads when files are updated.

        Args:
            state: Current agent state.
            runtime: Runtime context.

        Returns:
            Updated state with user_memory and project_memory populated.
        """
        result: AgentMemoryStateUpdate = {}

        # Gather all memory file paths to check for changes
        user_path = self.settings.get_user_agent_md_path(self.assistant_id)
        project_paths = self.settings.get_project_agent_md_paths() if not self.skip_project_memory else []
        all_paths = [user_path] + list(project_paths)

        # Check if any files have changed (hot-reload)
        needs_reload = self._files_changed(all_paths)

        # Load user memory if not in state or if file changed
        if needs_reload or "user_memory" not in state:
            if user_path.exists():
                with contextlib.suppress(OSError, UnicodeDecodeError):
                    content = user_path.read_text(encoding="utf-8")
                    if len(content) > MAX_MEMORY_CHARS:
                        content = content[:MAX_MEMORY_CHARS] + _MEMORY_TRUNCATION_NOTICE
                    result["user_memory"] = content

        # Load project memory from ALL available sources if not in state or if files changed
        if not self.skip_project_memory and (needs_reload or "project_memory" not in state):
            combined_memories: list[str] = []
            self.loaded_project_memory_sources = []

            for path in project_paths:
                with contextlib.suppress(OSError, UnicodeDecodeError):
                    content = path.read_text(encoding="utf-8")
                    if len(content) > MAX_MEMORY_CHARS:
                        content = content[:MAX_MEMORY_CHARS] + _MEMORY_TRUNCATION_NOTICE
                    if content.strip():
                        # Add header showing the source file
                        relative_path = (
                            path.relative_to(self.project_root) if self.project_root else path.name
                        )
                        combined_memories.append(f"<!-- Source: {relative_path} -->\n{content}")
                        self.loaded_project_memory_sources.append(str(relative_path))

            if combined_memories:
                result["project_memory"] = "\n\n---\n\n".join(combined_memories)

        # Record modification times after successful load
        self._record_mtimes(all_paths)

        return result

    def _build_system_prompt(self, request: ModelRequest) -> str:
        """Build the complete system prompt with memory sections.

        Args:
            request: The model request containing state and base system prompt.

        Returns:
            Complete system prompt with memory sections injected.
        """
        # Extract memory from state
        state = cast("AgentMemoryState", request.state)
        user_memory = state.get("user_memory")
        project_memory = state.get("project_memory")
        base_system_prompt = request.system_prompt

        # Build project memory info for documentation based on actually loaded files
        if self.project_root and self.loaded_project_memory_sources:
            sources_list = ", ".join(self.loaded_project_memory_sources)
            project_memory_info = f"`{self.project_root}` (loaded: {sources_list})"
        elif self.project_root:
            project_memory_info = f"`{self.project_root}` (no CLAUDE.md or Nova.md found)"
        else:
            project_memory_info = "None (not in a git project)"

        # Build project deepagents directory path (.claude or .Nova)
        if self.project_root:
            if (self.project_root / ".claude").exists():
                project_deepagents_dir = str(self.project_root / ".claude")
            elif (self.project_root / ".Nova").exists():
                project_deepagents_dir = str(self.project_root / ".Nova")
            else:
                project_deepagents_dir = "[project-root]/(.claude or .Nova not found)"
        else:
            project_deepagents_dir = "[project-root]/(.claude or .Nova not in a project)"

        # Format memory section with both memories
        memory_section = self.system_prompt_template.format(
            user_memory=user_memory if user_memory else "(No user agent.md)",
            project_memory=(
                project_memory if project_memory else "(No project CLAUDE.md or Nova.md)"
            ),
        )

        system_prompt = memory_section

        if base_system_prompt:
            system_prompt += "\n\n" + base_system_prompt

        system_prompt += "\n\n" + render_template(
            "longterm_memory.jinja",
            agent_dir_absolute=self.agent_dir_absolute,
            agent_dir_display=self.agent_dir_display,
            project_memory_info=project_memory_info,
            project_deepagents_dir=project_deepagents_dir,
        )

        return system_prompt

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        """Inject agent memory into the system prompt.

        Args:
            request: The model request being processed.
            handler: The handler function to call with the modified request.

        Returns:
            The model response from the handler.
        """
        system_prompt = self._build_system_prompt(request)
        return handler(request.override(system_prompt=system_prompt))  # type: ignore

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        """(async) Inject agent memory into the system prompt.

        Args:
            request: The model request being processed.
            handler: The handler function to call with the modified request.

        Returns:
            The model response from the handler.
        """
        system_prompt = self._build_system_prompt(request)
        return await handler(request.override(system_prompt=system_prompt))  # type: ignore

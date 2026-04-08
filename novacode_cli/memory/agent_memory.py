"""Middleware for loading agent-specific long-term memory into the system prompt."""

import contextlib
import os
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, TypedDict, cast

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
    
    When a sandbox backend is provided, memory files are read from the sandbox
    instead of the local filesystem.
    """

    state_schema = AgentMemoryState

    def __init__(
        self,
        *,
        settings: Settings,
        assistant_id: str,
        system_prompt_template: str | None = None,
        skip_project_memory: bool = False,
        backend: Any = None,
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
            backend: Optional sandbox backend for reading files from sandbox.
                When provided, memory files are read from the sandbox instead
                of the local filesystem.
        """
        self.settings = settings
        self.assistant_id = assistant_id
        self.skip_project_memory = skip_project_memory
        self._backend = backend

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
        # Cache for rendered memory section to avoid re-rendering on every request
        self._memory_section_cache: str | None = None
        self._memory_section_cache_time: float = 0
        self._memory_section_cache_ttl: float = 30.0  # 30 seconds TTL

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

    def _supports_sandbox_file_ops(self) -> bool:
        """Check if the backend supports file operations.
        
        Returns:
            True if backend implements file read operations.
        """
        if self._backend is None:
            return False
        
        # Check if backend has read method (BackendProtocol provides this)
        return hasattr(self._backend, 'read') and callable(getattr(self._backend, 'read', None))

    def _read_file(self, path: Path) -> str | None:
        """Read file content from local filesystem or sandbox.
        
        When a sandbox backend is provided and supports file operations,
        reads from the sandbox. Otherwise reads from local filesystem.
        
        Args:
            path: Path to the file to read.
            
        Returns:
            File content as string, or None if file doesn't exist or can't be read.
        """
        # Try sandbox first if available
        if self._supports_sandbox_file_ops():
            try:
                # Use sandbox backend's read method
                # The read method returns content with line numbers (cat -n format)
                result = self._backend.read(str(path))
                if result and isinstance(result, str):
                    # Check for error responses
                    if result.startswith("Error:") or result.startswith("error:"):
                        # File doesn't exist in sandbox, fall back to local
                        pass
                    else:
                        return result
            except Exception:
                # Fall back to local filesystem
                pass
        
        # Local filesystem read
        try:
            if path.exists():
                return path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            pass
        
        return None

    def _read_file_local(self, path: Path) -> str | None:
        """Read file content from local filesystem only.
        
        Used for user memory files that are stored locally and not synced to sandbox.
        
        Args:
            path: Path to the file to read.
            
        Returns:
            File content as string, or None if file doesn't exist or can't be read.
        """
        try:
            if path.exists():
                return path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            pass
        
        return None

    def _read_file_sandbox(self, path: Path) -> str | None:
        """Read file content from sandbox only.
        
        Used for project memory files that should be read from sandbox when available.
        
        Args:
            path: Path to the file to read.
            
        Returns:
            File content as string, or None if file doesn't exist or can't be read.
        """
        if not self._supports_sandbox_file_ops():
            # No sandbox available, fall back to local
            return self._read_file_local(path)
        
        try:
            # Use sandbox backend's read method
            result = self._backend.read(str(path))
            if result and isinstance(result, str):
                # Check for error responses
                if result.startswith("Error:") or result.startswith("error:"):
                    return None
                return result
        except Exception:
            pass
        
        return None

    def _file_exists(self, path: Path) -> bool:
        """Check if file exists in local filesystem or sandbox.
        
        Args:
            path: Path to check.
            
        Returns:
            True if file exists, False otherwise.
        """
        # Try sandbox first if available
        if self._supports_sandbox_file_ops():
            try:
                # Use sandbox backend's ls_info method to check existence
                if hasattr(self._backend, 'ls_info'):
                    parent_dir = str(path.parent)
                    result = self._backend.ls_info(parent_dir)
                    if result and isinstance(result, list):
                        # Check if our file is in the listing
                        for item in result:
                            if isinstance(item, dict) and item.get('path') == str(path):
                                return True
                # Try to read the file - if it succeeds, it exists
                content = self._read_file(path)
                return content is not None
            except Exception:
                pass
        
        # Local filesystem check
        return path.exists()

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
        
        When a sandbox backend is provided:
        - User memory files (~/.Nova/{agent}/agent.md) are ALWAYS read from local
          filesystem since they're not synced to the sandbox
        - Project memory files ({project_root}/.nova/NOVA.md) are read from the
          sandbox when available

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

        # Check if any files have changed (hot-reload) - only for local filesystem
        # In sandbox mode, we always reload since we can't track mtimes
        needs_reload = self._files_changed(all_paths) if self._backend is None else True

        # Load user memory if not in state or if file changed
        # User memory is ALWAYS read from local filesystem (not synced to sandbox)
        if needs_reload or "user_memory" not in state:
            content = self._read_file_local(user_path)
            if content is not None:
                if len(content) > MAX_MEMORY_CHARS:
                    content = content[:MAX_MEMORY_CHARS] + _MEMORY_TRUNCATION_NOTICE
                result["user_memory"] = content

        # Load project memory from ALL available sources if not in state or if files changed
        # Project memory is read from sandbox when available, local otherwise
        if not self.skip_project_memory and (needs_reload or "project_memory" not in state):
            combined_memories: list[str] = []
            self.loaded_project_memory_sources = []

            for path in project_paths:
                # Read project memory from sandbox if available, local otherwise
                content = self._read_file_sandbox(path)
                if content is not None:
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

        # Record modification times after successful load (local only)
        if self._backend is None:
            self._record_mtimes(all_paths)

        return result

    def _build_system_prompt(self, request: ModelRequest) -> str:
        """Build the complete system prompt with memory sections.

        Args:
            request: The model request containing state and base system prompt.

        Returns:
            Complete system prompt with memory sections injected.
        """
        import time
        
        # Extract memory from state
        state = cast("AgentMemoryState", request.state)
        user_memory = state.get("user_memory")
        project_memory = state.get("project_memory")
        base_system_prompt = request.system_prompt
        
        current_time = time.time()
        
        # Check if we can use cached memory section (sliding window)
        # Cache is valid if: TTL not expired AND memory content hasn't changed
        memory_content = (user_memory or "", project_memory or "")
        can_use_cache = (
            self._memory_section_cache is not None
            and current_time - self._memory_section_cache_time < self._memory_section_cache_ttl
            and (self._cached_user_memory or "") == memory_content[0]
            and (self._cached_project_memory or "") == memory_content[1]
        )
        
        if can_use_cache:
            # Sliding window: reset timer on access to keep cache alive during active use
            self._memory_section_cache_time = current_time
            memory_section = self._memory_section_cache
        else:
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
            
            # Add longterm memory template
            memory_section += "\n\n" + render_template(
                "longterm_memory.jinja",
                agent_dir_absolute=self.agent_dir_absolute,
                agent_dir_display=self.agent_dir_display,
                project_memory_info=project_memory_info,
                project_deepagents_dir=project_deepagents_dir,
            )
            
            # Cache the result
            self._memory_section_cache = memory_section
            self._memory_section_cache_time = current_time
            self._cached_user_memory = memory_content[0]
            self._cached_project_memory = memory_content[1]

        # memory_section is guaranteed to be set at this point
        assert memory_section is not None
        system_prompt: str = memory_section

        if base_system_prompt:
            system_prompt += "\n\n" + base_system_prompt

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

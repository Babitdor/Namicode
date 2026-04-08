"""Middleware for loading and exposing agent skills to the system prompt.

This middleware implements Anthropic's "Agent Skills" pattern with progressive disclosure:
1. Parse YAML frontmatter from SKILL.md files at session start
2. Inject skills metadata (name + description) into system prompt
3. Agent reads full SKILL.md content when relevant to a task

Skills directory structure (per-agent + project):
User-level: ~/.Nova/{AGENT_NAME}/skills/
Project-level: {PROJECT_ROOT}/.Nova/skills/

Example structure:
~/.Nova/{AGENT_NAME}/skills/
├── web-research/
│   ├── SKILL.md        # Required: YAML frontmatter + instructions
│   └── helper.py       # Optional: supporting files
├── code-review/
│   ├── SKILL.md
│   └── checklist.md

.Nova/skills/
├── project-specific/
│   └── SKILL.md        # Project-specific skills
"""

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import NotRequired, TypedDict, cast

from langchain.agents.middleware.types import (
    AgentMiddleware,
    AgentState,
    ModelRequest,
    ModelResponse,
)
from langgraph.runtime import Runtime

from novacode_cli.prompts import render_template
from novacode_cli.skills.load import ExtendedSkillMetadata, SkillMetadata, list_skills

# Context tracking for middleware optimization
try:
    from novacode_cli.utils.context_tracking import track_context, track_context_async
    CONTEXT_TRACKING_AVAILABLE = True
except ImportError:
    CONTEXT_TRACKING_AVAILABLE = False
    # Fallback: create no-op decorators
    def track_context(name):
        def decorator(func):
            return func
        return decorator
    def track_context_async(name):
        def decorator(func):
            return func
        return decorator


class SkillsState(AgentState):
    """State for the skills middleware."""

    skills_metadata: NotRequired[list[ExtendedSkillMetadata]]
    """List of loaded skill metadata (name, description, path, source)."""


class SkillsStateUpdate(TypedDict):
    """State update for the skills middleware."""

    skills_metadata: list[ExtendedSkillMetadata]
    """List of loaded skill metadata (name, description, path, source)."""


# Skills System Documentation - loaded from: NovaCode_cli/prompts/skills.jinja


class SkillsMiddleware(AgentMiddleware):
    """Middleware for loading and exposing agent skills.

    This middleware implements Anthropic's agent skills pattern:
    - Loads skills metadata (name, description) from YAML frontmatter at session start
    - Injects skills list into system prompt for discoverability
    - Agent reads full SKILL.md content when a skill is relevant (progressive disclosure)

    Supports both user-level and project-level skills:
    - User skills: ~/.Nova/{AGENT_NAME}/skills/
    - Project skills: {PROJECT_ROOT}/.Nova/skills/
    - Project skills override user skills with the same name

    Args:
        skills_dir: Path to the user-level skills directory (per-agent).
        assistant_id: The agent identifier for path references in prompts.
        project_skills_dir: Optional path to project-level skills directory.
    """

    state_schema = SkillsState

    def __init__(
        self,
        *,
        skills_dir: str | Path,
        assistant_id: str,
        project_skills_dir: str | Path | None = None,
        project_skills_dirs: list[Path] | None = None,
    ) -> None:
        """Initialize the skills middleware.

        Args:
            skills_dir: Path to the user-level skills directory.
            assistant_id: The agent identifier.
            project_skills_dir: Optional path to a single project-level skills directory (deprecated).
            project_skills_dirs: Optional list of project-level skills directories (preferred).
        """
        self.skills_dir = Path(skills_dir).expanduser()
        self.assistant_id = assistant_id
        self.project_skills_dir = (
            Path(project_skills_dir).expanduser() if project_skills_dir else None
        )
        self.project_skills_dirs = project_skills_dirs or []
        # Store display paths for prompts
        self.user_skills_display = f"~/.Nova/{assistant_id}/skills"
        # Cache for rendered skills section to avoid re-rendering on every request
        self._skills_section_cache: str | None = None
        self._skills_section_cache_time: float = 0
        self._skills_section_cache_ttl: float = 30.0  # 30 seconds TTL
        self._skills_section_cache_metadata: tuple = ()  # Track what was cached

    @property
    def skills_dir_display(self) -> str:
        """Get a human-friendly display path for the skills directory.

        Returns:
            Display path using ~ notation for home directory.
        """
        # Use the per-agent path format
        return f"~/.Nova/{self.assistant_id}/skills"

    @property
    def skills_dir_absolute(self) -> str:
        """Get the absolute path to the skills directory.

        Returns:
            Absolute path as string.
        """
        return str(self.skills_dir)

    def _format_skills_locations(self) -> str:
        """Format skills locations for display in system prompt."""
        locations = [f"**User Skills**: `{self.user_skills_display}`"]

        # Support both single and multiple project directories
        project_dirs = self.project_skills_dirs if self.project_skills_dirs else []
        if self.project_skills_dir:
            project_dirs.append(self.project_skills_dir)

        if project_dirs:
            locations.append("**Project Skills** (override user skills):")
            for proj_dir in project_dirs:
                locations.append(f"  - `{proj_dir}`")

        return "\n".join(locations)

    def _format_skills_list(self, skills: list[ExtendedSkillMetadata]) -> str:
        """Format skills metadata for display in system prompt.
        
        Uses O(n) algorithm with single pass grouping.
        """
        if not skills:
            locations = [f"{self.user_skills_display}/"]
            if self.project_skills_dir:
                locations.append(f"{self.project_skills_dir}/")
            return f"(No skills available yet. You can create skills in {' or '.join(locations)})"

        # O(n) - Group skills by source in single pass
        user_skills: list[SkillMetadata] = []
        project_skills: list[SkillMetadata] = []
        
        for skill in skills:
            if skill["source"] == "user": # type: ignore
                user_skills.append(skill)
            else:
                project_skills.append(skill)

        lines = []

        # Show user skills
        if user_skills:
            lines.append("**User Skills:**")
            for skill in user_skills:
                lines.append(f"- **{skill['name']}**: {skill['description']}")
                lines.append(f"  → Read `{skill['path']}` for full instructions")
            lines.append("")

        # Show project skills
        if project_skills:
            lines.append("**Project Skills:**")
            for skill in project_skills:
                lines.append(f"- **{skill['name']}**: {skill['description']}")
                lines.append(f"  → Read `{skill['path']}` for full instructions")

        return "\n".join(lines)

    def before_agent(
        self, state: SkillsState, runtime: Runtime
    ) -> SkillsStateUpdate | None:
        """Load skills metadata before agent execution.

        This runs once at session start to discover available skills from both
        user-level and project-level directories.

        Args:
            state: Current agent state.
            runtime: Runtime context.

        Returns:
            Updated state with skills_metadata populated.
        """
        # We re-load skills on every new interaction with the agent to capture
        # any changes in the skills directories.
        # list_skills accepts only one project dir at a time; for multiple dirs
        # merge incrementally so later dirs take precedence.
        if self.project_skills_dirs:
            merged: dict[str, object] = {
                s["name"]: s  # type: ignore[index]
                for s in list_skills(
                    user_skills_dir=self.skills_dir, project_skills_dir=None
                )
            }
            for proj_dir in self.project_skills_dirs:
                for s in list_skills(user_skills_dir=None, project_skills_dir=proj_dir):
                    merged[s["name"]] = s  # type: ignore[index]
            skills = list(merged.values())  # type: ignore[assignment]
        else:
            skills = list_skills(
                user_skills_dir=self.skills_dir,
                project_skills_dir=self.project_skills_dir,
            )
        return SkillsStateUpdate(skills_metadata=skills) # type: ignore

    def _get_skills_section(self, skills_metadata: list[ExtendedSkillMetadata]) -> str:
        """Get skills section with caching.

        Args:
            skills_metadata: List of skill metadata.

        Returns:
            Rendered skills section string.
        """
        import time
        current_time = time.time()
        
        # Create a cache key from the metadata
        cache_key = tuple((s["name"], s["source"]) for s in skills_metadata)
        
        # Use cached section if still valid and metadata hasn't changed (sliding window)
        if (
            self._skills_section_cache is not None
            and current_time - self._skills_section_cache_time < self._skills_section_cache_ttl
            and self._skills_section_cache_metadata == cache_key
        ):
            # Sliding window: reset timer on access to keep cache alive during active use
            self._skills_section_cache_time = current_time
            return self._skills_section_cache
        
        # Format skills locations and list
        skills_locations = self._format_skills_locations()
        skills_list = self._format_skills_list(skills_metadata)

        # Format the skills documentation using Jinja template
        skills_section = render_template(
            "skills.jinja",
            skills_locations=skills_locations,
            skills_list=skills_list,
        )
        
        # Cache the result
        self._skills_section_cache = skills_section
        self._skills_section_cache_time = current_time
        self._skills_section_cache_metadata = cache_key
        
        return skills_section

    @track_context("SkillsMiddleware")
    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        """Inject skills documentation into the system prompt.

        This runs on every model call to ensure skills info is always available.

        Args:
            request: The model request being processed.
            handler: The handler function to call with the modified request.

        Returns:
            The model response from the handler.
        """
        # Get skills metadata from state
        skills_metadata = request.state.get("skills_metadata", [])

        # Get skills section with caching
        skills_section = self._get_skills_section(skills_metadata)

        if request.system_prompt:
            system_prompt = request.system_prompt + "\n\n" + skills_section
        else:
            system_prompt = skills_section

        return handler(request.override(system_prompt=system_prompt))  # type: ignore

    @track_context_async("SkillsMiddleware")
    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        """(async) Inject skills documentation into the system prompt.

        Args:
            request: The model request being processed.
            handler: The handler function to call with the modified request.

        Returns:
            The model response from the handler.
        """
        # The state is guaranteed to be SkillsState due to state_schema
        state = cast("SkillsState", request.state)
        skills_metadata = state.get("skills_metadata", [])

        # Get skills section with caching
        skills_section = self._get_skills_section(skills_metadata)

        # Inject into system prompt
        if request.system_prompt:
            system_prompt = request.system_prompt + "\n\n" + skills_section
        else:
            system_prompt = skills_section

        return await handler(request.override(system_prompt=system_prompt))  # type: ignore

"""Middleware for loading and exposing agent skills to the system prompt.

This middleware implements Anthropic's "Agent Skills" pattern with progressive disclosure:
1. Parse YAML frontmatter from SKILL.md files at session start
2. Inject skills metadata (name + description) into system prompt
3. Agent reads full SKILL.md content when relevant to a task

Skills directory structure (per-agent + project):
User-level: ~/.nami/{AGENT_NAME}/skills/
Project-level: {PROJECT_ROOT}/.nami/skills/

Example structure:
~/.nami/{AGENT_NAME}/skills/
├── web-research/
│   ├── SKILL.md        # Required: YAML frontmatter + instructions
│   └── helper.py       # Optional: supporting files
├── code-review/
│   ├── SKILL.md
│   └── checklist.md

.nami/skills/
├── project-specific/
│   └── SKILL.md        # Project-specific skills
"""

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, NotRequired, TypedDict, cast

from langchain.agents.middleware.types import (
    AgentMiddleware,
    AgentState,
    ModelRequest,
    ModelResponse,
)
from langgraph.runtime import Runtime

from namicode_cli.skills.load import SkillMetadata, list_skills


class SkillsState(AgentState):
    """State for the skills middleware."""

    skills_metadata: NotRequired[list[SkillMetadata]]
    """List of loaded skill metadata (name, description, path)."""


class SkillsStateUpdate(TypedDict):
    """State update for the skills middleware."""

    skills_metadata: list[SkillMetadata]
    """List of loaded skill metadata (name, description, path)."""


# Skills System Documentation
SKILLS_SYSTEM_PROMPT = """

## Skills System

You have access to a skills library that provides specialized capabilities and domain knowledge.

{skills_locations}

**Available Skills:**

{skills_list}

---

### Skills-First Protocol (MANDATORY)

**Before starting ANY non-trivial task**, scan the available skills list above and ask:
> "Does any skill's description match what the user is asking for?"

If yes → read that skill's SKILL.md **immediately** using `read_file`, then follow its instructions exactly.
If no → proceed with your default approach.

This check must happen before you write any code, run any commands, or perform any research.

**Pattern matching — treat these as triggers:**

| User asks about… | Look for a skill named like… |
|-----------------|------------------------------|
| research / web search / finding info | `web-research`, `research` |
| reviewing / auditing code | `code-review`, `review` |
| writing tests | `test-writing`, `testing` |
| deploying / CI / infrastructure | `deployment`, `ci-cd` |
| documentation | `docs`, `documentation` |
| git / version control | `git-workflow`, `git` |
| performance / profiling | `performance` |
| security / vulnerabilities | `security-audit` |
| anything with a named workflow | match the workflow name |

**How skills work (progressive disclosure):**

1. You see the skill's name + description in the list above
2. You call `read_file` on the path shown (e.g., `read_file("/path/to/SKILL.md")`)
3. SKILL.md contains the full workflow, rules, and examples
4. Follow those instructions precisely — they encode proven patterns for that domain
5. Skills may include helper scripts in `scripts/` — always use absolute paths

**Skills override your defaults.** If a skill covers the task, its instructions take precedence over general reasoning. The skill was written specifically for that scenario.
"""


class SkillsMiddleware(AgentMiddleware):
    """Middleware for loading and exposing agent skills.

    This middleware implements Anthropic's agent skills pattern:
    - Loads skills metadata (name, description) from YAML frontmatter at session start
    - Injects skills list into system prompt for discoverability
    - Agent reads full SKILL.md content when a skill is relevant (progressive disclosure)

    Supports both user-level and project-level skills:
    - User skills: ~/.nami/{AGENT_NAME}/skills/
    - Project skills: {PROJECT_ROOT}/.nami/skills/
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
        self.user_skills_display = f"~/.nami/{assistant_id}/skills"
        self.system_prompt_template = SKILLS_SYSTEM_PROMPT

    @property
    def skills_dir_display(self) -> str:
        """Get a human-friendly display path for the skills directory.

        Returns:
            Display path using ~ notation for home directory.
        """
        # Use the per-agent path format
        return f"~/.nami/{self.assistant_id}/skills"

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

    def _format_skills_list(self, skills: list[SkillMetadata]) -> str:
        """Format skills metadata for display in system prompt."""
        if not skills:
            locations = [f"{self.user_skills_display}/"]
            if self.project_skills_dir:
                locations.append(f"{self.project_skills_dir}/")
            return f"(No skills available yet. You can create skills in {' or '.join(locations)})"

        # Group skills by source
        user_skills = [s for s in skills if s["source"] == "user"]
        project_skills = [s for s in skills if s["source"] == "project"]

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

    def before_agent(self, state: SkillsState, runtime: Runtime) -> SkillsStateUpdate | None:
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
        skills = list_skills(
            user_skills_dir=self.skills_dir,
            project_skills_dir=self.project_skills_dir,
            project_skills_dirs=self.project_skills_dirs if self.project_skills_dirs else None,
        )
        return SkillsStateUpdate(skills_metadata=skills)

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

        # Format skills locations and list
        skills_locations = self._format_skills_locations()
        skills_list = self._format_skills_list(skills_metadata)

        # Format the skills documentation
        skills_section = self.system_prompt_template.format(
            skills_locations=skills_locations,
            skills_list=skills_list,
        )

        if request.system_prompt:
            system_prompt = request.system_prompt + "\n\n" + skills_section
        else:
            system_prompt = skills_section

        return handler(request.override(system_prompt=system_prompt)) # type: ignore

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

        # Format skills locations and list
        skills_locations = self._format_skills_locations()
        skills_list = self._format_skills_list(skills_metadata)

        # Format the skills documentation
        skills_section = self.system_prompt_template.format(
            skills_locations=skills_locations,
            skills_list=skills_list,
        )

        # Inject into system prompt
        if request.system_prompt:
            system_prompt = request.system_prompt + "\n\n" + skills_section
        else:
            system_prompt = skills_section

        return await handler(request.override(system_prompt=system_prompt)) # type: ignore

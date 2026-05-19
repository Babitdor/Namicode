"""Skill loader for parsing and loading agent skills from SKILL.md files.

This module implements Anthropic's agent skills pattern with YAML frontmatter parsing.
Each skill is a directory containing a SKILL.md file with:
- YAML frontmatter (name, description required)
- Markdown instructions for the agent
- Optional supporting files (scripts, configs, etc.)

Example SKILL.md structure:
```markdown
---
name: web-research
description: Structured approach to conducting thorough web research
---

# Web Research Skill

## When to Use
- User asks you to research a topic
...
```
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from deepagents.backends.filesystem import FilesystemBackend
from deepagents.middleware.skills import SkillMetadata
from deepagents.middleware.skills import _list_skills as list_skills_from_backend

if TYPE_CHECKING:
    from pathlib import Path

# Maximum size for SKILL.md files (10MB)
MAX_SKILL_FILE_SIZE = 10 * 1024 * 1024

# Re-export for CLI commands
__all__ = ["SkillMetadata", "list_skills"]


def list_skills(
    *, user_skills_dir: Path | None = None, project_skills_dir: Path | None = None
) -> list[SkillMetadata]:
    """List skills from user and/or project directories.

    This is a CLI-specific wrapper around the prebuilt middleware's skill loading
    functionality. It uses FilesystemBackend to load skills from local directories.

    When both directories are provided, project skills with the same name as
    user skills will override them (project skills take precedence).

    Args:
        user_skills_dir: Path to the user-level skills directory.
        project_skills_dir: Path to the project-level skills directory.

    Returns:
        Merged list of skill metadata from both sources, with project skills
        taking precedence over user skills when names conflict. Each skill
        includes a 'source' field indicating its origin ('user' or 'project').
    """
    all_skills: dict[str, SkillMetadata] = {}

    # Load user skills first (foundation)
    if user_skills_dir and user_skills_dir.exists():
        user_backend = FilesystemBackend(root_dir=str(user_skills_dir), virtual_mode=True)
        user_skills = list_skills_from_backend(
            backend=user_backend, source_path="."
        )
        for skill in user_skills:
            skill["source"] = "user"  # type: ignore[typeddict-unknown-key]
            all_skills[skill["name"]] = skill

    # Load project skills second (override/augment)
    if project_skills_dir and project_skills_dir.exists():
        project_backend = FilesystemBackend(root_dir=str(project_skills_dir), virtual_mode=True)
        project_skills = list_skills_from_backend(
            backend=project_backend, source_path="."
        )
        for skill in project_skills:
            skill["source"] = "project"  # type: ignore[typeddict-unknown-key]
            all_skills[skill["name"]] = skill

    return list(all_skills.values())

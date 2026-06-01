"""Skills module for deepagents CLI.

Public API:
- SkillsMiddleware: Middleware for integrating skills into agent execution
- list_skills: List available skills from user and project directories
- SkillMetadata: Metadata for a skill

All other components are internal implementation details.
"""

from novacode_cli.skills.load import SkillMetadata, list_skills

# Re-export SkillsMiddleware from core library for convenience
from deepagents.middleware.skills import SkillsMiddleware

__all__ = [
    "SkillsMiddleware",
    "SkillMetadata",
    "list_skills",
]

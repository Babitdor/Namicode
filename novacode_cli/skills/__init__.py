"""Skills module for deepagents CLI.

Public API:
- SkillsMiddleware: Middleware for integrating skills into agent execution
- list_skills: List available skills from user and project directories
- SkillMetadata: Metadata for a skill

All other components are internal implementation details.
"""

from novacode_cli.skills.load import SkillMetadata, list_skills

# Re-export SkillsMiddleware from core library for convenience. Imported lazily
# so importing this package doesn't pull in deepagents (~4s) at CLI startup.
def __getattr__(name: str):
    if name == "SkillsMiddleware":
        from deepagents.middleware.skills import SkillsMiddleware

        return SkillsMiddleware
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "SkillsMiddleware",
    "SkillMetadata",
    "list_skills",
]

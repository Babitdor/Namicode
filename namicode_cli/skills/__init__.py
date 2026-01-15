"""Skills module for deepagents CLI.

Public API:
- SkillsMiddleware: Middleware for integrating skills into agent execution
- execute_skills_command: Execute skills subcommands (list/create/info)
- setup_skills_parser: Setup argparse configuration for skills commands

All other components are internal implementation details.
"""

from namicode_cli.skills.middleware import SkillsMiddleware
__all__ = [
    "SkillsMiddleware",
]

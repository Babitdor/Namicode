"""DeepAgents package."""

from nami_deepagents.graph import create_deep_agent
from nami_deepagents.middleware.filesystem import FilesystemMiddleware
from nami_deepagents.middleware.subagents import (
    CompiledSubAgent,
    SubAgent,
    SubAgentMiddleware,
    get_subagent_color,
    set_subagent_color,
    get_all_subagent_colors,
    clear_subagent_colors,
)

__all__ = [
    "CompiledSubAgent",
    "FilesystemMiddleware",
    "SubAgent",
    "SubAgentMiddleware",
    "create_deep_agent",
    "get_subagent_color",
    "set_subagent_color",
    "get_all_subagent_colors",
    "clear_subagent_colors",
]

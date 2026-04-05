"""DeepAgents package."""

from nova_deepagents.graph import create_deep_agent
from nova_deepagents.middleware.filesystem import FilesystemMiddleware
from nova_deepagents.middleware.memory import MemoryMiddleware
from nova_deepagents.middleware.subagents import (
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
    "MemoryMiddleware",
    "SubAgentMiddleware",
    "create_deep_agent",
    "get_subagent_color",
    "set_subagent_color",
    "get_all_subagent_colors",
    "clear_subagent_colors",
]

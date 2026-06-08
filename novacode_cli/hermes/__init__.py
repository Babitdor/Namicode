"""Nova autonomous learning and memory system for Nova-Code CLI.

Provides middleware, memory tiers, and skill discovery for continuous
self-improvement. Follows the same AgentMiddleware pattern as
AgentMemoryMiddleware and SteeringMiddleware.
"""

from novacode_cli.hermes.memory_tiers import (
    compact_memory_file,
    ensure_memory_tiers,
    update_session_memory,
    update_user_memory,
)
from novacode_cli.hermes.middleware import NovaLearningMiddleware
from novacode_cli.hermes.review import ReviewRunner
from novacode_cli.hermes.skill_discovery import (
    analyze_tool_history,
    check_skill_effectiveness,
    create_skill_from_pattern,
    refine_skill,
)
from novacode_cli.hermes.skill_manager import SkillManager
from novacode_cli.hermes.tracker import ToolUsageTracker

__all__ = [
    "NovaLearningMiddleware",
    "ReviewRunner",
    "SkillManager",
    "ToolUsageTracker",
    "ensure_memory_tiers",
    "compact_memory_file",
    "update_user_memory",
    "update_session_memory",
    "analyze_tool_history",
    "check_skill_effectiveness",
    "create_skill_from_pattern",
    "refine_skill",
]
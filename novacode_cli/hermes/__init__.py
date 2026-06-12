"""Nova autonomous learning and memory system for Nova-Code CLI.

Provides middleware, memory tiers, and skill discovery for continuous
self-improvement. Follows the same AgentMiddleware pattern as
AgentMemoryMiddleware and SteeringMiddleware.
"""

from novacode_cli.hermes.evolution import EvolutionEngine, score_task_complexity
from novacode_cli.hermes.memory_tiers import (
    compact_memory_file,
    ensure_memory_tiers,
    migrate_legacy_tiers,
    record_lesson,
    update_user_model,
)
from novacode_cli.hermes.middleware import NovaLearningMiddleware
from novacode_cli.hermes.review import ReviewRunner
from novacode_cli.hermes.skill_discovery import (
    check_skill_effectiveness,
    refine_skill,
)
from novacode_cli.hermes.skill_manager import SkillManager
from novacode_cli.hermes.tracker import ToolUsageTracker

__all__ = [
    "NovaLearningMiddleware",
    "ReviewRunner",
    "SkillManager",
    "ToolUsageTracker",
    "EvolutionEngine",
    "score_task_complexity",
    "ensure_memory_tiers",
    "compact_memory_file",
    "update_user_model",
    "record_lesson",
    "migrate_legacy_tiers",
    "check_skill_effectiveness",
    "refine_skill",
]

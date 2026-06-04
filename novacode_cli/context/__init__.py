"""Context-window management for NovaCode-cli.

One deep package, one public interface. ``ContextManager`` is the single entry
point for token breakdowns, window sizing, compaction recommendations, model
config lookup, the middleware budget tracker, and conversation digests. The data
types it returns are re-exported here for type annotations and pattern matching;
the implementation modules (``_analysis``, ``_budget``, ``_model_config``,
``_dynamic``, ``_conversation``) are private to the package.
"""

from novacode_cli.context._analysis import (
    CONTEXT_CRITICAL_THRESHOLD,
    CONTEXT_WARNING_THRESHOLD,
    CompactionRecommendation,
    CompactionResult,
    ContextBreakdown,
)
from novacode_cli.context._budget import ContextBudget
from novacode_cli.context._model_config import ModelConfig
from novacode_cli.context.manager import ContextManager

__all__ = [
    "ContextManager",
    # Data types
    "ContextBreakdown",
    "CompactionResult",
    "CompactionRecommendation",
    "ContextBudget",
    "ModelConfig",
    # Threshold constants
    "CONTEXT_WARNING_THRESHOLD",
    "CONTEXT_CRITICAL_THRESHOLD",
]

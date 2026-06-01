"""Integration example for context optimization utilities.

This module demonstrates how to use context tracking, growth monitoring,
eviction, and lazy loading together for optimal context management.
"""

import logging
from typing import Any

from novacode_cli.utils.context_budget import get_context_budget, reset_context_budget
from novacode_cli.utils.context_eviction import smart_evict
from novacode_cli.utils.context_growth_tracker import get_growth_tracker
from novacode_cli.utils.lazy_middleware import (
    ConditionalMiddleware,
    has_file_operations,
    has_memory_operations,
    has_skills,
    has_subagents,
)

logger = logging.getLogger(__name__)


class ContextOptimizedAgent:
    """Example agent with integrated context optimization.

    This demonstrates how to use all context optimization utilities:
    1. Context budget tracking
    2. Growth monitoring
    3. Automatic eviction
    4. Lazy/conditional middleware loading
    """

    def __init__(
        self,
        max_tokens: int = 50000,
        growth_threshold: float = 500.0,
        eviction_threshold: float = 0.7,
    ):
        """Initialize context-optimized agent.

        Args:
            max_tokens: Maximum context budget
            growth_threshold: Alert if growth exceeds this per turn
            eviction_threshold: Trigger eviction at this fraction of budget
        """
        # Initialize context budget
        self.budget = get_context_budget(max_tokens)

        # Initialize growth tracker
        self.growth_tracker = get_growth_tracker(
            max_tokens=max_tokens,
            growth_threshold=growth_threshold,
            eviction_threshold=eviction_threshold,
        )

        # Initialize lazy middleware loaders
        self.middleware = self._setup_middleware()

        logger.info(
            f"Initialized ContextOptimizedAgent with {max_tokens} token budget, "
            f"growth threshold {growth_threshold}, eviction threshold {eviction_threshold}"
        )

    def _setup_middleware(self) -> dict[str, Any]:
        """Setup middleware with lazy/conditional loading.

        Returns:
            Dictionary of middleware loaders
        """
        # Import middleware classes (lazy import)
        try:
            from deepagents.middleware.filesystem import FilesystemMiddleware
            from deepagents.middleware.skills import SkillsMiddleware
            from deepagents.middleware.subagents import SubAgentMiddleware

            # Conditional middleware - load only when needed
            middleware = {
                "filesystem": ConditionalMiddleware(
                    FilesystemMiddleware,
                    condition=has_file_operations,
                ),
                "skills": ConditionalMiddleware(
                    SkillsMiddleware,
                    condition=has_skills,
                ),
                "subagents": ConditionalMiddleware(
                    SubAgentMiddleware,
                    condition=has_subagents,
                ),
            }

            logger.info("Initialized conditional middleware loaders")
            return middleware

        except ImportError as e:
            logger.warning(f"Could not import middleware: {e}")
            return {}

    def process_request(self, request: Any, handler: Any) -> Any:
        """Process request with context optimization.

        This method demonstrates the full optimization pipeline:
        1. Track context before processing
        2. Apply middleware conditionally
        3. Track context after processing
        4. Monitor growth
        5. Trigger eviction if needed

        Args:
            request: Model request
            handler: Handler function

        Returns:
            Model response
        """
        # Reset budget for new request
        reset_context_budget()
        self.budget = get_context_budget()

        # Track initial context
        initial_context = getattr(request, "system_prompt", "")
        initial_tokens = self.budget._count_tokens(initial_context)

        logger.debug(f"Initial context: {initial_tokens} tokens")

        # Apply middleware conditionally
        for name, middleware in self.middleware.items():
            if hasattr(middleware, "is_loaded") and not middleware.is_loaded:
                logger.debug(f"Middleware {name} not loaded (condition not met)")
                continue

            # Track middleware context
            result = middleware.wrap_model_call(request, handler)
            request = result if result else request

        # Track final context
        final_context = getattr(request, "system_prompt", "")
        final_tokens = self.budget._count_tokens(final_context)

        # Track growth
        self.growth_tracker.track_turn(
            context_size=final_tokens,
            middleware_usage=self.budget.middleware_usage.copy(),
        )

        # Check if eviction needed
        if self.growth_tracker.should_evict():
            logger.warning("Context eviction triggered")
            request = self._evict_context(request)

        # Process with handler
        return handler(request)

    def _evict_context(self, request: Any) -> Any:
        """Evict context to reduce token usage.

        Args:
            request: Model request

        Returns:
            Modified request with evicted context
        """
        # Get eviction recommendation
        recommendation = self.growth_tracker.get_eviction_recommendation()

        if not recommendation["should_evict"]:
            return request

        # Evict old messages
        messages = getattr(request, "messages", [])
        if messages:
            evicted_messages = smart_evict(
                messages,
                target_tokens=recommendation["target_size"],
                current_tokens=recommendation["current_size"],
                strategy="balanced",
            )

            # Update request
            request = request.override(messages=evicted_messages)

            logger.info(
                f"Evicted {recommendation['turns_to_evict']} turns, "
                f"reduced context from {recommendation['current_size']} "
                f"to {recommendation['target_size']} tokens"
            )

        return request

    def get_optimization_report(self) -> dict[str, Any]:
        """Get comprehensive optimization report.

        Returns:
            Dictionary with optimization metrics and recommendations
        """
        budget_report = self.budget.get_usage_report()
        growth_report = self.growth_tracker.get_growth_report()

        # Check middleware loading status
        middleware_status = {}
        for name, middleware in self.middleware.items():
            if hasattr(middleware, "is_loaded"):
                middleware_status[name] = {
                    "loaded": middleware.is_loaded,
                    "type": "conditional",
                }
            else:
                middleware_status[name] = {
                    "loaded": True,
                    "type": "always",
                }

        return {
            "context_budget": budget_report,
            "growth_tracking": growth_report,
            "middleware_status": middleware_status,
            "recommendations": self._generate_recommendations(
                budget_report, growth_report
            ),
        }

    def _generate_recommendations(
        self,
        budget_report: dict[str, Any],
        growth_report: dict[str, Any],
    ) -> list[str]:
        """Generate optimization recommendations.

        Args:
            budget_report: Context budget report
            growth_report: Growth tracking report

        Returns:
            List of recommendation strings
        """
        recommendations = []

        # Budget-based recommendations
        if budget_report["percentage_used"] > 50:
            recommendations.append(
                "Context usage >50%. Consider implementing context eviction."
            )

        if budget_report["percentage_used"] > 70:
            recommendations.append(
                "Context usage >70%. Trigger context eviction immediately."
            )

        # Growth-based recommendations
        if growth_report.get("average_growth_per_turn", 0) > 500:
            recommendations.append(
                "High average growth detected. Implement lazy loading for middleware."
            )

        # Middleware-based recommendations
        unloaded_middleware = [
            name
            for name, status in self.middleware.items()
            if hasattr(status, "is_loaded") and not status.is_loaded
        ]

        if unloaded_middleware:
            recommendations.append(
                f"Lazy loading saved context for: {', '.join(unloaded_middleware)}"
            )

        # Top consumer recommendations
        if budget_report.get("top_consumers"):
            top_consumer = budget_report["top_consumers"][0]
            if top_consumer["tokens"] > budget_report["max_tokens"] * 0.1:
                recommendations.append(
                    f"{top_consumer['middleware']} uses >10% of budget. "
                    "Consider compression or lazy loading."
                )

        if not recommendations:
            recommendations.append(
                "Context optimization is healthy. Continue monitoring."
            )

        return recommendations


def create_optimized_agent(
    max_tokens: int = 50000,
    **kwargs: Any,
) -> ContextOptimizedAgent:
    """Create a context-optimized agent.

    Args:
        max_tokens: Maximum context budget
        **kwargs: Additional arguments for agent

    Returns:
        ContextOptimizedAgent instance
    """
    return ContextOptimizedAgent(max_tokens=max_tokens, **kwargs)


__all__ = [
    "ContextOptimizedAgent",
    "create_optimized_agent",
]

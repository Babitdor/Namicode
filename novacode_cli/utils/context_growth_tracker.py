"""Context growth tracking for monitoring context bloat over conversation turns.

This module provides utilities to track context growth per turn,
detect rapid growth, and alert when approaching budget limits.
"""

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class TurnMetrics:
    """Metrics for a single conversation turn."""
    
    turn_number: int
    timestamp: datetime
    context_size: int
    middleware_usage: dict[str, int]
    growth_rate: float = 0.0  # tokens added since last turn
    cumulative_growth: float = 0.0  # total growth rate


class ContextGrowthTracker:
    """Track context growth over conversation turns.
    
    This helps identify:
    - Rapid context growth patterns
    - Middleware that contributes most to growth
    - When to trigger context eviction
    """
    
    def __init__(
        self,
        max_tokens: int = 50000,
        growth_threshold: float = 500.0,  # tokens per turn
        eviction_threshold: float = 0.7,  # 70% of budget
    ):
        """Initialize context growth tracker.
        
        Args:
            max_tokens: Maximum context budget
            growth_threshold: Alert if growth exceeds this per turn
            eviction_threshold: Trigger eviction at this fraction of budget
        """
        self.max_tokens = max_tokens
        self.growth_threshold = growth_threshold
        self.eviction_threshold = eviction_threshold
        
        self.turns: list[TurnMetrics] = []
        self.current_turn = 0
        self.middleware_growth: dict[str, list[int]] = defaultdict(list)
    
    def track_turn(
        self,
        context_size: int,
        middleware_usage: dict[str, int],
    ) -> TurnMetrics:
        """Track context for a new conversation turn.
        
        Args:
            context_size: Total context size in tokens
            middleware_usage: Token usage per middleware
            
        Returns:
            TurnMetrics for this turn
        """
        self.current_turn += 1
        timestamp = datetime.now()
        
        # Calculate growth rate
        growth_rate = 0.0
        if self.turns:
            last_turn = self.turns[-1]
            growth_rate = context_size - last_turn.context_size
        
        # Calculate cumulative growth rate
        cumulative_growth = context_size / self.current_turn if self.current_turn > 0 else 0.0
        
        # Create turn metrics
        metrics = TurnMetrics(
            turn_number=self.current_turn,
            timestamp=timestamp,
            context_size=context_size,
            middleware_usage=middleware_usage.copy(),
            growth_rate=growth_rate,
            cumulative_growth=cumulative_growth,
        )
        
        self.turns.append(metrics)
        
        # Track middleware growth
        for middleware, tokens in middleware_usage.items():
            self.middleware_growth[middleware].append(tokens)
        
        # Check for alerts
        self._check_alerts(metrics)
        
        return metrics
    
    def _check_alerts(self, metrics: TurnMetrics) -> None:
        """Check for growth alerts and log warnings.
        
        Args:
            metrics: Current turn metrics
        """
        # Check rapid growth
        if metrics.growth_rate > self.growth_threshold:
            logger.warning(
                f"Rapid context growth detected: {metrics.growth_rate:.0f} tokens "
                f"in turn {metrics.turn_number} (threshold: {self.growth_threshold}). "
                f"Consider context eviction or compression."
            )
        
        # Check budget threshold
        budget_fraction = metrics.context_size / self.max_tokens
        if budget_fraction > self.eviction_threshold:
            logger.warning(
                f"Context budget approaching limit: {metrics.context_size}/{self.max_tokens} "
                f"({budget_fraction*100:.1f}%). Consider evicting old context."
            )
        
        # Check cumulative growth
        if metrics.cumulative_growth > self.growth_threshold * 2:
            logger.warning(
                f"High cumulative growth rate: {metrics.cumulative_growth:.0f} tokens/turn "
                f"over {metrics.turn_number} turns. Average growth is elevated."
            )
    
    def get_growth_report(self) -> dict[str, Any]:
        """Get a comprehensive growth report.
        
        Returns:
            Dictionary with growth statistics and recommendations
        """
        if not self.turns:
            return {
                "turns": 0,
                "message": "No turns tracked yet",
            }
        
        # Calculate statistics
        total_growth = self.turns[-1].context_size - self.turns[0].context_size
        avg_growth = total_growth / len(self.turns)
        max_growth = max(t.growth_rate for t in self.turns)
        min_growth = min(t.growth_rate for t in self.turns)
        
        # Identify growth trends
        recent_turns = self.turns[-5:] if len(self.turns) >= 5 else self.turns
        recent_avg = sum(t.growth_rate for t in recent_turns) / len(recent_turns)
        
        # Identify top growing middleware
        middleware_totals = {
            middleware: sum(tokens_list)
            for middleware, tokens_list in self.middleware_growth.items()
        }
        top_middleware = sorted(
            middleware_totals.items(),
            key=lambda x: x[1],
            reverse=True,
        )[:5]
        
        # Generate recommendations
        recommendations = self._generate_recommendations(avg_growth, recent_avg)
        
        return {
            "total_turns": len(self.turns),
            "total_growth": total_growth,
            "average_growth_per_turn": avg_growth,
            "max_growth_in_turn": max_growth,
            "min_growth_in_turn": min_growth,
            "recent_average_growth": recent_avg,
            "current_context_size": self.turns[-1].context_size,
            "budget_used_fraction": self.turns[-1].context_size / self.max_tokens,
            "top_growing_middleware": [
                {"middleware": m, "total_tokens": t}
                for m, t in top_middleware
            ],
            "recommendations": recommendations,
        }
    
    def _generate_recommendations(
        self,
        avg_growth: float,
        recent_avg: float,
    ) -> list[str]:
        """Generate optimization recommendations based on growth patterns.
        
        Args:
            avg_growth: Average growth per turn
            recent_avg: Recent average growth
            
        Returns:
            List of recommendation strings
        """
        recommendations = []
        
        if avg_growth > self.growth_threshold:
            recommendations.append(
                f"High average growth ({avg_growth:.0f} tokens/turn). "
                "Implement context eviction or compression."
            )
        
        if recent_avg > avg_growth * 1.5:
            recommendations.append(
                f"Recent growth spike detected ({recent_avg:.0f} vs {avg_growth:.0f} avg). "
                "Check for context bloat in recent turns."
            )
        
        if self.turns and self.turns[-1].context_size > self.max_tokens * 0.5:
            recommendations.append(
                "Context usage >50%. Consider implementing lazy loading for middleware."
            )
        
        if self.turns and self.turns[-1].context_size > self.max_tokens * 0.7:
            recommendations.append(
                "Context usage >70%. Trigger context eviction immediately."
            )
        
        # Middleware-specific recommendations
        middleware_totals = {
            middleware: sum(tokens_list)
            for middleware, tokens_list in self.middleware_growth.items()
        }
        
        for middleware, total in sorted(
            middleware_totals.items(),
            key=lambda x: x[1],
            reverse=True,
        )[:3]:
            if total > self.max_tokens * 0.1:
                recommendations.append(
                    f"{middleware} uses >10% of budget. "
                    "Consider lazy loading or compression."
                )
        
        if not recommendations:
            recommendations.append("Context growth is healthy. Continue monitoring.")
        
        return recommendations
    
    def should_evict(self) -> bool:
        """Check if context eviction should be triggered.
        
        Returns:
            True if eviction threshold reached
        """
        if not self.turns:
            return False
        
        current_size = self.turns[-1].context_size
        return current_size > self.max_tokens * self.eviction_threshold
    
    def get_eviction_recommendation(self) -> dict[str, Any]:
        """Get recommendation for context eviction.
        
        Returns:
            Dictionary with eviction details
        """
        if not self.should_evict():
            return {
                "should_evict": False,
                "message": "Context within safe limits",
            }
        
        current_size = self.turns[-1].context_size
        target_size = int(self.max_tokens * 0.5)  # Target 50% after eviction
        tokens_to_remove = current_size - target_size
        
        # Recommend keeping last N turns
        turns_to_keep = max(10, len(self.turns) // 3)
        
        return {
            "should_evict": True,
            "current_size": current_size,
            "target_size": target_size,
            "tokens_to_remove": tokens_to_remove,
            "turns_to_keep": turns_to_keep,
            "turns_to_evict": len(self.turns) - turns_to_keep,
            "message": (
                f"Evict {len(self.turns) - turns_to_keep} old turns "
                f"to reduce context from {current_size} to {target_size} tokens."
            ),
        }


# Global growth tracker
_growth_tracker: ContextGrowthTracker | None = None


def get_growth_tracker(
    max_tokens: int = 50000,
    growth_threshold: float = 500.0,
    eviction_threshold: float = 0.7,
) -> ContextGrowthTracker:
    """Get or create the global context growth tracker.
    
    Args:
        max_tokens: Maximum context budget
        growth_threshold: Alert if growth exceeds this per turn
        eviction_threshold: Trigger eviction at this fraction of budget
        
    Returns:
        Global ContextGrowthTracker instance
    """
    global _growth_tracker
    if _growth_tracker is None:
        _growth_tracker = ContextGrowthTracker(
            max_tokens=max_tokens,
            growth_threshold=growth_threshold,
            eviction_threshold=eviction_threshold,
        )
    return _growth_tracker


def reset_growth_tracker() -> None:
    """Reset the global growth tracker for a new conversation."""
    global _growth_tracker
    _growth_tracker = None


__all__ = [
    "ContextGrowthTracker",
    "TurnMetrics",
    "get_growth_tracker",
    "reset_growth_tracker",
]

"""Context budget tracking for LLM prompts.

This module provides utilities to track and manage context usage across
middleware layers, helping prevent context overflow and optimize token usage.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


class ContextBudget:
    """Track and manage context token usage across middleware layers.
    
    This helps prevent context overflow by monitoring token usage and
    providing visibility into which middleware layers consume the most context.
    """
    
    def __init__(self, max_tokens: int = 50000):
        """Initialize context budget tracker.
        
        Args:
            max_tokens: Maximum allowed tokens before compression/warning
        """
        self.max_tokens = max_tokens
        self.middleware_usage: dict[str, int] = {}
        self.total_tokens = 0
    
    def track_middleware(self, middleware_name: str, context: str | list[Any]) -> int:
        """Track context usage for a middleware layer.
        
        Args:
            middleware_name: Name of the middleware
            context: Context content (string or list of messages)
            
        Returns:
            Number of tokens used by this middleware
        """
        tokens = self._count_tokens(context)
        self.middleware_usage[middleware_name] = tokens
        self.total_tokens += tokens
        
        if self.total_tokens > self.max_tokens:
            logger.warning(
                f"Context budget exceeded: {self.total_tokens} > {self.max_tokens} tokens. "
                f"Consider compressing context or reducing middleware layers."
            )
        
        return tokens
    
    def _count_tokens(self, context: str | list[Any]) -> int:
        """Count tokens in context.
        
        Simple estimation: ~4 characters per token for English text.
        For more accurate counting, use tiktoken or the model's tokenizer.
        
        Args:
            context: Context content
            
        Returns:
            Estimated token count
        """
        if isinstance(context, str):
            # Simple estimation: ~4 chars per token
            return len(context) // 4
        elif isinstance(context, list):
            # List of messages
            total = 0
            for msg in context:
                if isinstance(msg, dict):
                    # Message dict with 'content' field
                    content = msg.get("content", "")
                    if isinstance(content, str):
                        total += len(content) // 4
                    elif isinstance(content, list):
                        # List of content blocks
                        for block in content:
                            if isinstance(block, dict):
                                total += len(str(block.get("text", ""))) // 4
                elif isinstance(msg, str):
                    total += len(msg) // 4
            return total
        return 0
    
    def get_usage_report(self) -> dict[str, Any]:
        """Get a report of context usage by middleware.
        
        Returns:
            Dictionary with usage statistics
        """
        return {
            "total_tokens": self.total_tokens,
            "max_tokens": self.max_tokens,
            "percentage_used": (self.total_tokens / self.max_tokens) * 100,
            "middleware_breakdown": dict(sorted(
                self.middleware_usage.items(),
                key=lambda x: x[1],
                reverse=True
            )),
            "top_consumers": [
                {"middleware": name, "tokens": tokens}
                for name, tokens in sorted(
                    self.middleware_usage.items(),
                    key=lambda x: x[1],
                    reverse=True
                )[:5]
            ]
        }
    
    def reset(self) -> None:
        """Reset tracking for a new request."""
        self.middleware_usage.clear()
        self.total_tokens = 0


# Global context budget tracker
_context_budget: ContextBudget | None = None


def get_context_budget(max_tokens: int = 50000) -> ContextBudget:
    """Get or create the global context budget tracker.
    
    Args:
        max_tokens: Maximum allowed tokens (only used on first call)
        
    Returns:
        Global ContextBudget instance
    """
    global _context_budget
    if _context_budget is None:
        _context_budget = ContextBudget(max_tokens)
    return _context_budget


def reset_context_budget() -> None:
    """Reset the global context budget tracker."""
    global _context_budget
    _context_budget = None


__all__ = [
    "ContextBudget",
    "get_context_budget",
    "reset_context_budget",
]
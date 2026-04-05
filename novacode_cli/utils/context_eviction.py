"""Context eviction strategies for managing context overflow.

This module provides utilities to evict old context when approaching
budget limits, ensuring conversations can continue without overflow.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


def evict_old_messages(
    messages: list[dict[str, Any]],
    keep_last_n: int = 10,
    preserve_system: bool = True,
) -> list[dict[str, Any]]:
    """Evict old messages to reduce context size.
    
    Args:
        messages: List of conversation messages
        keep_last_n: Number of recent messages to keep
        preserve_system: Whether to preserve system messages
        
    Returns:
        Reduced list of messages
    """
    if len(messages) <= keep_last_n:
        return messages
    
    # Separate system and non-system messages
    system_messages = []
    other_messages = []
    
    for msg in messages:
        if preserve_system and msg.get("role") == "system":
            system_messages.append(msg)
        else:
            other_messages.append(msg)
    
    # Keep last N non-system messages
    kept_messages = other_messages[-keep_last_n:] if len(other_messages) > keep_last_n else other_messages
    
    # Combine system messages with kept messages
    result = system_messages + kept_messages
    
    evicted_count = len(messages) - len(result)
    if evicted_count > 0:
        logger.info(
            f"Evicted {evicted_count} old messages "
            f"(kept {len(result)} messages: {len(system_messages)} system + {len(kept_messages)} recent)"
        )
    
    return result


def evict_by_age(
    messages: list[dict[str, Any]],
    max_age_turns: int = 20,
    preserve_system: bool = True,
) -> list[dict[str, Any]]:
    """Evict messages older than a certain number of turns.
    
    Args:
        messages: List of conversation messages
        max_age_turns: Maximum age in turns
        preserve_system: Whether to preserve system messages
        
    Returns:
        Reduced list of messages
    """
    if len(messages) <= max_age_turns:
        return messages
    
    # Separate system and non-system messages
    system_messages = []
    other_messages = []
    
    for msg in messages:
        if preserve_system and msg.get("role") == "system":
            system_messages.append(msg)
        else:
            other_messages.append(msg)
    
    # Keep messages within age limit
    kept_messages = other_messages[-max_age_turns:] if len(other_messages) > max_age_turns else other_messages
    
    result = system_messages + kept_messages
    
    evicted_count = len(messages) - len(result)
    if evicted_count > 0:
        logger.info(
            f"Evicted {evicted_count} messages older than {max_age_turns} turns"
        )
    
    return result


def evict_by_importance(
    messages: list[dict[str, Any]],
    importance_threshold: float = 0.5,
) -> list[dict[str, Any]]:
    """Evict messages based on importance scoring.
    
    Importance is determined by:
    - System messages: Always kept
    - User messages: High importance
    - Assistant messages with tool calls: Medium importance
    - Tool results: Low importance
    - Old messages: Lower importance
    
    Args:
        messages: List of conversation messages
        importance_threshold: Minimum importance score to keep
        
    Returns:
        Reduced list of messages
    """
    if not messages:
        return messages
    
    # Score each message
    scored_messages = []
    for i, msg in enumerate(messages):
        score = _calculate_importance(msg, i, len(messages))
        scored_messages.append((score, msg))
    
    # Filter by threshold
    kept_messages = [
        msg for score, msg in scored_messages
        if score >= importance_threshold
    ]
    
    evicted_count = len(messages) - len(kept_messages)
    if evicted_count > 0:
        logger.info(
            f"Evicted {evicted_count} low-importance messages "
            f"(threshold: {importance_threshold})"
        )
    
    return kept_messages


def _calculate_importance(
    message: dict[str, Any],
    index: int,
    total: int,
) -> float:
    """Calculate importance score for a message.
    
    Args:
        message: Message to score
        index: Position in conversation
        total: Total number of messages
        
    Returns:
        Importance score (0.0 to 1.0)
    """
    role = message.get("role", "")
    
    # Base score by role
    if role == "system":
        return 1.0  # Always keep system messages
    elif role == "user":
        base_score = 0.8
    elif role == "assistant":
        # Check if has tool calls
        has_tools = bool(message.get("tool_calls"))
        base_score = 0.6 if has_tools else 0.5
    elif role == "tool":
        base_score = 0.3
    else:
        base_score = 0.4
    
    # Adjust by recency (newer = more important)
    recency_factor = index / total if total > 0 else 0
    recency_bonus = recency_factor * 0.3
    
    # Adjust by content length (longer = potentially more important)
    content = message.get("content", "")
    if isinstance(content, str):
        length_factor = min(len(content) / 1000, 0.2)  # Max 0.2 bonus
    else:
        length_factor = 0.1
    
    final_score = base_score + recency_bonus + length_factor
    return min(final_score, 1.0)


def smart_evict(
    messages: list[dict[str, Any]],
    target_tokens: int,
    current_tokens: int,
    strategy: str = "balanced",
) -> list[dict[str, Any]]:
    """Intelligently evict messages to reach target token count.
    
    Args:
        messages: List of conversation messages
        target_tokens: Target token count
        current_tokens: Current token count
        strategy: Eviction strategy ('aggressive', 'balanced', 'conservative')
        
    Returns:
        Reduced list of messages
    """
    if current_tokens <= target_tokens:
        return messages
    
    tokens_to_remove = current_tokens - target_tokens
    
    # Choose strategy
    if strategy == "aggressive":
        # Remove as many as needed
        keep_last_n = max(5, len(messages) // 4)
    elif strategy == "conservative":
        # Remove minimal
        keep_last_n = max(10, len(messages) // 2)
    else:  # balanced
        # Balanced approach
        keep_last_n = max(10, len(messages) // 3)
    
    result = evict_old_messages(messages, keep_last_n=keep_last_n)
    
    # If still over target, try importance-based eviction
    if _estimate_tokens(result) > target_tokens:
        threshold = 0.4 if strategy == "aggressive" else 0.5 if strategy == "balanced" else 0.6
        result = evict_by_importance(result, importance_threshold=threshold)
    
    final_tokens = _estimate_tokens(result)
    logger.info(
        f"Smart eviction: {len(messages)} → {len(result)} messages "
        f"({current_tokens} → {final_tokens} tokens)"
    )
    
    return result


def _estimate_tokens(messages: list[dict[str, Any]]) -> int:
    """Estimate token count for messages.
    
    Simple estimation: ~4 characters per token.
    
    Args:
        messages: List of messages
        
    Returns:
        Estimated token count
    """
    total_chars = 0
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            total_chars += len(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    total_chars += len(str(block.get("text", "")))
    
    return total_chars // 4


def get_eviction_summary(
    original: list[dict[str, Any]],
    evicted: list[dict[str, Any]],
) -> dict[str, Any]:
    """Get summary of eviction operation.
    
    Args:
        original: Original message list
        evicted: Evicted message list
        
    Returns:
        Dictionary with eviction summary
    """
    original_tokens = _estimate_tokens(original)
    evicted_tokens = _estimate_tokens(evicted)
    
    return {
        "original_messages": len(original),
        "evicted_messages": len(evicted),
        "kept_messages": len(original) - len(evicted),
        "original_tokens": original_tokens,
        "evicted_tokens": evicted_tokens,
        "kept_tokens": original_tokens - evicted_tokens,
        "reduction_percentage": (evicted_tokens / original_tokens * 100) if original_tokens > 0 else 0,
    }


__all__ = [
    "evict_old_messages",
    "evict_by_age",
    "evict_by_importance",
    "smart_evict",
    "get_eviction_summary",
]

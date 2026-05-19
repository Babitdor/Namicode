"""Context tracking utilities for middleware layers.

This module provides a decorator and utilities to track context usage across
all middleware layers, helping identify context bloat and optimize token usage.

Performance notes
-----------------
* The budget singleton is resolved once at import time — no lazy import on
  every decorated call.
* Tracking is a no-op unless ``NOVA_DEBUG`` is set, eliminating overhead in
  normal operation.
* ``_count_tokens`` is kept as a pure function (no self) to allow the
  JIT/interpreter to inline it more easily.
"""

import functools
import logging
import os
from typing import Any, Callable

logger = logging.getLogger(__name__)

# Only pay the tracking cost in debug mode
_TRACKING_ENABLED = os.environ.get("NOVA_DEBUG", "").lower() in ("1", "true", "yes")

# Resolve singleton once — avoids repeated lazy imports in hot paths
_budget: Any = None

def _get_budget() -> Any:
    global _budget
    if _budget is None:
        try:
            from novacode_cli.utils.context_budget import get_context_budget
            _budget = get_context_budget()
        except ImportError:
            pass
    return _budget


def _count_tokens(text: str | None) -> int:
    """Cheap character-based token estimate (~4 chars/token)."""
    return len(text) // 4 if text else 0


def track_context(middleware_name: str):
    """Decorator to track context usage for sync middleware methods.

    When ``NOVA_DEBUG`` is not set this decorator is effectively a no-op:
    the wrapper function is replaced by the original at decoration time.
    """
    def decorator(func: Callable) -> Callable:
        if not _TRACKING_ENABLED:
            return func  # zero overhead in production

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            budget = _get_budget()
            if budget is None:
                return func(*args, **kwargs)

            req = args[1] if len(args) > 1 else kwargs.get("request")
            before = _count_tokens(getattr(req, "system_prompt", None))

            result = func(*args, **kwargs)

            after_text = getattr(result, "system_prompt", None)
            after = _count_tokens(after_text)
            added = after - before
            if added > 0:
                budget.track_middleware(middleware_name, after_text or "")
                logger.debug(
                    "%s added %d tokens (total: %d/%d)",
                    middleware_name, added, budget.total_tokens, budget.max_tokens,
                )
            return result

        return wrapper
    return decorator


def track_context_async(middleware_name: str):
    """Async version of :func:`track_context`."""
    def decorator(func: Callable) -> Callable:
        if not _TRACKING_ENABLED:
            return func  # zero overhead in production

        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            budget = _get_budget()
            if budget is None:
                return await func(*args, **kwargs)

            req = args[1] if len(args) > 1 else kwargs.get("request")
            before = _count_tokens(getattr(req, "system_prompt", None))

            result = await func(*args, **kwargs)

            after_text = getattr(result, "system_prompt", None)
            after = _count_tokens(after_text)
            added = after - before
            if added > 0:
                budget.track_middleware(middleware_name, after_text or "")
                logger.debug(
                    "%s added %d tokens (total: %d/%d)",
                    middleware_name, added, budget.total_tokens, budget.max_tokens,
                )
            return result

        return wrapper
    return decorator


__all__ = [
    "track_context",
    "track_context_async",
]

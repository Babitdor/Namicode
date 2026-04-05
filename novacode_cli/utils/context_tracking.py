"""Context tracking utilities for middleware layers.

This module provides a decorator and utilities to track context usage across
all middleware layers, helping identify context bloat and optimize token usage.
"""

import functools
import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)


def track_context(middleware_name: str):
    """Decorator to track context usage for middleware methods.
    
    This decorator measures the context size before and after middleware processing,
    logging the token impact and tracking it in the global context budget.
    
    Args:
        middleware_name: Name of the middleware for tracking
        
    Usage:
        @track_context("FilesystemMiddleware")
        def wrap_model_call(self, request, handler):
            # ... middleware logic ...
            return handler(request)
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            # Try to get context budget tracker
            try:
                from novacode_cli.utils.context_budget import get_context_budget
                budget = get_context_budget()
            except ImportError:
                # Context budget tracking not available
                return func(*args, **kwargs)
            
            # Extract context from request if available
            context_before = None
            if len(args) > 1 and hasattr(args[1], 'system_prompt'):
                context_before = args[1].system_prompt
            elif 'request' in kwargs and hasattr(kwargs['request'], 'system_prompt'):
                context_before = kwargs['request'].system_prompt
            
            # Track before
            tokens_before = budget._count_tokens(context_before) if context_before else 0
            
            # Execute middleware
            result = func(*args, **kwargs)
            
            # Track after
            context_after = None
            if hasattr(result, 'system_prompt'):
                context_after = result.system_prompt
            elif isinstance(result, dict) and 'system_prompt' in result:
                context_after = result['system_prompt']
            
            tokens_after = budget._count_tokens(context_after) if context_after else 0
            tokens_added = tokens_after - tokens_before
            
            # Log and track
            if tokens_added > 0:
                budget.track_middleware(middleware_name, context_after or "")
                logger.debug(
                    f"{middleware_name} added {tokens_added} tokens to context "
                    f"(total: {budget.total_tokens}/{budget.max_tokens})"
                )
            
            return result
        
        return wrapper
    return decorator


def track_context_async(middleware_name: str):
    """Async decorator to track context usage for middleware methods.
    
    This is the async version of track_context for async middleware methods.
    
    Args:
        middleware_name: Name of the middleware for tracking
        
    Usage:
        @track_context_async("FilesystemMiddleware")
        async def awrap_model_call(self, request, handler):
            # ... middleware logic ...
            return await handler(request)
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            # Try to get context budget tracker
            try:
                from novacode_cli.utils.context_budget import get_context_budget
                budget = get_context_budget()
            except ImportError:
                # Context budget tracking not available
                return await func(*args, **kwargs)
            
            # Extract context from request if available
            context_before = None
            if len(args) > 1 and hasattr(args[1], 'system_prompt'):
                context_before = args[1].system_prompt
            elif 'request' in kwargs and hasattr(kwargs['request'], 'system_prompt'):
                context_before = kwargs['request'].system_prompt
            
            # Track before
            tokens_before = budget._count_tokens(context_before) if context_before else 0
            
            # Execute middleware
            result = await func(*args, **kwargs)
            
            # Track after
            context_after = None
            if hasattr(result, 'system_prompt'):
                context_after = result.system_prompt
            elif isinstance(result, dict) and 'system_prompt' in result:
                context_after = result['system_prompt']
            
            tokens_after = budget._count_tokens(context_after) if context_after else 0
            tokens_added = tokens_after - tokens_before
            
            # Log and track
            if tokens_added > 0:
                budget.track_middleware(middleware_name, context_after or "")
                logger.debug(
                    f"{middleware_name} added {tokens_added} tokens to context "
                    f"(total: {budget.total_tokens}/{budget.max_tokens})"
                )
            
            return result
        
        return wrapper
    return decorator


__all__ = [
    "track_context",
    "track_context_async",
]

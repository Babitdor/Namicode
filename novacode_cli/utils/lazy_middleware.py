"""Lazy loading utilities for middleware.

This module provides utilities to load middleware on-demand,
reducing initial context footprint and improving performance.
"""

import logging
from typing import Any, Callable, Optional, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class LazyMiddleware:
    """Lazy loader for middleware.
    
    Loads middleware only when needed, reducing initial context footprint.
    
    Usage:
        # Instead of loading middleware immediately
        middleware = FilesystemMiddleware()
        
        # Use lazy loading
        lazy_middleware = LazyMiddleware(
            FilesystemMiddleware,
            backend=StateBackend()
        )
        
        # Middleware is loaded only when accessed
        result = lazy_middleware.wrap_model_call(request, handler)
    """
    
    def __init__(
        self,
        middleware_class: type,
        *args: Any,
        **kwargs: Any,
    ):
        """Initialize lazy middleware loader.
        
        Args:
            middleware_class: Middleware class to load
            *args: Positional arguments for middleware constructor
            **kwargs: Keyword arguments for middleware constructor
        """
        self.middleware_class = middleware_class
        self.args = args
        self.kwargs = kwargs
        self._instance: Optional[Any] = None
        self._loaded = False
    
    def _load(self) -> Any:
        """Load the middleware instance.
        
        Returns:
            Middleware instance
        """
        if not self._loaded:
            logger.debug(f"Lazy loading middleware: {self.middleware_class.__name__}")
            self._instance = self.middleware_class(*self.args, **self.kwargs)
            self._loaded = True
        return self._instance
    
    def __getattr__(self, name: str) -> Any:
        """Delegate attribute access to loaded middleware.
        
        Args:
            name: Attribute name
            
        Returns:
            Attribute value
        """
        instance = self._load()
        return getattr(instance, name)
    
    def wrap_model_call(self, request: Any, handler: Callable) -> Any:
        """Wrap model call (delegates to loaded middleware).
        
        Args:
            request: Model request
            handler: Handler function
            
        Returns:
            Model response
        """
        instance = self._load()
        return instance.wrap_model_call(request, handler)
    
    async def awrap_model_call(self, request: Any, handler: Callable) -> Any:
        """Async wrap model call (delegates to loaded middleware).
        
        Args:
            request: Model request
            handler: Handler function
            
        Returns:
            Model response
        """
        instance = self._load()
        return await instance.awrap_model_call(request, handler)
    
    @property
    def is_loaded(self) -> bool:
        """Check if middleware is loaded.
        
        Returns:
            True if loaded, False otherwise
        """
        return self._loaded


class ConditionalMiddleware:
    """Conditionally load middleware based on request.
    
    Loads middleware only when certain conditions are met,
    such as specific tools being available or certain keywords in the request.
    
    Usage:
        # Load FilesystemMiddleware only when file operations detected
        conditional = ConditionalMiddleware(
            FilesystemMiddleware,
            condition=lambda req: has_file_operations(req),
            backend=StateBackend()
        )
        
        # Middleware is loaded only when condition is True
        result = conditional.wrap_model_call(request, handler)
    """
    
    def __init__(
        self,
        middleware_class: type,
        condition: Callable[[Any], bool],
        *args: Any,
        **kwargs: Any,
    ):
        """Initialize conditional middleware loader.
        
        Args:
            middleware_class: Middleware class to load
            condition: Function that returns True if middleware should be loaded
            *args: Positional arguments for middleware constructor
            **kwargs: Keyword arguments for middleware constructor
        """
        self.middleware_class = middleware_class
        self.condition = condition
        self.args = args
        self.kwargs = kwargs
        self._instance: Optional[Any] = None
        self._loaded = False
    
    def _should_load(self, request: Any) -> bool:
        """Check if middleware should be loaded.
        
        Args:
            request: Model request
            
        Returns:
            True if middleware should be loaded
        """
        try:
            return self.condition(request)
        except Exception as e:
            logger.warning(
                f"Error checking condition for {self.middleware_class.__name__}: {e}"
            )
            return False
    
    def _load(self) -> Any:
        """Load the middleware instance.
        
        Returns:
            Middleware instance
        """
        if not self._loaded:
            logger.debug(f"Conditionally loading middleware: {self.middleware_class.__name__}")
            self._instance = self.middleware_class(*self.args, **self.kwargs)
            self._loaded = True
        return self._instance
    
    def wrap_model_call(self, request: Any, handler: Callable) -> Any:
        """Wrap model call (conditionally loads middleware).
        
        Args:
            request: Model request
            handler: Handler function
            
        Returns:
            Model response
        """
        if self._should_load(request):
            instance = self._load()
            return instance.wrap_model_call(request, handler)
        else:
            # Skip middleware if condition not met
            logger.debug(f"Skipping {self.middleware_class.__name__} - condition not met")
            return handler(request)
    
    async def awrap_model_call(self, request: Any, handler: Callable) -> Any:
        """Async wrap model call (conditionally loads middleware).
        
        Args:
            request: Model request
            handler: Handler function
            
        Returns:
            Model response
        """
        if self._should_load(request):
            instance = self._load()
            return await instance.awrap_model_call(request, handler)
        else:
            # Skip middleware if condition not met
            logger.debug(f"Skipping {self.middleware_class.__name__} - condition not met")
            return await handler(request)
    
    @property
    def is_loaded(self) -> bool:
        """Check if middleware is loaded.
        
        Returns:
            True if loaded, False otherwise
        """
        return self._loaded


def has_file_operations(request: Any) -> bool:
    """Check if request involves file operations.
    
    Args:
        request: Model request
        
    Returns:
        True if file operations detected
    """
    # Check for file-related tools
    if hasattr(request, "tools"):
        file_tools = {
            "read_file", "write_file", "edit_file",
            "list_directory", "search_files", "grep_search",
        }
        for tool in request.tools:
            tool_name = getattr(tool, "name", None) or tool.get("name")
            if tool_name in file_tools:
                return True
    
    # Check for file-related keywords in prompt
    if hasattr(request, "system_prompt"):
        file_keywords = {"file", "directory", "path", "read", "write", "edit"}
        if any(keyword in request.system_prompt.lower() for keyword in file_keywords):
            return True
    
    return False


def has_skills(request: Any) -> bool:
    """Check if request involves skills.
    
    Args:
        request: Model request
        
    Returns:
        True if skills detected
    """
    # Check for skill-related keywords
    if hasattr(request, "system_prompt"):
        skill_keywords = {"skill", "SKILL.md", "invoke", "delegate"}
        if any(keyword in request.system_prompt.lower() for keyword in skill_keywords):
            return True
    
    return False


def has_subagents(request: Any) -> bool:
    """Check if request involves subagents.
    
    Args:
        request: Model request
        
    Returns:
        True if subagents detected
    """
    # Check for task tool
    if hasattr(request, "tools"):
        for tool in request.tools:
            tool_name = getattr(tool, "name", None) or tool.get("name")
            if tool_name == "task":
                return True
    
    return False


def has_memory_operations(request: Any) -> bool:
    """Check if request involves memory operations.
    
    Args:
        request: Model request
        
    Returns:
        True if memory operations detected
    """
    # Check for memory-related tools
    if hasattr(request, "tools"):
        memory_tools = {
            "write_memory", "read_memory",
            "list_memories", "delete_memory",
        }
        for tool in request.tools:
            tool_name = getattr(tool, "name", None) or tool.get("name")
            if tool_name in memory_tools:
                return True
    
    return False


__all__ = [
    "LazyMiddleware",
    "ConditionalMiddleware",
    "has_file_operations",
    "has_skills",
    "has_subagents",
    "has_memory_operations",
]

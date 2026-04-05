"""Tool call limits and loop detection to prevent infinite tool calling.

This module provides safeguards against infinite tool calling loops:
- Maximum tool call limits per turn
- Repetitive pattern detection
- Context size monitoring
- Circuit breaker pattern
"""

import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolCallLimit:
    """Configuration for tool call limits."""
    
    max_calls_per_turn: int = 50
    """Maximum number of tool calls allowed in a single turn."""
    
    max_repeated_calls: int = 3
    """Maximum times the same tool can be called with identical arguments."""
    
    max_context_tokens: int = 100000
    """Maximum context tokens before triggering compaction."""
    
    reset_after_seconds: int = 60
    """Reset call counters after this many seconds."""
    
    warning_threshold: int = 20
    """Warn user when tool calls exceed this threshold."""


@dataclass
class ToolCallTracker:
    """Tracks tool calls to detect infinite loops."""
    
    calls: list[dict[str, Any]] = field(default_factory=list)
    """List of all tool calls in current turn."""
    
    call_counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    """Count of calls per tool name."""
    
    identical_calls: dict[str, list[dict[str, Any]]] = field(default_factory=lambda: defaultdict(list))
    """Track identical calls by argument hash."""
    
    start_time: float = field(default_factory=time.time)
    """When this turn started."""
    
    total_tokens: int = 0
    """Total tokens consumed in this turn."""
    
    def reset(self) -> None:
        """Reset tracker for a new turn."""
        self.calls.clear()
        self.call_counts.clear()
        self.identical_calls.clear()
        self.start_time = time.time()
        self.total_tokens = 0
    
    def add_call(self, tool_name: str, args: dict[str, Any]) -> None:
        """Record a tool call.
        
        Args:
            tool_name: Name of the tool called
            args: Arguments passed to the tool
        """
        call_record = {
            "tool": tool_name,
            "args": args,
            "timestamp": time.time(),
        }
        
        self.calls.append(call_record)
        self.call_counts[tool_name] += 1
        
        # Track identical calls by hashing arguments
        args_hash = self._hash_args(args)
        self.identical_calls[args_hash].append(call_record)
    
    def _hash_args(self, args: dict[str, Any]) -> str:
        """Create a hash of tool arguments for comparison.
        
        Args:
            args: Tool arguments
            
        Returns:
            Hash string for comparison
        """
        import json
        try:
            return json.dumps(args, sort_keys=True)
        except (TypeError, ValueError):
            return str(args)
    
    def get_identical_call_count(self, tool_name: str, args: dict[str, Any]) -> int:
        """Get count of identical calls to the same tool with same arguments.
        
        Args:
            tool_name: Tool name
            args: Tool arguments
            
        Returns:
            Number of identical calls
        """
        args_hash = self._hash_args(args)
        return len(self.identical_calls.get(args_hash, []))
    
    def is_loop_detected(self, config: ToolCallLimit) -> tuple[bool, str]:
        """Check if an infinite loop is detected.
        
        Args:
            config: Tool call limit configuration
            
        Returns:
            Tuple of (is_loop, reason) where is_loop is True if loop detected
        """
        # Check total call count
        if len(self.calls) > config.max_calls_per_turn:
            return True, f"Exceeded maximum tool calls ({config.max_calls_per_turn})"
        
        # Check for repeated identical calls
        for args_hash, calls in self.identical_calls.items():
            if len(calls) > config.max_repeated_calls:
                tool_name = calls[0]["tool"]
                return True, (
                    f"Tool '{tool_name}' called {len(calls)} times with identical arguments "
                    f"(max: {config.max_repeated_calls})"
                )
        
        # Check for time-based reset
        elapsed = time.time() - self.start_time
        if elapsed > config.reset_after_seconds:
            # Auto-reset after timeout
            self.reset()
        
        return False, ""
    
    def should_warn(self, config: ToolCallLimit) -> tuple[bool, str]:
        """Check if warning should be displayed.
        
        Args:
            config: Tool call limit configuration
            
        Returns:
            Tuple of (should_warn, message)
        """
        if len(self.calls) > config.warning_threshold:
            return True, (
                f"Excessive tool calls detected: {len(self.calls)} calls, "
                f"{self.total_tokens:,} tokens"
            )
        
        return False, ""


class ToolCallCircuitBreaker:
    """Circuit breaker pattern for tool calls.
    
    Prevents runaway tool calling by opening the circuit when
    too many calls are made in a short time period.
    """
    
    def __init__(self, config: ToolCallLimit | None = None):
        """Initialize circuit breaker.
        
        Args:
            config: Tool call limit configuration
        """
        self.config = config or ToolCallLimit()
        self.tracker = ToolCallTracker()
        self._is_open = False
        self._open_until: float | None = None
    
    def should_allow_call(self, tool_name: str, args: dict[str, Any]) -> tuple[bool, str]:
        """Check if tool call should be allowed.
        
        Args:
            tool_name: Name of tool to call
            args: Tool arguments
            
        Returns:
            Tuple of (should_allow, reason)
        """
        # Check if circuit is open
        if self._is_open:
            if self._open_until and time.time() < self._open_until:
                return False, "Circuit breaker is open - too many tool calls"
            else:
                # Reset circuit breaker
                self._is_open = False
                self._open_until = None
                self.tracker.reset()
        
        # Record the call
        self.tracker.add_call(tool_name, args)
        
        # Check for loops
        is_loop, reason = self.tracker.is_loop_detected(self.config)
        if is_loop:
            # Open the circuit
            self._is_open = True
            self._open_until = time.time() + 60  # 1 minute cooldown
            return False, f"Circuit breaker triggered: {reason}"
        
        # Check for warnings
        should_warn, warning = self.tracker.should_warn(self.config)
        if should_warn:
            # Log warning but allow call
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(warning)
        
        return True, ""
    
    def update_token_count(self, tokens: int) -> None:
        """Update total token count.
        
        Args:
            tokens: Number of tokens to add
        """
        self.tracker.total_tokens += tokens
        
        # Check if context limit exceeded
        if self.tracker.total_tokens > self.config.max_context_tokens:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(
                f"Context limit approaching: {self.tracker.total_tokens:,} tokens "
                f"(max: {self.config.max_context_tokens:,})"
            )
    
    def reset(self) -> None:
        """Reset the circuit breaker."""
        self.tracker.reset()
        self._is_open = False
        self._open_until = None


# Global circuit breaker instance
_circuit_breaker: ToolCallCircuitBreaker | None = None


def get_circuit_breaker(config: ToolCallLimit | None = None) -> ToolCallCircuitBreaker:
    """Get or create global circuit breaker instance.
    
    Args:
        config: Optional configuration (only used on first call)
        
    Returns:
        Global circuit breaker instance
    """
    global _circuit_breaker
    
    if _circuit_breaker is None:
        _circuit_breaker = ToolCallCircuitBreaker(config)
    
    return _circuit_breaker


def reset_circuit_breaker() -> None:
    """Reset the global circuit breaker."""
    global _circuit_breaker
    
    if _circuit_breaker:
        _circuit_breaker.reset()


__all__ = [
    "ToolCallLimit",
    "ToolCallTracker",
    "ToolCallCircuitBreaker",
    "get_circuit_breaker",
    "reset_circuit_breaker",
]
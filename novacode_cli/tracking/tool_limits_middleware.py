"""Tool Limits Middleware for preventing infinite tool calling loops.

This middleware provides:
1. Circuit breaker to stop runaway tool calls
2. Loop detection for repeated identical calls
3. Token consumption monitoring
4. User warnings for excessive tool usage
"""

import logging
from collections.abc import Awaitable, Callable
from typing import Any, NotRequired, TypedDict

from langchain.agents.middleware.types import (
    AgentMiddleware,
    AgentState,
    ModelRequest,
    ModelResponse,
)
from langchain.tools.tool_node import ToolCallRequest
from langchain_core.messages import ToolMessage
from langgraph.types import Command

from novacode_cli.config.config import console
from novacode_cli.utils.tool_limits import (
    ToolCallLimit,
    ToolCallCircuitBreaker,
    get_circuit_breaker,
    reset_circuit_breaker,
)

logger = logging.getLogger(__name__)


class ToolLimitsState(AgentState):
    """State for the tool limits middleware."""

    tool_limits_warning_shown: NotRequired[bool]
    """Whether warning has been shown to user."""


class ToolLimitsStateUpdate(TypedDict):
    """State update for the tool limits middleware."""

    tool_limits_warning_shown: bool
    """Whether warning has been shown."""


class ToolLimitsMiddleware(AgentMiddleware):
    """Middleware for enforcing tool call limits and preventing infinite loops.

    This middleware:
    - Tracks all tool calls in a turn
    - Detects loops (repeated identical calls)
    - Opens circuit breaker when limits exceeded
    - Warns users about excessive tool usage
    - Monitors token consumption

    Args:
        config: Optional ToolCallLimit configuration
    """

    state_schema = ToolLimitsState

    def __init__(self, config: ToolCallLimit | None = None) -> None:
        """Initialize the tool limits middleware.

        Args:
            config: Optional configuration for limits. Uses defaults if not provided.
        """
        self.config = config or ToolCallLimit()
        self.circuit_breaker = get_circuit_breaker(self.config)

    async def on_session_start(
        self,
        runtime: Any,
        *,
        state: ToolLimitsState,
    ) -> ToolLimitsStateUpdate | None:
        """Reset circuit breaker at session start.

        Args:
            runtime: The LangGraph runtime instance
            state: Current agent state

        Returns:
            State update with warning flag reset
        """
        # Reset circuit breaker for new session
        reset_circuit_breaker()
        self.circuit_breaker = get_circuit_breaker(self.config)

        return {"tool_limits_warning_shown": False}

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        """Intercept tool calls to enforce limits and detect loops.

        Args:
            request: The tool call request
            handler: The handler function to execute the tool

        Returns:
            Tool result or error message if blocked
        """
        # Extract tool name and args
        tool_name = request.tool_call.get("name", "unknown")
        tool_args = request.tool_call.get("args", {})

        # Check circuit breaker
        should_proceed, reason = self.circuit_breaker.should_allow_call(
            tool_name, tool_args
        )

        if not should_proceed:
            # Circuit breaker is open - block the call
            logger.warning(f"Tool call blocked by circuit breaker: {reason}")
            console.print(f"\n[red]✗ Tool call blocked: {reason}[/red]")
            console.print(
                "[dim]Consider using /compact to reduce context or starting a new session[/dim]"
            )

            # Return error message
            return ToolMessage(
                content=f"Tool call blocked: {reason}. Please try a different approach or start a new session.",
                tool_call_id=request.tool_call.get("id", ""),
            )

        # Check for warning threshold
        if len(self.circuit_breaker.tracker.calls) >= self.config.warning_threshold:
            # Show warning to user (only once per session)
            state = request.state
            if not state.get("tool_limits_warning_shown"):
                console.print(
                    f"\n[yellow]⚠ Excessive tool calls detected ({len(self.circuit_breaker.tracker.calls)} calls)[/yellow]"
                )
                console.print(
                    f"[dim]Tokens used: {self.circuit_breaker.tracker.total_tokens:,}[/dim]"
                )
                console.print(
                    "[dim]Consider using /compact to reduce context size[/dim]"
                )

        # Execute the tool
        result = handler(request)

        # Track token consumption if available
        self._track_tokens(result)

        return result

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        """(async) Intercept tool calls to enforce limits and detect loops.

        Args:
            request: The tool call request
            handler: The handler function to execute the tool

        Returns:
            Tool result or error message if blocked
        """
        # Extract tool name and args
        tool_name = request.tool_call.get("name", "unknown")
        tool_args = request.tool_call.get("args", {})

        # Check circuit breaker
        should_proceed, reason = self.circuit_breaker.should_allow_call(
            tool_name, tool_args
        )

        if not should_proceed:
            # Circuit breaker is open - block the call
            logger.warning(f"Tool call blocked by circuit breaker: {reason}")
            console.print(f"\n[red]✗ Tool call blocked: {reason}[/red]")
            console.print(
                "[dim]Consider using /compact to reduce context or starting a new session[/dim]"
            )

            # Return error message
            return ToolMessage(
                content=f"Tool call blocked: {reason}. Please try a different approach or start a new session.",
                tool_call_id=request.tool_call.get("id", ""),
            )

        # Check for warning threshold
        if len(self.circuit_breaker.tracker.calls) >= self.config.warning_threshold:
            # Show warning to user (only once per session)
            state = request.state
            if not state.get("tool_limits_warning_shown"):
                console.print(
                    f"\n[yellow]⚠ Excessive tool calls detected ({len(self.circuit_breaker.tracker.calls)} calls)[/yellow]"
                )
                console.print(
                    f"[dim]Tokens used: {self.circuit_breaker.tracker.total_tokens:,}[/dim]"
                )
                console.print(
                    "[dim]Consider using /compact to reduce context size[/dim]"
                )

        # Execute the tool
        result = await handler(request)

        # Track token consumption if available
        self._track_tokens(result)

        return result

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        """Inject tool limits context into model request.

        This adds metadata about current tool call counts and token usage
        to help the model understand when it's approaching limits.

        Args:
            request: The model request being processed
            handler: The handler function to call with the request

        Returns:
            The model response from the handler
        """
        # Add tool limits context to state
        updated_state = dict(request.state)
        updated_state["tool_limits"] = {
            "calls_this_turn": len(self.circuit_breaker.tracker.calls),
            "max_calls": self.config.max_calls_per_turn,
            "tokens_used": self.circuit_breaker.tracker.total_tokens,
            "max_tokens": self.config.max_context_tokens,
        }

        # Build updated request
        updated_request = request.override(state=updated_state)  # type: ignore

        return handler(updated_request)

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        """(async) Inject tool limits context into model request.

        This adds metadata about current tool call counts and token usage
        to help the model understand when it's approaching limits.

        Args:
            request: The model request being processed
            handler: The handler function to call with the request

        Returns:
            The model response from the handler
        """
        # Add tool limits context to state
        updated_state = dict(request.state)
        updated_state["tool_limits"] = {
            "calls_this_turn": len(self.circuit_breaker.tracker.calls),
            "max_calls": self.config.max_calls_per_turn,
            "tokens_used": self.circuit_breaker.tracker.total_tokens,
            "max_tokens": self.config.max_context_tokens,
        }

        # Build updated request
        updated_request = request.override(state=updated_state)  # type: ignore

        return await handler(updated_request)

    def _track_tokens(self, result: ToolMessage | Command) -> None:
        """Track token consumption from tool result.

        Args:
            result: The tool result to analyze
        """
        # Try to extract token count from result
        if isinstance(result, ToolMessage):
            # Check for token metadata
            if hasattr(result, "tokens_used"):
                self.circuit_breaker.update_token_count(result.tokens_used)  # type: ignore
            elif hasattr(result, "usage_metadata"):
                metadata = result.usage_metadata  # type: ignore
                if metadata and "total_tokens" in metadata:
                    self.circuit_breaker.update_token_count(metadata["total_tokens"])


# ============================================================================
# Utility Functions
# ============================================================================


def get_tool_limits_status() -> dict[str, Any]:
    """Get current tool limits status.

    Returns:
        Dictionary with current limits and usage
    """
    circuit_breaker = get_circuit_breaker()
    return {
        "is_open": circuit_breaker._is_open,
        "calls_count": len(circuit_breaker.tracker.calls),
        "max_calls": circuit_breaker.config.max_calls_per_turn,
        "tokens_used": circuit_breaker.tracker.total_tokens,
        "max_tokens": circuit_breaker.config.max_context_tokens,
        "warning_threshold": circuit_breaker.config.warning_threshold,
    }


def reset_tool_limits() -> None:
    """Reset the tool limits circuit breaker."""
    reset_circuit_breaker()


__all__ = [
    "ToolLimitsMiddleware",
    "ToolLimitsState",
    "ToolLimitsStateUpdate",
    "get_tool_limits_status",
    "reset_tool_limits",
]
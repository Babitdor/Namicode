"""Steering middleware for injecting persistent user guidance into every model call.

Steering lets the user add standing instructions that persist across turns,
unlike regular chat messages which are "one and done."  Examples:

    /steer focus on the database layer
    /steer never modify test files without asking first
    /steer prioritize backward compatibility
    /steer use async patterns everywhere

These instructions are injected into every model call as a dedicated
section in the system prompt, ensuring the agent obeys them on every
turn — not just the one where they were typed.

The steering state is held in ``session_state.steering_instructions``,
a list of ``(label, instruction)`` tuples.  The ``/steer`` slash command
is the primary interface for managing them.

Architecture
-----------
``SteeringMiddleware`` sits in the agent middleware stack alongside
``GraphContextMiddleware``, ``ShellMiddleware``, etc.  It intercepts
every ``awrap_model_call`` and prepends the current steering instructions
to the system prompt, right after the base prompt but before any other
middleware injections.

The injection format is::

    [Steering Instructions]
    - focus on the database layer
    - never modify test files without asking first
    - prioritize backward compatibility
    [/Steering Instructions]

This is deliberately verbose — the agent sees these on every call, so
they act as persistent guardrails rather than one-off suggestions.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from langchain.agents.middleware.types import (
    AgentMiddleware,
    AgentState,
    ModelRequest,
    ModelResponse,
)
from langchain_core.messages import SystemMessage


# ---------------------------------------------------------------------------
# Steering instruction storage
# ---------------------------------------------------------------------------


class SteeringInstruction:
    """A single steering instruction with a label for display.

    Attributes:
        label: Short human-readable label (e.g., "focus", "constraint", "style").
        instruction: The full instruction text.
    """

    __slots__ = ("label", "instruction")

    def __init__(self, label: str, instruction: str) -> None:
        self.label = label
        self.instruction = instruction

    def __repr__(self) -> str:
        return f"SteeringInstruction({self.label!r}, {self.instruction!r})"


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------


class SteeringMiddleware(AgentMiddleware):
    """Inject persistent steering instructions into every model call.

    The middleware holds a reference to a shared list of
    ``SteeringInstruction`` objects.  The same list is stored in
    ``session_state.steering_instructions``, so updates via the ``/steer``
    command are immediately visible to the middleware — no state
    synchronization needed.

    When no steering instructions are active, this middleware is a no-op.
    """

    state_schema = AgentState

    def __init__(
        self,
        instructions: list[SteeringInstruction] | None = None,
        enabled: bool = True,
    ) -> None:
        """Initialize the steering middleware.

        Args:
            instructions: Shared list of steering instructions.  If None,
                creates an empty list internally (not connected to session state).
            enabled: If False, this middleware is a no-op.
        """
        self._enabled = enabled
        self._instructions: list[SteeringInstruction] = instructions if instructions is not None else []

    def _inject(self, request: ModelRequest) -> ModelRequest:
        """Inject steering instructions into the system prompt."""
        if not self._enabled:
            return request

        instructions = self._instructions
        if not instructions:
            return request

        # Format the steering section
        lines: list[str] = []
        for si in instructions:
            if si.label:
                lines.append(f"- [{si.label}] {si.instruction}")
            else:
                lines.append(f"- {si.instruction}")

        if not lines:
            return request

        block = "[Steering Instructions]\n" + "\n".join(lines) + "\n[/Steering Instructions]"

        system_prompt = request.system_prompt
        new_prompt = (system_prompt + "\n\n" + block) if system_prompt else block
        return request.override(system_message=SystemMessage(new_prompt))

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        """Inject steering into the system prompt (sync)."""
        return handler(self._inject(request))

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        """Inject steering into the system prompt (async)."""
        return await handler(self._inject(request))


# ---------------------------------------------------------------------------
# Formatting helpers (used by /steer command)
# ---------------------------------------------------------------------------


def format_steering_status(instructions: list[SteeringInstruction]) -> str:
    """Format the current steering instructions as a Rich-displayable summary.

    Args:
        instructions: List of active steering instructions.

    Returns:
        Formatted string for console display.  Empty string if none.
    """
    if not instructions:
        return "[dim]No steering instructions active.[/dim]"

    lines = [f"[cyan]{len(instructions)} steering instruction(s) active:[/cyan]"]
    for i, si in enumerate(instructions, 1):
        if si.label:
            lines.append(f"  [dim]{i}.[/dim] [bold]{si.label}[/bold]: {si.instruction}")
        else:
            lines.append(f"  [dim]{i}.[/dim] {si.instruction}")

    return "\n".join(lines)


def classify_instruction(text: str) -> str:
    """Classify a steering instruction into a category label.

    This is a simple heuristic that assigns a label based on keywords
    in the instruction text.  The label is used for display and
    organization, not for any logic.

    Args:
        text: The raw instruction text.

    Returns:
        A short label string (e.g., "focus", "constraint", "style", "priority").
    """
    text_lower = text.lower()

    # Constraint signals
    constraint_keywords = [
        "never", "don't", "dont", "do not", "must not", "cannot",
        "avoid", "refrain", "forbidden", "disallow", "no ",
    ]
    if any(kw in text_lower for kw in constraint_keywords):
        return "constraint"

    # Focus signals
    focus_keywords = [
        "focus on", "concentrate on", "prioritize", "emphasize",
        "pay attention to", "concentrate", "center on",
    ]
    if any(kw in text_lower for kw in focus_keywords):
        return "focus"

    # Priority signals
    priority_keywords = [
        "always", "make sure", "ensure", "guarantee", "important",
        "critical", "essential", "must",
    ]
    if any(kw in text_lower for kw in priority_keywords):
        return "priority"

    # Style signals
    style_keywords = [
        "use async", "use ", "prefer ", "style", "format", "pattern",
        "verbose", "concise", "brief", "detailed",
    ]
    if any(kw in text_lower for kw in style_keywords):
        return "style"

    return "guide"
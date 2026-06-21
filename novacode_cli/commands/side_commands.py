"""Shared logic for the /goal and /btw commands.

These commands are UI-triggered but their behaviour must be identical across the
Textual TUI, the Rich REPL, and the remote bridge (Discord/Telegram). The pure
logic lives here so each front-end only handles rendering, not semantics — see
``CLAUDE.md`` on keeping cross-UI behaviour in shared code rather than per-renderer
copies (which drift).

- ``handle_goal_command`` mutates ``session_state.active_goal`` and reports what
  happened; ``active_goal`` is injected into every turn by
  :func:`novacode_cli.core.agent_loop.iterate_agent_events`.
- ``run_btw_question`` answers a side question on an ephemeral thread using a
  dedicated web-search agent, leaving the main conversation untouched.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

__all__ = [
    "GoalCommandResult",
    "build_goal_kickoff",
    "handle_goal_command",
    "run_btw_question",
]

_GOAL_CLEAR_WORDS = frozenset({"clear", "off", "done", "stop"})


def build_goal_kickoff(goal: str) -> str:
    """Build the autonomous kick-off prompt streamed when a goal is set."""
    return (
        f"[GOAL] {goal}\n\n"
        "You are now in goal mode. Work autonomously to achieve the goal above.\n"
        "1. Analyse what is needed and form a clear execution plan.\n"
        "2. Execute the plan step by step, using your tools as needed.\n"
        "3. After each step verify your progress against the goal.\n"
        "4. When the goal is fully and verifiably achieved, say **GOAL ACHIEVED** "
        "and summarise what was done.\n"
        "Start now."
    )


@dataclass
class GoalCommandResult:
    """Outcome of a ``/goal`` invocation.

    Attributes:
        action: One of ``"set"``, ``"clear"``, ``"status"``, ``"usage"``.
        message: Plain-text summary suitable for any front-end to display.
        goal: The active goal after the command (``None`` once cleared).
        kickoff: When ``action == "set"``, the prompt a front-end should run to
            start autonomous execution; otherwise ``None``.
    """

    action: str
    message: str
    goal: str | None = None
    kickoff: str | None = None


def handle_goal_command(session_state: Any, args: str) -> GoalCommandResult:  # noqa: ANN401
    """Parse and apply a ``/goal`` command, mutating ``session_state.active_goal``.

    Args:
        session_state: The session state (its ``active_goal`` is read/written).
        args: Everything after ``/goal`` (already stripped of the command word).

    Returns:
        A :class:`GoalCommandResult` describing what happened.
    """
    low = args.strip().lower()

    if low == "status":
        goal = getattr(session_state, "active_goal", None)
        if goal:
            return GoalCommandResult("status", f"🎯 Active goal:\n{goal}", goal=goal)
        return GoalCommandResult(
            "status",
            "No active goal. Use /goal <description> to set one.",
        )

    if low in _GOAL_CLEAR_WORDS:
        session_state.active_goal = None
        return GoalCommandResult("clear", "🎯 Goal cleared.")

    if not args.strip():
        return GoalCommandResult(
            "usage",
            "Usage: /goal <description>  ·  /goal status  ·  /goal clear",
        )

    goal = args.strip()
    session_state.active_goal = goal
    return GoalCommandResult(
        "set",
        f"🎯 Goal set:\n{goal}",
        goal=goal,
        kickoff=build_goal_kickoff(goal),
    )


# The web-search agent is created lazily and cached for the process: it is
# stateless across questions (each /btw uses a fresh thread_id) so one instance
# is safe to share between the TUI and the remote bridge.
_btw_agent: Any = None


def get_btw_agent() -> Any:  # noqa: ANN401
    """Return the cached /btw web-search agent, creating it on first use."""
    global _btw_agent  # process-wide singleton by design
    if _btw_agent is None:
        from novacode_cli.agents.btw_agent import create_btw_agent
        from novacode_cli.config.model_create import create_model

        _btw_agent, _ = create_btw_agent(create_model())
    return _btw_agent


async def run_btw_question(
    question: str,
    *,
    on_event: Any = None,  # noqa: ANN401
) -> str:
    """Answer a side question on an ephemeral thread, isolated from the main chat.

    Runs the dedicated web-search agent on a fresh ``thread_id`` so nothing
    touches the main conversation history. Returns the agent's answer text.

    Args:
        question: The side question to answer.
        on_event: Optional callback invoked with each streamed ui_event (used by
            front-ends that want live tool/typing feedback). May be ``None``.

    Returns:
        The answer text, or a short error string prefixed with ``↩ btw``.
    """
    from novacode_cli.agent_stream import run_agent_stream
    from novacode_cli.ui_events import AssistantMessage, Done, Error

    question = question.strip()
    if not question:
        return "Usage: /btw <question>"

    try:
        agent = get_btw_agent()
    except Exception as ex:  # noqa: BLE001 — surface as a message, never crash the turn
        return f"↩ btw: could not start web-search agent — {ex}"

    class _BtwSession:
        """Minimal session shim — only the fields the agent loop reads."""

        def __init__(self) -> None:
            self.thread_id = f"btw-{uuid.uuid4().hex[:12]}"
            self.active_goal: str | None = None
            self.plan_mode_enabled: bool = False
            self.auto_approve: bool = True

    answer_parts: list[str] = []
    try:
        async for e in run_agent_stream(
            question,
            agent,
            "btw-agent",
            _BtwSession(),
            backend=None,
            seen_message_ids=set(),
        ):
            if on_event is not None:
                on_event(e)
            if isinstance(e, AssistantMessage):
                answer_parts.append(e.text)
            elif isinstance(e, Error):
                # Surface a recognised provider failure (usage cap, etc.) as the
                # answer rather than silently returning "(no response)".
                return e.message if e.is_provider_notice else f"↩ btw failed: {e.message}"
            elif isinstance(e, Done):
                break
    except Exception as ex:  # noqa: BLE001
        return f"↩ btw failed: {ex}"

    return "\n\n".join(answer_parts).strip() or "(no response)"

"""Autonomous goal loop — wraps ``iterate_agent_events`` (goal mode).

:func:`run_with_goal` is a drop-in for
:func:`~novacode_cli.core.agent_loop.iterate_agent_events`: it yields the *same*
UI events, but when ``session_state.active_goal`` is set it keeps re-driving the
agent across turns until the goal is reported achieved, the turn budget is
exhausted, or the goal is cleared.

The kickoff/follow-up prompts (``commands/side_commands.py``) instruct the agent
to emit ``GOAL ACHIEVED`` once the goal is verifiably done; this wrapper watches
for that marker in each turn's assistant text. ``Done`` is withheld until the
run actually ends (same contract as
:func:`~novacode_cli.core.verification_loop.run_with_verification`), so the
front-ends see one terminal event. ``Cancelled`` / ``Error`` pass straight
through and end the run.

When ``verify`` is set, each turn is routed through
:func:`~novacode_cli.core.verification_loop.run_with_verification` so the rubric
grader still gates every autonomous turn.

It wraps the canonical generator from *outside* rather than implementing an
``AgentMiddleware`` — so it sidesteps the sync/async ``wrap_*`` contract entirely
and keeps ``iterate_agent_events`` (and therefore both front-ends) untouched.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from novacode_cli import ui_events as ev
from novacode_cli.commands.side_commands import (
    DEFAULT_GOAL_MAX_TURNS,
    build_goal_followup,
    goal_achieved,
)
from novacode_cli.core.agent_loop import iterate_agent_events
from novacode_cli.tracking.usage_tree import scoped_stream

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

logger = logging.getLogger("nova.core.autonomous_loop")


async def run_with_goal(  # noqa: PLR0912
    user_input: str,
    agent: object,
    assistant_id: str | None,
    session_state: object,
    *,
    backend: object = None,
    image_tracker: object = None,
    seen_message_ids: set[str] | None = None,
    skip_file_mentions: bool = False,
    max_turns: int | None = None,
    verify: bool = False,
) -> AsyncIterator[Any]:
    """Run the agent autonomously toward the active goal, bounded by a turn cap.

    With no active goal this is a zero-overhead passthrough to
    :func:`iterate_agent_events`. With a goal, each turn is followed by a
    continuation prompt (unless the agent reported ``GOAL ACHIEVED``, the turn
    budget is exhausted, or the goal was cleared mid-run).

    Yields the same events as :func:`iterate_agent_events`. ``Done`` is withheld
    until the run ends; ``Cancelled`` / ``Error`` pass straight through.
    """
    goal = getattr(session_state, "active_goal", None)
    if not goal:
        async for event in iterate_agent_events(
            user_input,
            agent,
            assistant_id,
            session_state,
            backend=backend,
            image_tracker=image_tracker,
            seen_message_ids=seen_message_ids,
            skip_file_mentions=skip_file_mentions,
        ):
            yield event
        return

    limit = max_turns or getattr(session_state, "goal_max_turns", DEFAULT_GOAL_MAX_TURNS)
    turn = 0
    current_input = user_input

    while True:
        turn += 1
        assistant_texts: list[str] = []
        done_event: ev.Done | None = None

        if verify:
            from novacode_cli.core.verification_loop import run_with_verification
            from novacode_cli.hermes.verifier import InlineVerifier
            from novacode_cli.memory.store import get_durable_store

            source = run_with_verification(
                current_input,
                agent,
                assistant_id,
                session_state,
                backend=backend,
                image_tracker=image_tracker,
                seen_message_ids=seen_message_ids,
                skip_file_mentions=skip_file_mentions,
                verifier=InlineVerifier(get_durable_store(), enabled=True),
            )
        else:
            source = iterate_agent_events(
                current_input,
                agent,
                assistant_id,
                session_state,
                backend=backend,
                image_tracker=image_tracker,
                seen_message_ids=seen_message_ids,
                skip_file_mentions=skip_file_mentions,
            )

        # Each autonomous turn is attributed to "goal" so the tree separates
        # the base turn from the autonomous re-drives.
        async for event in scoped_stream(source, "goal"):
            if isinstance(event, ev.AssistantMessage):
                assistant_texts.append(event.text)
                yield event
            elif isinstance(event, ev.Done):
                done_event = event  # held back pending the goal check
            elif isinstance(event, (ev.Cancelled, ev.Error)):
                yield event
                return
            else:
                yield event

        # Stream ended. No Done means Cancelled/Error already returned above.
        if done_event is None:
            return

        # Re-read the goal each iteration so `/goal clear` stops the run.
        goal = getattr(session_state, "active_goal", None)
        agent_output = "\n\n".join(t for t in assistant_texts if t).strip()
        if not goal or goal_achieved(agent_output) or turn >= limit:
            # A single clean turn (achieved on turn 1) needs no notice; a
            # mid-run goal clear is an interruption and always gets one.
            if turn > 1 or not goal:
                if not goal:
                    message = "Autonomous goal run stopped — goal cleared."
                    color = "yellow"
                elif goal_achieved(agent_output):
                    message = f"Autonomous goal run finished after {turn} turn(s)."
                    color = "green"
                else:
                    message = f"Autonomous goal run stopped after {turn}/{limit} turn(s)."
                    color = "yellow"
                yield ev.ContextMessage(
                    message=message,
                    event_type="nova_goal_finish",
                    icon="🎯",
                    color=color,
                )
            yield done_event
            return

        yield ev.ContextMessage(
            message=f"Continuing toward goal — turn {turn}/{limit}.",
            event_type="nova_goal_continue",
            icon="🎯",
            color="cyan",
        )
        current_input = build_goal_followup(goal, turn, limit)

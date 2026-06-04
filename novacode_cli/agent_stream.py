"""UI-agnostic agent streaming.

Thin wrapper around :func:`novacode_cli.core.agent_loop.iterate_agent_events`
that preserves the public ``run_agent_stream`` API for backward compatibility.

Human-in-the-loop interrupts are surfaced as :class:`~novacode_cli.ui_events.InterruptRequest`
events carrying an ``asyncio.Future`` that the consumer must resolve with the
decision; the generator awaits it and resumes the graph.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from novacode_cli.core.agent_loop import iterate_agent_events


async def run_agent_stream(
    user_input: str,
    agent,
    assistant_id: str | None,
    session_state,
    *,
    backend=None,
    image_tracker=None,
    seen_message_ids: set[str] | None = None,
    skip_file_mentions: bool = False,
) -> AsyncIterator[Any]:
    """Run the agent and yield UI events.

    Delegates to :func:`~novacode_cli.core.agent_loop.iterate_agent_events`.
    Yields instances from :mod:`novacode_cli.ui_events`. Terminates with a
    :class:`~novacode_cli.ui_events.Done`, :class:`~novacode_cli.ui_events.Cancelled`,
    or :class:`~novacode_cli.ui_events.Error` event.
    """
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

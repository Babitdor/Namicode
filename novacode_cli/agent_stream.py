"""UI-agnostic agent streaming.

Thin wrapper around :func:`novacode_cli.core.agent_loop.iterate_agent_events`
that preserves the public ``run_agent_stream`` API for backward compatibility.

Human-in-the-loop interrupts are surfaced as :class:`~novacode_cli.ui_events.InterruptRequest`
events carrying an ``asyncio.Future`` that the consumer must resolve with the
decision; the generator awaits it and resumes the graph.

When the learning loop is enabled, each completed turn is graded out-of-band and
the verdict is logged — that verdict is the quality signal ``/prompt`` evolution
(prompt-template A/B testing) and ``verification_log`` feed on. Historically only
the legacy CLI path (``ui/execution.py`` via ``run_with_verification``) produced
this signal, so the TUI — which calls ``iterate_agent_events`` through here —
generated nothing, leaving ``verification_log`` empty and auto prompt-evolution
starved. The grade runs as a fire-and-forget background task: no retries and no
UI events, so it never delays or alters the turn.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from novacode_cli import ui_events as ev
from novacode_cli.core.agent_loop import iterate_agent_events

# Hold references to in-flight grade tasks so they aren't GC'd mid-run.
_verification_tasks: set[asyncio.Task] = set()


def _maybe_verifier() -> Any | None:
    """An ``InlineVerifier`` when the learning loop is enabled, else ``None``.

    Gated behind ``learning_enabled`` (opt-in) because grading adds one
    out-of-band model call per turn. Best-effort — any setup failure returns
    ``None`` and the turn runs unverified.
    """
    try:
        from novacode_cli.config.nova_config import NovaConfig

        if not NovaConfig().get_learning_enabled():
            return None
        from novacode_cli.hermes.verifier import InlineVerifier
        from novacode_cli.memory.store import get_durable_store

        return InlineVerifier(get_durable_store(), enabled=True)
    except Exception:  # noqa: BLE001 — learning is best-effort, never break a turn
        return None


def _spawn_verification_signal(
    verifier: Any, user_input: str, agent_output: str, file_ops: list, session_state: Any
) -> None:
    """Grade the finished turn and log the verdict (verification_log + prompt A/B).

    Fire-and-forget: no retries, no UI events. Skipped for a pure no-op turn
    (nothing produced to grade).
    """
    if verifier is None or (not agent_output and not file_ops):
        return

    async def _grade() -> None:
        try:
            from novacode_cli.core.verification_loop import _record_prompt_ab_outcome

            verdict = await verifier.grade(user_input, agent_output, file_ops)
            await verifier.log_outcome(getattr(session_state, "thread_id", ""), verdict, 0)
            # Feed prompt-evolution (Enhancement 2) its quality signal.
            await _record_prompt_ab_outcome(passed=verdict.passed)
        except Exception:  # noqa: BLE001 — a grading failure must never surface
            pass

    task = asyncio.create_task(_grade())
    _verification_tasks.add(task)
    task.add_done_callback(_verification_tasks.discard)


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
    or :class:`~novacode_cli.ui_events.Error` event. When learning is enabled,
    grades the completed turn out-of-band (see module docstring).
    """
    verifier = _maybe_verifier()
    texts: list[str] = []
    file_ops: list[Any] = []

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
        if verifier is not None:
            if isinstance(event, ev.AssistantMessage):
                texts.append(event.text)
            elif isinstance(event, ev.FileOp) and getattr(event, "record", None) is not None:
                file_ops.append(event.record)
        yield event

    if verifier is not None:
        agent_output = "\n\n".join(t for t in texts if t).strip()
        _spawn_verification_signal(verifier, user_input, agent_output, file_ops, session_state)

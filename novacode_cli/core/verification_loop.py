"""Inline verification loop — wraps ``iterate_agent_events`` (Enhancement 1).

:func:`run_with_verification` is a drop-in for
:func:`~novacode_cli.core.agent_loop.iterate_agent_events`: it yields the *same*
UI events, but intercepts the terminal :class:`~novacode_cli.ui_events.Done`.
Before letting ``Done`` through it asks an :class:`~novacode_cli.hermes.verifier.InlineVerifier`
to grade the turn; on a failing verdict (and while retries remain) it re-drives
the agent with the verifier's feedback as a fresh, clearly-labelled prompt, then
grades again. The user sees the passing attempt plus a small ``ContextMessage``
trail of any retries.

It wraps the canonical generator from *outside* rather than implementing an
``AgentMiddleware`` — so it sidesteps the sync/async ``wrap_*`` contract entirely
and keeps ``iterate_agent_events`` (and therefore both front-ends) untouched.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

from novacode_cli import ui_events as ev
from novacode_cli.core.agent_loop import iterate_agent_events

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from novacode_cli.hermes.verifier import InlineVerifier

logger = logging.getLogger("nova.core.verification_loop")

#: Prefix on the synthesized retry prompt. Signals to the agent that the text is
#: a self-correction directive, not a fresh user request.
_RETRY_PREFIX = "[VERIFICATION FEEDBACK]"

_GENERIC_FEEDBACK = (
    "The previous attempt did not fully satisfy the request. Re-examine the task "
    "and complete any missing or incorrect parts."
)

#: Cap on how much raw tool output we retain as test evidence per turn. Keeps the
#: rubric prompt bounded even when the agent runs a huge suite.
_MAX_TEST_EVIDENCE_CHARS = 4000
#: Cap on how many distinct tool outputs we keep as test evidence.
_MAX_TEST_EVIDENCE_BLOCKS = 6
#: Minimum number of test markers in short output before it counts as a test run.
_MIN_TEST_MARKERS = 2

#: Content markers that indicate a tool result is a test run. We match on the
#: *output* (not the tool name) so this is robust to tool-name variations across
#: backends (shell, python kernel, sandbox exec, etc.).
_TEST_RUN_MARKERS = (
    "pytest",
    "Ran ",
    " tests",
    "passed",
    "failed",
    "FAILED",
    "OK",
    "Traceback",
    "AssertionError",
    "exit code",
    "Exit code",
    "test session",
    "tests collected",
    "no tests ran",
    "no tests ran",
    "1 failed",
    "1 passed",
)

#: Regexes that strongly indicate a test run, used to avoid false positives on
#: ordinary prose that merely contains a marker word like "passed".
_TEST_RUN_STRONG_RE = re.compile(
    r"(pytest|test session|tests collected|Ran \d+ tests|"
    r"\d+ passed|\d+ failed|\d+ errors?|AssertionError|"
    r"FAILED|OK\s*$|no tests ran)",
    re.IGNORECASE,
)


def _looks_like_test_run(output: str) -> bool:
    """Heuristically decide whether a tool result is a test run.

    Uses a strong regex first (test-framework signatures); falls back to a
    marker-word scan only when the output is short and dense with markers, to
    avoid flagging ordinary prose.
    """
    if not output:
        return False
    if _TEST_RUN_STRONG_RE.search(output):
        return True
    # Short output with several markers is likely a test summary.
    if len(output) <= _MAX_TEST_EVIDENCE_CHARS:
        hits = sum(1 for m in _TEST_RUN_MARKERS if m in output)
        return hits >= _MIN_TEST_MARKERS
    return False


def _extract_test_evidence(tool_results: list[Any]) -> list[str]:
    """Collect test-run outputs from the turn's tool results.

    Returns a bounded list of truncated outputs that look like test runs, so the
    verifier can grade ``tests_pass`` against real evidence rather than the
    agent's claims.
    """
    evidence: list[str] = []
    for result in tool_results:
        output = getattr(result, "full_output", "") or ""
        if not _looks_like_test_run(output):
            continue
        block = output.strip()
        if len(block) > _MAX_TEST_EVIDENCE_CHARS:
            block = block[:_MAX_TEST_EVIDENCE_CHARS] + "\n...[truncated]"
        evidence.append(block)
        if len(evidence) >= _MAX_TEST_EVIDENCE_BLOCKS:
            break
    return evidence


def _extract_diffs(file_ops: list[Any]) -> list[str]:
    """Collect unified diffs from the turn's file-op records.

    Each :class:`~novacode_cli.file_ops.FileOperationRecord` already carries a
    ``diff`` field; we surface the non-empty ones so the verifier can detect
    reward hacking (e.g. edits that weaken tests).
    """
    diffs: list[str] = []
    for rec in file_ops or []:
        diff = getattr(rec, "diff", None)
        if diff:
            diffs.append(diff)
    return diffs


def _plural(n: int) -> str:
    return "retry" if n == 1 else "retries"


async def _record_prompt_ab_outcome(*, passed: bool) -> None:
    """Best-effort: feed a turn's verdict to prompt A/B testing (Enhancement 2).

    Lazily imported so ``core`` keeps no hard dependency on ``hermes``; any
    failure (including no candidate under test) is swallowed.
    """
    try:
        from novacode_cli.hermes.prompt_evolution import PromptEvolutionEngine
        from novacode_cli.memory.store import get_durable_store

        engine = PromptEvolutionEngine(get_durable_store())
        await engine.record_outcome(passed=passed)
    except Exception:
        logger.exception("Prompt A/B outcome recording skipped")


async def run_with_verification(  # noqa: PLR0912
    user_input: str,
    agent: object,
    assistant_id: str | None,
    session_state: object,
    *,
    backend: object = None,
    image_tracker: object = None,
    seen_message_ids: set[str] | None = None,
    skip_file_mentions: bool = False,
    verifier: InlineVerifier,
    max_retries: int | None = None,
) -> AsyncIterator[Any]:
    """Run the agent with an inline rubric grader and bounded feedback retries.

    Yields the same events as :func:`iterate_agent_events`. ``Done`` is withheld
    until a passing (or retry-exhausted) verdict; ``Cancelled`` / ``Error`` pass
    straight through and end the run.
    """
    limit = verifier.max_retries if max_retries is None else max_retries
    retries = 0
    current_input = user_input

    while True:
        assistant_texts: list[str] = []
        file_ops: list[Any] = []
        tool_results: list[Any] = []
        done_event: ev.Done | None = None

        async for event in iterate_agent_events(
            current_input,
            agent,
            assistant_id,
            session_state,
            backend=backend,
            image_tracker=image_tracker,
            seen_message_ids=seen_message_ids,
            skip_file_mentions=skip_file_mentions,
        ):
            if isinstance(event, ev.AssistantMessage):
                assistant_texts.append(event.text)
                yield event
            elif isinstance(event, ev.FileOp):
                if getattr(event, "record", None) is not None:
                    file_ops.append(event.record)
                yield event
            elif isinstance(event, ev.ToolResult):
                tool_results.append(event)
                yield event
            elif isinstance(event, ev.Done):
                done_event = event  # held back pending the verdict
            elif isinstance(event, (ev.Cancelled, ev.Error)):
                yield event
                return
            else:
                yield event

        # Stream ended. No Done means Cancelled/Error already returned above.
        if done_event is None:
            return

        agent_output = "\n\n".join(t for t in assistant_texts if t).strip()

        # Skip grading when disabled or when there's nothing to grade (a pure
        # no-op turn): just let the turn finish.
        if not verifier.enabled or (not agent_output and not file_ops):
            yield done_event
            return

        test_evidence = _extract_test_evidence(tool_results)
        diffs = _extract_diffs(file_ops)
        verdict = await verifier.grade(
            user_input,
            agent_output,
            file_ops,
            test_evidence=test_evidence,
            diffs=diffs,
        )
        await verifier.log_outcome(getattr(session_state, "thread_id", ""), verdict, retries)
        # Feed the verdict to prompt A/B testing (Enhancement 2) as the quality
        # signal for any template under test. Best-effort; never breaks the turn.
        await _record_prompt_ab_outcome(passed=verdict.passed)

        if verdict.passed:
            if retries > 0:
                yield ev.ContextMessage(
                    message=f"Verification passed after {retries} {_plural(retries)}.",
                    event_type="nova_verification_pass",
                    icon="✅",
                    color="green",
                )
            yield done_event
            return

        if retries >= limit:
            yield ev.ContextMessage(
                message=(
                    f"Verification still failing after {retries} {_plural(retries)}; "
                    "returning best effort."
                ),
                event_type="nova_verification_fail",
                icon="⚠",
                color="yellow",
            )
            yield done_event
            return

        retries += 1
        feedback = verdict.feedback or _GENERIC_FEEDBACK
        yield ev.ContextMessage(
            message=f"Verification failed — retrying ({retries}/{limit}): {feedback[:160]}",
            event_type="nova_verification_retry",
            icon="🔄",
            color="yellow",
        )
        current_input = f"{_RETRY_PREFIX} {feedback}\n\nOriginal task: {user_input}"

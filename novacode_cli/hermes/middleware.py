"""Nova learning middleware — tool call tracking, review triggers, and lesson extraction.

This middleware implements the core "Periodic Review Loop" pillar of the Nova
system. It wraps every tool call to count usage, and after a threshold of calls
injects review instructions into the next model call.

Architecture:
    Follows the same AgentMiddleware pattern as AgentMemoryMiddleware and
    SteeringMiddleware (see ``novacode_cli/memory/agent_memory.py`` and
    ``novacode_cli/bootstrap/steering.py``).  Uses the shared durable store
    for persistence across restarts.

Durable Store Schema (namespace="Nova"):
    ("nova", "tool_counter")    → {"count": int}
    ("nova", "tool_history")    → [{"tool": str, "success": bool, "timestamp": float}, ...]
    ("nova", "last_review")     → {"timestamp": float, "lessons": list[str], "lessons_str": str}
    ("nova", "skill_stats")     → {skill_name: {"uses": int, "successes": int, "failures": int}}
    ("nova", "reviews")         → {review_id: {"timestamp": float, "content": str}}
    ("nova", "meta")            → {"last_review": float, "review_count": int, "review_just_completed": bool}
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from langchain.agents.middleware.types import (
    AgentMiddleware,
    AgentState,
    ExtendedModelResponse,
    ModelRequest,
    ModelResponse,
)
from langchain_core.messages import SystemMessage, ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command
from typing_extensions import NotRequired

from novacode_cli.prompts import render_template

if TYPE_CHECKING:
    from langgraph.store.base import BaseStore
    from pathlib import Path

logger = logging.getLogger("nova.hermes.middleware")

_MAX_COUNTER = 1_000_000  # Sanity cap to prevent integer overflow
_MAX_EVENT_LOG = 200  # Cap on nova_event_log to prevent unbounded growth

# Module-level event buffer for Nova events (review cycles, skill activity).
# The middleware appends ``(event_type, icon, message)`` tuples here, and
# ``iterate_agent_events`` in ``core/agent_loop.py`` drains them into proper
# :class:`~novacode_cli.ui_events.ContextMessage` events that both the Rich
# console renderer and the Textual TUI consume.
nova_event_log: list[tuple[str, str, str, str]] = []
"""``(event_type, icon, color, message)`` log drained by the agent event loop.

The list is cleared after each drain.  Event types:
- ``nova_review_start``
- ``nova_review_complete``
- ``nova_skill_refinement``
"""


class NovaState(AgentState):
    """Extended agent state for tracking Nova learning cycle."""

    nova_review_triggered: NotRequired[bool]
    """Whether a review prompt was injected into the current model call."""
    last_review_timestamp: NotRequired[float]
    """Unix timestamp of the most recent review."""
    review_count: NotRequired[int]
    """Total number of reviews completed in this session."""
    last_review_content: NotRequired[str]
    """Preview of the last review content."""


class AtomicCounter:
    """Atomic counter using asyncio lock for thread-safe operations."""

    def __init__(self, store: BaseStore):
        self._store = store
        self._lock = asyncio.Lock()

    async def increment(self) -> int:
        """Increment counter atomically and return new value."""
        async with self._lock:
            # Read current
            entry = await self._store.aget(("nova", "tool_counter"), "counter")
            current = 0
            if entry and isinstance(entry.value, dict):
                current = entry.value.get("count", 0)

            new_value = min(current + 1, _MAX_COUNTER)

            # Write back
            await self._store.aput(
                ("nova", "tool_counter"), "counter", {"count": new_value}
            )
            return new_value

    async def get(self) -> int:
        """Get current counter value."""
        async with self._lock:
            entry = await self._store.aget(("nova", "tool_counter"), "counter")
            if entry and isinstance(entry.value, dict):
                return min(entry.value.get("count", 0), _MAX_COUNTER)
            return 0

    async def reset(self) -> None:
        """Reset counter to zero."""
        async with self._lock:
            await self._store.aput(("nova", "tool_counter"), "counter", {"count": 0})


class NovaLearningMiddleware(AgentMiddleware[NovaState]):
    """Track tool usage, trigger periodic reviews, and manage learning state.

    The middleware sits in the agent middleware stack and wraps both tool call
    and model call hooks to implement the Nova learning loop.

    State schema:
        - ``nova_review_triggered`` — set to True when a review is injected
        - ``last_review_timestamp`` — updated after each review completes
        - ``review_count`` — incremented after each review completes
    """

    state_schema = NovaState
    tools: list = []

    def __init__(
        self,
        store: BaseStore,
        *,
        review_threshold: int = 10,
        skills_dir: Path | None = None,
        agent_dir: Path | None = None,
        enabled: bool = True,
    ) -> None:
        """Initialize the Nova learning middleware.

        Args:
            store: Shared durable store (from ``get_durable_store()``).
            review_threshold: Number of tool calls between automatic reviews.
            skills_dir: Path to the skills directory (for skill creation/refinement).
            agent_dir: Path to the agent directory (for USER.md / MEMORY.md).
            enabled: If False, all hooks are no-ops.
        """
        super().__init__()
        self._store = store
        self._review_threshold = review_threshold
        self._skills_dir = skills_dir
        self._agent_dir = agent_dir
        self._enabled = enabled
        self._counter = AtomicCounter(store)
        self._refinement_tasks: set[asyncio.Task] = set()
        """Track refinement tasks to prevent garbage collection issues."""

    # ------------------------------------------------------------------
    # Tool call tracking
    # ------------------------------------------------------------------

    async def _get_tool_call_count(self) -> int:
        """Return the current tool call count from the durable store."""
        if not self._enabled:
            return 0
        return await self._counter.get()

    async def _set_tool_call_count(self, count: int) -> None:
        """Persist the tool call count to the durable store."""
        if not self._enabled:
            return
        # This is handled by AtomicCounter, but keep for interface compatibility
        await self._store.aput(
            ("nova", "tool_counter"), "counter", {"count": min(count, _MAX_COUNTER)}
        )

    async def _increment_counter(self) -> int:
        """Increment and persist the tool call counter. Returns the new count."""
        return await self._counter.increment()

    async def _reset_counter(self) -> None:
        """Reset the tool call counter to zero (after a review)."""
        await self._counter.reset()
        # Mark that a review was just completed (persisted to durable store)
        await self._set_review_just_completed(True)

    async def _record_tool_usage(self, tool_name: str, success: bool) -> None:
        """Record a single tool call in the tool history."""
        if not self._enabled:
            return
        try:
            # Get existing history (capped at last 200 entries)
            existing = await self._store.aget(("nova", "tool_history"), "history")
            history: list[dict[str, Any]] = []
            if (
                existing
                and isinstance(existing.value, dict)
                and "entries" in existing.value
            ):
                # Value is wrapped as {"entries": [...]}
                history = existing.value["entries"][-199:]

            history.append(
                {
                    "tool": tool_name,
                    "success": success,
                    "timestamp": time.time(),
                }
            )
            # Wrap the list in a dict for storage
            await self._store.aput(
                ("nova", "tool_history"), "history", {"entries": history}
            )

            # Also track skill-level stats
            await self._track_skill_usage(tool_name, success)
        except Exception:  # noqa: BLE001
            logger.exception("Failed to record tool usage for '%s'", tool_name)

    async def _track_skill_usage(self, tool_name: str, success: bool) -> None:
        """Track per-skill usage statistics.

        Only tracks tool calls that correspond to known skills (i.e. not
        built-in tools like read_file, write_file, edit_file, grep).
        """
        # Skip built-in filesystem and basic tools
        builtin = {
            "read_file",
            "write_file",
            "edit_file",
            "grep",
            "ls",
            "glob",
            "execute",
            "think",
            "web_search",
            "duckduckgo_search",
            "docs_search",
            "code_search",
            "find_related_code",
            "fetch_url",
            "package_info",
        }
        if tool_name in builtin:
            return

        try:
            entry = await self._store.aget(("nova", "skill_stats"), tool_name)
            stats: dict[str, int] = {"uses": 0, "successes": 0, "failures": 0}
            if entry and isinstance(entry.value, dict):
                stats = dict(entry.value)

            stats["uses"] += 1
            if success:
                stats["successes"] += 1
            else:
                stats["failures"] += 1

            await self._store.aput(("nova", "skill_stats"), tool_name, stats)
        except Exception:  # noqa: BLE001
            logger.exception("Failed to track skill usage for '%s'", tool_name)

    # ------------------------------------------------------------------
    # Review injection
    # ------------------------------------------------------------------

    async def _run_review(self, request: ModelRequest) -> None:
        """Run a self-review as a *separate, out-of-band* model call.

        CRITICAL: the review must NOT be injected into the agent's task turn.
        Injecting the review prompt as the final message made the model answer
        the review (plain text, no tool calls); the agent loop then saw a
        no-tool-call response and terminated — abandoning the user's actual
        task. Instead we issue an independent ``model.ainvoke`` with the
        conversation history plus the review prompt, parse the result, and
        persist learnings. The agent's real turn is returned untouched by the
        caller, so the loop continues normally.

        Tool calls in the review response (if any) are ignored — this call is
        never wired into the graph's tool node.
        """
        if not self._enabled:
            return

        try:
            review_content = render_template(
                "nova_review.jinja", tool_call_count=self._review_threshold
            )
            messages = [*request.messages, SystemMessage(content=review_content)]

            review_msg = await request.model.ainvoke(messages)

            content = ""
            raw = getattr(review_msg, "content", "")
            content = raw if isinstance(raw, str) else str(raw)

            await self._apply_review_content(content)
        except Exception:  # noqa: BLE001
            logger.exception("Nova out-of-band review failed")

    async def _should_review(self) -> bool:
        """Check whether a review cycle should be triggered.

        Returns True if:
        - Tool call count >= threshold, AND
        - No review was just completed (to avoid back-to-back reviews)
        """
        count = await self._get_tool_call_count()
        if count < self._review_threshold:
            return False

        # Check if a review just completed (in this middleware session)
        just_completed = await self._get_review_just_completed()
        if just_completed:
            # Clear the flag for next cycle
            await self._set_review_just_completed(False)
            return False

        return True

    async def _apply_review_content(self, response_content: str) -> None:
        """Persist a completed review's learnings.

        Given the raw text produced by the out-of-band review call, this:
        1. Parses structured updates from XML tags
        2. Updates USER.md and MEMORY.md with learnings
        3. Stores review metadata in the durable store
        4. Compacts memory files if needed
        5. Checks if any skills need refinement (every 5th review)

        It performs no state mutation on the agent graph — the agent's real
        turn output is owned by the caller and returned untouched.
        """
        if not self._enabled:
            return

        try:
            response_content = response_content or ""

            # Parse structured updates from the response
            from novacode_cli.hermes.memory_tiers import (
                parse_review_response,
                update_from_review,
            )

            parsed = parse_review_response(response_content)

            # Apply to memory files
            if self._agent_dir and (parsed["user_updates"] or parsed["session_memory"]):
                update_from_review(
                    self._agent_dir, parsed["user_updates"], parsed["session_memory"]
                )
                logger.info(
                    f"Nova review applied: user_updates={bool(parsed['user_updates'])}, session_memory={bool(parsed['session_memory'])}"
                )
            elif self._agent_dir and response_content:
                # Fallback: if no XML but content exists, treat as session memory
                update_from_review(self._agent_dir, "", response_content)
                logger.info("Nova review applied as session memory (no XML structure)")

            # Load existing review count before any state changes
            current_count = await self._get_review_count()

            # Store the review in the durable store
            review_id = f"review_{int(time.time())}"
            await self._store.aput(
                ("nova", "reviews"),
                review_id,
                {
                    "timestamp": time.time(),
                    "content": response_content[:2000],
                },  # Store preview
            )

            # Update last_review meta
            new_count = current_count + 1
            await self._store.aput(
                ("nova", "meta"),
                "last_review",
                {
                    "timestamp": time.time(),
                    "lessons_str": response_content[:500] if response_content else "",
                    "review_count": new_count,
                },
            )

            # Try memory compaction if we have an agent directory
            if self._agent_dir:
                try:
                    from novacode_cli.hermes.memory_tiers import compact_memory_file

                    user_md = self._agent_dir / "USER.md"
                    memory_md = self._agent_dir / "MEMORY.md"
                    for f in [user_md, memory_md]:
                        if f.exists():
                            compact_memory_file(f)
                except Exception:  # noqa: BLE001
                    logger.exception("Failed to compact memory files")

            # Skill maintenance, periodically (every 5th review). Both creation
            # and refinement run as tracked background tasks via _generate_skill,
            # which spins up a dedicated file-writing agent — so the toolless
            # review model.ainvoke never needs to create files itself.
            if self._skills_dir and new_count % 5 == 0:
                await self._maybe_create_skills()
                await self._maybe_refine_skills()

        except Exception:  # noqa: BLE001
            logger.exception("Failed to apply review content")

    def _spawn_skill_task(self, coro) -> None:
        """Run a skill create/refine coroutine as a tracked background task."""
        task = asyncio.create_task(coro)
        self._refinement_tasks.add(task)

        def _done(t: asyncio.Task) -> None:
            self._refinement_tasks.discard(t)
            if not t.cancelled() and t.exception():
                logger.error("Skill task failed: %s", t.exception())

        task.add_done_callback(_done)

    async def _maybe_create_skills(self) -> None:
        """Autonomously create a skill from a repeated, successful tool pattern.

        Detects patterns from tool history and, for the top candidate, kicks off
        ``create_skill_from_pattern`` — which runs a dedicated agent that writes
        ``SKILL.md`` to disk. Deduped by deterministic skill name so the same
        workflow isn't recreated.
        """
        if not self._skills_dir:
            return
        try:
            from novacode_cli.hermes.skill_discovery import (
                analyze_tool_history,
                create_skill_from_pattern,
                generate_skill_name,
            )

            patterns = await analyze_tool_history(self._store)
            for pattern in patterns[:1]:  # one creation per cycle (it's an LLM call)
                skill_name = generate_skill_name(pattern)
                # Skip if already created (store record or on-disk SKILL.md).
                already = await self._store.aget(("nova", "created_skills"), skill_name)
                if already is not None or (self._skills_dir / skill_name).exists():
                    continue
                await self._emit_tui_event(
                    "nova_skill_created",
                    f"🧠 Nova: creating skill from pattern "
                    f"{' → '.join(pattern.sequence)}",
                )
                self._spawn_skill_task(
                    create_skill_from_pattern(pattern, self._skills_dir, self._store)
                )
        except Exception:  # noqa: BLE001
            logger.exception("Failed to analyze / create skills")

    async def _maybe_refine_skills(self) -> None:
        """Refine an existing skill flagged as ineffective."""
        if not self._skills_dir:
            return
        try:
            from novacode_cli.hermes.skill_discovery import (
                check_skill_effectiveness,
                refine_skill,
            )

            candidates = await check_skill_effectiveness(self._store)
            for skill_name, issue in candidates[:1]:  # one per cycle
                # Only refine skills that actually exist on disk (skill_stats can
                # hold tool names that aren't skills).
                if not (self._skills_dir / skill_name / "SKILL.md").exists():
                    continue
                await self._emit_tui_event(
                    "nova_skill_refinement",
                    f"🛠 Nova: skill '{skill_name}' needs refinement ({issue})",
                )
                self._spawn_skill_task(
                    refine_skill(skill_name, self._skills_dir, issue)
                )
        except Exception:  # noqa: BLE001
            logger.exception("Failed to check skill effectiveness / refine")

    async def _get_review_count(self) -> int:
        """Return the total number of reviews completed from the durable store."""
        try:
            entry = await self._store.aget(("nova", "meta"), "last_review")
            if entry and isinstance(entry.value, dict):
                return entry.value.get("review_count", 0)
        except Exception:  # noqa: BLE001
            logger.exception("Failed to get review count")
        return 0

    async def _get_review_just_completed(self) -> bool:
        """Check if a review was just completed (in this middleware session).

        Used to prevent rapid back-to-back review injections when the middleware
        is instantiated fresh (e.g., /init creating its own agent) but the counter
        still reports >= threshold from a prior review.
        """
        try:
            entry = await self._store.aget(("nova", "meta"), "review_just_completed")
            if entry and isinstance(entry.value, dict):
                return entry.value.get("value", False)
        except Exception:  # noqa: BLE001
            logger.exception("Failed to check if review just completed")
        return False

    async def _set_review_just_completed(self, value: bool) -> None:
        """Mark whether a review was just completed (to skip next trigger)."""
        if not self._enabled:
            return
        try:
            await self._store.aput(
                ("nova", "meta"),
                "review_just_completed",
                {"value": value},  # Wrap bool in dict
            )
        except Exception:  # noqa: BLE001
            logger.exception("Failed to set review_just_completed flag")

    async def _emit_tui_event(self, event_type: str, message: str) -> None:
        """Append a Nova event to the shared module-level buffer.

        The buffer is drained by ``iterate_agent_events`` which yields proper
        :class:`~novacode_cli.ui_events.ContextMessage` events — consumed by
        both the Rich console renderer and the Textual TUI.

        Events are:
        - nova_review_start: Review cycle beginning
        - nova_review_complete: Review cycle finished
        - nova_skill_refinement: Skill detected for improvement
        """
        try:
            event_config = {
                "nova_review_start": {"icon": "🔄", "color": "cyan"},
                "nova_review_complete": {"icon": "✓", "color": "green"},
                "nova_skill_created": {"icon": "🧠", "color": "green"},
                "nova_skill_refinement": {"icon": "🛠", "color": "yellow"},
            }
            conf = event_config.get(event_type, {"icon": "•", "color": "cyan"})
            nova_event_log.append((event_type, conf["icon"], conf["color"], message))
            # Cap the buffer to prevent unbounded growth if drain stalls
            if len(nova_event_log) > _MAX_EVENT_LOG:
                del nova_event_log[: len(nova_event_log) - _MAX_EVENT_LOG]
        except Exception:  # noqa: BLE001
            logger.exception("Failed to emit TUI event '%s'", event_type)

    # ------------------------------------------------------------------
    # Middleware hooks
    # ------------------------------------------------------------------

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command[Any]],
    ) -> ToolMessage | Command[Any]:
        """Synchronous wrapper — pass-through only.

        The agent runs in an async context (``astream`` / ``ainvoke``), so
        ``asyncio.run()`` would raise ``RuntimeError`` from a running event
        loop.  All tracking happens in the async hooks (``awrap_tool_call`` /
        ``awrap_model_call``).  This sync stub exists solely to satisfy the
        ``AgentMiddleware`` interface for synchronous test contexts.
        """
        return handler(request)

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse | ExtendedModelResponse:
        """Synchronous wrapper — pass-through only.

        See ``wrap_tool_call`` for the rationale.  All review injection and
        tracking happens in the async hooks.
        """
        return handler(request)

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        """Track every tool call: increment counter and record usage."""
        if not self._enabled:
            return await handler(request)

        try:
            response = await handler(request)
            tool_name = (
                request.tool_call.get("name", "unknown")
                if hasattr(request, "tool_call")
                else "unknown"
            )
            success = (
                (getattr(response, "status", "success") != "error")
                if response
                else True
            )
            await self._increment_counter()
            await self._record_tool_usage(tool_name, success)
            return response
        except Exception as exc:
            # Track failures too
            tool_name = (
                request.tool_call.get("name", "unknown")
                if hasattr(request, "tool_call")
                else "unknown"
            )
            await self._increment_counter()
            await self._record_tool_usage(tool_name, False)
            raise

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        """Run the agent's turn, then trigger an out-of-band review if due.

        The agent's real model call is ALWAYS executed and its response is
        returned untouched, so the agent loop continues normally. When the tool
        call count has reached the threshold, the review runs as a separate
        ``model.ainvoke`` (see :meth:`_run_review`) — it never replaces the
        agent's task turn. This avoids the previous bug where injecting the
        review prompt into the turn produced a no-tool-call response that
        terminated the agent mid-task.
        """
        if not self._enabled:
            return await handler(request)

        should_review = await self._should_review()

        # The agent's real turn — always executed, always returned untouched.
        response = await handler(request)

        if should_review:
            # Reset immediately so the next model call doesn't re-trigger while
            # the review is in flight.
            await self._reset_counter()
            await self._emit_tui_event(
                "nova_review_start",
                "🔄 Nova review cycle starting...",
            )
            # Run the review as a tracked background task so it never blocks the
            # event stream. This lets the UI surface a live "reviewing…"
            # indicator (drained between stream chunks) while the out-of-band
            # review call is in flight, and the completion event fires when the
            # task finishes.
            task = asyncio.create_task(self._run_review_task(request))
            self._refinement_tasks.add(task)
            task.add_done_callback(self._refinement_tasks.discard)

        return response

    async def _run_review_task(self, request: ModelRequest) -> None:
        """Background wrapper around :meth:`_run_review`.

        Emits the completion event in a ``finally`` so the live indicator is
        always cleared/updated even if the review call fails.
        """
        try:
            await self._run_review(request)
        finally:
            await self._emit_tui_event(
                "nova_review_complete",
                "✓ Nova review cycle complete",
            )

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    async def get_tool_history(self, limit: int = 50) -> list[dict[str, Any]]:
        """Return the most recent tool usage history."""
        try:
            entry = await self._store.aget(("nova", "tool_history"), "history")
            if entry and isinstance(entry.value, dict):
                entries = entry.value.get("entries", [])
                if isinstance(entries, list):
                    return entries[-limit:]
        except Exception:  # noqa: BLE001
            logger.exception("Failed to get tool history")
        return []

    async def get_skill_stats(self) -> dict[str, dict[str, int]]:
        """Return all tracked skill usage statistics."""
        try:
            results = await self._store.asearch(("nova", "skill_stats"))
            stats: dict[str, dict[str, int]] = {}
            for item in results:
                if hasattr(item, "key") and hasattr(item, "value"):
                    stats[item.key] = dict(item.value)  # type: ignore[arg-type]
            return stats
        except Exception:  # noqa: BLE001
            logger.exception("Failed to get skill stats")
        return {}

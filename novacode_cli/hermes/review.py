"""Review orchestration — out-of-band model invocation, content persistence.

Extracted from ``NovaLearningMiddleware``.  Owns the periodic review lifecycle:
triggering when the tool-call threshold is reached, running a separate model
call, parsing the result, and persisting learnings to memory files + durable
store.

Depends on ``ToolUsageTracker`` for counter resets and ``SkillManager`` for
post-review skill creation/refinement (both injected).
"""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING

from langchain_core.messages import SystemMessage

from novacode_cli.events import cap_event_log, nova_event_log
from novacode_cli.prompts import render_template

if TYPE_CHECKING:
    from langchain.agents.middleware.types import ModelRequest
    from langgraph.store.base import BaseStore

    from novacode_cli.hermes.skill_manager import SkillManager
    from novacode_cli.hermes.tracker import ToolUsageTracker

logger = logging.getLogger("nova.hermes.review")

# Tools that signal *real work* happened in a window (vs. read-only browsing).
# Any non-builtin tool (a skill or MCP tool) also counts as substantive.
_SUBSTANTIVE_TOOLS: frozenset[str] = frozenset(
    {"write_file", "edit_file", "execute", "run_tests"}
)
# Read-only/builtin tools that, on their own, are not worth reviewing.
_TRIVIAL_BUILTINS: frozenset[str] = frozenset(
    {"read_file", "grep", "ls", "glob", "think", "web_search",
     "duckduckgo_search", "docs_search", "fetch_url", "package_info"}
)
# A burst of failures in the window is worth reviewing *early* (before the count
# threshold), so the agent captures the recovery while it's fresh.
_FAILURE_BURST = 3


def _window_recovered(window: list[dict]) -> bool:
    """True if the window shows an error *that was then recovered from*.

    Defined as: at least one failed call, followed later by a successful
    *substantive* call (a write/edit/execute/test or non-builtin tool). That
    "hit an error, then made it work" shape is exactly what's worth distilling
    into a skill.
    """
    last_fail = max(
        (i for i, h in enumerate(window) if not h.get("success", True)),
        default=-1,
    )
    if last_fail < 0:
        return False
    for h in window[last_fail + 1 :]:
        if h.get("success", True) and (
            h.get("tool") in _SUBSTANTIVE_TOOLS
            or h.get("tool") not in _TRIVIAL_BUILTINS
        ):
            return True
    return False

# Icon / color mapping for TUI events emitted by this module.
_EVENT_CONFIG: dict[str, dict[str, str]] = {
    "nova_review_start": {"icon": "🔄", "color": "cyan"},
    "nova_review_complete": {"icon": "✓", "color": "green"},
    "nova_skill_created": {"icon": "🧠", "color": "green"},
    "nova_skill_refinement": {"icon": "🛠", "color": "yellow"},
}


def _emit_event(event_type: str, message: str) -> None:
    """Append a Nova event to the shared module-level buffer.

    Best-effort — never raise from a notification.
    """
    try:
        conf = _EVENT_CONFIG.get(event_type, {"icon": "•", "color": "cyan"})
        nova_event_log.append((event_type, conf["icon"], conf["color"], message))
        cap_event_log()
    except Exception:  # noqa: BLE001
        logger.exception("Failed to emit TUI event '%s'", event_type)


class ReviewRunner:
    """Periodic review lifecycle: trigger, run, persist.

    Designed to be created by ``NovaLearningMiddleware`` which injects the
    ``ToolUsageTracker`` and ``SkillManager`` instances.
    """

    def __init__(
        self,
        store: BaseStore,
        tracker: ToolUsageTracker,
        skill_manager: SkillManager,
        *,
        review_threshold: int = 10,
        agent_dir: Path | None = None,
        enabled: bool = True,
    ) -> None:
        self._store = store
        self._tracker = tracker
        self._skill_manager = skill_manager
        self._review_threshold = review_threshold
        self._agent_dir = agent_dir
        self._enabled = enabled

    # -- Trigger decision ---------------------------------------------------

    async def should_review(self) -> bool:
        """Decide whether to trigger a review — by *signal*, not raw count.

        A review fires when any of these hold (and a review wasn't just done):

        - **Failure burst**: >= ``_FAILURE_BURST`` failed tool calls in the
          current window (review early, while the recovery is fresh).
        - **Substantive threshold**: count >= threshold *and* the window
          contains real work (a write/edit/execute/test or any non-builtin
          tool) — not just read-only browsing.
        - **Hard cap**: count >= 2× threshold, so an all-trivial window can't
          defer a review forever.

        A count-only window of pure reads is *deferred* (not reviewed), since
        there's nothing worth distilling. When window history is unavailable we
        treat it as substantive, preserving plain count-based behavior.
        """
        count = await self._tracker.get_call_count()
        min_floor = max(3, self._review_threshold // 2)

        # Inspect the current window (calls since the last counter reset).
        window: list[dict] = []
        if count > 0:
            try:
                window = await self._tracker.get_tool_history(limit=count)
            except Exception:  # noqa: BLE001
                window = []

        failures = sum(1 for h in window if not h.get("success", True))
        # Only suppress when we positively know the window was all-trivial.
        substantive = (not window) or any(
            (h.get("tool") in _SUBSTANTIVE_TOOLS)
            or (h.get("tool") not in _TRIVIAL_BUILTINS)
            for h in window
        )

        failure_burst = failures >= _FAILURE_BURST and count >= min_floor
        reached = count >= self._review_threshold
        hard_cap = count >= 2 * self._review_threshold

        if not (hard_cap or failure_burst or (reached and substantive)):
            return False

        just_completed = await self._get_review_just_completed()
        if just_completed:
            await self._set_review_just_completed(False)
            return False

        return True

    async def reset_after_review(self) -> None:
        """Reset the counter and mark review-just-completed."""
        await self._tracker.reset_counter()
        await self._set_review_just_completed(True)

    # -- OOB model invoke ---------------------------------------------------

    async def run_review(self, request: ModelRequest) -> None:
        """Run a self-review as a *separate, out-of-band* model call.

        CRITICAL: the review must NOT be injected into the agent's task turn.
        Instead we issue an independent ``model.ainvoke`` with the conversation
        history plus a review prompt, parse the result, and persist learnings.
        The agent's real turn is returned untouched by the caller.
        """
        if not self._enabled:
            return

        try:
            prior_lessons = await self._recent_lessons()
            # The counter is reset before this task runs, so look back a fixed
            # recent window (history isn't reset) to detect an error-recovery.
            try:
                recent = await self._tracker.get_tool_history(
                    limit=2 * self._review_threshold
                )
            except Exception:  # noqa: BLE001
                recent = []
            recovered_from_error = _window_recovered(recent)
            review_content = render_template(
                "nova_review.jinja",
                tool_call_count=self._review_threshold,
                prior_lessons=prior_lessons,
                recovered_from_error=recovered_from_error,
            )
            messages = [*request.messages, SystemMessage(content=review_content)]

            # Name + tag + annotate this call so it's findable in LangSmith.
            # The review runs in a fire-and-forget asyncio task, so it surfaces
            # as its OWN top-level trace (not nested under the agent run) — a
            # generic name makes it impossible to pick out. With this config it
            # is filterable via:  langsmith trace list --name nova_oob_review
            review_count = await self._get_review_count()
            review_config = {
                "run_name": "nova_oob_review",
                "tags": ["nova", "hermes", "oob-review"],
                "metadata": {
                    "nova_review_count": review_count,
                    "nova_review_threshold": self._review_threshold,
                    "nova_window_messages": len(request.messages),
                    "nova_prior_lessons": bool(prior_lessons),
                },
            }
            review_msg = await request.model.ainvoke(messages, config=review_config)

            content = ""
            raw = getattr(review_msg, "content", "")
            content = raw if isinstance(raw, str) else str(raw)

            await self._apply_review_content(content)
        except Exception:  # noqa: BLE001
            logger.exception("Nova out-of-band review failed")

    async def run_review_task(self, request: ModelRequest) -> None:
        """Background wrapper around :meth:`run_review`.

        Emits the completion event in a ``finally`` so the live indicator is
        always cleared/updated even if the review call fails.
        """
        try:
            await self.run_review(request)
        finally:
            _emit_event("nova_review_complete", "✓ Nova review cycle complete")

    async def _recent_lessons(self, limit: int = 5, max_chars: int = 1500) -> str:
        """Return a digest of recent prior reviews to suppress repeat lessons.

        Pulls the most recent ``("nova", "reviews")`` entries (newest first) and
        concatenates their content up to ``max_chars``. Injected into the review
        prompt so the LLM doesn't re-derive lessons already captured. Best-effort.
        """
        try:
            results = await self._store.asearch(("nova", "reviews"))
        except Exception:  # noqa: BLE001
            return ""

        entries: list[tuple[float, str]] = []
        for item in results or []:
            value = getattr(item, "value", None)
            if isinstance(value, dict) and value.get("content"):
                entries.append((value.get("timestamp", 0.0), str(value["content"])))

        entries.sort(key=lambda e: e[0], reverse=True)

        digest: list[str] = []
        used = 0
        for _ts, content in entries[:limit]:
            snippet = content.strip()
            if not snippet:
                continue
            if used + len(snippet) > max_chars:
                snippet = snippet[: max_chars - used]
            digest.append(snippet)
            used += len(snippet)
            if used >= max_chars:
                break
        return "\n\n---\n\n".join(digest)

    # -- Content persistence -------------------------------------------------

    async def _apply_review_content(self, response_content: str) -> None:
        """Persist a completed review's learnings.

        Parses structured updates from XML tags, updates memory files,
        stores review metadata, compacts memory, and triggers skill
        creation/refinement.
        """
        if not self._enabled:
            return

        try:
            response_content = response_content or ""

            from novacode_cli.hermes.memory_tiers import (
                compact_memory_file,
                parse_review_response,
                update_from_review,
            )

            parsed = parse_review_response(response_content)

            if self._agent_dir and (
                parsed["user_updates"] or parsed["session_memory"]
            ):
                update_from_review(
                    self._agent_dir,
                    parsed["user_updates"],
                    parsed["session_memory"],
                )
                logger.info(
                    "Nova review applied: user_updates=%s, session_memory=%s",
                    bool(parsed["user_updates"]),
                    bool(parsed["session_memory"]),
                )
            elif self._agent_dir and response_content:
                update_from_review(self._agent_dir, "", response_content)
                logger.info("Nova review applied as session memory (no XML structure)")

            current_count = await self._get_review_count()

            review_id = f"review_{int(time.time())}"
            await self._store.aput(
                ("nova", "reviews"),
                review_id,
                {"timestamp": time.time(), "content": response_content[:2000]},
            )

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

            if self._agent_dir:
                try:
                    user_md = self._agent_dir / "USER.md"
                    memory_md = self._agent_dir / "MEMORY.md"
                    for f in [user_md, memory_md]:
                        if f.exists():
                            compact_memory_file(f)
                except Exception:  # noqa: BLE001
                    logger.exception("Failed to compact memory files")

            if self._skill_manager:
                await self._skill_manager.cleanup_legacy_skills_once()
                await self._skill_manager.maybe_create_from_review(response_content)

            if self._skill_manager and new_count % 5 == 0:
                await self._skill_manager.maybe_refine_skills()

            # Periodic library hygiene: archive unused, flag overlaps.
            if self._skill_manager and new_count % 10 == 0:
                await self._skill_manager.maybe_curate()

        except Exception:  # noqa: BLE001
            logger.exception("Failed to apply review content")

    # -- Review state helpers ------------------------------------------------

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
        """Check if a review was just completed."""
        try:
            entry = await self._store.aget(
                ("nova", "meta"), "review_just_completed"
            )
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
                {"value": value},
            )
        except Exception:  # noqa: BLE001
            logger.exception("Failed to set review_just_completed flag")
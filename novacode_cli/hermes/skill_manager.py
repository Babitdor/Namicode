"""Skill management — create, clean up, and refine skills from review feedback.

Extracted from ``NovaLearningMiddleware``.  Delegates to ``skill_discovery``
for the actual pattern-detection logic; this module owns the orchestration
decisions (when to create, guard against duplicates, rate-limit refinement).
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from langgraph.store.base import BaseStore

logger = logging.getLogger("nova.hermes.skill_manager")


class SkillManager:
    """Manages skill lifecycle: creation from reviews, legacy cleanup, refinement.

    Used by ``ReviewRunner`` (via the middleware) after a review cycle completes.
    """

    def __init__(
        self,
        store: BaseStore,
        *,
        skills_dir: Path | None = None,
        enabled: bool = True,
    ) -> None:
        self._store = store
        self._skills_dir = skills_dir
        self._enabled = enabled
        self._refinement_tasks: set[asyncio.Task] = set()

    # -- Background task management -----------------------------------------

    def spawn_task(self, coro) -> None:
        """Run a skill create/refine coroutine as a tracked background task."""
        task = asyncio.create_task(coro)
        self._refinement_tasks.add(task)

        def _done(t: asyncio.Task) -> None:
            self._refinement_tasks.discard(t)
            if not t.cancelled() and t.exception():
                logger.error("Skill task failed: %s", t.exception())

        task.add_done_callback(_done)

    @property
    def pending_tasks(self) -> set[asyncio.Task]:
        """Return the set of tracked background tasks."""
        return self._refinement_tasks

    # -- Skill creation from review -----------------------------------------

    async def maybe_create_from_review(self, review_text: str) -> None:
        """Persist an episode-grounded skill if the review proposed one.

        The review LLM writes a ``<skill>`` block (name + trigger + steps) only
        when it recognizes a genuinely reusable workflow from this session.
        Deduped by skill name (directory existence + store record).
        """
        if not self._enabled or not self._skills_dir:
            return
        try:
            from novacode_cli.hermes.skill_discovery import (
                parse_skill_spec,
                write_skill_from_spec,
            )

            spec = parse_skill_spec(review_text)
            if spec is None:
                return
            await write_skill_from_spec(spec, self._skills_dir, self._store)
        except Exception:  # noqa: BLE001
            logger.exception("Failed to create skill from review")

    # -- Legacy cleanup -----------------------------------------------------

    async def cleanup_legacy_skills_once(self) -> None:
        """One-time removal of old ``nova-<hash>`` n-gram skills (guarded)."""
        if not self._enabled or not self._skills_dir:
            return
        try:
            done = await self._store.aget(
                ("nova", "meta"), "legacy_skills_cleaned_v1"
            )
            if done is not None:
                return
            from novacode_cli.hermes.skill_discovery import (
                cleanup_legacy_pattern_skills,
            )

            removed = cleanup_legacy_pattern_skills(self._skills_dir)
            await self._store.aput(
                ("nova", "meta"), "legacy_skills_cleaned_v1", {"removed": removed}
            )
            if removed:
                from novacode_cli.events import nova_event_log

                nova_event_log.append(
                    (
                        "nova_skill_refinement",
                        "🛠",
                        "yellow",
                        f"🧹 Nova: removed {len(removed)} legacy auto-skill(s) "
                        "(opaque nova-* patterns; replaced by episode-grounded skills)",
                    )
                )
        except Exception:  # noqa: BLE001
            logger.exception("Failed legacy skill cleanup")

    # -- Skill refinement ---------------------------------------------------

    async def maybe_refine_skills(self) -> None:
        """Refine an existing skill flagged as ineffective (one per cycle)."""
        if not self._enabled or not self._skills_dir:
            return
        try:
            from novacode_cli.hermes.skill_discovery import (
                check_skill_effectiveness,
                refine_skill,
            )

            candidates = await check_skill_effectiveness(self._store)
            for skill_name, issue in candidates[:1]:  # one per cycle
                if issue != "high_failure":
                    continue
                if not (self._skills_dir / skill_name / "SKILL.md").exists():
                    continue

                # Pull the captured failure samples so refinement is grounded
                # in what actually went wrong, not a generic "improve this".
                failure_samples: list = []
                try:
                    entry = await self._store.aget(("nova", "skill_usage"), skill_name)
                    if entry and isinstance(entry.value, dict):
                        failure_samples = list(entry.value.get("failure_samples") or [])
                except Exception:  # noqa: BLE001
                    failure_samples = []

                from novacode_cli.events import nova_event_log

                nova_event_log.append(
                    (
                        "nova_skill_refinement",
                        "🛠",
                        "yellow",
                        f"🛠 Nova: skill '{skill_name}' needs refinement ({issue})",
                    )
                )
                self.spawn_task(
                    refine_skill(
                        skill_name,
                        self._skills_dir,
                        issue,
                        failure_samples=failure_samples,
                    )
                )
        except Exception:  # noqa: BLE001
            logger.exception("Failed to check skill effectiveness / refine")

    # -- Skill curation -----------------------------------------------------

    async def maybe_curate(self) -> None:
        """Run a background curation pass (archive unused, flag overlaps)."""
        if not self._enabled or not self._skills_dir:
            return
        try:
            from novacode_cli.hermes.curator import run_curation

            self.spawn_task(run_curation(self._store, self._skills_dir))
        except Exception:  # noqa: BLE001
            logger.exception("Failed to start skill curation")
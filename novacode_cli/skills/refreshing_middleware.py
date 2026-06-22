"""Skills middleware that refreshes its list when the skill files change.

deepagents' :class:`SkillsMiddleware` loads the available-skills list once per
session and caches it in the ``skills_metadata`` agent-state key, so a skill
created mid-session (by ``skill_manage`` or a Hermes review) is invisible to the
agent until a restart. This subclass re-lists when the watched skill directories
change, closing the within-session learning loop. See
``specs/2026-06-22-mid-session-skill-refresh-design.md``.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from deepagents.middleware.skills import SkillsMiddleware

if TYPE_CHECKING:
    from collections.abc import Sequence

    from deepagents.middleware.skills import SkillsState, SkillsStateUpdate
    from langchain_core.runnables import RunnableConfig
    from langgraph.runtime import Runtime


class RefreshingSkillsMiddleware(SkillsMiddleware):
    """:class:`SkillsMiddleware` that re-lists skills when watched dirs change.

    A change is detected by a per-file ``SKILL.md`` mtime signature over
    ``watch_dirs`` (real filesystem paths). When it changes, the cached
    ``skills_metadata`` is dropped from a state copy so the parent's loader
    re-runs; otherwise behaviour is identical to the base middleware.
    """

    def __init__(
        self,
        *,
        backend: object,
        sources: Sequence[object],
        watch_dirs: Sequence[Path],
    ) -> None:
        """Forward ``backend``/``sources`` to the base; keep ``watch_dirs`` for refresh."""
        super().__init__(backend=backend, sources=sources)  # type: ignore[arg-type]
        self._watch_dirs = [Path(d) for d in watch_dirs]
        self._last_signature: frozenset[tuple[str, float]] | None = None

    def _compute_signature(self) -> frozenset[tuple[str, float]]:
        """A (path, mtime) frozenset over every ``*/SKILL.md`` under watch dirs."""
        sig: set[tuple[str, float]] = set()
        for directory in self._watch_dirs:
            try:
                skill_files = list(directory.glob("*/SKILL.md"))
            except OSError:
                continue
            for skill_md in skill_files:
                try:
                    sig.add((str(skill_md), skill_md.stat().st_mtime))
                except OSError:
                    continue
        return frozenset(sig)

    def _skills_changed(self) -> bool:
        """True if the skill files changed since the last call (best-effort)."""
        try:
            current = self._compute_signature()
        except Exception:  # noqa: BLE001 - best-effort; never break a turn
            return False
        changed = current != self._last_signature
        self._last_signature = current
        return changed

    def before_agent(
        self, state: SkillsState, runtime: Runtime, config: RunnableConfig
    ) -> SkillsStateUpdate | None:
        """Force a re-list when skills changed, else defer to the base loader."""
        if self._skills_changed():
            state = {  # type: ignore[assignment]
                k: v for k, v in state.items() if k != "skills_metadata"
            }
        return super().before_agent(state, runtime, config)

    async def abefore_agent(
        self, state: SkillsState, runtime: Runtime, config: RunnableConfig
    ) -> SkillsStateUpdate | None:
        """Async twin of :meth:`before_agent` (the path the agent actually runs)."""
        if self._skills_changed():
            state = {  # type: ignore[assignment]
                k: v for k, v in state.items() if k != "skills_metadata"
            }
        return await super().abefore_agent(state, runtime, config)

"""Skill-curation middleware — clamp the loaded skills to the enabled set.

The skills loader (deepagents' ``SkillsMiddleware`` / Nova's
``RefreshingSkillsMiddleware``) populates the ``skills_metadata`` state key with
*every* discovered skill. This middleware runs **after** that loader and drops
any skill whose name is in the effective disabled set (see
:mod:`novacode_cli.skills.skills_prefs`).

``skills_metadata`` is the single source of truth for the system-prompt skills
list, the skill count, and what the agent can invoke — so clamping it here
curates all of them at once, for the main agent and for subagents alike.

Ordering is the only requirement: this middleware must sit *after* the loader in
the middleware list. langchain compiles ``before_agent`` hooks into sequential
graph nodes, so a later node sees the loader's ``skills_metadata`` update.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from langchain.agents.middleware.types import AgentMiddleware

from novacode_cli.skills.skills_prefs import effective_disabled

if TYPE_CHECKING:
    from langchain.tools import BaseTool
    from langchain_core.runnables import RunnableConfig
    from langgraph.runtime import Runtime


class SkillCurationMiddleware(AgentMiddleware):
    """Drop user-disabled skills from ``skills_metadata`` (opt-out curation)."""

    def __init__(self) -> None:
        """Curation middleware carries no tools and no config of its own."""
        super().__init__()
        self.tools: list[BaseTool] = []

    def _clamp(self, state: dict) -> dict | None:
        """Return a clamped ``skills_metadata`` update, or None if unchanged."""
        skills = state.get("skills_metadata")
        if not skills:
            return None
        disabled = effective_disabled()
        if not disabled:
            return None
        kept = [s for s in skills if s.get("name") not in disabled]
        if len(kept) == len(skills):
            return None
        return {"skills_metadata": kept}

    def before_agent(
        self,
        state: dict,
        runtime: Runtime,  # noqa: ARG002 - required by the middleware interface
        config: RunnableConfig,  # noqa: ARG002 - required by the middleware interface
    ) -> dict | None:
        """Clamp the loaded skills to the enabled set (sync path)."""
        return self._clamp(state)

    async def abefore_agent(
        self,
        state: dict,
        runtime: Runtime,  # noqa: ARG002 - required by the middleware interface
        config: RunnableConfig,  # noqa: ARG002 - required by the middleware interface
    ) -> dict | None:
        """Clamp the loaded skills to the enabled set (async path)."""
        return self._clamp(state)

"""WikiFileEngine — files conversation knowledge into the wiki.

Uses the live agent (via a guided prompt) to extract key knowledge from
the recent conversation and create a wiki page, update the index, and
log the action.
"""

from __future__ import annotations

from novacode_cli.prompts import render_template
from novacode_cli.wiki.manager import WikiManager


class WikiFileEngine:
    """Drives the /file workflow.

    Usage::

        engine = WikiFileEngine()
        await engine.file_knowledge(
            topic="comparisons/CrewAI-vs-LangGraph",
            session_state=session_state,
            agent=agent,
            execute_fn=execute_task,
        )
    """

    def __init__(self, wiki_mgr: WikiManager | None = None) -> None:
        self._mgr = wiki_mgr or WikiManager()
        self._mgr.ensure_structure()

    async def file_knowledge(
        self,
        topic: str,
        agent,
        session_state,
        execute_fn,
        token_tracker=None,
        assistant_id: str | None = None,
    ) -> None:
        """Extract knowledge from the recent conversation and file it as a wiki page.

        Args:
            topic: Suggested wiki topic/path (e.g. ``comparisons/CrewAI-vs-LangGraph``).
            agent: The live LangGraph agent.
            session_state: Current session state.
            execute_fn: Callable to stream a prompt through the agent.
            token_tracker: Optional token tracker for usage display.
            assistant_id: Optional assistant ID for display.
        """
        mgr = self._mgr

        # Build a filing prompt
        prompt = render_template(
            "wiki_file.jinja",
            topic=topic,
            wiki_index=mgr.read_index(),
        )

        backend = getattr(agent, "backend", None)
        display_id = assistant_id or "wiki"
        await execute_fn(
            prompt,
            agent,
            display_id,
            session_state,
            token_tracker=token_tracker,
            backend=backend,
        )

        session_state.wiki_page_count = len(list((mgr.root / "wiki").rglob("*.md")))
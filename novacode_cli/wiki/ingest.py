"""IngestEngine — ingests raw sources into synthesized wiki pages.

Instead of hardcoded parsing, the engine builds a prompt and streams it
through the live agent, letting the LLM analyze the source and produce
wiki content that the agent then writes to disk.
"""

from __future__ import annotations

from pathlib import Path

from novacode_cli.prompts import render_template
from novacode_cli.wiki.manager import WikiManager


class IngestEngine:
    """Drives the /ingest workflow.

    Usage::

        engine = IngestEngine()
        await engine.ingest_source(
            source_path=".nova/wiki/raw/articles/langgraph-multi-agent.md",
            session_state=session_state,
            agent=agent,
            execute_fn=execute_task,
        )
    """

    def __init__(self, wiki_mgr: WikiManager | None = None) -> None:
        self._mgr = wiki_mgr or WikiManager()
        self._mgr.ensure_structure()

    # Source-input folders under the wiki root, in priority order. ``Clippings``
    # is the Obsidian Web Clipper inbox (the clipper's default folder name);
    # ``Clipping`` is a singular alias; ``raw`` is the legacy categorized
    # location. /ingest scans all of them, so a file in any is found.
    INPUT_DIRNAMES = ("Clippings", "Clipping", "raw")

    # -- source discovery ----------------------------------------------------

    def _input_dirs(self) -> list[Path]:
        """Existing source-input directories under the wiki root."""
        return [d for d in (self._mgr.root / n for n in self.INPUT_DIRNAMES) if d.is_dir()]

    def list_raw_sources(self) -> list[str]:
        """List every source file in the input folders (``Clipping/``, ``raw/``).

        Returns paths relative to the wiki root (e.g. ``Clipping/langgraph.md``
        or ``raw/articles/x.md``), sorted. Hidden files are skipped. Auto-
        discovers whatever was dropped in (Obsidian Web Clipper, manual files).
        """
        root = self._mgr.root
        sources: list[str] = []
        for base in self._input_dirs():
            sources += [
                p.relative_to(root).as_posix()
                for p in base.rglob("*")
                if p.is_file() and not p.name.startswith(".")
            ]
        return sorted(sources)

    def resolve_source(self, source_path: str) -> Path:
        """Resolve a user-supplied source to a concrete file in an input folder.

        So the user never has to know the exact path, this tries, in order:
        1. the exact path under an input folder, or relative to the wiki root
           (``Clipping/x.md``);
        2. a unique file in any input folder whose relative path *ends with* the
           argument, or whose basename matches it (``x.md`` → found anywhere).

        Raises:
            ValueError: the argument matches more than one file (ambiguous).
            FileNotFoundError: nothing matches (message lists what's available).
        """
        root = self._mgr.root
        target = source_path.replace("\\", "/").strip().lstrip("/")

        # 1. exact — under an input folder, or relative to the wiki root.
        for base in self._input_dirs():
            cand = base / target
            if cand.is_file():
                return cand
        root_cand = root / target
        if root_cand.is_file():
            return root_cand

        # 2. search every input folder.
        target_name = Path(target).name
        matches = [
            p
            for base in self._input_dirs()
            for p in base.rglob("*")
            if p.is_file()
            and (p.relative_to(root).as_posix().endswith(target) or p.name == target_name)
        ]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            rels = ", ".join(sorted(m.relative_to(root).as_posix() for m in matches))
            msg = (
                f"Ambiguous source '{source_path}' — matches multiple files: {rels}. "
                "Pass a more specific path."
            )
            raise ValueError(msg)

        available = self.list_raw_sources()
        clipping = root / "Clippings"
        hint = (
            "\nAvailable sources: " + ", ".join(available)
            if available
            else f" (no sources yet — drop files into {clipping})"
        )
        msg = f"Source not found: '{source_path}'." + hint
        raise FileNotFoundError(msg)

    async def ingest_source(
        self,
        source_path: str,
        agent,
        session_state,
        execute_fn,
        token_tracker=None,
        assistant_id: str | None = None,
    ) -> None:
        """Ingest a raw source file into the wiki.

        Args:
            source_path: Virtual path under ``.nova/wiki/raw/`` (e.g.
                ``articles/langgraph-multi-agent.md``).
            agent: The live LangGraph agent to stream the prompt through.
            session_state: Current session state (updated after ingest).
            execute_fn: Callable that streams a prompt through the agent
                (``execute_task`` or TUI equivalent).
            token_tracker: Optional token tracker for usage display.
            assistant_id: Optional assistant ID for display name.
        """
        # 1. Resolve + read the source file (found in Clipping/ or raw/).
        mgr = self._mgr
        source_full = self.resolve_source(source_path)
        # Record the path the user can reference later (relative to the wiki root).
        source_path = source_full.relative_to(mgr.root).as_posix()

        source_content = source_full.read_text(encoding="utf-8")

        # 2. Read current wiki index for context
        wiki_index = mgr.read_index()

        # 3. Build the prompt
        from datetime import UTC, datetime

        prompt = render_template(
            "wiki_ingest.jinja",
            source_content=source_content,
            wiki_index=wiki_index,
            source_url=source_path,
            ingest_date=datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC"),
        )

        # 4. Hand off to the agent — the agent's system prompt + tools let it
        #    write pages, update the index, and append to the log.
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

        # 5. Update session state metadata
        session_state.wiki_last_ingest = source_path
        # Re-count pages
        session_state.wiki_page_count = self._count_pages()

    def _count_pages(self) -> int:
        """Count all .md files under wiki/."""
        wiki_dir = self._mgr.root / "wiki"
        if not wiki_dir.exists():
            return 0
        return len(list(wiki_dir.rglob("*.md")))

"""WikiAskEngine — searches wiki and prepends context for /ask.

Instead of a separate subagent, this engine reads relevant wiki pages and
prepends them as context to the user's question, then passes through to
the normal agent workflow.
"""

from __future__ import annotations

from novacode_cli.wiki.manager import WikiManager


class WikiAskEngine:
    """Prepends relevant wiki context to a user query.

    Usage::

        engine = WikiAskEngine()
        prompt = await engine.build_prompt("How does MCP compare to REST?")
        # → "📚 Wiki context:\\n\\n## MCP\\n...\\n\\n---\\n\\nHow does MCP compare to REST?"
    """

    def __init__(self, wiki_mgr: WikiManager | None = None) -> None:
        self._mgr = wiki_mgr or WikiManager()

    async def build_prompt(self, question: str) -> str:
        """Search the wiki for relevant pages and prepend their content."""
        # 1. Search the index
        results = self._mgr.search(question)
        if not results:
            return question  # No wiki matches — pass through unchanged

        # 2. Build context block from matched pages
        lines: list[str] = []
        seen: set[str] = set()

        for topic, path, summary in results[:5]:  # Top 5 matches max
            key = path if path else topic
            if key in seen:
                continue
            seen.add(key)

            # Read the page content
            content = self._mgr.read_page(path)
            if content:
                # Extract just the summary / first section
                lines.append(f"### {topic}")
                lines.append(content[:1500])  # Trim to avoid context bloat
                lines.append("")

        if not lines:
            return question

        body = "\n".join(lines).strip()
        prompt = f"[Wiki Context]\n\n{body}\n\n[/Wiki Context]\n\n{question}"
        return prompt
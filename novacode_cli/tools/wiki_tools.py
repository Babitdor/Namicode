"""Agent-accessible wiki tools for autonomous wiki operations.

These tools let the agent consult and update the wiki during coding
sessions — searching, reading, writing pages, and updating the index
without requiring slash commands.
"""

from __future__ import annotations

from pathlib import Path

from langchain.tools import tool

from novacode_cli.wiki.manager import WikiManager


@tool
def wiki_search(query: str) -> str:
    """Search the project wiki for pages matching a query.

    Returns a list of (topic, path, summary) tuples ranked by relevance.

    Args:
        query: Search keywords or phrase (e.g. "MCP protocol comparison")

    Returns:
        Formatted search results or "(no matches)".
    """
    try:
        mgr = WikiManager()
        results = mgr.search(query)
        if not results:
            return "(no wiki matches found)"

        lines = ["### Wiki Search Results\n"]
        for topic, path, summary in results:
            lines.append(f"- **[{topic}]({path})**")
            if summary:
                lines.append(f" — {summary}")
            lines.append("")
        return "".join(lines)
    except RuntimeError:
        return "(wiki is not available — not in a git project)"
    except Exception as ex:  # noqa: BLE001
        return f"(wiki search failed: {ex})"


@tool
def wiki_read(path: str) -> str:
    """Read a wiki page by path.

    The path is relative to the wiki directory, e.g.
    ``technologies/LangGraph.md`` or ``comparisons/CrewAI-vs-LangGraph.md``.

    Args:
        path: Wiki page path like ``technologies/LangGraph.md``.

    Returns:
        The page content, or an error message.
    """
    try:
        mgr = WikiManager()
        p = path.replace("\\", "/").strip().lstrip("/")
        if p.startswith(".nova/wiki/"):
            p = p[len(".nova/wiki/"):]
        elif p.startswith("wiki/"):
            p = p[len("wiki/"):]
        content = mgr.read_page(p)
        if content is None:
            return f"(wiki page not found: {path})"
        return content
    except RuntimeError:
        return "(wiki is not available — not in a git project)"
    except Exception as ex:  # noqa: BLE001
        return f"(wiki read failed: {ex})"


@tool
def wiki_write(path: str, content: str) -> str:
    """Write or overwrite a wiki page.

    The path should include the topic directory and filename,
    e.g. ``technologies/LangGraph.md`` or ``patterns/MultiAgentPatterns.md``.

    Valid topic directories: technologies/, frameworks/, patterns/,
    projects/, comparisons/.

    After writing, you should also call ``wiki_update_index`` to keep the
    index in sync.

    Args:
        path: Page path like ``technologies/LangGraph.md``.
        content: Markdown content for the page.

    Returns:
        Confirmation message.
    """
    try:
        mgr = WikiManager()
        mgr.ensure_structure()

        p = path.replace("\\", "/").strip().lstrip("/")
        if p.startswith(".nova/wiki/"):
            p = p[len(".nova/wiki/"):]
        elif p.startswith("wiki/"):
            p = p[len("wiki/"):]

        # Split path into topic & title
        parts = p.split("/")
        if len(parts) < 2:
            return (
                f"(invalid path '{path}' — use topic/filename.md, "
                "e.g. technologies/LangGraph.md)"
            )
        topic = parts[0]
        title = "/".join(parts[1:])

        mgr.write_page(topic, title, content)
        return f"✓ Wrote wiki page: {topic}/{title}"
    except RuntimeError:
        return "(wiki is not available — not in a git project)"
    except Exception as ex:  # noqa: BLE001
        return f"(wiki write failed: {ex})"


@tool
def wiki_update_index(topic: str, path: str, summary: str = "") -> str:
    """Add or update an entry in the wiki index.

    Use this after creating or updating a wiki page so it appears in
    search results.

    Args:
        topic: Display name for the entry (e.g. "LangGraph").
        path: Relative path to the page (e.g. "technologies/LangGraph.md").
        summary: Optional one-line description.

    Returns:
        Confirmation message.
    """
    try:
        mgr = WikiManager()
        p = path.replace("\\", "/").strip().lstrip("/")
        if p.startswith(".nova/wiki/"):
            p = p[len(".nova/wiki/"):]
        elif p.startswith("wiki/"):
            p = p[len("wiki/"):]
        mgr.update_index(topic, p, summary)
        return f"✓ Index updated: {topic} → {p}"
    except RuntimeError:
        return "(wiki is not available — not in a git project)"
    except Exception as ex:  # noqa: BLE001
        return f"(wiki index update failed: {ex})"
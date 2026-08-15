"""Agent tools for creating and updating artifacts.

An artifact is a useful session output (a walkthrough, analysis, dashboard, …)
turned into a live, shareable web page. Create one when a result benefits from
visualization or when the user asks. The content is rendered in a sandboxed
browser context — it is never executed on the host.
"""

from __future__ import annotations

from langchain.tools import tool

_TYPES = "html, markdown, or dashboard"


@tool
def create_artifact(title: str, type: str = "markdown", content: str = "") -> str:
    """Create a live, shareable web artifact from a session output.

    Use when a result is clearer as a visual page (a PR walkthrough, a code
    analysis, an architecture dashboard) or when the user asks to "create an
    artifact". A persistent `◈ Artifacts` component in the TUI updates and the
    user can open it in the browser.

    Args:
        title: Human-readable name shown in the TUI list and the page header.
        type: One of html, markdown, or dashboard. `html`/`dashboard` render as a
            full HTML page inside a sandboxed iframe (safe to include CSS/JS);
            `markdown` renders as formatted prose. Defaults to markdown.
        content: The artifact body — full HTML for html/dashboard, Markdown text
            for markdown. Never has access to the host, filesystem, or secrets.

    Returns:
        The artifact id and its shareable URL.
    """
    from novacode_cli.artifacts.registry import get_registry
    from novacode_cli.artifacts.server import artifact_url

    art = get_registry().create(title, type, content)
    url = artifact_url(art.id)
    return (
        f"Artifact created: '{art.title}' ({art.type}).\n"
        f"id: {art.id}\nURL: {url}\n"
        f"Update it in place with update_artifact(id='{art.id}', content='...') "
        f"instead of creating a duplicate."
    )


@tool
def update_artifact(
    id: str,
    title: str | None = None,
    type: str | None = None,
    content: str | None = None,
) -> str:
    """Update an existing artifact in place (keeps its id/URL; bumps the version).

    Prefer this over creating a new artifact when refining the same output.

    Args:
        id: The artifact id returned by create_artifact / list_artifacts.
        title: New title (optional).
        type: New type — one of html, markdown, dashboard (optional).
        content: New body (optional).
    """
    from novacode_cli.artifacts.registry import get_registry
    from novacode_cli.artifacts.server import artifact_url

    art = get_registry().update(id, title=title, type=type, content=content)
    if art is None:
        return f"No artifact with id '{id}'. Use list_artifacts() to see current ids."
    return (
        f"Artifact '{art.title}' updated to v{art.version}.\n"
        f"URL: {artifact_url(art.id)} (the open page refreshes automatically)."
    )


@tool
def list_artifacts() -> str:
    """List the artifacts created in this session with their ids, types, and URLs."""
    from novacode_cli.artifacts.registry import get_registry
    from novacode_cli.artifacts.server import artifact_url

    arts = get_registry().list()
    if not arts:
        return "No artifacts yet. Create one with create_artifact(title, type, content)."
    lines = [f"{len(arts)} artifact(s):"]
    for a in arts:
        lines.append(f"  {a.id}  [{a.type}] v{a.version} {a.status} - {a.title}  ->  {artifact_url(a.id)}")
    return "\n".join(lines)


__all__ = ["create_artifact", "list_artifacts", "update_artifact"]

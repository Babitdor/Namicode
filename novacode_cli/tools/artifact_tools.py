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

    DESIGN FIRST (html/dashboard): before writing the HTML, read the
    `frontend-design` skill and follow it. An artifact is a *designed page*, not
    a dump of default-styled tags — unstyled output is the most common failure
    of this tool. Commit to a deliberate direction: a real type scale and font
    pairing, CSS custom properties for the palette, intentional spacing and
    layout, and restraint. Read `create-html-artifact` too if present; it covers
    this viewer specifically.

    Write a complete standalone document: `<style>` in the `<head>`, semantic
    markup in the `<body>`. Everything must be inline — the page is rendered from
    a `srcdoc` iframe, so relative URLs and local files do not resolve. Web fonts
    from a CDN (e.g. Google Fonts) do load, so use them rather than settling for
    system defaults. Set an explicit background on `body`: the viewer's iframe
    is white, so a page that assumes a dark canvas will look broken without one.

    Args:
        title: Human-readable name shown in the TUI list and the page header.
        type: One of html, markdown, or dashboard. `html`/`dashboard` render as a
            full HTML page inside a sandboxed iframe (safe to include CSS/JS);
            `markdown` renders as formatted prose with raw HTML disabled, so it
            cannot be styled — choose `html` whenever presentation matters.
            Defaults to markdown.
        content: The artifact body — a full HTML document for html/dashboard,
            Markdown text for markdown. Never has access to the host,
            filesystem, or secrets.

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

    `content` REPLACES the whole body — it is not a patch. Re-send the complete
    document, including its `<style>`, or the page loses its design. The same
    design bar as `create_artifact` applies to the replacement.

    Args:
        id: The artifact id returned by create_artifact / list_artifacts.
        title: New title (optional).
        type: New type — one of html, markdown, dashboard (optional).
        content: New body — the full document, not a fragment (optional).
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

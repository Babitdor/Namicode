"""Project extraction module for /init pipeline.

Wraps graphify.extract for AST-based code extraction and provides
semantic extraction via Nova's subagent system. Merges both
extraction results into a unified format for graph building.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

from novacode_cli.config.config import COLORS


def _make_console() -> Console:
    """Create a Console that handles Unicode on Windows.

    On Windows, the default console encoding (cp1252) cannot represent
    characters like emojis and special symbols that Rich renders in panel
    titles. Wrapping stdout with UTF-8 avoids UnicodeEncodeError.
    """
    from novacode_cli.config.config import console as _global_console
    return _global_console


def extract_project(
    project_root: Path,
    detection: dict[str, Any],
    console: Console | None = None,
    deep: bool = False,
) -> dict[str, Any]:
    """Extract entities from project files using AST analysis.

    Uses graphify.extract for code files (tree-sitter AST extraction)
    and returns a unified extraction result with nodes and edges.

    Args:
        project_root: Path to the project root directory.
        detection: Detection result from detect_project().
        console: Rich console for output.
        deep: If True, extract from all files. If False, limit to
            a reasonable subset for large projects.

    Returns:
        Extraction result dict with keys: nodes, edges, input_tokens,
        output_tokens. Returns empty dict if graphify is not available.
    """
    if console is None:
        console = _make_console()

    try:
        from graphify.extract import extract
    except ImportError:
        console.print(
            "[yellow]graphify not installed — install with: "
            "pip install novacode-cli[graphify][/yellow]"
        )
        return {}

    files_dict = detection.get("files", {})
    code_files = files_dict.get("code", [])
    doc_files = files_dict.get("document", [])

    # Build list of paths to extract
    paths = []
    for rel_path in code_files + doc_files:
        full_path = project_root / rel_path
        if full_path.exists():
            paths.append(full_path)

    # Limit for very large projects (unless --deep)
    max_files = len(paths) if deep else min(len(paths), 200)
    if len(paths) > max_files:
        console.print(
            f"[yellow]⚠ Large project ({len(paths)} files) — "
            f"extracting {max_files} most relevant. Use --deep for all.[/yellow]"
        )
        paths = paths[:max_files]

    if not paths:
        console.print("[yellow]⚠ No files found to extract[/yellow]")
        return {}

    # Run extraction with progress indicator
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task(
            f"Extracting {len(paths)} files (AST analysis)...", total=None
        )
        result = extract(paths)
        progress.update(task, completed=True)

    # Show extraction results
    nodes = result.get("nodes", [])
    edges = result.get("edges", [])
    _show_extraction_panel(nodes, edges, console)

    return result


def extract_project_incremental(
    project_root: Path,
    detection: dict[str, Any],
    cached_extraction: dict[str, Any] | None = None,
    console: Console | None = None,
) -> dict[str, Any]:
    """Extract entities incrementally, only processing changed files.

    Checks the semantic cache for unchanged files and only re-extracts
    files that have been modified since the last extraction.

    Args:
        project_root: Path to the project root directory.
        detection: Incremental detection result.
        cached_extraction: Previously cached extraction result to merge with.
        console: Rich console for output.

    Returns:
        Merged extraction result with cached + new nodes/edges.
    """
    if console is None:
        console = _make_console()

    try:
        from graphify.extract import extract
        from graphify.cache import check_semantic_cache, load_cached, save_cached
    except ImportError:
        console.print(
            "[yellow]graphify not installed — install with: "
            "pip install novacode-cli[graphify][/yellow]"
        )
        return {}

    # new_files is a dict of file-type categories (e.g. {"code": [...], "document": [...]})
    # Flatten all file paths across categories
    new_files_raw = detection.get("new_files", {})
    new_paths = []
    if isinstance(new_files_raw, dict):
        for file_list in new_files_raw.values():
            if isinstance(file_list, list):
                new_paths.extend(file_list)
    elif isinstance(new_files_raw, list):
        new_paths = new_files_raw

    paths = []
    for rel_path in new_paths:
        full_path = project_root / rel_path
        if full_path.exists():
            paths.append(full_path)

    if not paths:
        console.print("[green]✓ No files need re-extraction[/green]")
        return cached_extraction or {}

    # Extract only changed/new files
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task(
            f"Re-extracting {len(paths)} changed files...", total=None
        )
        new_result = extract(paths)
        progress.update(task, completed=True)

    # Merge with cached extraction
    if cached_extraction:
        merged = merge_extractions(cached_extraction, new_result)
    else:
        merged = new_result

    # Show results
    nodes = merged.get("nodes", [])
    edges = merged.get("edges", [])
    _show_extraction_panel(nodes, edges, console, incremental=True)

    return merged


def merge_extractions(
    base: dict[str, Any], new: dict[str, Any]
) -> dict[str, Any]:
    """Merge two extraction results, deduplicating nodes and edges.

    New nodes/edges override existing ones with the same ID. This
    allows incremental updates to replace stale data.

    Args:
        base: Base extraction result (e.g., cached).
        new: New extraction result to merge in.

    Returns:
        Merged extraction result.
    """
    # Deduplicate nodes by ID
    existing_nodes = {n["id"]: n for n in base.get("nodes", [])}
    for node in new.get("nodes", []):
        existing_nodes[node["id"]] = node

    # Deduplicate edges by (source, target, relation) tuple
    existing_edges = {}
    for edge in base.get("edges", []):
        key = (edge["source"], edge["target"], edge.get("relation", ""))
        existing_edges[key] = edge
    for edge in new.get("edges", []):
        key = (edge["source"], edge["target"], edge.get("relation", ""))
        existing_edges[key] = edge

    return {
        "nodes": list(existing_nodes.values()),
        "edges": list(existing_edges.values()),
        "input_tokens": base.get("input_tokens", 0) + new.get("input_tokens", 0),
        "output_tokens": base.get("output_tokens", 0) + new.get("output_tokens", 0),
    }


def save_extraction_cache(
    project_root: Path, extraction: dict[str, Any]
) -> None:
    """Save extraction result to cache for incremental updates.

    Args:
        project_root: Path to the project root directory.
        extraction: Extraction result to cache.
    """
    cache_path = project_root / ".nova" / "extraction_cache.json"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(extraction, indent=2, default=str), encoding="utf-8")


def load_extraction_cache(project_root: Path) -> dict[str, Any] | None:
    """Load cached extraction result for incremental updates.

    Args:
        project_root: Path to the project root directory.

    Returns:
        Cached extraction result, or None if no cache exists.
    """
    cache_path = project_root / ".nova" / "extraction_cache.json"
    if cache_path.exists():
        try:
            return json.loads(cache_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
    return None


def _show_extraction_panel(
    nodes: list[dict], edges: list[dict], console: Console, *, incremental: bool = False
) -> None:
    """Show a Rich panel with extraction results.

    Args:
        nodes: List of extracted nodes.
        edges: List of extracted edges.
        console: Rich console for output.
        incremental: Whether this was an incremental extraction.
    """
    # Count node types
    node_types: dict[str, int] = {}
    for node in nodes:
        ft = node.get("file_type", "unknown")
        node_types[ft] = node_types.get(ft, 0) + 1

    type_lines = []
    for ft, count in sorted(node_types.items()):
        type_lines.append(f"  {ft}: {count} nodes")

    label = "Incremental Extraction" if incremental else "Extraction"
    content = "\n".join([
        f"[cyan]Nodes:[/cyan] {len(nodes)}",
        f"[cyan]Edges:[/cyan] {len(edges)}",
        "",
        "[dim]Node types:[/dim]",
        *type_lines,
    ])

    panel = Panel(
        content,
        title=f"[bold {COLORS['primary']}]🔬 {label}[/bold {COLORS['primary']}]",
        border_style=COLORS["primary"],
        padding=(1, 2),
    )
    console.print(panel)
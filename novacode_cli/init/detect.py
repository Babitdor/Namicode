"""Project detection module for /init pipeline.

Wraps graphify.detect to scan project files, count words, and classify
file types. Provides Rich-formatted output for each detection step.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from novacode_cli.config.config import COLORS


def _make_console() -> Console:
    """Create a Console that handles Unicode on Windows.

    On Windows, the default console encoding (cp1252) cannot represent
    characters like emojis and special symbols that Rich renders in panel
    titles. Wrapping stdout with UTF-8 avoids UnicodeEncodeError.
    """
    from novacode_cli.config.config import console as _global_console
    return _global_console

# Lazy import — graphify is an optional dependency
_graphify_detect = None
_graphify_detect_incremental = None


def _import_graphify_detect():
    """Lazily import graphify.detect functions."""
    global _graphify_detect, _graphify_detect_incremental
    try:
        from graphify.detect import detect, detect_incremental

        _graphify_detect = detect
        _graphify_detect_incremental = detect_incremental
        return True
    except ImportError:
        return False


def is_graphify_available() -> bool:
    """Check if the graphify package is installed and importable.

    Returns:
        True if graphify is available, False otherwise.
    """
    return _import_graphify_detect()


def detect_project(project_root: Path, console: Console | None = None) -> dict[str, Any]:
    """Detect project files and classify them by type.

    Uses graphify.detect to scan the project directory, count files and
    words, and classify files into code, document, paper, image, and
    video categories.

    Args:
        project_root: Path to the project root directory.
        console: Rich console for output. If None, creates a new one.

    Returns:
        Detection result dict with keys: files, total_files, total_words,
        needs_graph, warning, skipped_sensitive, graphifyignore_patterns.
        Returns empty dict if graphify is not available.
    """
    if console is None:
        console = _make_console()

    if not _import_graphify_detect():
        console.print(
            "[yellow]graphify not installed — install with: "
            "pip install novacode-cli[graphify][/yellow]"
        )
        return {}

    result = _graphify_detect(project_root)

    # Show detection results
    _show_detection_panel(result, console)

    return result


def detect_project_incremental(
    project_root: Path,
    manifest_path: str | None = None,
    console: Console | None = None,
) -> dict[str, Any]:
    """Detect project files incrementally, only processing changed files.

    Uses graphify's manifest system to compare file mtimes against a
    saved manifest, returning only new/changed/deleted files.

    Args:
        project_root: Path to the project root directory.
        manifest_path: Path to the manifest JSON file. Defaults to
            .nova/manifest.json within the project root.
        console: Rich console for output.

    Returns:
        Incremental detection result dict. Returns empty dict if
        graphify is not available.
    """
    if console is None:
        console = _make_console()

    if not _import_graphify_detect():
        console.print(
            "[yellow]graphify not installed — install with: "
            "pip install novacode-cli[graphify][/yellow]"
        )
        return {}

    if manifest_path is None:
        manifest_path = str(project_root / ".nova" / "manifest.json")

    result = _graphify_detect_incremental(project_root, manifest_path=manifest_path)

    # Show incremental results
    _show_incremental_panel(result, console)

    return result


def _show_detection_panel(result: dict[str, Any], console: Console) -> None:
    """Show a Rich panel with detection results.

    Args:
        result: Detection result from graphify.detect.
        console: Rich console for output.
    """
    files = result.get("files", {})
    total_files = result.get("total_files", 0)
    total_words = result.get("total_words", 0)
    warning = result.get("warning")

    # Build summary table
    table = Table(show_header=True, header_style=f"bold {COLORS['primary']}")
    table.add_column("Category", style="cyan")
    table.add_column("Files", justify="right")
    table.add_column("Words", justify="right")

    for category, file_list in files.items():
        if file_list:
            table.add_row(category.capitalize(), str(len(file_list)), "")

    table.add_row("[bold]Total[/bold]", str(total_files), f"{total_words:,}")

    panel = Panel(
        table,
        title=f"[bold {COLORS['primary']}]📊 Project Detection[/bold {COLORS['primary']}]",
        border_style=COLORS["primary"],
        padding=(1, 2),
    )
    console.print(panel)

    if warning:
        console.print(f"[yellow]⚠ {warning}[/yellow]")


def _show_incremental_panel(result: dict[str, Any], console: Console) -> None:
    """Show a Rich panel with incremental detection results.

    The incremental detection result has 'new_files' as a dict of
    file-type categories (e.g. {"code": [...], "document": [...]}),
    not a flat list. We count total files across all categories.

    Args:
        result: Incremental detection result.
        console: Rich console for output.
    """
    new_files_raw = result.get("new_files", {})
    unchanged_files_raw = result.get("unchanged_files", {})

    # Count files across all categories (new_files is a dict of lists)
    new_count = sum(len(v) for v in new_files_raw.values()) if isinstance(new_files_raw, dict) else len(new_files_raw)
    unchanged_count = sum(len(v) for v in unchanged_files_raw.values()) if isinstance(unchanged_files_raw, dict) else len(unchanged_files_raw)

    if new_count == 0 and unchanged_count == 0:
        console.print("[green]✓ No changes detected since last run[/green]")
        return

    lines = []
    if new_count:
        lines.append(f"[green]+ {new_count} new files[/green]")
    if unchanged_count:
        lines.append(f"[cyan]≈ {unchanged_count} unchanged files[/cyan]")

    panel = Panel(
        "\n".join(lines),
        title=f"[bold {COLORS['primary']}]📊 Incremental Detection[/bold {COLORS['primary']}]",
        border_style=COLORS["primary"],
        padding=(1, 2),
    )
    console.print(panel)


def save_manifest(project_root: Path, result: dict[str, Any]) -> None:
    """Save detection manifest for incremental updates.

    Note: graphify.detect.save_manifest expects files: dict[str, list[str]],
    NOT the full result dict (which includes total_files, total_words, etc.).

    Args:
        project_root: Path to the project root directory.
        result: Detection result to save as manifest.
    """
    try:
        from graphify.detect import save_manifest as _graphify_save_manifest

        manifest_path = str(project_root / ".nova" / "manifest.json")
        # Pass only the files dict, not the full result (which has int keys
        # like total_files that would cause 'int' object is not iterable).
        files = result.get("files", {})
        _graphify_save_manifest(files, manifest_path)
    except ImportError:
        pass
"""File operation tools for voice agent.

These are read-only tools that allow the voice agent to explore
and understand the codebase without modifying it. Implementation
tasks are delegated to the text-based agent.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any


class FileAccessError(Exception):
    """Raised when file access is denied or file not found."""

    def __init__(self, message: str) -> None:
        """Initialize with error message.

        Args:
            message: Error description.
        """
        super().__init__(message)


class DirectoryAccessError(Exception):
    """Raised when directory access is denied or directory not found."""

    def __init__(self, message: str) -> None:
        """Initialize with error message.

        Args:
            message: Error description.
        """
        super().__init__(message)


async def read_file(file_path: str, working_dir: Path) -> dict[str, Any]:
    """Read a file's contents.

    Args:
        file_path: Path to the file (relative or absolute).
        working_dir: Working directory for relative paths.

    Returns:
        Dictionary with file contents or error.
    """

    def _read_sync() -> dict[str, Any]:
        path = working_dir / file_path if not Path(file_path).is_absolute() else Path(file_path)

        if not path.exists():
            return {"error": f"File not found: {file_path}"}

        if not path.is_file():
            return {"error": f"Not a file: {file_path}"}

        # Security check: ensure file is within working directory
        try:
            path.resolve().relative_to(working_dir.resolve())
        except ValueError:
            return {"error": "Access denied: file is outside working directory"}

        content = path.read_text(encoding="utf-8", errors="replace")

        # Limit content size for voice responses
        max_chars = 5000
        if len(content) > max_chars:
            content = content[:max_chars] + "\n... (truncated)"

        return {
            "success": True,
            "file_path": str(path),
            "content": content,
            "lines": content.count("\n") + 1,
        }

    try:
        return await asyncio.to_thread(_read_sync)
    except (OSError, PermissionError, UnicodeDecodeError) as e:
        return {"error": f"Error reading file: {e}"}


async def list_directory(directory: str, working_dir: Path) -> dict[str, Any]:
    """List files in a directory.

    Args:
        directory: Directory path (relative or absolute).
        working_dir: Working directory for relative paths.

    Returns:
        Dictionary with directory contents or error.
    """

    def _list_sync() -> dict[str, Any]:
        path = working_dir / directory if not Path(directory).is_absolute() else Path(directory)

        if not path.exists():
            return {"error": f"Directory not found: {directory}"}

        if not path.is_dir():
            return {"error": f"Not a directory: {directory}"}

        # Security check
        try:
            path.resolve().relative_to(working_dir.resolve())
        except ValueError:
            return {"error": "Access denied: directory is outside working directory"}

        items = [
            {
                "name": item.name,
                "type": "directory" if item.is_dir() else "file",
                "size": item.stat().st_size if item.is_file() else None,
            }
            for item in sorted(path.iterdir())
        ]

        return {
            "success": True,
            "directory": str(path),
            "items": items,
            "count": len(items),
        }

    try:
        return await asyncio.to_thread(_list_sync)
    except (OSError, PermissionError) as e:
        return {"error": f"Error listing directory: {e}"}


async def search_files(pattern: str, working_dir: Path) -> dict[str, Any]:
    """Search for files matching a pattern.

    Args:
        pattern: Glob pattern to search for.
        working_dir: Working directory for search.

    Returns:
        Dictionary with matching files or error.
    """

    def _search_sync() -> dict[str, Any]:
        matches = list(working_dir.glob(f"**/{pattern}"))

        # Limit results
        max_results = 20
        matches = matches[:max_results]

        results = [
            str(match.relative_to(working_dir)) if match.is_relative_to(working_dir) else str(match)
            for match in matches
        ]

        return {
            "success": True,
            "pattern": pattern,
            "matches": results,
            "count": len(results),
        }

    try:
        return await asyncio.to_thread(_search_sync)
    except (OSError, PermissionError) as e:
        return {"error": f"Error searching files: {e}"}


async def get_project_structure(working_dir: Path) -> dict[str, Any]:
    """Get an overview of the project structure.

    Args:
        working_dir: Project root directory.

    Returns:
        Dictionary with project structure.
    """

    def _get_structure_sync() -> dict[str, Any]:
        structure = _build_tree(working_dir, working_dir, max_depth=3)
        return {
            "success": True,
            "project": working_dir.name,
            "structure": structure,
        }

    try:
        return await asyncio.to_thread(_get_structure_sync)
    except (OSError, PermissionError) as e:
        return {"error": f"Error getting project structure: {e}"}


def _build_tree(
    path: Path,
    root: Path,
    max_depth: int = 3,
    current_depth: int = 0
) -> dict[str, Any]:
    """Build a tree structure of the project.

    Args:
        path: Current path.
        root: Root path for relative paths.
        max_depth: Maximum depth to traverse.
        current_depth: Current depth.

    Returns:
        Dictionary representing the tree.
    """
    if current_depth >= max_depth:
        return {"...": "max depth reached"}

    # Skip hidden directories and common exclusions
    exclude_dirs = {".git", "__pycache__", "node_modules", ".venv", "venv", ".idea", ".vscode"}

    result: dict[str, Any] = {}
    try:
        for item in sorted(path.iterdir()):
            # Skip hidden files/dirs except .nova and .claude
            if item.name.startswith(".") and item.name not in {".nova", ".claude"}:
                continue

            if item.is_dir():
                if item.name in exclude_dirs:
                    continue
                result[item.name + "/"] = _build_tree(item, root, max_depth, current_depth + 1)
            else:
                result[item.name] = None
    except PermissionError:
        result["[permission denied]"] = None

    return result


async def create_handoff_summary(
    conversation_context: list[dict[str, str]],
    task_description: str,
    working_dir: Path
) -> str:
    """Create a summary for handoff to text agent.

    Args:
        conversation_context: Key points from the voice conversation.
        task_description: What the user wants to implement.
        working_dir: Project directory.

    Returns:
        Formatted summary string for text agent.
    """
    # Get project structure for context
    structure = await get_project_structure(working_dir)

    summary = f"""--- VOICE SESSION HANDOFF ---
Task: {task_description}

Project: {working_dir.name}
Working Directory: {working_dir}

Conversation Context:
"""
    for i, point in enumerate(conversation_context, 1):
        summary += f"  {i}. {point['role']}: {point['content']}\n"

    if structure.get("success"):
        summary += f"\nProject Structure:\n{structure['structure']}\n"

    summary += "\n--- END HANDOFF ---\n"
    summary += "\nPaste this into the text agent (run 'nova' without arguments)."

    return summary

"""Utilities for persisting agent plans as markdown files in .nova/plans/."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from deepagents.backends.protocol import BackendProtocol

_STATUS_CHECKBOX: dict[str, str] = {
    "completed": "x",
    "in_progress": "-",
    "pending": " ",
    "blocked": " ",
}


def todos_to_markdown(todos: list[dict]) -> str:
    """Convert a list of Todo dicts to a markdown task list.

    Args:
        todos: List of Todo dicts with keys: id, content, status,
               and optionally subtasks (list) and depends_on (list[str]).

    Returns:
        Markdown string suitable for writing to a .md file.
    """
    lines: list[str] = [
        "# Plan",
        "",
        f"_Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}_",
        "",
        "## Tasks",
        "",
    ]

    def _render(todo: dict, indent: int = 0) -> None:
        checkbox = _STATUS_CHECKBOX.get(todo.get("status", "pending"), " ")
        prefix = "  " * indent
        content = todo.get("content", "")

        depends_on: list[str] = todo.get("depends_on") or []
        suffix = f" _(depends on: {', '.join(depends_on)})_" if depends_on else ""

        lines.append(f"{prefix}- [{checkbox}] {content}{suffix}")

        for subtask in todo.get("subtasks") or []:
            _render(subtask, indent + 1)

    for todo in todos:
        _render(todo)

    return "\n".join(lines) + "\n"


def write_plan_file(
    todos: list[dict],
    Nova_dir: Path,
    backend: BackendProtocol | None = None,
) -> Path:
    """Write todos as a markdown file to ``<Nova_dir>/plans/``.

    Creates the ``plans/`` subdirectory if it does not exist.
    When a backend is provided, writes through the backend using
    virtual paths. Falls back to direct filesystem write.

    Args:
        todos: List of Todo dicts (see ``todos_to_markdown``).
        Nova_dir: Path to the project ``.nova`` directory.
        backend: Optional CompositeBackend for virtual path access.

    Returns:
        Path of the written file.
    """
    plans_dir = Nova_dir / "plans"
    plans_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    filename = f"plan-{timestamp}.md"
    plan_path = plans_dir / filename
    content = todos_to_markdown(todos)

    # Try writing through backend when available.
    if backend is not None:
        try:
            from novacode_cli.utils.backend_paths import write_via_backend

            virtual_path = f"/.nova/plans/{filename}"
            if write_via_backend(virtual_path, content, backend):
                return plan_path
        except Exception:
            pass

    # Filesystem fallback.
    plan_path.write_text(content, encoding="utf-8")
    return plan_path


__all__ = ["todos_to_markdown", "write_plan_file"]

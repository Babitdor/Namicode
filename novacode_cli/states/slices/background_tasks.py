"""Background task state slice.

Owns Ralph background tasks and the Trello server reference — processes that
run independently of the main agent loop.
"""

from __future__ import annotations

from typing import Any


class BackgroundTaskState:
    """Background processes: Ralph tasks and Trello server."""

    def __init__(self) -> None:
        # Import here to avoid circular dependency at module level
        from novacode_cli.states.Session import BackgroundRalphTask

        self.background_ralph_tasks: dict[str, BackgroundRalphTask] = {}
        self.trello_server: Any = None  # TrelloServer instance
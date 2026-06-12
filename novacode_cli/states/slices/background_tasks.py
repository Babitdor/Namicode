"""Background task state slice.

Owns Ralph background tasks, the Trello server, and the Create server
references — processes that run independently of the main agent loop.
"""

from __future__ import annotations

from typing import Any


class BackgroundTaskState:
    """Background processes: Ralph tasks, Trello server, and Create server."""

    def __init__(self) -> None:
        # Import here to avoid circular dependency at module level
        from novacode_cli.states.Session import BackgroundRalphTask

        self.background_ralph_tasks: dict[str, BackgroundRalphTask] = {}
        self.trello_server: Any = None  # TrelloServer instance
        self.create_server: Any = None  # CreateServer instance
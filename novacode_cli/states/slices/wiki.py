"""Wiki state slice — tracks the agent's persistent wiki memory.

Holds session-level wiki metadata so slash commands and the TUI can
report wiki state without re-reading the filesystem.
"""

from __future__ import annotations


class WikiState:
    """Session state for the project wiki (``.nova/wiki/``).

    All fields are optional and lazily resolved — the wiki is not
    required for normal operation.
    """

    def __init__(self) -> None:
        # Lazily resolved absolute path to the wiki root (e.g. ``/home/.../.nova/wiki/``).
        self.wiki_root: str | None = None
        # Whether wiki features are active.
        self.wiki_enabled: bool = True
        # Approximate count of synthesized wiki pages (excluding raw/).
        self.page_count: int = 0
        # Filename of the most recently ingested source (or ``None``).
        self.last_ingest: str | None = None
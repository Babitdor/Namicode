"""Remote bridge (Discord/Telegram) state slice.

Owns the queue, lock, bridge manager, auto-approve snapshot, image tracker,
seen-message tracking, and the console/composite-backend references used by
the remote message processor.
"""

from __future__ import annotations

import asyncio
from typing import Any


class RemoteBridgeState:
    """State for Discord/Telegram remote bridge subsystem."""

    def __init__(self) -> None:
        self._remote_message_queue: asyncio.Queue | None = None
        self._remote_message_lock: asyncio.Lock = asyncio.Lock()
        self._remote_bridge_manager: Any = None  # RemoteBridgeManager
        self._pre_remote_auto_approve: bool | None = None
        self._image_tracker: Any = None  # ImageTracker
        self._seen_message_ids: set = set()  # Message IDs seen by remote bridge
        self._composite_backend: Any = None  # Composite backend for remote bridge
        self._console: Any = None  # Rich Console reference
"""Remote bridge (Discord/Telegram) state slice.

Owns the queue, lock, bridge manager, auto-approve snapshot, image tracker,
seen-message tracking, and the console/composite-backend references used by
the remote message processor.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable

# Maximum number of remote-bridge message IDs retained for dedup. The set is
# session-persistent and grows with every message/tool result seen; an unbounded
# set leaks memory across a long session. The cap is large enough that only very
# old IDs (no longer needed for dedup) are evicted.
_MAX_SEEN_MESSAGE_IDS = 100_000


class _BoundedSet(set):
    """A ``set`` that evicts members once it exceeds a cap.

    Used for remote-bridge message dedup IDs, which accumulate across a long
    session. ``set`` has no insertion order, so eviction is approximate: when
    the cap is exceeded we drop a batch of arbitrary members. The cap is large
    enough that this only affects very old IDs, which are no longer needed for
    dedup.
    """

    def __init__(self, iterable: Iterable[str] = ()) -> None:
        super().__init__(iterable)
        self._maxlen = _MAX_SEEN_MESSAGE_IDS

    def add(self, element: str) -> None:
        super().add(element)
        if len(self) > self._maxlen:
            # Drop a batch of the oldest (arbitrary) members to stay bounded.
            for _ in range(len(self) - self._maxlen):
                self.pop()


class RemoteBridgeState:
    """State for Discord/Telegram remote bridge subsystem."""

    def __init__(self) -> None:
        self._remote_message_queue: asyncio.Queue | None = None
        self._remote_message_lock: asyncio.Lock = asyncio.Lock()
        self._remote_bridge_manager: Any = None  # RemoteBridgeManager
        self._pre_remote_auto_approve: bool | None = None
        self._image_tracker: Any = None  # ImageTracker
        self._seen_message_ids: set = _BoundedSet()  # Message IDs seen by remote bridge
        self._composite_backend: Any = None  # Composite backend for remote bridge
        self._console: Any = None  # Rich Console reference
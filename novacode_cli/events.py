"""Shared event buffer for Nova middleware events.

This module owns the module-level ``nova_event_log`` list that multiple
middleware modules (Hermes, Security) append to, and which the agent event
loop drains into ``ContextMessage`` UI events.

Extracted from ``hermes/middleware.py`` to break the implicit dependency:
SecurityMiddleware and memory_tiers must NOT depend on NovaLearningMiddleware
just to surface a TUI-safe notice.

Usage::

    from novacode_cli.events import nova_event_log

    nova_event_log.append(("nova_security", "🛡", "yellow", "Blocked spoofed domain"))

The list is cleared after each drain by ``iterate_agent_events`` in
``core/agent_loop.py``.
"""

from __future__ import annotations

from typing import Any

_MAX_EVENT_LOG = 200  # Cap to prevent unbounded growth if drain stalls

# Module-level event buffer for Nova events (review cycles, skill activity,
# security notices, memory operations).
# The middleware appends ``(event_type, icon, color, message)`` tuples here, and
# ``iterate_agent_events`` in ``core/agent_loop.py`` drains them into proper
# :class:`~novacode_cli.ui_events.ContextMessage` events that both the Rich
# console renderer and the Textual TUI consume.
nova_event_log: list[tuple[str, str, str, str]] = []
"""``(event_type, icon, color, message)`` log drained by the agent event loop.

The list is cleared after each drain.  Event types:
- ``nova_review_start``
- ``nova_review_complete``
- ``nova_skill_refinement``
- ``nova_skill_created``
- ``nova_security``
- ``nova_memory``
"""


def cap_event_log() -> None:
    """Trim the event log to ``_MAX_EVENT_LOG`` entries if it exceeds the limit.

    Called by append sites to prevent unbounded growth when the drain stalls.
    """
    if len(nova_event_log) > _MAX_EVENT_LOG:
        del nova_event_log[: len(nova_event_log) - _MAX_EVENT_LOG]
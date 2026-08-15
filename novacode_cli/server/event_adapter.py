"""Event adapter: converts ui_events dataclasses to JSON-serializable dicts.

This module provides the bridge between the agent runtime's internal event
types (``novacode_cli.ui_events``) and the WebSocket JSON protocol.

Each event dataclass is mapped to a ``(event_type, data_dict)`` pair where
``event_type`` is a short string like ``"assistant_token"`` and ``data_dict``
is a plain dict suitable for ``json.dumps``.

The reverse direction (client → server) is handled separately in the WebSocket
handler for interrupt responses and cancellation.
"""

from __future__ import annotations

import dataclasses
from typing import Any

from novacode_cli import ui_events


def serialize_event(event: object) -> dict[str, Any] | None:
    """Convert a ui_events dataclass to a JSON-serializable event dict.

    Returns ``{"type": str, "data": dict}`` or ``None`` if the event should
    be skipped (e.g. internal-only events that don't map to the protocol).
    """
    # Dispatch by type
    if isinstance(event, ui_events.TextDelta):
        return {"type": "assistant_token", "data": {"token": event.text}}

    if isinstance(event, ui_events.ReasoningDelta):
        return {"type": "reasoning_token", "data": {"token": event.text}}

    if isinstance(event, ui_events.AssistantMessage):
        return {
            "type": "assistant_message",
            "data": {
                "text": event.text,
                "agent_name": event.agent_name,
                "agent_color": event.agent_color,
                "is_subagent": event.is_subagent,
            },
        }

    if isinstance(event, ui_events.ToolCall):
        return {
            "type": "tool_started",
            "data": {
                "name": event.name,
                "display_str": event.display_str,
                "icon": event.icon,
                "is_main_agent": event.is_main_agent,
                "args": event.args,
                "call_id": event.call_id,
            },
        }

    if isinstance(event, ui_events.ToolResult):
        return {
            "type": "tool_finished",
            "data": {
                "preview": event.preview,
                "is_error": event.is_error,
                "full_output": event.full_output,
                "call_id": event.call_id,
            },
        }

    if isinstance(event, ui_events.FileOp):
        return {
            "type": "file_changed",
            "data": {
                "record": _serialize_record(event.record),
                "full_output": event.full_output,
                "call_id": event.call_id,
            },
        }

    if isinstance(event, ui_events.StatusUpdate):
        return {
            "type": "status",
            "data": {"message": event.message},
        }

    if isinstance(event, ui_events.Done):
        return {
            "type": "assistant_done",
            "data": {"had_response": event.had_response},
        }

    if isinstance(event, ui_events.Error):
        return {
            "type": "error",
            "data": {
                "message": event.message,
                "is_provider_notice": event.is_provider_notice,
            },
        }

    if isinstance(event, ui_events.Cancelled):
        return {"type": "cancelled", "data": {}}

    if isinstance(event, ui_events.InterruptRequest):
        return {
            "type": "interrupt",
            "data": {
                "kind": event.kind,
                "payload": _serialize_payload(event.kind, event.payload),
            },
        }

    if isinstance(event, ui_events.SubagentActivity):
        return {
            "type": "subagent_activity",
            "data": {
                "kind": event.kind,
                "subagent_type": event.subagent_type,
                "message": event.message,
                "detail": event.detail,
                "color": event.color,
                "call_id": event.call_id,
            },
        }

    if isinstance(event, ui_events.TodoUpdate):
        return {
            "type": "todo_update",
            "data": {
                "todos": event.todos,
                "agent_name": event.agent_name,
            },
        }

    if isinstance(event, ui_events.UsageUpdate):
        return {
            "type": "usage",
            "data": {
                "input_tokens": event.input_tokens,
                "output_tokens": event.output_tokens,
                "cache_read_tokens": event.cache_read_tokens,
                "cache_creation_tokens": event.cache_creation_tokens,
            },
        }

    if isinstance(event, ui_events.ContextMessage):
        return {
            "type": "context_message",
            "data": {
                "message": event.message,
                "event_type": event.event_type,
                "icon": event.icon,
                "color": event.color,
            },
        }

    if isinstance(event, ui_events.CompactionNotice):
        return {"type": "compaction_notice", "data": {}}

    if isinstance(event, ui_events.TextDiscard):
        return {"type": "text_discard", "data": {}}

    # Unknown event type — skip silently
    return None


def _serialize_record(record: Any) -> dict[str, Any] | None:
    """Safely serialize a file-op record to a dict."""
    if record is None:
        return None
    if dataclasses.is_dataclass(record):
        return dataclasses.asdict(record)
    if isinstance(record, dict):
        return record
    return str(record)


def _serialize_payload(kind: str, payload: Any) -> Any:
    """Serialize an InterruptRequest payload to JSON-safe form."""
    if kind == "tool":
        # HITLRequest — try dataclass fields
        if dataclasses.is_dataclass(payload):
            return dataclasses.asdict(payload)
        return str(payload)
    if kind == "question":
        return payload if isinstance(payload, dict) else str(payload)
    if kind == "plan":
        return payload if isinstance(payload, list) else str(payload)
    return str(payload)

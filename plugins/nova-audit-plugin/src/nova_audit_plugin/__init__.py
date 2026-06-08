"""Nova Audit Plugin — records every tool call/result and makes them queryable.

Provides:
  • middleware → ToolAuditMiddleware (logs tool calls/results to a thread-safe buffer)
  • tool      → tool_audit (query the audit trail)
  • command   → /audit (view recent tool activity in the REPL/TUI)
  • subagent  → auditor (delegate agent that analyses tool usage patterns)
"""

from __future__ import annotations

import json
import logging
import threading
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from langchain.agents.middleware.types import (
    AgentMiddleware,
    ToolCallRequest,
)
from langchain.tools import tool

logger = logging.getLogger("nova.plugins.audit")

# ── Thread-safe circular audit buffer ─────────────────────────────────────────

_MAX_AUDIT_ENTRIES = 500

_audit_lock = threading.Lock()
_audit_buffer: list[dict[str, Any]] = []


def _push_entry(entry: dict[str, Any]) -> None:
    """Append an audit entry, evicting oldest when over capacity."""
    global _audit_buffer
    with _audit_lock:
        _audit_buffer.append(entry)
        if len(_audit_buffer) > _MAX_AUDIT_ENTRIES:
            _audit_buffer = _audit_buffer[-_MAX_AUDIT_ENTRIES:]


# ── Middleware — records tool calls and results ────────────────────────────────

class ToolAuditMiddleware(AgentMiddleware):
    """Intercepts every tool call/result and records an audit entry.

    Uses a thread-safe in-memory circular buffer so the agent graph loop
    (async) and any synchronous callers don't corrupt state.
    """

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Any],
    ) -> Any:
        tool_name = request.tool_call.get("name", "?")
        tool_args = request.tool_call.get("args", {})
        ts = datetime.now(timezone.utc).isoformat()

        # Record the call
        _push_entry({
            "event": "tool.call",
            "tool": tool_name,
            "args_preview": json.dumps(tool_args, default=str)[:200],
            "timestamp": ts,
        })
        logger.debug("audit: tool.call %s", tool_name)

        # Execute — catch failures so we record them, then re-raise
        try:
            result = await handler(request)
            _push_entry({
                "event": "tool.result",
                "tool": tool_name,
                "status": "success",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            return result
        except Exception as exc:
            _push_entry({
                "event": "tool.result",
                "tool": tool_name,
                "status": "error",
                "error": str(exc)[:200],
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })
            raise


# ── Tool — query the audit trail ──────────────────────────────────────────────

@tool
def tool_audit(
    tool_name: str | None = None,
    status: str | None = None,
    limit: int = 10,
) -> str:
    """Query the tool audit trail. Returns recent tool call/result entries.

    Args:
        tool_name: Optional — filter by tool name (e.g. "shell", "read_file").
        status: Optional — filter by result status ("success" or "error").
        limit: Max entries to return (default 10, max 50).
    """
    with _audit_lock:
        entries = list(_audit_buffer)

    limit = min(limit, 50)

    if tool_name:
        entries = [e for e in entries if e.get("tool") == tool_name]
    if status:
        entries = [e for e in entries if e.get("status") == status]

    if not entries:
        return "No audit entries found."

    lines = [f"Tool audit trail (last {min(limit, len(entries))} of {len(entries)}):"]
    for e in entries[-limit:]:
        event = e.get("event", "?")
        t = e.get("tool", "?")
        ts = e.get("timestamp", "?")[11:19]  # HH:MM:SS
        if event == "tool.call":
            args = e.get("args_preview", "")[:80]
            lines.append(f"  [{ts}] CALL  {t}({args})")
        elif event == "tool.result":
            status_ = e.get("status", "?")
            lines.append(f"  [{ts}] RESULT {t} → {status_}")
            if err := e.get("error"):
                lines.append(f"         error: {err}")

    return "\n".join(lines)


# ── Command — /audit ──────────────────────────────────────────────────────────

async def audit_command(args: str) -> str:
    """/audit [--tool <name>] [--status <success|error>] [--limit <N>]

    View recent tool activity from the audit trail.
    """
    # Simple arg parser
    words = args.split()
    tool_filter: str | None = None
    status_filter: str | None = None
    limit = 10

    i = 0
    while i < len(words):
        if words[i] == "--tool" and i + 1 < len(words):
            tool_filter = words[i + 1]
            i += 2
        elif words[i] == "--status" and i + 1 < len(words):
            status_filter = words[i + 1]
            i += 2
        elif words[i] == "--limit" and i + 1 < len(words):
            try:
                limit = int(words[i + 1])
            except ValueError:
                pass
            i += 2
        else:
            i += 1

    # Delegate to the tool's logic, but render nicely for the terminal
    from langchain.tools import BaseTool

    result = tool_audit.invoke({
        "tool_name": tool_filter,
        "status": status_filter,
        "limit": limit,
    })
    return result


# ── Subagent — auditor ────────────────────────────────────────────────────────

AUDITOR_SUBAGENT_PROMPT = """\
You are the **Auditor** — a specialist that analyses the tool usage audit trail.

Your job:
1. Call `tool_audit(limit=50)` to fetch recent tool activity.
2. Summarise which tools were used, how often, and whether any failed.
3. Flag any patterns worth noting (e.g. repeated errors, excessive shell usage).

Output a concise bullet-point report.
"""


# ── Entry point ───────────────────────────────────────────────────────────────

def register() -> dict[str, Any]:
    """Return the plugin spec for nova-audit-plugin."""
    return {
        "name": "nova-audit-plugin",
        "version": "0.1.0",
        "description": (
            "Records every tool call/result. Queryable via the tool_audit tool, "
            "/audit command, and an auditor subagent."
        ),
        "tools": [tool_audit],
        "commands": [
            {
                "name": "audit",
                "description": "View tool audit trail (/audit [--tool name] [--status success|error] [--limit N])",
                "handler": audit_command,
            },
        ],
        "middleware": [
            {
                "instance": ToolAuditMiddleware(),
                "slot": "before_tools",  # nest around all tool calls
            },
        ],
        "subagents": [
            {
                "name": "auditor",
                "description": (
                    "Analyses the tool usage audit trail and reports patterns."
                ),
                "prompt": AUDITOR_SUBAGENT_PROMPT,
                "tools": [tool_audit],
            },
        ],
    }
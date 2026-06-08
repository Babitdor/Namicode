"""Nova Context Plugin — injects dynamic context into every model call.

Provides:
  • middleware → ContextInjectionMiddleware (injects time, workspace,
    and custom variables into the system prompt via wrap_model_call)
  • tool      → read_context (inspect current context variables)
  • command   → /context [key=value] (view or set context variables)
  • subagent  → context-writer (researches and stores context snippets)
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from langchain.agents.middleware.types import (
    AgentMiddleware,
    ModelRequest,
    ModelResponse,
)
from langchain.messages import SystemMessage
from langchain.tools import tool

logger = logging.getLogger("nova.plugins.context")

# ── Mutable context store (global — single-process; Nova is single-process) ───

_context_vars: dict[str, str] = {}


def _build_context_block() -> str:
    """Assemble the context text block injected into the system prompt."""
    now = datetime.now(timezone.utc)
    parts = [
        "--- dynamic context (nova-context-plugin) ---",
        f"Current timestamp (UTC): {now.strftime('%Y-%m-%d %H:%M:%S')}",
        f"Day of week: {now.strftime('%A')}",
        f"Workspace: {Path.cwd().name}",
    ]
    if _context_vars:
        parts.append("Custom context variables:")
        for k, v in _context_vars.items():
            parts.append(f"  {k} = {v}")
    parts.append("--- end dynamic context ---")
    return "\n".join(parts)


# ── Middleware — injects context into the system prompt ───────────────────────

class ContextInjectionMiddleware(AgentMiddleware):
    """Injects dynamic context (time, workspace, custom vars) into the system
    prompt before every model call via ``wrap_model_call``.

    This uses the system prompt override mechanism described in the custom
    middleware docs: reads ``request.system_message.content_blocks``, appends
    a context block, and returns an overridden request.
    """

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        context_block = _build_context_block()
        existing_blocks = list(request.system_message.content_blocks)
        new_content = existing_blocks + [
            {"type": "text", "text": context_block}
        ]
        new_system = SystemMessage(content=new_content)
        return handler(request.override(system_message=new_system))

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        # Same logic, async path
        context_block = _build_context_block()
        existing_blocks = list(request.system_message.content_blocks)
        new_content = existing_blocks + [
            {"type": "text", "text": context_block}
        ]
        new_system = SystemMessage(content=new_content)
        return await handler(request.override(system_message=new_system))


# ── Tool — read current context ───────────────────────────────────────────────

@tool
def read_context() -> str:
    """Read the current dynamic context variables and the context block that
    is injected into the system prompt on every model call.

    Useful for the agent to inspect what it knows about the environment.
    """
    return _build_context_block()


# ── Command — /context ────────────────────────────────────────────────────────

async def context_command(args: str) -> str:
    """/context [key=value] [key=value ...]

    Without arguments: display the current context variables.
    With ``key=value`` pairs: set custom context variables.
    """
    args = args.strip()
    if not args:
        # Display current context
        lines = ["Current context injection state:"]
        lines.append(_build_context_block())
        return "\n".join(lines)

    # Parse key=value pairs
    pairs = args.split()
    set_count = 0
    for pair in pairs:
        if "=" in pair:
            k, v = pair.split("=", 1)
            _context_vars[k.strip()] = v.strip()
            set_count += 1

    return (
        f"✅ Set {set_count} custom context variable(s). "
        "They will appear in the system prompt on the next model call."
    )


# ── Subagent — context-writer ─────────────────────────────────────────────────

CONTEXT_WRITER_PROMPT = """\
You are the **Context Writer** — a specialist that researches and saves
context snippets for the development session.

Your job:
1. Use the `read_context` tool to check what context is already set.
2. For any new context the user tasks you with, set it via the `/context` command
   (or instruct the user to run `/context key=value`).
3. Output a brief summary of the context state.
"""


# ── Entry point ───────────────────────────────────────────────────────────────

def register() -> dict[str, Any]:
    """Return the plugin spec for nova-context-plugin."""
    return {
        "name": "nova-context-plugin",
        "version": "0.1.0",
        "description": (
            "Injects dynamic context (time, workspace, custom vars) into "
            "every model call. Includes a read_context tool, /context command, "
            "and a context-writer subagent."
        ),
        "tools": [read_context],
        "commands": [
            {
                "name": "context",
                "description": "View or set context variables (/context [key=value ...])",
                "handler": context_command,
            },
        ],
        "middleware": [
            {
                "instance": ContextInjectionMiddleware(),
                "slot": "before_shell",  # early in the stack — before ShellMiddleware
            },
        ],
        "subagents": [
            {
                "name": "context-writer",
                "description": (
                    "Researches and saves context snippets for the session."
                ),
                "prompt": CONTEXT_WRITER_PROMPT,
                "tools": [read_context],
            },
        ],
    }
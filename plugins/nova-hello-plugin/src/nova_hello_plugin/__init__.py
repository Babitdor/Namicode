"""Example Nova plugin.

Demonstrates all four things a plugin can contribute to Nova:

  • a tool          → ``greet`` (the agent can call it)
  • a slash command → ``/hello`` (you can type it in the TUI/REPL)
  • a middleware    → ``HelloMiddleware`` (wraps every model call)
  • a subagent      → ``greeter`` (dispatchable via the ``task`` tool)

Install (from the Nova repo root, into Nova's environment)::

    uv pip install -e examples/nova-hello-plugin
    # or:  pip install -e examples/nova-hello-plugin

Enable::

    # In Nova: run  /plugins  → select "nova-hello-plugin" → Enable → restart
    # (commands work immediately on enable; middleware/tools/subagents need the
    #  restart, since they're wired in when the agent graph is built.)

Verify::

    /hello Ada                  → the slash command replies
    "use the greet tool on Bob" → the agent calls the greet tool
    "ask the greeter subagent to welcome the team"
"""

from __future__ import annotations

import logging
from typing import Any

from langchain.agents.middleware.types import (
    AgentMiddleware,
    ModelRequest,
    ModelResponse,
)
from langchain.tools import tool

logger = logging.getLogger("nova.plugins.hello")


# ── A tool the agent can call ────────────────────────────────────────────────
@tool
def greet(name: str = "world") -> str:
    """Return a friendly greeting for the given name."""
    return f"Hello, {name}! 👋 (from nova-hello-plugin)"


# ── A middleware that wraps every model call (minimal observability) ──────────
class HelloMiddleware(AgentMiddleware):
    """Logs each model call. A template for cross-cutting behavior."""

    async def awrap_model_call(
        self, request: ModelRequest, handler
    ) -> ModelResponse:
        logger.info(
            "nova-hello-plugin: model call with %d messages", len(request.messages)
        )
        return await handler(request)


# ── A slash command (UI-agnostic: takes the arg string, returns text) ─────────
async def hello_command(args: str) -> str:
    """``/hello [name]`` — greet someone, straight from the plugin."""
    name = args.strip() or "world"
    return f"👋 Hello, {name}! This /hello command comes from nova-hello-plugin."


# ── The entry point Nova calls at startup ─────────────────────────────────────
def register() -> dict[str, Any]:
    """Return the plugin spec describing everything this plugin provides."""
    return {
        "name": "nova-hello-plugin",
        "version": "0.1.0",
        "description": (
            "Example: a greet tool, a /hello command, an audit middleware, "
            "and a greeter subagent."
        ),
        "tools": [greet],
        "commands": [
            {
                "name": "hello",
                "description": "Greet someone (/hello [name])",
                "handler": hello_command,
            },
        ],
        "middleware": [
            # slot controls where it sits in the stack; see docs/plugins.md.
            {"instance": HelloMiddleware(), "slot": "before_shell"},
        ],
        "subagents": [
            {
                "name": "greeter",
                "description": (
                    "Delegate greeting tasks here — it welcomes people warmly."
                ),
                "prompt": (
                    "You are a cheerful greeter. Use the greet tool to welcome "
                    "people, then reply with a warm one-line message."
                ),
                "tools": [greet],
            }
        ],
    }

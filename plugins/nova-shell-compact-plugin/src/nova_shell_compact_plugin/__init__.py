"""Nova Shell Compact Plugin — compacts long shell tool outputs.

When the agent runs a shell command that produces lots of output, all those
lines get stuffed into a ToolMessage and sent back to the LLM — burning tokens.
This middleware intercepts the result before it reaches the agent, trims the
middle, and replaces it with a compact summary that preserves:
  • the first N lines (head)
  • the last N lines (tail)
  • any lines containing "error" / "Error" / "ERROR" / "traceback" / "Exit"
  • a header showing original vs. compacted size
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from typing import Any

from langchain.agents.middleware.types import (
    AgentMiddleware,
    ToolCallRequest,
)
from langchain.messages import ToolMessage

logger = logging.getLogger("nova.plugins.shell-compact")

# ── Configuration (mutable at runtime via /shell-compact) ─────────────────────

_compact_config = {
    "threshold": 1500,   # chars — outputs longer than this are compacted
    "head_lines": 20,    # leading lines to keep
    "tail_lines": 10,    # trailing lines to keep
    "enabled": True,
}


def _compact_output(output: str, tool_name: str) -> str:
    """Compact a tool output string if it exceeds the threshold.

    Returns the compacted string with a header annotation, or the original
    if it's already short enough or compaction is disabled.
    """
    if not _compact_config["enabled"]:
        return output

    threshold = _compact_config["threshold"]

    if len(output) <= threshold:
        return output

    head_n = _compact_config["head_lines"]
    tail_n = _compact_config["tail_lines"]

    lines = output.splitlines(keepends=True)
    total_lines = len(lines)

    # Always keep lines that look like errors
    error_pattern = re.compile(r"(?i)(error|traceback|exception|fail|exit \d)")
    error_lines: list[int] = []
    for i, line in enumerate(lines):
        if error_pattern.search(line):
            error_lines.append(i)

    # Build compacted output
    # 1. Head
    head = lines[:head_n]

    # 2. Tail
    tail = lines[-tail_n:] if tail_n > 0 else []

    # 3. Error lines outside head/tail range
    extra_errors: list[str] = []
    seen_indices = set(range(head_n)) | set(range(total_lines - tail_n, total_lines))
    for idx in error_lines:
        if idx not in seen_indices:
            extra_errors.append(lines[idx].rstrip("\n"))
            seen_indices.add(idx)

    # Assemble
    compressed: list[str] = []
    omitted = total_lines - len(head) - len(tail) - len(extra_errors)
    original_chars = len(output)

    compressed.append(
        f"[compact: {original_chars}→? chars, "
        f"showing {len(head)} head + {len(tail)} tail"
        f"{' + ' + str(len(extra_errors)) + ' error lines' if extra_errors else ''}"
        f", omitted {omitted} lines]\n\n"
    )

    if head:
        compressed.extend(head)
        if omitted or extra_errors:
            compressed.append("… [truncated]\n")

    if extra_errors:
        compressed.append("── key error lines ──\n")
        compressed.extend(e + "\n" for e in extra_errors)
        compressed.append("── end error lines ──\n")

    if tail:
        if omitted:
            compressed.append("… [resumed]\n")
        compressed.extend(tail)

    compacted = "".join(compressed)
    compacted_chars = len(compacted)

    # Update the header with actual char count
    compacted = (
        f"[compact: {original_chars}→{compacted_chars} chars, "
        f"showing {len(head)} head + {len(tail)} tail"
        f"{' + ' + str(len(extra_errors)) + ' error lines' if extra_errors else ''}"
        f", omitted {omitted} lines]\n\n"
    )
    if head:
        compacted += "".join(head)
        if omitted or extra_errors:
            compacted += "… [truncated]\n"
    if extra_errors:
        compacted += "── key error lines ──\n"
        compacted += "\n".join(extra_errors) + "\n"
        compacted += "── end error lines ──\n"
    if tail:
        if omitted:
            compacted += "… [resumed]\n"
        compacted += "".join(tail)

    logger.info(
        "compact: %s %d→%d chars (%d lines omitted)",
        tool_name, original_chars, len(compacted), omitted,
    )
    return compacted


# ── Middleware — compacts shell tool results ──────────────────────────────────

class ShellCompactMiddleware(AgentMiddleware):
    """Intercepts tool call results and compacts long ``shell`` outputs.

    Uses ``wrap_tool_call`` so it runs *after* the tool executes but *before*
    the result is returned to the agent loop. The ``handler`` receives the
    original ``ToolCallRequest`` and returns a ``ToolMessage`` (or ``Command``).
    We intercept the ``ToolMessage``, compact its ``content`` if the tool name
    matches ``shell``, and return a new ``ToolMessage`` with the compacted text.

    Slot: ``after_tools`` — placed after tool execution so we see the raw result.
    """

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Any],
    ) -> ToolMessage | Any:
        result = handler(request)

        tool_name = request.tool_call.get("name", "")
        if tool_name == "shell" and isinstance(result, ToolMessage):
            original = result.content if isinstance(result.content, str) else ""
            compacted = _compact_output(original, tool_name)
            if compacted != original:
                result = ToolMessage(
                    content=compacted,
                    tool_call_id=result.tool_call_id,
                    name=result.name,
                    status=result.status,
                    artifact=result.artifact,
                )

        return result

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Any],
    ) -> ToolMessage | Any:
        return self.wrap_tool_call(request, handler)


# ── Command — /shell-compact ──────────────────────────────────────────────────

async def shell_compact_command(args: str) -> str:
    """/shell-compact [threshold] [--head N] [--tail N] [--on|--off]

    Without arguments: display current configuration.
    With a number: set the character threshold.
    """
    args = args.strip()
    if not args:
        return (
            f"ShellCompact configuration:\n"
            f"  enabled:   {_compact_config['enabled']}\n"
            f"  threshold: {_compact_config['threshold']} chars\n"
            f"  head:      {_compact_config['head_lines']} lines\n"
            f"  tail:      {_compact_config['tail_lines']} lines\n\n"
            "Usage: /shell-compact <threshold>  — set char threshold\n"
            "       /shell-compact --head N      — set head lines\n"
            "       /shell-compact --tail N      — set tail lines\n"
            "       /shell-compact --on|--off    — enable/disable"
        )

    words = args.split()
    i = 0
    while i < len(words):
        w = words[i]
        if w == "--head" and i + 1 < len(words):
            try:
                _compact_config["head_lines"] = max(1, int(words[i + 1]))
            except ValueError:
                pass
            i += 2
        elif w == "--tail" and i + 1 < len(words):
            try:
                _compact_config["tail_lines"] = max(0, int(words[i + 1]))
            except ValueError:
                pass
            i += 2
        elif w == "--on":
            _compact_config["enabled"] = True
            i += 1
        elif w == "--off":
            _compact_config["enabled"] = False
            i += 1
        elif w.isdigit():
            _compact_config["threshold"] = int(w)
            i += 1
        else:
            i += 1

    return (
        f"✅ ShellCompact updated:\n"
        f"  enabled:   {_compact_config['enabled']}\n"
        f"  threshold: {_compact_config['threshold']} chars\n"
        f"  head:      {_compact_config['head_lines']} lines\n"
        f"  tail:      {_compact_config['tail_lines']} lines"
    )


# ── Entry point ───────────────────────────────────────────────────────────────

def register() -> dict[str, Any]:
    """Return the plugin spec for nova-shell-compact-plugin."""
    return {
        "name": "nova-shell-compact-plugin",
        "version": "0.1.0",
        "description": (
            "Compacts long shell tool outputs before they reach the agent. "
            "Saves tokens by trimming the middle while preserving head, tail, "
            "and error lines."
        ),
        "tools": [],
        "commands": [
            {
                "name": "shell-compact",
                "description": "View/change compaction threshold (/shell-compact [threshold] [--head N] [--tail N] [--on|--off])",
                "handler": shell_compact_command,
            },
        ],
        "middleware": [
            {
                "instance": ShellCompactMiddleware(),
                # after_tools places us after the tool executes so we see the
                # raw ToolMessage before it flows back into the agent loop.
                "slot": "after_tools",
            },
        ],
        "subagents": [],
    }
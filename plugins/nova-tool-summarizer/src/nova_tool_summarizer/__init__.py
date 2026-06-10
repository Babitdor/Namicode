"""Nova Tool Summarizer Plugin — compacts verbose tool outputs across all tools.

When the agent runs tools like bash, read_file, grep, or glob that produce
lots of output, every line gets stuffed into a ToolMessage and sent to the
LLM — burning tokens. This middleware intercepts each tool result *before*
it reaches the agent and compacts it using tool-aware strategies.

Strategies per tool:
  • bash/execute/shell  → head + tail, preserving error lines
  • read_file           → head + tail with byte context
  • grep                → head + tail of match lines
  • glob/ls             → head + tail of file listings
  • JSON-bearing tools  → formatted with line count
  • default             → head/tail on raw line count

Configuration is mutable at runtime via /summarizer command.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from typing import Any

from langchain.agents.middleware.types import (
    AgentMiddleware,
    ModelRequest,
    ModelResponse,
    ToolCallRequest,
)
from langchain.tools import tool

logger = logging.getLogger("nova.plugins.tool-summarizer")

# ── Default configuration ─────────────────────────────────────────────────────

_SUMMARY_CONFIG = {
    "enabled": True,
    "global_threshold_chars": 2000,  # compact if any tool output exceeds this
    "global_head_lines": 15,  # leading lines to keep (default)
    "global_tail_lines": 10,  # trailing lines to keep (default)
    "per_tool": {
        "bash": {"threshold": 1500, "head": 20, "tail": 10},
        "execute": {"threshold": 1500, "head": 20, "tail": 10},
        "shell": {"threshold": 1500, "head": 20, "tail": 10},
        "read_file": {"threshold": 3000, "head": 15, "tail": 5},
        "grep": {"threshold": 2000, "head": 20, "tail": 10},
        "glob": {"threshold": 2000, "head": 20, "tail": 10},
        "ls": {"threshold": 2000, "head": 20, "tail": 10},
        "fetch_url": {"threshold": 5000, "head": 15, "tail": 5},
    },
}

_ERROR_PATTERN = re.compile(
    r"(?i)(error|traceback|exception|fail|fatal|aborted|killed|exit \d|returned non-zero)"
)


# ── Tool-aware compaction strategies ──────────────────────────────────────────


def _get_tool_config(tool_name: str) -> dict[str, Any]:
    """Resolve effective config for a tool: per-tool overrides global defaults."""
    overrides = _SUMMARY_CONFIG["per_tool"].get(tool_name, {})
    return {
        "threshold": overrides.get(
            "threshold", _SUMMARY_CONFIG["global_threshold_chars"]
        ),
        "head": overrides.get("head", _SUMMARY_CONFIG["global_head_lines"]),
        "tail": overrides.get("tail", _SUMMARY_CONFIG["global_tail_lines"]),
    }


def _maybe_compact_json(output: str) -> str | None:
    """If output is valid JSON, re-format it compactly. Returns None if not JSON."""
    stripped = output.strip()
    if not (
        stripped.startswith("{") or stripped.startswith("[") or stripped.startswith('"')
    ):
        return None
    try:
        parsed = json.loads(stripped)
        formatted = json.dumps(parsed, indent=2, default=str, ensure_ascii=False)
        # If formatting didn't save much space, leave it alone
        if len(formatted) >= len(output) * 0.9:
            return None
        return formatted
    except (json.JSONDecodeError, ValueError):
        return None


def _compact_by_lines(
    output: str, tool_name: str, threshold: int, head_n: int, tail_n: int
) -> str:
    """Compact a tool output by keeping head + tail + error lines.

    Returns the compacted string with a header annotation, or the original
    if it's already short enough or compaction is disabled.
    """
    if not _SUMMARY_CONFIG["enabled"]:
        return output

    if len(output) <= threshold:
        return output

    lines = output.splitlines(keepends=True)
    total_lines = len(lines)

    # Always keep lines that look like errors
    error_lines: list[int] = []
    for i, line in enumerate(lines):
        if _ERROR_PATTERN.search(line):
            error_lines.append(i)

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

    # Build compacted output
    omitted = total_lines - len(head) - len(tail) - len(extra_errors)
    original_chars = len(output)
    compressed: list[str] = []

    compressed.append(
        f"[compact: {tool_name}, "
        f"{original_chars} chars → ? ({total_lines} lines), "
        f"showing {len(head)} head + {len(tail)} tail"
        f"{' + ' + str(len(extra_errors)) + ' error lines' if extra_errors else ''}"
        f", omitted {omitted} lines]\n\n"
    )

    if head:
        compressed.extend(head)
        if omitted or extra_errors:
            compressed.append("… [truncated — use the tool directly for full output]\n")

    if extra_errors:
        compressed.append("── key error lines ──\n")
        compressed.extend(e + "\n" for e in extra_errors)
        compressed.append("── end error lines ──\n")

    if tail and (omitted or extra_errors):
        compressed.append("\n── tail ──\n")
        compressed.extend(tail)

    return "".join(compressed)


def _compact_output(output: str, tool_name: str) -> str:
    """Compact a tool's output string using a strategy appropriate for the tool.

    If compaction results in a longer string than the original (unlikely but
    possible for small inputs), the original is returned instead.
    """
    if not _SUMMARY_CONFIG["enabled"]:
        return output

    config = _get_tool_config(tool_name)
    threshold = config["threshold"]
    head_n = config["head"]
    tail_n = config["tail"]

    # Try JSON reformatting first for applicable tools
    if tool_name in ("fetch_url", "read_file"):
        reformed = _maybe_compact_json(output)
        if reformed is not None and len(reformed) < len(output):
            return (
                f"[compact: {tool_name} — reformatted JSON "
                f"({len(output)} → {len(reformed)} chars)]\n\n"
                f"{reformed}\n"
            )

    compacted = _compact_by_lines(output, tool_name, threshold, head_n, tail_n)

    # Safety: never return a compacted string longer than the original
    if len(compacted) > len(output):
        logger.debug("compaction grew output for '%s' — returning original", tool_name)
        return output

    return compacted


# ── Middleware ─────────────────────────────────────────────────────────────────


class ToolOutputSummarizer(AgentMiddleware):
    """Intercepts tool call results and compacts verbose outputs.

    Uses tool-aware strategies:
    - bash/execute/shell: head + tail with error line preservation
    - read_file: head/tail with JSON detection
    - grep/glob/ls: head/tail of match listings
    - fetch_url: JSON reformatting + head/tail fallback
    - all others: generic head/tail on line count

    Configurable at runtime via /summarizer command.
    """

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Any],
    ) -> Any:
        result = handler(request)
        return self._maybe_compact(request, result)

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Any],
    ) -> Any:
        result = await handler(request)
        return self._maybe_compact(request, result)

    def _maybe_compact(self, request: ToolCallRequest, result: Any) -> Any:
        """Compact the tool result if it's a ToolMessage with string content."""
        if not _SUMMARY_CONFIG["enabled"]:
            return result

        from langchain.messages import ToolMessage

        if not isinstance(result, ToolMessage):
            return result

        tool_name = request.tool_call.get("name", "?")
        content = result.content

        if isinstance(content, str) and content:
            compacted = _compact_output(content, tool_name)
            if compacted != content:
                return ToolMessage(
                    content=compacted,
                    tool_call_id=result.tool_call_id,
                    name=result.name,
                    artifact=result.artifact,
                    status=result.status,
                )

        return result


# ── Tool — inspect current config ─────────────────────────────────────────────


@tool
def summary_config(
    tool_name: str | None = None,
) -> str:
    """Inspect the current tool-summarizer configuration.

    Args:
        tool_name: Optional tool name to show per-tune config for
            (e.g. "bash", "read_file", "grep"). If omitted, shows global
            config plus all per-tool overrides.

    Returns:
        Formatted string showing current settings.
    """
    lines: list[str] = ["## Tool Summarizer Configuration\n"]
    enabled = _SUMMARY_CONFIG["enabled"]
    lines.append(f"Enabled: {enabled}")
    lines.append(f"Global threshold: {_SUMMARY_CONFIG['global_threshold_chars']} chars")
    lines.append(f"Global head lines: {_SUMMARY_CONFIG['global_head_lines']}")
    lines.append(f"Global tail lines: {_SUMMARY_CONFIG['global_tail_lines']}")
    lines.append("")

    if tool_name:
        cfg = _get_tool_config(tool_name)
        lines.append(f"### {tool_name}")
        lines.append(f"  threshold: {cfg['threshold']} chars")
        lines.append(f"  head: {cfg['head']} lines")
        lines.append(f"  tail: {cfg['tail']} lines")
    else:
        lines.append("### Per-tool overrides")
        for tname, cfg in sorted(_SUMMARY_CONFIG["per_tool"].items()):
            lines.append(
                f"  {tname}: threshold={cfg['threshold']}, head={cfg['head']}, tail={cfg['tail']}"
            )

    return "\n".join(lines)


# ── Command — /summarizer ─────────────────────────────────────────────────────


async def summarizer_command(args: str) -> str:
    """``/summarizer [on|off|status]`` — control the tool summarizer plugin.

    Sub-commands:
      on       — enable compaction (default)
      off      — disable compaction
      status   — show current configuration (same as calling summary_config tool)
      reset    — reset all config to defaults
      set <tool> threshold=<N> head=<N> tail=<N> — tune per-tool settings
                  e.g. /summarizer set bash threshold=3000 head=30 tail=15
    """
    parts = args.strip().split()
    if not parts:
        # Show status by default
        return await _do_status()

    cmd = parts[0].lower()

    if cmd == "on":
        _SUMMARY_CONFIG["enabled"] = True
        return "✅ Tool summarizer enabled."
    if cmd == "off":
        _SUMMARY_CONFIG["enabled"] = False
        return "⏸️  Tool summarizer disabled."
    if cmd == "status":
        return await _do_status()
    if cmd == "reset":
        _SUMMARY_CONFIG.clear()
        _SUMMARY_CONFIG.update(
            {
                "enabled": True,
                "global_threshold_chars": 2000,
                "global_head_lines": 15,
                "global_tail_lines": 10,
                "per_tool": {},
            }
        )
        return "🔄 Tool summarizer reset to defaults."
    if cmd == "set" and len(parts) >= 2:
        return await _do_set(parts[1], parts[2:])

    return (
        "Usage: /summarizer [on|off|status|reset|set <tool> <key=value>...]\n"
        "Example: /summarizer set bash threshold=3000 head=30 tail=15"
    )


async def _do_status() -> str:
    """Show current configuration as formatted text."""
    lines: list[str] = ["## Tool Summarizer - Status\n"]
    lines.append(f"Enabled: {'✅' if _SUMMARY_CONFIG['enabled'] else '⏸️'}")
    lines.append(f"Global threshold: {_SUMMARY_CONFIG['global_threshold_chars']} chars")
    lines.append(f"Global head lines: {_SUMMARY_CONFIG['global_head_lines']}")
    lines.append(f"Global tail lines: {_SUMMARY_CONFIG['global_tail_lines']}")
    lines.append("")
    if _SUMMARY_CONFIG["per_tool"]:
        lines.append("### Per-tool overrides")
        for tname, cfg in sorted(_SUMMARY_CONFIG["per_tool"].items()):
            lines.append(
                f"  [{tname}] threshold={cfg.get('threshold', 'global')}, "
                f"head={cfg.get('head', 'global')}, "
                f"tail={cfg.get('tail', 'global')}"
            )
    else:
        lines.append(
            "No per-tool overrides configured — all tools use global defaults."
        )
    return "\n".join(lines)


async def _do_set(tool_name: str, kv_pairs: list[str]) -> str:
    """Update per-tool config from ``key=value`` pairs."""
    if tool_name not in _SUMMARY_CONFIG["per_tool"]:
        _SUMMARY_CONFIG["per_tool"][tool_name] = {}

    updates: list[str] = []
    for pair in kv_pairs:
        if "=" not in pair:
            continue
        key, val = pair.split("=", 1)
        key = key.strip().lower()
        try:
            val_int = int(val)
        except ValueError:
            return f"⚠️  Invalid value for {key}: expected integer, got '{val}'."

        if key in ("threshold", "head", "tail"):
            _SUMMARY_CONFIG["per_tool"][tool_name][key] = val_int
            updates.append(f"{key}={val_int}")
        else:
            return f"⚠️  Unknown setting '{key}'. Valid keys: threshold, head, tail."

    if updates:
        return (
            f"✅ Updated [{tool_name}]: {', '.join(updates)}\n"
            "Use `/summarizer status` to verify."
        )
    return "⚠️  No valid settings provided. Use: threshold=<N> head=<N> tail=<N>"


# ── Entry point ───────────────────────────────────────────────────────────────


def register() -> dict[str, Any]:
    """Return the plugin spec for nova-tool-summarizer."""
    return {
        "name": "nova-tool-summarizer",
        "version": "0.1.0",
        "description": (
            "Compacts verbose tool outputs (bash, read_file, grep, glob, etc.) "
            "using tool-aware strategies to save LLM context tokens."
        ),
        "tools": [summary_config],
        "commands": [
            {
                "name": "summarizer",
                "description": "Control tool output compaction (/summarizer on|off|status|reset|set)",
                "handler": summarizer_command,
            },
        ],
        "middleware": [
            {
                "instance": ToolOutputSummarizer(),
                "slot": "before_shell",
            },
        ],
        "subagents": [],
    }

"""Dynamic memory tiers — USER.md & MEMORY.md auto-maintenance.

This module implements the "Dynamic Memory Tiers" pillar of the Nova system.
It creates and maintains two separate memory files alongside the existing
``agent.md``:

    ~/.nova/{assistant_id}/
    ├── agent.md     # Existing — general preferences
    ├── USER.md      # NEW — user modeling (personality, style, communication)
    └── MEMORY.md    # NEW — session cross-cutting memory (decisions, patterns, facts)

Files are automatically compacted when they exceed ``MAX_MEMORY_CHARS`` using
LLM-based summarization (reusing the ``summarize_conversation`` pattern from
``compaction.py``).
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

logger = logging.getLogger("nova.hermes.memory_tiers")


def _emit_memory_event(message: str, icon: str = "📝") -> None:
    """Surface a memory-tier note without printing to the console.

    These writes run inside Hermes's *out-of-band* review, so a direct
    ``console.print`` here bypasses the UI event stream and corrupts the Textual
    TUI (it overlaps the input box). Instead we append to the shared Nova event
    buffer, which ``iterate_agent_events`` drains into a ``ContextMessage`` that
    both the Rich console and the TUI render. Best-effort — a memory write must
    never fail because its notice couldn't be shown.
    """
    try:
        from novacode_cli.hermes.middleware import nova_event_log

        nova_event_log.append(("nova_memory", icon, "dim", message))
    except Exception:  # noqa: BLE001
        logger.debug("memory event (not surfaced): %s", message)

# Maximum characters per memory file before compaction (~3K tokens at 4 chars/token).
# Matches the existing MAX_MEMORY_CHARS from agent_memory.py.
MAX_MEMORY_CHARS = 12_000
_MEMORY_TRUNCATION_NOTICE = (
    "\n\n... [older history truncated — only recent entries shown]"
)

# ── Default templates ──────────────────────────────────────────────────────

DEFAULT_USER_MD = """# USER.md — User Model

This file captures the user's personality, preferences, communication style,
and working patterns. It persists across sessions so the agent can provide
consistent, personalized assistance.

## Communication Style
- (auto-detected)

## Preferred Workflows
- (auto-detected)

## Technical Preferences
- (auto-detected)

## Known Frustrations
- (auto-detected)
"""

DEFAULT_MEMORY_MD = """# MEMORY.md — Cross-Session Memory

This file stores decisions, patterns, facts, and lessons learned across
sessions. Unlike agent.md (preferences) and USER.md (user model), this file
focuses on actionable memory: things the agent learned by doing.

## Architecture Decisions
- (captured during reviews)

## Reusable Patterns
- (captured during reviews)

## Key Facts Learned
- (captured during reviews)
"""


# ── Public API ─────────────────────────────────────────────────────────────


def ensure_memory_tiers(agent_dir: Path) -> None:
    """Create USER.md and MEMORY.md with default content if they don't exist.

    Args:
        agent_dir: Path to the agent directory (``~/.nova/{assistant_id}/``).
    """
    agent_dir.mkdir(parents=True, exist_ok=True)

    user_md = agent_dir / "USER.md"
    if not user_md.exists():
        user_md.write_text(DEFAULT_USER_MD, encoding="utf-8")
        _emit_memory_event(f"Created USER.md at {user_md}")

    memory_md = agent_dir / "MEMORY.md"
    if not memory_md.exists():
        memory_md.write_text(DEFAULT_MEMORY_MD, encoding="utf-8")
        _emit_memory_event(f"Created MEMORY.md at {memory_md}")


def compact_memory_file(path: Path, max_chars: int = MAX_MEMORY_CHARS) -> bool:
    """Compact a memory file by keeping most recent entries.

    When a file exceeds the limit, this method truncates it by keeping the
    last ``max_chars // 2`` characters (most recent entries) and prepending
    a truncation notice.

    Args:
        path: Path to the memory file to compact.
        max_chars: Maximum allowed characters (default: 12_000).

    Returns:
        True if compaction was performed, False otherwise.
    """
    if not path.exists():
        return False

    content = path.read_text(encoding="utf-8")
    if len(content) <= max_chars:
        return False

    # Keep last half (most recent entries)
    keep_chars = max_chars // 2

    # Find a good break point (near a newline) to avoid cutting mid-line
    start_pos = max(0, len(content) - keep_chars)
    search_start = max(0, start_pos - 200)
    newline_pos = content.find("\n", search_start)

    if newline_pos != -1 and newline_pos < start_pos + 200:
        start_pos = newline_pos + 1

    # Find section header to ensure we don't start mid-section
    header_pos = content.rfind("\n## ", 0, start_pos)
    if header_pos != -1 and header_pos > start_pos - 500:
        start_pos = header_pos

    truncated = f"{_MEMORY_TRUNCATION_NOTICE}\n\n" + content[start_pos:]

    # Guard: don't write if compaction would grow file
    if len(truncated) >= len(content):
        return False
    path.write_text(truncated, encoding="utf-8")

    _emit_memory_event(
        f"Compacted {path.name} ({len(content)} → {len(truncated)} chars)",
        icon="📦",
    )
    return True


def update_user_memory(agent_dir: Path, new_content: str) -> None:
    """Append or update entries in USER.md.

    If ``new_content`` is a complete section (starts with ``## ``), it will
    replace any existing section with the same heading. Otherwise it appends
    as a bullet point.

    Args:
        agent_dir: Path to the agent directory.
        new_content: Content to add to USER.md.
    """
    user_md = agent_dir / "USER.md"
    if not user_md.exists():
        user_md.write_text(DEFAULT_USER_MD, encoding="utf-8")

    content = user_md.read_text(encoding="utf-8")

    # If it's a section header, try to replace existing section
    if new_content.startswith("## "):
        section_name = new_content.split("\n")[0].strip()
        if section_name in content:
            # Replace existing section content
            lines = content.split("\n")
            new_lines: list[str] = []
            in_section = False
            section_found = False
            i = 0
            while i < len(lines):
                line = lines[i]
                if line.strip() == section_name:
                    in_section = True
                    section_found = True
                    new_lines.append(line)
                    # Add new section content (skip the header line itself)
                    for sub_line in new_content.split("\n")[1:]:
                        new_lines.append(sub_line)
                    i += 1
                elif in_section:
                    # Check if we've reached the next section
                    if line.startswith("## ") or (
                        line.startswith("# ") and not line.startswith("##")
                    ):
                        in_section = False
                        new_lines.append(line)
                    # else skip old section content
                    i += 1
                else:
                    new_lines.append(line)
                    i += 1

            if section_found:
                user_md.write_text("\n".join(new_lines), encoding="utf-8")
                _emit_memory_event(f"Updated section in USER.md: {section_name}")
                return

    # Append as new section or bullets
    content += "\n" + new_content
    user_md.write_text(content, encoding="utf-8")
    _emit_memory_event("Appended to USER.md")


def update_session_memory(agent_dir: Path, session_summary: str) -> None:
    """Write session memory to MEMORY.md.

    Prepends the session summary to MEMORY.md so the most recent session
    appears first.

    Args:
        agent_dir: Path to the agent directory.
        session_summary: Summary of the session to persist.
    """
    memory_md = agent_dir / "MEMORY.md"
    if not memory_md.exists():
        memory_md.write_text(DEFAULT_MEMORY_MD, encoding="utf-8")

    content = memory_md.read_text(encoding="utf-8")

    # Insert after the header (before the first ## section)
    header_end = content.find("\n## ")
    if header_end == -1:
        header_end = len(content)

    before = content[:header_end]
    after = content[header_end:]

    # Create a timestamped entry
    timestamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
    entry = f"\n## Session — {timestamp}\n\n{session_summary}\n"

    new_content = before + entry + after
    memory_md.write_text(new_content, encoding="utf-8")
    _emit_memory_event("Updated MEMORY.md")

    # Compact if needed
    compact_memory_file(memory_md)


def parse_review_response(response_content: str) -> dict[str, str]:
    """Extract structured data from LLM review response.

    Expected format (XML tags):
        <user_updates>
        ## Communication Style
        - Prefers concise bullet points
        </user_updates>

        <session_memory>
        - Discovered that pytest with -x flag is preferred for quick feedback
        - User rejected async/await patterns in favor of explicit sync code
        </session_memory>

    Args:
        response_content: The raw response content from the LLM.

    Returns:
        Dictionary with 'user_updates' and 'session_memory' keys.
    """
    result = {"user_updates": "", "session_memory": ""}

    if not response_content:
        return result

    # Extract user model updates (all blocks)
    user_matches = re.findall(
        r"<user_updates>(.*?)</user_updates>",
        response_content,
        re.DOTALL | re.IGNORECASE,
    )
    if user_matches:
        result["user_updates"] = "\n".join(m.strip() for m in user_matches)

    # Extract session memory (all blocks)
    memory_matches = re.findall(
        r"<session_memory>(.*?)</session_memory>",
        response_content,
        re.DOTALL | re.IGNORECASE,
    )
    if memory_matches:
        result["session_memory"] = "\n".join(m.strip() for m in memory_matches)

    # Fallback: if no XML tags but content exists, treat as session memory
    if (
        not result["user_updates"]
        and not result["session_memory"]
        and response_content.strip()
    ):
        result["session_memory"] = response_content.strip()

    return result


def update_from_review(agent_dir: Path, user_updates: str, session_memory: str) -> None:
    """Apply review learnings to USER.md and MEMORY.md.

    Args:
        agent_dir: Path to the agent directory.
        user_updates: Content to add to USER.md (usually a section with updates).
        session_memory: Content to add to MEMORY.md as a session review.
    """
    if user_updates:
        update_user_memory(agent_dir, user_updates)

    if session_memory:
        memory_md = agent_dir / "MEMORY.md"
        if not memory_md.exists():
            memory_md.write_text(DEFAULT_MEMORY_MD, encoding="utf-8")

        content = memory_md.read_text(encoding="utf-8")

        # Insert after header
        header_end = content.find("\n## ")
        if header_end == -1:
            header_end = len(content)

        before = content[:header_end]
        after = content[header_end:]

        timestamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
        entry = f"\n## Review — {timestamp}\n\n{session_memory}\n"

        new_content = before + entry + after
        memory_md.write_text(new_content, encoding="utf-8")
        _emit_memory_event("Applied review to MEMORY.md")

        # Compact if needed
        compact_memory_file(memory_md)

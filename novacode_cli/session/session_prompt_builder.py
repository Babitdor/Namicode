"""Prompt construction for session continuation.

This module builds prompts in the correct order as specified in Task.md:
1. Static system instructions
2. Nova.md contents
3. memory.md contents
4. Workspace state (git + FS)
5. Messages from recent.jsonl
6. Continuation instruction
"""

from pathlib import Path
from typing import Any

from langchain_core.messages import BaseMessage, SystemMessage

from novacode_cli.session.session_persistence import SessionData
from novacode_cli.tracking.workspace_anchoring import format_workspace_state_for_prompt

CONTINUATION_INSTRUCTION = """## Continuation Mode

You are continuing from a previous session. The information above represents the current state:
- Nova.md contains the authoritative project rules (ALWAYS follow these)
- Session memory contains what was accomplished and learned
- Workspace state shows the CURRENT filesystem and git status
- Recent messages show the last few turns of conversation

**Important:**
- The filesystem has been re-scanned and reflects CURRENT reality
- Nova.md rules are AUTHORITATIVE - they override session memory
- If Nova.md has changed, use the NEW rules
- Do not hallucinate file contents or git state - rely on what's shown above

**Your task:**
- Review the current goal and session memory
- Check if the task is complete, blocked, or can continue
- If complete: report status and summarize what was done
- If blocked: explain the blocker clearly
- If continuing: proceed with the next logical step

Continue working on the task from the current state."""


def build_continuation_prompt(
    session_data: SessionData,
    system_prompt: str,
    Nova_md_content: str | None = None,
    workspace_state: dict[str, Any] | None = None,
) -> list[BaseMessage]:
    """Build a complete continuation prompt in the correct order.

    Order per Task.md:
    1. Static system instructions
    2. Nova.md contents
    3. memory.md contents
    4. Workspace state (git + FS)
    5. Messages from recent.jsonl
    6. Continuation instruction

    Args:
        session_data: Loaded session data
        system_prompt: Base system prompt (static instructions)
        Nova_md_content: Content of Nova.md (if available)
        workspace_state: Current workspace state from scan_workspace()

    Returns:
        List of messages ready to send to the agent
    """
    # Start with system message containing all context
    system_parts = []

    # 1. Static system instructions
    system_parts.append(system_prompt)

    # 2. Nova.md contents (project rules - AUTHORITATIVE)
    if Nova_md_content:
        system_parts.append("\n\n## Project Rules (Nova.md)\n\n" + Nova_md_content)

    # 3. memory.md contents (session memory - declarative facts)
    if session_data.memory:
        system_parts.append("\n\n## Session Memory\n\n" + session_data.memory)
    else:
        system_parts.append(
            "\n\n## Session Memory\n\n(No session memory available - this is a fresh start)"
        )

    # 4. Workspace state (current git + filesystem)
    if workspace_state:
        workspace_section = format_workspace_state_for_prompt(workspace_state)
        system_parts.append("\n\n" + workspace_section)

    # 5. Task state from meta
    task_section = _format_task_state(session_data)
    system_parts.append("\n\n" + task_section)

    # 6. Continuation instruction
    system_parts.append("\n\n" + CONTINUATION_INSTRUCTION)

    # Build final system message
    full_system_message = "\n".join(system_parts)

    # Start messages list with system message
    messages: list[BaseMessage] = [SystemMessage(content=full_system_message)]

    # 7. Add recent messages from conversation (if any)
    # Filter out system messages from recent history (we have a new system message).
    # Apply a token-budget guard to avoid exceeding context limits when tool outputs
    # or file reads are large — always prefer the most recent messages.
    MAX_RECENT_TOKENS = 30_000
    non_system = [msg for msg in session_data.messages if not isinstance(msg, SystemMessage)]
    budget_messages: list[BaseMessage] = []
    token_count = 0
    for msg in reversed(non_system):
        est = len(str(msg.content)) // 3
        if token_count + est > MAX_RECENT_TOKENS:
            break
        budget_messages.insert(0, msg)
        token_count += est
    messages.extend(budget_messages)

    return messages


def _format_task_state(session_data: SessionData) -> str:
    """Format task state from session metadata.

    Args:
        session_data: Session data with metadata

    Returns:
        Formatted task state section
    """
    meta = session_data.meta

    lines = [
        "## Task State",
        "",
    ]

    if meta.current_task:
        lines.append(f"**Current Task:** {meta.current_task}")
    else:
        lines.append("**Current Task:** (Not specified)")

    lines.append(f"**Task Status:** {meta.task_status}")

    if meta.task_status == "blocked" and meta.blocked_reason:
        lines.append(f"**Blocked Reason:** {meta.blocked_reason}")

    if meta.next_step_hint:
        lines.append(f"**Next Step Hint:** {meta.next_step_hint}")

    lines.append("")

    return "\n".join(lines)


def load_Nova_md(project_root: Path | None) -> str | None:
    """Load Nova.md or .Nova/agent.md from project root.

    Args:
        project_root: Path to project root

    Returns:
        Nova.md content or None if not found
    """
    if not project_root:
        return None

    # Try Nova.md first
    Nova_md_paths = [
        project_root / "Nova.md",
        project_root / "CLAUDE.md",
        project_root / ".Nova" / "Nova.md",
        project_root / ".claude" / "CLAUDE.md",
    ]

    for path in Nova_md_paths:
        if path.exists():
            try:
                return path.read_text(encoding="utf-8")
            except OSError:
                continue

    return None

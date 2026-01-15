"""Session restoration and validation for namicode-cli.

This module provides functionality to restore sessions and validate
compatibility with the current environment.
"""

from datetime import datetime
from pathlib import Path

from namicode_cli.session.session_persistence import SessionData, SessionManager, SessionMeta


def validate_session_compatibility(
    meta: SessionMeta,
    current_project_root: Path | None = None,
) -> tuple[bool, list[str]]:
    """Check if a session is compatible with the current environment.

    Args:
        meta: Session metadata to validate
        current_project_root: Current project root path

    Returns:
        Tuple of (is_valid, list of warning messages)
    """
    warnings: list[str] = []

    # Check project root match
    if meta.project_root and current_project_root:
        if meta.project_root != str(current_project_root):
            warnings.append(
                f"Session was created in different project: {meta.project_root}"
            )

    # Check repo hash (git commit) - only warn, don't block
    if meta.project_root and meta.repo_hash and current_project_root:
        manager = SessionManager()
        current_hash = manager._compute_repo_hash(current_project_root)
        if current_hash and current_hash != meta.repo_hash:
            warnings.append(
                "Repository has changed since session was saved. "
                "Some file references may be outdated."
            )

    # Check NAMI.md checksum - only warn
    if meta.project_root and meta.nami_md_checksum and current_project_root:
        manager = SessionManager()
        current_checksum = manager._compute_nami_md_checksum(current_project_root)
        if current_checksum and current_checksum != meta.nami_md_checksum:
            warnings.append(
                "NAMI.md / agent.md has changed since session was saved. "
                "New instructions will be used."
            )

    # Sessions are always valid (warnings don't block continuation)
    return True, warnings


def format_session_age(iso_timestamp: str) -> str:
    """Format a session timestamp as a human-readable age.

    Args:
        iso_timestamp: ISO format timestamp string

    Returns:
        Human-readable age string (e.g., "2 hours ago", "yesterday")
    """
    try:
        # Parse ISO timestamp
        if iso_timestamp.endswith("Z"):
            iso_timestamp = iso_timestamp[:-1] + "+00:00"
        dt = datetime.fromisoformat(iso_timestamp)
        now = datetime.now(dt.tzinfo)
        delta = now - dt

        seconds = int(delta.total_seconds())
        if seconds < 60:
            return "just now"
        if seconds < 3600:
            minutes = seconds // 60
            return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
        if seconds < 86400:
            hours = seconds // 3600
            return f"{hours} hour{'s' if hours != 1 else ''} ago"
        if seconds < 604800:
            days = seconds // 86400
            if days == 1:
                return "yesterday"
            return f"{days} days ago"

        weeks = seconds // 604800
        return f"{weeks} week{'s' if weeks != 1 else ''} ago"
    except (ValueError, TypeError):
        return "unknown"


def format_session_summary(meta: SessionMeta) -> str:
    """Format a session for display in session list.

    Args:
        meta: Session metadata

    Returns:
        Formatted summary string
    """
    age = format_session_age(meta.last_active)
    project = Path(meta.project_root).name if meta.project_root else "no project"
    model = meta.model_name or "unknown model"
    msg_count = meta.message_count

    return (
        f"[bold]{meta.session_id[:8]}[/bold] - {project} ({model})\n"
        f"  {msg_count} messages, {age}"
    )


def build_session_summary_message(messages: list, max_length: int = 500) -> str:
    """Build a compressed summary of conversation for long sessions.

    This is used when a session has too many messages to inject all of them
    into context. The summary provides key context points.

    Args:
        messages: List of conversation messages
        max_length: Maximum length of summary

    Returns:
        Summary string
    """
    if not messages:
        return "No previous conversation."

    # Count message types
    user_count = sum(1 for m in messages if m.__class__.__name__ == "HumanMessage")
    ai_count = sum(1 for m in messages if m.__class__.__name__ == "AIMessage")
    tool_count = sum(1 for m in messages if m.__class__.__name__ == "ToolMessage")

    summary_parts = [
        f"[Continuing session with {len(messages)} messages: "
        f"{user_count} user, {ai_count} assistant, {tool_count} tool results]"
    ]

    # Extract key points from recent messages
    recent = messages[-10:] if len(messages) > 10 else messages

    for msg in recent:
        msg_type = msg.__class__.__name__
        content = str(msg.content)[:200] if msg.content else ""

        if msg_type == "HumanMessage" and content:
            # Include recent user messages
            summary_parts.append(f"User: {content}")
        elif msg_type == "AIMessage" and content and not content.startswith("["):
            # Include AI responses (skip tool call markers)
            summary_parts.append(f"Assistant: {content[:100]}...")

    summary = "\n".join(summary_parts)
    if len(summary) > max_length:
        summary = summary[:max_length] + "..."

    return summary


def restore_session(
    session_manager: SessionManager,
    session_id: str | None = None,
    project_root: Path | None = None,
) -> tuple[SessionData, list[str]] | None:
    """Restore a session from disk.

    Args:
        session_manager: SessionManager instance
        session_id: Specific session ID to restore, or None for latest
        project_root: Current project root for validation

    Returns:
        Tuple of (SessionData, warnings) or None if not found
    """
    # Find session to restore
    if session_id:
        session_data = session_manager.load_session(session_id)
        if not session_data:
            return None
    else:
        # Get latest session (optionally filtered by project)
        latest = session_manager.get_latest_session(project_root)
        if not latest:
            return None
        session_data = session_manager.load_session(latest.session_id)
        if not session_data:
            return None

    # Validate compatibility
    _is_valid, warnings = validate_session_compatibility(
        session_data.meta,
        current_project_root=project_root,
    )

    return session_data, warnings

"""File Tracker Middleware for enforcing read-before-edit and tracking file operations.

This middleware provides:
1. Hard enforcement of read-before-edit (rejects edits for unread files)
2. File content caching for edit verification
3. Session-level file operation tracking
4. Smart tool result truncation to prevent context overflow
"""

import hashlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, NotRequired, TypedDict

from langchain.agents.middleware.types import (
    AgentMiddleware,
    AgentState,
    ModelRequest,
    ModelResponse,
)
from langchain.tools import BaseTool
from langchain.tools.tool_node import ToolCallRequest
from langchain_core.messages import ToolMessage
from langgraph.types import Command


# ============================================================================
# Data Structures
# ============================================================================


@dataclass
class FileReadRecord:
    """Record of a file read operation."""

    path: str
    """Absolute path to the file."""

    content_hash: str
    """SHA-256 hash of the file content when read."""

    line_count: int
    """Number of lines in the file."""

    char_count: int
    """Number of characters in the file."""

    read_at: str
    """ISO timestamp when the file was read."""

    offset: int = 0
    """Starting line offset (0-based)."""

    limit: int | None = None
    """Number of lines read (None = full file)."""

    content_preview: str = ""
    """First 500 chars of content for context."""


@dataclass
class FileWriteRecord:
    """Record of a file write operation."""

    path: str
    """Absolute path to the file."""

    operation: str
    """Type of operation: 'write', 'edit', 'create'."""

    content_hash: str
    """SHA-256 hash of the new content."""

    written_at: str
    """ISO timestamp when the file was written."""

    old_content_hash: str | None = None
    """Hash of content before edit (for edit operations)."""

    lines_changed: int = 0
    """Number of lines affected."""


@dataclass
class SessionFileTracker:
    """Tracks all file operations in the current session."""

    files_read: dict[str, FileReadRecord] = field(default_factory=dict)
    """Map of file path -> most recent read record."""

    files_written: dict[str, list[FileWriteRecord]] = field(default_factory=dict)
    """Map of file path -> list of write records (history)."""

    read_order: list[str] = field(default_factory=list)
    """Order in which files were first read."""

    write_order: list[str] = field(default_factory=list)
    """Order in which files were first written."""

    total_reads: int = 0
    """Total number of read operations."""

    total_writes: int = 0
    """Total number of write operations."""

    rejected_edits: int = 0
    """Number of edit operations rejected for unread files."""

    def has_read_file(self, path: str) -> bool:
        """Check if a file has been read in this session."""
        return path in self.files_read

    def get_read_record(self, path: str) -> FileReadRecord | None:
        """Get the read record for a file."""
        return self.files_read.get(path)

    def record_read(
        self,
        path: str,
        content: str,
        offset: int = 0,
        limit: int | None = None,
    ) -> FileReadRecord:
        """Record a file read operation."""
        content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]
        lines = content.split("\n")

        record = FileReadRecord(
            path=path,
            content_hash=content_hash,
            line_count=len(lines),
            char_count=len(content),
            read_at=datetime.now(timezone.utc).isoformat(),
            offset=offset,
            limit=limit,
            content_preview=content[:500] if content else "",
        )

        # Track first read order
        if path not in self.files_read:
            self.read_order.append(path)

        self.files_read[path] = record
        self.total_reads += 1

        return record

    def record_write(
        self,
        path: str,
        content: str,
        operation: str = "write",
        old_content: str | None = None,
        lines_changed: int = 0,
    ) -> FileWriteRecord:
        """Record a file write operation."""
        content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]
        old_hash = (
            hashlib.sha256(old_content.encode()).hexdigest()[:16]
            if old_content
            else None
        )

        record = FileWriteRecord(
            path=path,
            operation=operation,
            content_hash=content_hash,
            written_at=datetime.now(timezone.utc).isoformat(),
            old_content_hash=old_hash,
            lines_changed=lines_changed,
        )

        # Track first write order
        if path not in self.files_written:
            self.write_order.append(path)
            self.files_written[path] = []

        self.files_written[path].append(record)
        self.total_writes += 1

        return record

    def record_rejected_edit(self) -> None:
        """Record a rejected edit attempt."""
        self.rejected_edits += 1

    def get_session_summary(self) -> str:
        """Get a summary of file operations in this session."""
        lines = ["## Session File Operations Summary\n"]

        if self.files_read:
            lines.append(f"### Files Read ({len(self.files_read)})")
            for path in self.read_order[-10:]:  # Last 10 reads
                record = self.files_read[path]
                lines.append(f"- `{path}` ({record.line_count} lines)")
            if len(self.read_order) > 10:
                lines.append(f"  ... and {len(self.read_order) - 10} more")
            lines.append("")

        if self.files_written:
            lines.append(f"### Files Modified ({len(self.files_written)})")
            for path in self.write_order[-10:]:  # Last 10 writes
                records = self.files_written[path]
                ops = [r.operation for r in records]
                lines.append(f"- `{path}` ({', '.join(ops)})")
            if len(self.write_order) > 10:
                lines.append(f"  ... and {len(self.write_order) - 10} more")
            lines.append("")

        lines.append(f"**Stats**: {self.total_reads} reads, {self.total_writes} writes")
        if self.rejected_edits > 0:
            lines.append(f"**Rejected edits** (unread files): {self.rejected_edits}")

        return "\n".join(lines)


# ============================================================================
# Module-level singleton
# ============================================================================

_session_tracker: SessionFileTracker | None = None


def get_session_tracker() -> SessionFileTracker:
    """Get or create the session file tracker."""
    global _session_tracker
    if _session_tracker is None:
        _session_tracker = SessionFileTracker()
    return _session_tracker


def reset_session_tracker() -> None:
    """Reset the session tracker (for new sessions)."""
    global _session_tracker
    _session_tracker = None


# ============================================================================
# Tool Result Truncation
# ============================================================================

# Maximum characters for different tool result types
RESULT_LIMITS = {
    "read_file": 50000,  # ~12.5k tokens
    "grep": 20000,  # ~5k tokens
    "glob": 10000,  # ~2.5k tokens
    "ls": 8000,  # ~2k tokens
    "shell": 30000,  # ~7.5k tokens
    "execute": 30000,  # ~7.5k tokens
    "web_search": 15000,  # ~3.75k tokens
    "fetch_url": 40000,  # ~10k tokens
    "default": 20000,  # ~5k tokens
}


def truncate_tool_result(
    tool_name: str,
    result: str,
    custom_limit: int | None = None,
) -> tuple[str, bool]:
    """Truncate a tool result if it exceeds the limit.

    Args:
        tool_name: Name of the tool that produced the result.
        result: The tool result string.
        custom_limit: Optional custom character limit.

    Returns:
        Tuple of (possibly truncated result, was_truncated).
    """
    limit = custom_limit or RESULT_LIMITS.get(tool_name, RESULT_LIMITS["default"])

    if len(result) <= limit:
        return result, False

    # Calculate truncation point
    truncate_at = limit - 500  # Leave room for truncation message

    # Try to truncate at a line boundary
    last_newline = result.rfind("\n", 0, truncate_at)
    if last_newline > truncate_at * 0.8:  # If reasonable line boundary found
        truncate_at = last_newline

    truncated = result[:truncate_at]

    # Add truncation notice with guidance
    chars_removed = len(result) - truncate_at
    lines_removed = result[truncate_at:].count("\n")

    truncation_msg = f"""

... [TRUNCATED: {chars_removed:,} characters, ~{lines_removed} lines removed]

**To see more content:**
- Use pagination: `read_file(path, offset={truncated.count(chr(10))}, limit=200)`
- Use grep to search for specific patterns
- Use glob to find specific files"""

    return truncated + truncation_msg, True


# ============================================================================
# State Schema
# ============================================================================


class FileTrackerState(AgentState):
    """State schema for file tracker middleware."""

    _file_tracker: NotRequired[SessionFileTracker]
    """The session file tracker instance."""


# ============================================================================
# Middleware Implementation
# ============================================================================

FILE_TRACKER_SYSTEM_PROMPT = """## File Operation Rules (ENFORCED)

**CRITICAL: Read-Before-Edit Rule**
You MUST read a file before editing it. The system tracks all file reads and will REJECT
edit operations on files you haven't read in this session.

**Why this matters:**
- Prevents editing the wrong file or wrong location
- Ensures you have current file content before making changes
- Catches stale edits if the file changed since you last saw it

**File Operation Best Practices:**
1. **Always read first**: Before any edit_file or write_file (to existing file), use read_file
2. **Use pagination for large files**: `read_file(path, limit=100)` for initial scan
3. **Verify before edit**: Check the content you want to replace actually exists
4. **Track your changes**: The system logs all file operations for the session

**If an edit is rejected:**
- Read the file first: `read_file("/path/to/file")`
- Then retry your edit with the exact string from the file content
"""


class FileTrackerMiddleware(AgentMiddleware):
    """Middleware that enforces read-before-edit and tracks file operations.

    This middleware:
    1. Tracks all file read operations
    2. Enforces that files must be read before editing
    3. Truncates large tool results to prevent context overflow
    4. Provides session-level file operation summary
    5. Injects file operation rules into the system prompt

    Args:
        enforce_read_before_edit: Whether to reject edits on unread files (default: True).
        truncate_results: Whether to truncate large tool results (default: True).
        include_system_prompt: Whether to inject file operation rules (default: True).
        tracker: Optional custom SessionFileTracker (uses singleton if None).
    """

    state_schema = FileTrackerState

    def __init__(
        self,
        enforce_read_before_edit: bool = True,
        truncate_results: bool = True,
        include_system_prompt: bool = True,
        tracker: SessionFileTracker | None = None,
    ) -> None:
        super().__init__()
        self.enforce_read_before_edit = enforce_read_before_edit
        self.truncate_results = truncate_results
        self.include_system_prompt = include_system_prompt
        self._tracker = tracker
        self.tools: list[BaseTool] = []  # No additional tools

    @property
    def tracker(self) -> SessionFileTracker:
        """Get the session tracker."""
        if self._tracker is not None:
            return self._tracker
        return get_session_tracker()

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        """Inject file operation rules into the system prompt."""
        if self.include_system_prompt:
            system_prompt = (
                request.system_prompt + "\n\n" + FILE_TRACKER_SYSTEM_PROMPT
                if request.system_prompt
                else FILE_TRACKER_SYSTEM_PROMPT
            )
            return handler(request.override(system_prompt=system_prompt))
        return handler(request)

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        """(async) Inject file operation rules into the system prompt."""
        if self.include_system_prompt:
            system_prompt = (
                request.system_prompt + "\n\n" + FILE_TRACKER_SYSTEM_PROMPT
                if request.system_prompt
                else FILE_TRACKER_SYSTEM_PROMPT
            )
            return await handler(request.override(system_prompt=system_prompt))
        return await handler(request)

    def _check_edit_allowed(self, request: ToolCallRequest) -> ToolMessage | None:
        """Check if an edit operation is allowed (file has been read).

        Returns ToolMessage with rejection if not allowed, None if allowed.
        """
        tool_call = request.tool_call
        tool_name = tool_call.get("name", "")
        args = tool_call.get("args", {})

        # Only check edit_file operations
        if tool_name != "edit_file" or not self.enforce_read_before_edit:
            return None

        file_path = args.get("file_path") or args.get("path", "")
        if file_path and not self.tracker.has_read_file(file_path):
            self.tracker.record_rejected_edit()
            return ToolMessage(
                content=(
                    f"**EDIT REJECTED**: File '{file_path}' has not been read in this session.\n\n"
                    f"You must read a file before editing it. This prevents errors from:\n"
                    f"- Editing stale content\n"
                    f"- Using incorrect old_string values\n"
                    f"- Modifying the wrong file\n\n"
                    f'**To fix**: First run `read_file("{file_path}")`, then retry your edit.'
                ),
                tool_call_id=tool_call.get("id", ""),
            )

        return None

    def _track_and_truncate(
        self, request: ToolCallRequest, result: ToolMessage | Command
    ) -> ToolMessage | Command:
        """Track file operations and optionally truncate results."""
        tool_call = request.tool_call
        tool_name = tool_call.get("name", "")
        args = tool_call.get("args", {})

        # Get content from result
        if isinstance(result, ToolMessage):
            content = result.content
        elif isinstance(result, Command):
            # For Command results, we don't modify
            return result
        else:
            return result

        # Track read_file operations
        if tool_name == "read_file" and isinstance(content, str) and not content.startswith("Error"):
            file_path = args.get("file_path") or args.get("path", "")
            offset = args.get("offset", 0)
            limit = args.get("limit")
            if file_path:
                self.tracker.record_read(file_path, content, offset, limit)

        # Track write_file operations
        if tool_name == "write_file" and isinstance(content, str) and "success" in content.lower():
            file_path = args.get("file_path") or args.get("path", "")
            new_content = args.get("content", "")
            if file_path:
                self.tracker.record_write(file_path, new_content, operation="write")

        # Track edit_file operations
        if tool_name == "edit_file" and isinstance(content, str) and "success" in content.lower():
            file_path = args.get("file_path") or args.get("path", "")
            if file_path:
                self.tracker.record_write(
                    file_path,
                    args.get("new_string", ""),
                    operation="edit",
                    old_content=args.get("old_string"),
                )

        # Truncate large results
        if self.truncate_results and isinstance(content, str):
            truncated_content, was_truncated = truncate_tool_result(tool_name, content)
            if was_truncated and isinstance(result, ToolMessage):
                return ToolMessage(
                    content=truncated_content,
                    tool_call_id=result.tool_call_id,
                    name=result.name if hasattr(result, 'name') else None,
                )

        return result

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        """Intercept tool calls to enforce read-before-edit and track operations."""
        # Check if edit is allowed
        rejection = self._check_edit_allowed(request)
        if rejection is not None:
            return rejection

        # Execute the tool
        result = handler(request)

        # Track operations and truncate if needed
        return self._track_and_truncate(request, result)

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        """(async) Intercept tool calls to enforce read-before-edit and track operations."""
        # Check if edit is allowed
        rejection = self._check_edit_allowed(request)
        if rejection is not None:
            return rejection

        # Execute the tool
        result = await handler(request)

        # Track operations and truncate if needed
        return self._track_and_truncate(request, result)


# ============================================================================
# Utility Functions
# ============================================================================


def get_files_summary() -> str:
    """Get a summary of file operations for the current session."""
    return get_session_tracker().get_session_summary()


def get_recently_read_files(limit: int = 10) -> list[str]:
    """Get the most recently read file paths."""
    tracker = get_session_tracker()
    return tracker.read_order[-limit:]


def get_modified_files() -> list[str]:
    """Get all files modified in this session."""
    tracker = get_session_tracker()
    return list(tracker.files_written.keys())


def was_file_read(path: str) -> bool:
    """Check if a file was read in this session."""
    return get_session_tracker().has_read_file(path)


__all__ = [
    "FileTrackerMiddleware",
    "SessionFileTracker",
    "FileReadRecord",
    "FileWriteRecord",
    "get_session_tracker",
    "reset_session_tracker",
    "get_files_summary",
    "get_recently_read_files",
    "get_modified_files",
    "was_file_read",
    "truncate_tool_result",
    "RESULT_LIMITS",
]

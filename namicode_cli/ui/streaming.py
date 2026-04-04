"""Streaming constants and helper functions for execution display.

This module contains:
- Tool icons and category mappings
- Internal context keywords for filtering
- Helper functions for activity formatting
"""

from pathlib import Path

from namicode_cli.config.config import COLORS

# Tool icons for display
TOOL_ICONS: dict[str, str] = {
    # File operations
    "read_file": "📖",
    "write_file": "✏️",
    "edit_file": "✂️",
    "ls": "📁",
    "glob": "🔍",
    "grep": "🔎",
    # Serena MCP tools (capitalized names)
    "Read": "📖",
    "Write": "✏️",
    "Edit": "✂️",
    "List": "📁",
    "Glob": "🔍",
    "Grep": "🔎",
    "Search": "🔍",
    # Shell
    "shell": "⚡",
    "execute": "🔧",
    # Web
    "web_search": "🌐",
    "duckduckgo_search": "🦆",
    "fetch_url": "🔗",
    "http_request": "🌐",
    # Task
    "task": "🤖",
    # Todos
    "write_todos": "📋",
    # Server management
    "start_dev_server": "🚀",
    "stop_server": "🛑",
    "list_servers": "📋",
    # Test runner
    "run_tests": "🧪",
    # Memory
    "write_memory": "💾",
    "read_memory": "📖",
    "list_memories": "📑",
    "delete_memory": "🗑️",
    # Code quality
    "lint_code": "🔍",
    "check_types": "🔎",
    "package_info": "📦",
    # Question/Plan
    "ask_question": "❓",
    "exit_plan_mode": "✅",
    # Browser
    "browser_navigate": "🌐",
    "browser_click": "👆",
    "browser_type": "⌨️",
    "browser_screenshot": "📸",
    "browser_query": "❓",
    "browser_get_content": "📄",
    "browser_get_url": "🔗",
    # Recovery
    "list_trash": "🗑️",
    "restore_file": "♻️",
}

# Tool category icons for summary display
TOOL_CATEGORY_ICONS: dict[str, str] = {
    "files_read": "📖",
    "files_written": "✏️",
    "search": "🔎",
    "web": "🌐",
    "shell": "⚡",
    "tests": "🧪",
    "server": "🚀",
    "git": "📊",
    "browser": "🌐",
    "memory": "💾",
    "other": "🔧",
}

# Tool category mapping for summary categorization
TOOL_CATEGORIES: dict[str, str] = {
    # Files read
    "read_file": "files_read",
    "ls": "files_read",
    "glob": "files_read",
    "grep": "files_read",
    # Serena MCP tools (capitalized names)
    "Read": "files_read",
    "List": "files_read",
    "Glob": "files_read",
    "Grep": "files_read",
    "Search": "files_read",
    # Files written
    "write_file": "files_written",
    "edit_file": "files_written",
    # Serena MCP tools (capitalized names)
    "Write": "files_written",
    "Edit": "files_written",
    # Search
    "web_search": "search",
    "duckduckgo_search": "search",
    "docs_search": "search",
    # Web
    "fetch_url": "web",
    "http_request": "web",
    # Recovery
    "list_trash": "recovery",
    "restore_file": "recovery",
    # Shell
    "shell": "shell",
    "execute": "shell",
    "execute_bash": "shell",
    # Tests
    "run_tests": "tests",
    # Server
    "start_dev_server": "server",
    "stop_server": "server",
    "list_servers": "server",
    # Browser
    "browser_navigate": "browser",
    "browser_click": "browser",
    "browser_screenshot": "browser",
    "browser_type": "browser",
    "browser_query": "browser",
    "browser_fill_form": "browser",
    "browser_upload": "browser",
    # Memory
    "write_memory": "memory",
    "read_memory": "memory",
    "list_memories": "memory",
    "delete_memory": "memory",
}

# Category display order for summary
CATEGORY_ORDER = [
    "files_read",
    "files_written",
    "search",
    "web",
    "shell",
    "tests",
    "server",
    "git",
    "browser",
    "memory",
]

# Internal context keywords the LLM writes as scratchpad text before tool calls.
# Matched case-insensitively after stripping any leading markdown heading markers (# ## ###).
# These are not user-facing and should be stripped from display.
INTERNAL_CONTEXT_KEYWORDS = (
    "extracted context",
    "context summary",
    "current goal",
    "current task",
    "task context",
    "planning context",
    "internal context",
    "working context",
    "session intent",
    "session context",
    "session summary",
    "agent context",
    "agent state",
    # LLM-generated project preamble before tool calls (e.g. "**Project:** Nami-Code...")
    "project:",
    "project overview",
)


def format_condensed_activity(activity: dict, max_items: int = 3) -> str:
    """Format a condensed activity summary for display.

    Shows key files/operations in a compact format:
    - File paths: "auth.py, utils.py, +2 more"
    - Categories: "🔎 3 searches • 🌐 2 web"
    """
    parts = []

    # Show file operations with paths (most useful)
    files_read = activity.get("files_read", [])
    if files_read:
        # Get just filenames, not full paths
        filenames = [Path(f).name for f in files_read[:max_items]]
        remaining = len(files_read) - max_items
        if remaining > 0:
            parts.append(f"📖 {', '.join(filenames)}, +{remaining}")
        else:
            parts.append(f"📖 {', '.join(filenames)}")

    files_written = activity.get("files_written", [])
    if files_written:
        filenames = [Path(f).name for f in files_written[:max_items]]
        remaining = len(files_written) - max_items
        if remaining > 0:
            parts.append(f"✏️ {', '.join(filenames)}, +{remaining}")
        else:
            parts.append(f"✏️ {', '.join(filenames)}")

    # Show other categories as counts
    categories = activity.get("categories", {})
    for cat in CATEGORY_ORDER:
        if cat in ("files_read", "files_written"):
            continue  # Already handled above
        count = categories.get(cat, 0)
        if count > 0:
            icon = TOOL_CATEGORY_ICONS.get(cat, "🔧")
            parts.append(f"{icon} {count}")

    # Show errors count
    errors = activity.get("errors", [])
    if errors:
        parts.append(f"❌ {len(errors)}")

    return " • ".join(parts) if parts else "starting..."


def get_tool_icon(tool_name: str) -> str:
    """Get the icon for a tool name."""
    return TOOL_ICONS.get(tool_name, "🔧")


def get_tool_category(tool_name: str) -> str:
    """Get the category for a tool name."""
    return TOOL_CATEGORIES.get(tool_name, "other")


def is_internal_context_text(text: str) -> bool:
    """Check if text is internal context/scratchpad content.

    Normalizes by stripping leading markdown heading markers (# / ## / ###) and
    bold markers (** / __) and whitespace, then checks case-insensitively against
    known internal keywords.
    """
    stripped = text.lstrip()
    heading_stripped = stripped.lstrip("#*_").lstrip()
    return any(
        heading_stripped.lower().startswith(kw)
        for kw in INTERNAL_CONTEXT_KEYWORDS
    )
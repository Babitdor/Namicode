"""Human-in-the-loop interrupt configurations.

This module defines interrupt configurations for tools that require user approval
before execution. Each configuration includes:
- allowed_decisions: What actions the user can take (typically approve/reject)
- description: A function that formats the tool call for the approval prompt

Tool Categories:
- Destructive operations: shell, execute, write_file, edit_file
- External operations: web_search, fetch_url, http_request, browser_automate
- Code execution: execute_in_e2b, run_tests, start_dev_server
- Memory operations: write_memory, create_memory_structure
- User interaction: ask_question
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, TypedDict

try:
    from typing import NotRequired
except ImportError:
    from typing_extensions import NotRequired

from langchain.agents.middleware import InterruptOnConfig
from langchain.agents.middleware.types import AgentState
from langchain.messages import ToolCall
from langgraph.runtime import Runtime


class InterruptConfig(TypedDict):
    """Configuration for a human-in-the-loop interrupt.

    Attributes:
        allowed_decisions: List of allowed user decisions (e.g., ["approve", "edit", "reject"])
        description: Function to format the tool call for the approval prompt
        args_schema: Optional JSON schema for edit validation (enables inline arg editing)
    """

    allowed_decisions: list[str]
    description: callable  # type: ignore[valid-type]
    args_schema: NotRequired[dict[str, Any]]


# ---------------------------------------------------------------------------
# Description Formatter Functions
# ---------------------------------------------------------------------------


def _format_shell_description(
    tool_call: ToolCall, _state: AgentState, _runtime: Runtime
) -> str:
    """Format shell tool call for approval prompt."""
    args = tool_call["args"]
    command = args.get("command", "N/A")
    return f"Shell Command: {command}\nWorking Directory: {Path.cwd()}"


def _format_execute_description(
    tool_call: ToolCall, _state: AgentState, _runtime: Runtime
) -> str:
    """Format execute tool call for approval prompt."""
    args = tool_call["args"]
    command = args.get("command", "N/A")
    return f"Execute Command: {command}\nLocation: Remote Sandbox"


def _format_write_file_description(
    tool_call: ToolCall, _state: AgentState, _runtime: Runtime
) -> str:
    """Format write_file tool call for approval prompt."""
    args = tool_call["args"]
    file_path = args.get("file_path", "unknown")
    content = args.get("content", "")
    content_preview = content[:200] + "..." if len(content) > 200 else content
    return f"File: {file_path}\nContent Preview:\n{content_preview}"


def _format_edit_file_description(
    tool_call: ToolCall, _state: AgentState, _runtime: Runtime
) -> str:
    """Format edit_file tool call for approval prompt."""
    args = tool_call["args"]
    file_path = args.get("file_path", "unknown")
    old_string = args.get("old_string", "")
    new_string = args.get("new_string", "")
    old_preview = old_string[:100] + "..." if len(old_string) > 100 else old_string
    new_preview = new_string[:100] + "..." if len(new_string) > 100 else new_string
    return f"File: {file_path}\n" f"Replace:\n{old_preview}\n" f"With:\n{new_preview}"


def _format_web_search_description(
    tool_call: ToolCall, _state: AgentState, _runtime: Runtime
) -> str:
    """Format web_search tool call for approval prompt."""
    args = tool_call["args"]
    query = args.get("query", "unknown")
    max_results = args.get("max_results", 5)
    return f"Query: {query}\nMax results: {max_results}\n\n⚠️  This will use Tavily API credits"


def _format_fetch_url_description(
    tool_call: ToolCall, _state: AgentState, _runtime: Runtime
) -> str:
    """Format fetch_url tool call for approval prompt."""
    args = tool_call["args"]
    url = args.get("url", "unknown")
    timeout = args.get("timeout", 30)
    return f"URL: {url}\nTimeout: {timeout}s\n\n⚠️  Will fetch and convert web content to markdown"


def _format_run_tests_description(
    tool_call: ToolCall, _state: AgentState, _runtime: Runtime
) -> str:
    """Format run_tests tool call for approval prompt."""
    args = tool_call["args"]
    command = args.get("command", "")
    working_dir = args.get("working_dir", ".")
    timeout = args.get("timeout", 300)

    command_display = command if command else "(auto-detect framework)"
    return (
        f"Test Command: {command_display}\n"
        f"Working Directory: {working_dir}\n"
        f"Timeout: {timeout}s\n\n"
        "⚠️  Will execute tests and stream output in real-time"
    )


def _format_start_dev_server_description(
    tool_call: ToolCall, _state: AgentState, _runtime: Runtime
) -> str:
    """Format start_dev_server tool call for approval prompt."""
    args = tool_call["args"]
    command = args.get("command", "unknown")
    name = args.get("name", "dev-server")
    port = args.get("port", "auto")
    working_dir = args.get("working_dir", ".")
    auto_open_browser = args.get("auto_open_browser", True)

    return (
        f"Server Command: {command}\n"
        f"Name: {name}\n"
        f"Port: {port if port else 'auto-detect'}\n"
        f"Working Directory: {working_dir}\n"
        f"Auto-open browser: {'Yes' if auto_open_browser else 'No'}\n\n"
        "⚠️  Will start a background process (killed on CLI exit)"
    )


def _format_write_memory_description(
    tool_call: ToolCall, _state: AgentState, _runtime: Runtime
) -> str:
    """Format write_memory tool call for approval prompt."""
    args = tool_call["args"]
    memory_type = args.get("memory_type", "user")
    path = args.get("path", "default location")
    append = args.get("append", False)
    content = args.get("content", "")
    content_preview = content[:100] + "..." if len(content) > 100 else content

    return (
        f"Memory Type: {memory_type}\n"
        f"Path: {path}\n"
        f"Mode: {'Append' if append else 'Replace'}\n"
        f"Content Preview:\n{content_preview}\n\n"
        "⚠️  Will write to memory file"
    )


def _format_duckduckgo_description(
    tool_call: ToolCall, _state: AgentState, _runtime: Runtime
) -> str:
    """Format duckduckgo_search and docs_search tool calls for approval prompt."""
    args = tool_call["args"]
    query = args.get("query", "unknown")
    max_results = args.get("max_results", 5)
    topic = args.get("topic", "general")

    return (
        f"Query: {query}\n"
        f"Max results: {max_results}\n"
        f"Topic: {topic}\n\n"
        "⚠️  Will make web search requests"
    )


# ---------------------------------------------------------------------------
# Interrupt Configuration Factory
# ---------------------------------------------------------------------------


def get_interrupt_configs() -> dict[str, InterruptOnConfig]:
    """Get all human-in-the-loop interrupt configurations.

    Returns:
        Dictionary mapping tool names to their interrupt configurations.

    Interrupt Categories:
        - Destructive operations: shell, execute, write_file, edit_file
        - External operations: web_search, fetch_url, browser_automate
        - Code execution: execute_in_e2b, run_tests, start_dev_server
        - Memory operations: write_memory
        - Browser operations: capture_browser_console
        - Search operations: duckduckgo_search, docs_search
        - User interaction: ask_question

    Each config now includes ``"edit"`` in ``allowed_decisions`` so the user
    can modify tool arguments before approval (the input form is built from
    the ``args_schema``).
    """
    # Destructive operations - shell and file system
    shell_interrupt_config: InterruptOnConfig = {
        "allowed_decisions": ["approve", "edit", "reject"],
        "description": _format_shell_description,  # type: ignore
        "args_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Shell command to run"},
                "timeout": {"type": "integer", "description": "Timeout in seconds", "default": 120},
            },
            "required": ["command"],
        },
    }

    execute_interrupt_config: InterruptOnConfig = {
        "allowed_decisions": ["approve", "edit", "reject"],
        "description": _format_execute_description,  # type: ignore
        "args_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Command to execute in sandbox"},
                "timeout": {"type": "integer", "description": "Timeout in seconds", "default": 120},
            },
            "required": ["command"],
        },
    }

    write_file_interrupt_config: InterruptOnConfig = {
        "allowed_decisions": ["approve", "edit", "reject"],
        "description": _format_write_file_description,  # type: ignore
        "args_schema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Absolute path to write"},
                "content": {"type": "string", "description": "File content"},
            },
            "required": ["file_path", "content"],
        },
    }

    edit_file_interrupt_config: InterruptOnConfig = {
        "allowed_decisions": ["approve", "edit", "reject"],
        "description": _format_edit_file_description,  # type: ignore
        "args_schema": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string", "description": "Absolute path to edit"},
                "old_string": {"type": "string", "description": "Text to replace"},
                "new_string": {"type": "string", "description": "Replacement text"},
            },
            "required": ["file_path", "old_string", "new_string"],
        },
    }

    # External operations - network and web
    web_search_interrupt_config: InterruptOnConfig = {
        "allowed_decisions": ["approve", "edit", "reject"],
        "description": _format_web_search_description,  # type: ignore
        "args_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "max_results": {"type": "integer", "description": "Max results", "default": 5},
            },
            "required": ["query"],
        },
    }

    fetch_url_interrupt_config: InterruptOnConfig = {
        "allowed_decisions": ["approve", "edit", "reject"],
        "description": _format_fetch_url_description,  # type: ignore
        "args_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL to fetch"},
                "timeout": {"type": "integer", "description": "Timeout in seconds", "default": 30},
            },
            "required": ["url"],
        },
    }

    # Code execution - remote and testing
    run_tests_interrupt_config: InterruptOnConfig = {
        "allowed_decisions": ["approve", "edit", "reject"],
        "description": _format_run_tests_description,  # type: ignore
        "args_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Test command"},
                "working_dir": {"type": "string", "description": "Working directory"},
                "timeout": {"type": "integer", "description": "Timeout in seconds", "default": 300},
            },
            "required": [],
        },
    }

    start_dev_server_interrupt_config: InterruptOnConfig = {
        "allowed_decisions": ["approve", "edit", "reject"],
        "description": _format_start_dev_server_description,  # type: ignore
        "args_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Server start command"},
                "name": {"type": "string", "description": "Server name"},
                "port": {"type": "integer", "description": "Port number"},
                "working_dir": {"type": "string", "description": "Working directory"},
            },
            "required": ["command"],
        },
    }

    # Memory operations - file system
    write_memory_interrupt_config: InterruptOnConfig = {
        "allowed_decisions": ["approve", "edit", "reject"],
        "description": _format_write_memory_description,  # type: ignore
        "args_schema": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "Memory content to write"},
                "memory_type": {"type": "string", "description": "Type of memory", "enum": ["user", "project"]},
                "path": {"type": "string", "description": "Virtual path to write to"},
                "append": {"type": "boolean", "description": "Append to existing", "default": False},
            },
            "required": ["content"],
        },
    }

    # Search operations
    duckduckgo_search_interrupt_config: InterruptOnConfig = {
        "allowed_decisions": ["approve", "edit", "reject"],
        "description": _format_duckduckgo_description,  # type: ignore
        "args_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "max_results": {"type": "integer", "description": "Max results", "default": 5},
            },
            "required": ["query"],
        },
    }

    return {
        # Destructive operations
        "shell": shell_interrupt_config,
        "execute": execute_interrupt_config,
        "write_file": write_file_interrupt_config,
        "edit_file": edit_file_interrupt_config,
        # External operations
        "web_search": web_search_interrupt_config,
        "fetch_url": fetch_url_interrupt_config,
        # Code execution
        "run_tests": run_tests_interrupt_config,
        "start_dev_server": start_dev_server_interrupt_config,
        # Memory operations
        "write_memory": write_memory_interrupt_config,
        # Search operations
        "duckduckgo_search": duckduckgo_search_interrupt_config,
    }


__all__ = [
    "get_interrupt_configs",
    "InterruptConfig",
]

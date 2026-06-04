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
from typing import TypedDict

from langchain.agents.middleware import InterruptOnConfig
from langchain.agents.middleware.types import AgentState
from langchain.messages import ToolCall
from langgraph.runtime import Runtime


class InterruptConfig(TypedDict):
    """Configuration for a human-in-the-loop interrupt.

    Attributes:
        allowed_decisions: List of allowed user decisions (e.g., ["approve", "reject"])
        description: Function to format the tool call for the approval prompt
    """

    allowed_decisions: list[str]
    description: callable  # type: ignore[valid-type]


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
    """
    # Destructive operations - shell and file system
    shell_interrupt_config: InterruptOnConfig = {
        "allowed_decisions": ["approve", "reject"],
        "description": _format_shell_description,  # type: ignore
    }

    execute_interrupt_config: InterruptOnConfig = {
        "allowed_decisions": ["approve", "reject"],
        "description": _format_execute_description,  # type: ignore
    }

    write_file_interrupt_config: InterruptOnConfig = {
        "allowed_decisions": ["approve", "reject"],
        "description": _format_write_file_description,  # type: ignore
    }

    edit_file_interrupt_config: InterruptOnConfig = {
        "allowed_decisions": ["approve", "reject"],
        "description": _format_edit_file_description,  # type: ignore
    }

    # External operations - network and web
    web_search_interrupt_config: InterruptOnConfig = {
        "allowed_decisions": ["approve", "reject"],
        "description": _format_web_search_description,  # type: ignore
    }

    fetch_url_interrupt_config: InterruptOnConfig = {
        "allowed_decisions": ["approve", "reject"],
        "description": _format_fetch_url_description,  # type: ignore
    }

    # Code execution - remote and testing
    run_tests_interrupt_config: InterruptOnConfig = {
        "allowed_decisions": ["approve", "reject"],
        "description": _format_run_tests_description,  # type: ignore
    }

    start_dev_server_interrupt_config: InterruptOnConfig = {
        "allowed_decisions": ["approve", "reject"],
        "description": _format_start_dev_server_description,  # type: ignore
    }

    # Memory operations - file system
    write_memory_interrupt_config: InterruptOnConfig = {
        "allowed_decisions": ["approve", "reject"],
        "description": _format_write_memory_description,  # type: ignore
    }

    # Search operations
    duckduckgo_search_interrupt_config: InterruptOnConfig = {
        "allowed_decisions": ["approve", "reject"],
        "description": _format_duckduckgo_description,  # type: ignore
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

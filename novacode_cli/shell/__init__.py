"""Shell middleware package.

Provides ShellMiddleware — a LangGraph agent middleware for shell command
execution with interactive prompt detection, background process management,
sandbox support, and security checks.

Usage:
    from novacode_cli.shell import ShellMiddleware
"""

from __future__ import annotations

from novacode_cli.shell.middleware import ShellMiddleware
from novacode_cli.shell.utils import (
    is_dangerous_command,
    is_interactive_prompt,
    is_long_running_command,
    is_server_ready,
)

__all__ = [
    "ShellMiddleware",
    "is_dangerous_command",
    "is_interactive_prompt",
    "is_long_running_command",
    "is_server_ready",
]
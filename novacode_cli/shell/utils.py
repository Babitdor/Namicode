"""Shell module: standalone utility functions.

This module contains the utility functions used by ShellMiddleware for
command validation, prompt detection, server readiness checks, and
environment sanitization.
"""

from __future__ import annotations

import os
import re
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

from novacode_cli.shell.patterns import (
    _COMPILED_AUTO_ANSWER,
    _COMPILED_DANGEROUS,
    _COMPILED_PATTERNS,
    _COMPILED_SERVER_READY,
    _API_KEY_SUFFIXES,
    _DANGEROUS_ENV_VARS,
    INTERACTIVE_COMMANDS,
    LONG_RUNNING_COMMANDS,
)


def _convert_unix_command_to_windows(command: str) -> str:
    """Convert Unix-style commands to Windows-compatible commands.

    This function transforms common Unix commands to work on Windows:
    - mkdir -p -> mkdir (Windows creates parent dirs automatically)
    - rm -rf -> rmdir /s /q or del /s /q
    - rm -r -> rmdir /s /q or del /s /q
    - cp -r -> xcopy /e /i /y
    - touch -> type nul >

    Args:
        command: The Unix-style command to convert

    Returns:
        Windows-compatible command string
    """
    if sys.platform != "win32":
        return command

    # Convert mkdir -p to Windows mkdir (Windows creates parent dirs automatically)
    command = re.sub(r"\bmkdir\s+-p\s+", "mkdir ", command, flags=re.IGNORECASE)

    # Convert rm -rf to Windows rmdir /s /q
    command = re.sub(r"\brm\s+-rf\s+", "rmdir /s /q ", command, flags=re.IGNORECASE)

    # Convert rm -r to Windows rmdir /s /q
    command = re.sub(r"\brm\s+-r\s+", "rmdir /s /q ", command, flags=re.IGNORECASE)

    # Convert cp -r to Windows xcopy
    command = re.sub(r"\bcp\s+-r\s+", "xcopy /e /i /y ", command, flags=re.IGNORECASE)

    # Convert touch to Windows type nul >
    command = re.sub(r"\btouch\s+", "type nul > ", command, flags=re.IGNORECASE)

    return command


def _sanitize_env(env: dict[str, str]) -> dict[str, str]:
    """Strip dangerous and secret env vars from a subprocess environment copy.

    Removes all env vars whose names appear in ``_DANGEROUS_ENV_VARS`` OR
    that end with common API-key / token suffixes.

    Args:
        env: A mutable copy of working environment (e.g. ``os.environ.copy()``).

    Returns:
        The cleaned env dict.
    """
    to_strip: set[str] = set(_DANGEROUS_ENV_VARS)
    for key in env:
        upper = key.upper()
        for suffix in _API_KEY_SUFFIXES:
            if upper.endswith(suffix):
                to_strip.add(key)
                break
    for k in to_strip:
        env.pop(k, None)
    return env


def is_dangerous_command(command: str) -> tuple[bool, str]:
    """Return (True, pattern) if the command matches a destructive pattern.

    Args:
        command: The shell command string to inspect.

    Returns:
        A tuple of (is_dangerous, matched_pattern_string).
    """
    for pattern in _COMPILED_DANGEROUS:
        if pattern.search(command):
            return True, pattern.pattern
    return False, ""


def is_interactive_prompt(line: str) -> bool:
    """Detect if a line is an interactive prompt requiring user input.

    Args:
        line: The output line to check.

    Returns:
        True if the line appears to be a prompt requiring input.
    """
    stripped = line.strip()
    if not stripped:
        return False

    # Check against known prompt patterns
    return any(pattern.search(stripped) for pattern in _COMPILED_PATTERNS)


def get_auto_answer(prompt_text: str) -> str | None:
    """Return a safe automatic response for known package-manager prompts.

    Args:
        prompt_text: The prompt text to check.

    Returns:
        The auto-response string, or None if user input is required.
    """
    for pattern, response in _COMPILED_AUTO_ANSWER.items():
        if pattern.search(prompt_text):
            return response
    return None


def is_server_ready(line: str) -> bool:
    """Detect if a line indicates a server has successfully started.

    Args:
        line: The output line to check.

    Returns:
        True if the line indicates the server is ready.
    """
    stripped = line.strip()
    if not stripped:
        return False

    # Check against server ready patterns
    return any(pattern.search(stripped) for pattern in _COMPILED_SERVER_READY)


def is_long_running_command(command: str) -> bool:
    """Detect if a command is a known long-running server command.

    Args:
        command: The command to check.

    Returns:
        True if this is a known long-running command.
    """
    command_lower = command.lower()
    return any(pattern in command_lower for pattern in LONG_RUNNING_COMMANDS)


def is_interactive_command(command: str) -> bool:
    """Detect if a command is known to be interactive and requires user input.

    These commands typically prompt the user for configuration options,
    project names, framework selections, etc.

    Args:
        command: The command to check.

    Returns:
        True if this is a known interactive command.
    """
    command_lower = command.lower()
    return any(pattern in command_lower for pattern in INTERACTIVE_COMMANDS)


__all__ = [
    "_convert_unix_command_to_windows",
    "_sanitize_env",
    "is_dangerous_command",
    "is_interactive_prompt",
    "get_auto_answer",
    "is_server_ready",
    "is_long_running_command",
    "is_interactive_command",
]
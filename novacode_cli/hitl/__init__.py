"""Human-in-the-loop (HITL) module for agent interrupts.

This module provides interrupt configurations for tools that require user approval
before execution. These interrupts allow users to review and approve/reject
potentially destructive or external operations.

Key components:
- Interrupt configurations for destructive tools (shell, write_file, etc.)
- Interrupt configurations for external operations (web_search, http_request, etc.)
- Interrupt configurations for user interaction tools (ask_question)

Usage:
    from novacode_cli.hitl import get_interrupt_configs

    configs = get_interrupt_configs()
"""

from novacode_cli.hitl.interrupts import get_interrupt_configs

__all__ = [
    "get_interrupt_configs",
]
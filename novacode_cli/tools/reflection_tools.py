"""Reflection tools.

This module provides tools for strategic reflection during task execution.
"""

from __future__ import annotations

from langchain.tools import tool


@tool
def think(reflection: str) -> str:
    """Tool for strategic reflection on code exploration and task progress.

    Use this tool to pause and analyze your findings, assess what you've learned,
    and make deliberate decisions about next steps in code analysis and exploration.

    This creates a checkpoint for quality decision-making before continuing.

    When to use:
    - After exploring codebase sections: What key patterns did I discover?
    - Before deciding next exploration targets: Do I understand the architecture enough?
    - When assessing code understanding: What crucial details am I still missing?
    - When planning refactoring/fixes: Is my analysis complete and correct?
    - Before recommending changes: Have I considered all implications?
    - When context is complex: Am I on the right track?

    Reflection should address:
    1. Key findings - What concrete code patterns, dependencies, or issues did I discover?
    2. Current understanding - What have I learned about the architecture/functionality?
    3. Knowledge gaps - What critical information is still missing?
    4. Quality assessment - Do I have sufficient evidence to proceed with recommendations?
    5. Strategic decision - Should I explore further or am I ready to make recommendations?

    Args:
        reflection: Your detailed reflection on code findings, understanding gaps,
                   analysis quality, and decision about next steps

    Returns:
        Confirmation that reflection was recorded for decision-making
    """
    return f"Reflection recorded: {reflection}"

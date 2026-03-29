from collections.abc import Callable
from typing import Any

from langchain.tools import BaseTool
from nami_deepagents.middleware.subagents import SubAgent

from .prompt import (
    BUG_FIX_AGENT,
    CODE_DOC_AGENT,
    CODE_EXPLORER,
    CODE_SIMPLIFIER,
    REFACTORING_SPECIALIST_AGENT,
    REVIEWER_AGENT,
    SECURITY_AUDITOR_AGENT,
    TEST_WRITER_AGENT,
)


AnyTool = BaseTool | Callable[..., Any]


def _tool_name(t: AnyTool) -> str | None:
    """Return the name of a tool, whether it's a BaseTool instance or a plain callable."""
    return getattr(t, "name", None) or getattr(t, "__name__", None)


def _filter_tools(tools: list[AnyTool], names: list[str]) -> list[AnyTool]:
    """Return the subset of tools whose names appear in `names`."""
    if not names:
        return tools
    name_set = set(names)
    return [t for t in tools if _tool_name(t) in name_set]


def retrieve_core_subagents(tools: list[AnyTool] | None = None) -> list[SubAgent]:
    all_tools: list[AnyTool] = tools or []

    # Define subagent configurations
    subagent_configs = [
        ("code-explorer-agent", CODE_EXPLORER),
        ("code-doc-Agent", CODE_DOC_AGENT),
        ("code-simplifier-agent", CODE_SIMPLIFIER),
        ("bug-fix-agent", BUG_FIX_AGENT),
        ("test-writer-agent", TEST_WRITER_AGENT),
        ("reviewer-agent", REVIEWER_AGENT),
        ("security-auditor-agent", SECURITY_AUDITOR_AGENT),
        ("refactoring-specialist-agent", REFACTORING_SPECIALIST_AGENT),
    ]

    subagents: list[SubAgent] = [
        {
            "name": name,
            "description": config["description"],
            "system_prompt": config["prompt"],
            "tools": _filter_tools(all_tools, config["tools"]),
        }
        for name, config in subagent_configs
    ]

    return subagents

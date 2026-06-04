# Built-In Agents for NOVA CLI

from collections.abc import Callable
from typing import Any

from langchain.tools import BaseTool
from deepagents.middleware.subagents import SubAgent

from .prompt import (
    CODE_DOC_AGENT,
    CODE_EXPLORER,
    CODE_SIMPLIFIER,
    REFACTORING_SPECIALIST_AGENT,
    REVIEWER_AGENT,
    SECURITY_AUDITOR_AGENT,
    # Bug fix agent
    BUG_FIX_AGENT,
    # Test agents
    TEST_WRITER_AGENT,
    TESTING_AGENT,
    # Browser automation agent
    BROWSER_AUTOMATION_AGENT,
    # Domain-specific engineering agents
    FRONTEND_AGENT,
    BACKEND_AGENT,
    DOCKER_AGENT,
    # Research swarm agents
    WEB_RESEARCHER,
    FACT_CHECKER,
    RESEARCH_SYNTHESIZER,
    LITERATURE_REVIEWER,
    MARKET_ANALYST,
    FINANCIAL_ANALYST,
    TECHNICAL_RESEARCHER,
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


def retrieve_core_subagents(
    tools: list[AnyTool] | None = None,
) -> list[SubAgent]:
    all_tools: list[AnyTool] = tools or []

    # Define subagent configurations
    subagent_configs = [
        # Code quality agents
        ("code-doc-Agent", CODE_DOC_AGENT),
        ("code-simplifier-agent", CODE_SIMPLIFIER),
        ("code-explorer", CODE_EXPLORER),
        ("reviewer-agent", REVIEWER_AGENT),
        ("security-auditor-agent", SECURITY_AUDITOR_AGENT),
        ("refactoring-specialist-agent", REFACTORING_SPECIALIST_AGENT),
        # Bug fix agent
        ("bug-fix-agent", BUG_FIX_AGENT),
        # Test agents
        ("test-writer-agent", TEST_WRITER_AGENT),
        ("testing-agent", TESTING_AGENT),
        # Browser automation agent
        ("browser-automation-agent", BROWSER_AUTOMATION_AGENT),
        # Domain-specific engineering agents
        ("frontend-agent", FRONTEND_AGENT),
        ("backend-agent", BACKEND_AGENT),
        ("docker-agent", DOCKER_AGENT),
        # Research swarm agents
        ("web-researcher", WEB_RESEARCHER),
        ("fact-checker", FACT_CHECKER),
        ("research-synthesizer", RESEARCH_SYNTHESIZER),
        ("literature-reviewer", LITERATURE_REVIEWER),
        ("market-analyst", MARKET_ANALYST),
        ("financial-analyst", FINANCIAL_ANALYST),
        ("technical-researcher", TECHNICAL_RESEARCHER),
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

    # Selectively assign 1-2 targeted skills per subagent.
    # SkillsMiddleware is instantiated per-subagent only when `skills` is set,
    # so skipping agents that don't need skills saves middleware overhead and
    # avoids polluting their system prompt with irrelevant skill content.
    # The general-purpose subagent auto-inherits the main agent's skills from
    # create_deep_agent's top-level `skills` parameter — no need to list it here.
    subagent_skills: dict[str, list[str]] = {
        # Code quality agents
        "code-doc-Agent": [
            "/skills/code-documentation/",
        ],
        "code-simplifier-agent": [
            "/skills/code-review-expert/",
        ],
        "code-explorer": [
            "/skills/codebase-explorer/",
            "/skills/graphify/",
        ],
        "reviewer-agent": [
            "/skills/code-review-expert/",
        ],
        "security-auditor-agent": [
            "/skills/web-research/",
        ],
        "refactoring-specialist-agent": [
            "/skills/improve-codebase-architecture/",
        ],
        # Bug fix agent
        "bug-fix-agent": [
            "/skills/systematic-debugging/",
        ],
        # Test agents
        "test-writer-agent": [
            "/skills/test-driven-development/",
        ],
        "testing-agent": [
            "/skills/testing-skills/",
            "/skills/webapp-testing/",
        ],
        # Browser automation agent
        "browser-automation-agent": [
            "/skills/agent-browser/",
            "/skills/browser-use/",
        ],
        # Domain-specific engineering agents
        "frontend-agent": [
            "/skills/frontend-design/",
            "/skills/expert-css-skills/",
        ],
        "backend-agent": [
            "/skills/backend-dev-guidelines/",
            "/skills/async-python-patterns/",
        ],
        "docker-agent": [
            "/skills/docker-deploy/",
        ],
        # Research swarm agents
        "web-researcher": [
            "/skills/web-research/",
            "/skills/arxiv-search/",
        ],
        "fact-checker": [
            "/skills/web-research/",
        ],
        "technical-researcher": [
            "/skills/web-research/",
            "/skills/codebase-explorer/",
        ],
        "literature-reviewer": [
            "/skills/arxiv-search/",
            "/skills/web-research/",
        ],
        "market-analyst": [
            "/skills/web-research/",
        ],
        "financial-analyst": [
            "/skills/web-research/",
            "/skills/xlsx/",
        ],
    }
    for sa in subagents:
        skills = subagent_skills.get(sa["name"])
        if skills:
            sa["skills"] = skills

    return subagents

from langchain.tools import BaseTool
from nami_deepagents.middleware.subagents import SubAgent

from .prompt import (
    API_DESIGNER_AGENT,
    BUG_FIX_AGENT,
    CODE_DOC_AAGENT,
    CODE_EXPLORER,
    CODE_SIMPLIFIER,
    CRITIQUE_AGENT,
    IMPLEMENTATION_AGENT,
    PERFORMANCE_ANALYST_AGENT,
    REFACTORING_SPECIALIST_AGENT,
    REVIEWER_AGENT,
    SECURITY_AUDITOR_AGENT,
    TEST_ARCHITECT_AGENT,
    TEST_WRITER_AGENT,
    TYPE_EXPERT_AGENT,
)


def retrieve_core_subagents(
    tools: list[BaseTool],
) -> list[SubAgent]:  # type: ignore
    subagents: list[SubAgent] = []

    # Core subagents
    code_explorer: SubAgent = {
        "name": "code-explorer-agent",
        "description": "Used to research more in depth questions",
        "system_prompt": CODE_EXPLORER,
        "tools": tools,
    }
    subagents.append(code_explorer)

    code_doc_agent: SubAgent = {
        "name": "code-doc-Agent",
        "description": "Generates human-readable documentation (README, API docs, docstrings) only from structured inputs such as IRs or retrieved code snippets. Does not explore the codebase independently.",
        "system_prompt": CODE_DOC_AAGENT,
        "tools": tools,
    }
    subagents.append(code_doc_agent)

    code_simplifier_agent: SubAgent = {
        "name": "code-simplifier-agent",
        "description": "Simplifies and refines code for clarity, consistency, and maintainability while preserving all functionality. Focuses on recently modified code unless instructed otherwise.",
        "system_prompt": CODE_SIMPLIFIER,
        "tools": tools,
    }
    subagents.append(code_simplifier_agent)

    # Workflow-based subagents
    implementation_agent: SubAgent = {
        "name": "implementation-agent",
        "description": "Implements new features following a structured workflow: plan, implement, verify. Use for complex feature implementations that need systematic approach.",
        "system_prompt": IMPLEMENTATION_AGENT,
        "tools": tools,
    }
    subagents.append(implementation_agent)

    bug_fix_agent: SubAgent = {
        "name": "bug-fix-agent",
        "description": "Fixes bugs following a structured workflow: reproduce, diagnose, fix, verify. Ensures minimal changes and adds regression tests.",
        "system_prompt": BUG_FIX_AGENT,
        "tools": tools,
    }
    subagents.append(bug_fix_agent)

    test_writer_agent: SubAgent = {
        "name": "test-writer-agent",
        "description": "Creates comprehensive test coverage following a structured workflow: analyze code paths, write tests (happy, edge, error cases), verify coverage.",
        "system_prompt": TEST_WRITER_AGENT,
        "tools": tools,
    }
    subagents.append(test_writer_agent)

    reviewer_agent: SubAgent = {
        "name": "reviewer-agent",
        "description": "Performs code review for correctness, security, performance, and maintainability. Provides structured feedback with critical issues, important issues, and praise.",
        "system_prompt": REVIEWER_AGENT,
        "tools": tools,
    }
    subagents.append(reviewer_agent)

    # Specialized subagents
    security_auditor_agent: SubAgent = {
        "name": "security-auditor-agent",
        "description": "Performs security audit for OWASP Top 10 vulnerabilities, secrets detection, input validation issues, authentication/authorization flaws, and dependency vulnerabilities. Reports critical/high/medium/low issues.",
        "system_prompt": SECURITY_AUDITOR_AGENT,
        "tools": tools,
    }
    subagents.append(security_auditor_agent)

    test_architect_agent: SubAgent = {
        "name": "test-architect-agent",
        "description": "Designs test strategy with coverage analysis, test levels (unit/integration/E2E), edge case identification, and mocking strategy. Creates test architecture plans for comprehensive coverage.",
        "system_prompt": TEST_ARCHITECT_AGENT,
        "tools": tools,
    }
    subagents.append(test_architect_agent)

    performance_analyst_agent: SubAgent = {
        "name": "performance-analyst-agent",
        "description": "Profiles code for CPU, memory, and I/O bottlenecks. Identifies database issues (N+1, missing indexes), algorithm complexity issues, and provides optimization recommendations.",
        "system_prompt": PERFORMANCE_ANALYST_AGENT,
        "tools": tools,
    }
    subagents.append(performance_analyst_agent)

    type_expert_agent: SubAgent = {
        "name": "type-expert-agent",
        "description": "Analyzes type safety with mypy/pyright, identifies missing type annotations, fixes type errors, and provides strict mode roadmap. Expert in Python type hints and TypeScript interfaces.",
        "system_prompt": TYPE_EXPERT_AGENT,
        "tools": tools,
    }
    subagents.append(type_expert_agent)

    api_designer_agent: SubAgent = {
        "name": "api-designer-agent",
        "description": "Designs REST/GraphQL APIs with best practices for resource modeling, HTTP methods, status codes, versioning, authentication, and documentation. Creates API specifications.",
        "system_prompt": API_DESIGNER_AGENT,
        "tools": tools,
    }
    subagents.append(api_designer_agent)

    refactoring_specialist_agent: SubAgent = {
        "name": "refactoring-specialist-agent",
        "description": "Identifies code smells (long methods, duplication, dead code), prioritizes technical debt, and creates incremental refactoring plans. Applies design patterns and SOLID principles.",
        "system_prompt": REFACTORING_SPECIALIST_AGENT,
        "tools": tools,
    }
    subagents.append(refactoring_specialist_agent)

    critique_agent: SubAgent = {
        "name": "critique-agent",
        "description": "Self-reflection agent that evaluates recent code changes for correctness, completeness, safety, and regressions. Uses git diff to discover changes and reports structured findings (PASS/WARN/FAIL).",
        "system_prompt": CRITIQUE_AGENT,
        "tools": tools,
        "color": "#f59e0b",
    }
    subagents.append(critique_agent)

    return subagents

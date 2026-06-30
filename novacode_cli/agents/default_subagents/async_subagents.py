# Async Subagents for NOVA CLI
# These run on remote LangGraph servers in the background

import os

from deepagents.middleware.async_subagents import AsyncSubAgent

# ── Base URL resolution ────────────────────────────────────────────────────────

_ASYNC_AGENT_BASE_URL = os.environ.get("ASYNC_AGENT_BASE_URL", "http://localhost")


def _resolve_async_agent_url(port: int) -> str | None:
    """Resolve the LangGraph server URL for an async subagent.

    Priority:
    1. ``ASYNC_AGENT_BASE_URL`` environment variable (shared base, e.g.
       ``http://localhost`` or ``http://doc-agent`` in Docker)
    2. ``LANGGRAPH_API_URL`` environment variable (shared LangGraph Platform URL)
    3. ``None`` — falls back to ASGI in-process transport (only works when
       running inside a LangGraph server process, e.g. ``langgraph dev``)

    The port is appended as ``{base}:{port}``.
    """
    base = os.environ.get("ASYNC_AGENT_BASE_URL") or os.environ.get("LANGGRAPH_API_URL")
    if base is None:
        return None
    return f"{base}:{port}"


def _resolve_async_agent_headers() -> dict[str, str]:
    """Resolve auth headers for the async subagent server.

    Uses ``LANGGRAPH_API_KEY`` if set, otherwise returns empty headers
    (assumes local/unauthenticated server).
    """
    api_key = os.environ.get("LANGGRAPH_API_KEY")
    if api_key:
        return {"Authorization": f"Bearer {api_key}"}
    return {}


# ── Agent descriptions ─────────────────────────────────────────────────────────

DOCUMENTATION_UPDATE_AGENT_DESCRIPTION = """An async agent that automatically updates documentation in the background.

Use this agent when:
- You've committed code changes that need documentation updates
- README files need to reflect new features or API changes
- Changelog entries need to be generated from commit messages
- API documentation needs to be synchronized with code changes
- Code comments or docstrings need updating

The agent runs remotely and asynchronously, so you can continue working while it processes documentation updates.
"""

CODE_REVIEW_AGENT_DESCRIPTION = """An async agent that reviews code changes in the background.

Use this agent when:
- You need a code review on uncommitted or recently committed changes
- You want to catch bugs, security issues, or style problems before PR
- You need a second opinion on code quality
- You want structured feedback with severity ratings

The agent analyzes diffs, reads full file context, and produces a structured review report.
"""

TEST_GENERATION_AGENT_DESCRIPTION = """An async agent that generates and maintains test suites in the background.

Use this agent when:
- You need tests for new or modified code
- You want to increase test coverage
- You need to verify existing tests still pass after changes
- You want edge case and error condition coverage

The agent analyzes source code, checks existing tests, generates pytest suites, and verifies they pass.
"""

DEPENDENCY_AUDIT_AGENT_DESCRIPTION = """An async agent that audits project dependencies in the background.

Use this agent when:
- You want to check for outdated packages
- You need a security vulnerability scan (CVEs)
- You want to review the dependency tree
- You need upgrade recommendations with compatibility notes

The agent checks pyproject.toml, runs pip-audit, and produces a structured report with severity levels.
"""

REFACTORING_AGENT_DESCRIPTION = """An async agent that analyzes and improves code quality in the background.

Use this agent when:
- You want to identify code smells and technical debt
- You need linting analysis across the codebase
- You want targeted refactoring suggestions
- You need to reduce complexity or duplication

The agent scans files, runs linters, analyzes structure, and proposes incremental improvements.
"""


# ── Agent builders ─────────────────────────────────────────────────────────────

def _build_agent_spec(
    name: str,
    graph_id: str,
    description: str,
    port: int,
) -> AsyncSubAgent:
    """Build an AsyncSubAgent spec with resolved URL and headers."""
    return {
        "name": name,
        "description": description,
        "graph_id": graph_id,
        "url": _resolve_async_agent_url(port),
        "headers": _resolve_async_agent_headers(),
    }


def build_documentation_update_agent() -> AsyncSubAgent:
    """Build the documentation update async subagent config."""
    return _build_agent_spec(
        name="documentation-update-agent",
        graph_id="documentation-update-agent",
        description=DOCUMENTATION_UPDATE_AGENT_DESCRIPTION,
        port=2024,
    )


def build_code_review_agent() -> AsyncSubAgent:
    """Build the code review async subagent config."""
    return _build_agent_spec(
        name="code-review-agent",
        graph_id="code-review-agent",
        description=CODE_REVIEW_AGENT_DESCRIPTION,
        port=2025,
    )


def build_test_generation_agent() -> AsyncSubAgent:
    """Build the test generation async subagent config."""
    return _build_agent_spec(
        name="test-generation-agent",
        graph_id="test-generation-agent",
        description=TEST_GENERATION_AGENT_DESCRIPTION,
        port=2026,
    )


def build_dependency_audit_agent() -> AsyncSubAgent:
    """Build the dependency audit async subagent config."""
    return _build_agent_spec(
        name="dependency-audit-agent",
        graph_id="dependency-audit-agent",
        description=DEPENDENCY_AUDIT_AGENT_DESCRIPTION,
        port=2027,
    )


def build_refactoring_agent() -> AsyncSubAgent:
    """Build the refactoring async subagent config."""
    return _build_agent_spec(
        name="refactoring-agent",
        graph_id="refactoring-agent",
        description=REFACTORING_AGENT_DESCRIPTION,
        port=2028,
    )


def retrieve_async_subagents() -> list[AsyncSubAgent]:
    """Return the list of available async subagents.

    Async subagents run on remote Agent Protocol servers and execute
    in the background, returning a task ID immediately.

    Returns:
        List of AsyncSubAgent configurations.
    """
    return [
        build_documentation_update_agent(),
        build_code_review_agent(),
        build_test_generation_agent(),
        build_dependency_audit_agent(),
        build_refactoring_agent(),
    ]
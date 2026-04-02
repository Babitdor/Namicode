from namicode_cli.prompts import render_template


def _load_prompt(template_name: str) -> str:
    """Load a subagent prompt from a Jinja template."""
    return render_template(f"subagents/{template_name}")


CODE_EXPLORER = {
    "description": "Used to research more in depth questions",
    "prompt": _load_prompt("code_explorer.jinja"),
    "tools": [
        # Research tools — fetch external docs, search web, inspect dependencies
        "fetch_url",
        "duckduckgo_search",
        "docs_search",
        "package_info",
    ],
}


CODE_DOC_AGENT = {
    "description": "Generates human-readable documentation (README, API docs, docstrings) only from structured inputs such as IRs or retrieved code snippets. Does not explore the codebase independently.",
    "prompt": _load_prompt("code_doc_agent.jinja"),
    "tools": [
        # No extra tools — works purely from provided code snippets
    ],
}


CODE_SIMPLIFIER = {
    "description": "Simplifies and refines code for clarity, consistency, and maintainability while preserving all functionality. Focuses on recently modified code unless instructed otherwise.",
    "prompt": _load_prompt("code_simplifier.jinja"),
    "tools": [
        # Code quality — verify simplifications don't break linting or types
        "lint_code",
        "format_code_file",
        "check_types",
    ],
}


BUG_FIX_AGENT = {
    "description": "Fixes bugs following a structured workflow: reproduce, diagnose, fix, verify. Ensures minimal changes and adds regression tests.",
    "prompt": _load_prompt("bug_fix_agent.jinja"),
    "tools": [
        # Run tests to reproduce & verify fix; lint/type-check the patch
        "run_tests_tool",
        "lint_code",
        "check_types",
    ],
}


TEST_WRITER_AGENT = {
    "description": "Creates comprehensive test coverage following a structured workflow: analyze code paths, write tests (happy, edge, error cases), verify coverage.",
    "prompt": _load_prompt("test_writer_agent.jinja"),
    "tools": [
        # Run newly written tests; lint/type-check the test files
        "run_tests_tool",
        "lint_code",
        "check_types",
    ],
}


REVIEWER_AGENT = {
    "description": "Performs code review for correctness, security, performance, and maintainability. Provides structured feedback with critical issues, important issues, and praise.",
    "prompt": _load_prompt("reviewer_agent.jinja"),
    "tools": [
        # Read-only review — lint/type checks to surface issues; inspect deps
        "lint_code",
        "check_types",
        "package_info",
    ],
}


SECURITY_AUDITOR_AGENT = {
    "description": "Performs security audit for OWASP Top 10 vulnerabilities, secrets detection, input validation issues, authentication/authorization flaws, and dependency vulnerabilities. Reports critical/high/medium/low issues.",
    "prompt": _load_prompt("security_auditor_agent.jinja"),
    "tools": [
        # Look up CVEs, fetch security advisories, inspect vulnerable packages
        "duckduckgo_search",
        "docs_search",
        "fetch_url",
        "package_info",
    ],
}


REFACTORING_SPECIALIST_AGENT = {
    "description": "Identifies code smells (long methods, duplication, dead code), prioritizes technical debt, and creates incremental refactoring plans. Applies design patterns and SOLID principles.",
    "prompt": _load_prompt("refactoring_specialist_agent.jinja"),
    "tools": [
        # Run tests to verify safety; lint/type-check and format after refactoring
        "run_tests_tool",
        "lint_code",
        "check_types",
        "format_code_file",
    ],
}

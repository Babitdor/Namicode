"""Test execution with real-time output streaming.

This module provides functionality to run tests with streaming output,
command validation, and framework detection.
"""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from namicode_cli.process_manager import stream_subprocess_output


class TestFramework(Enum):
    """Supported test frameworks."""

    PYTEST = "pytest"
    NPM_TEST = "npm_test"
    GO_TEST = "go_test"
    CARGO_TEST = "cargo_test"
    JEST = "jest"
    VITEST = "vitest"
    UNKNOWN = "unknown"


# Command allow-list for safety
ALLOWED_TEST_COMMANDS: dict[TestFramework, list[str]] = {
    TestFramework.PYTEST: [
        "pytest",
        "python -m pytest",
        "py.test",
        "python3 -m pytest",
    ],
    TestFramework.NPM_TEST: [
        "npm test",
        "npm run test",
        "yarn test",
        "yarn run test",
        "pnpm test",
        "pnpm run test",
    ],
    TestFramework.GO_TEST: [
        "go test",
    ],
    TestFramework.CARGO_TEST: [
        "cargo test",
    ],
    TestFramework.JEST: [
        "npx jest",
        "jest",
        "npm run jest",
        "yarn jest",
    ],
    TestFramework.VITEST: [
        "npx vitest",
        "vitest",
        "npm run vitest",
        "yarn vitest",
    ],
}

# Patterns that indicate dangerous commands (blocked)
BLOCKED_PATTERNS: list[str] = [
    r"\bsudo\b",
    r"\brm\s+-rf\b",
    r"\brm\s+-r\b",
    r"\brmdir\b.*\/s",
    r"\bdel\s+\/",
    r"\b&&\s*rm\b",
    r"\|\s*sh\b",
    r"\|\s*bash\b",
    r"\|\s*cmd\b",
    r"\beval\b",
    r"\bcurl\b.*\|\s*bash",
    r"\bwget\b.*\|\s*bash",
    r"\bexec\b",
    r"\bchmod\s+777\b",
    r"\bchown\b",
    r">\s*/dev/",
    r">\s*[A-Za-z]:\\",
    r"\bformat\b.*[A-Za-z]:",
]


@dataclass
class TestResult:
    """Result of a test execution.

    Attributes:
        success: Whether all tests passed
        exit_code: Process exit code
        output: Full captured output
        framework: Detected test framework
        tests_run: Number of tests executed (if parseable)
        tests_passed: Number of passing tests (if parseable)
        tests_failed: Number of failing tests (if parseable)
        duration_seconds: Total execution time
        error: Error message if execution failed
    """

    success: bool
    exit_code: int
    output: str
    framework: TestFramework
    tests_run: int | None = None
    tests_passed: int | None = None
    tests_failed: int | None = None
    duration_seconds: float | None = None
    error: str | None = None


def detect_test_framework(working_dir: str | Path) -> TestFramework:
    """Detect the test framework used in a project.

    Args:
        working_dir: Project directory to analyze

    Returns:
        Detected test framework
    """
    working_dir = Path(working_dir)

    # Check for Python/pytest
    pytest_indicators = [
        working_dir / "pytest.ini",
        working_dir / "pyproject.toml",
        working_dir / "setup.py",
        working_dir / "conftest.py",
        working_dir / "tests",
    ]
    for indicator in pytest_indicators:
        if indicator.exists():
            # Check if pyproject.toml has pytest config
            if indicator.name == "pyproject.toml":
                try:
                    content = indicator.read_text()
                    if "[tool.pytest" in content or "pytest" in content.lower():
                        return TestFramework.PYTEST
                except Exception:
                    pass
            elif indicator.name == "tests" and indicator.is_dir():
                # Check if there are Python test files
                if list(indicator.glob("test_*.py")) or list(indicator.glob("*_test.py")):
                    return TestFramework.PYTEST
            else:
                return TestFramework.PYTEST

    # Check for Node.js/npm test
    package_json = working_dir / "package.json"
    if package_json.exists():
        try:
            import json

            content = json.loads(package_json.read_text())
            scripts = content.get("scripts", {})

            # Check for specific test runners
            if "vitest" in scripts.get("test", ""):
                return TestFramework.VITEST
            if "jest" in scripts.get("test", ""):
                return TestFramework.JEST
            if "test" in scripts:
                return TestFramework.NPM_TEST

            # Check devDependencies
            dev_deps = content.get("devDependencies", {})
            if "vitest" in dev_deps:
                return TestFramework.VITEST
            if "jest" in dev_deps:
                return TestFramework.JEST
        except Exception:
            pass

        return TestFramework.NPM_TEST

    # Check for Go
    go_indicators = [
        working_dir / "go.mod",
        working_dir / "go.sum",
    ]
    for indicator in go_indicators:
        if indicator.exists():
            return TestFramework.GO_TEST

    # Check for Rust/Cargo
    cargo_indicators = [
        working_dir / "Cargo.toml",
        working_dir / "Cargo.lock",
    ]
    for indicator in cargo_indicators:
        if indicator.exists():
            return TestFramework.CARGO_TEST

    return TestFramework.UNKNOWN


def get_default_test_command(framework: TestFramework) -> str:
    """Get the default test command for a framework.

    Args:
        framework: Test framework

    Returns:
        Default test command
    """
    commands = {
        TestFramework.PYTEST: "pytest",
        TestFramework.NPM_TEST: "npm test",
        TestFramework.GO_TEST: "go test ./...",
        TestFramework.CARGO_TEST: "cargo test",
        TestFramework.JEST: "npx jest",
        TestFramework.VITEST: "npx vitest run",
        TestFramework.UNKNOWN: "",
    }
    return commands.get(framework, "")


def validate_test_command(command: str) -> tuple[bool, str | None]:
    """Validate a test command against the allow-list.

    Args:
        command: Command to validate

    Returns:
        Tuple of (is_valid, error_message)
    """
    # Check for blocked patterns first
    for pattern in BLOCKED_PATTERNS:
        if re.search(pattern, command, re.IGNORECASE):
            return False, f"Command contains blocked pattern for security: {pattern}"

    # Empty command is valid (will auto-detect)
    if not command.strip():
        return True, None

    # Check if command starts with allowed prefix
    command_lower = command.lower().strip()

    for framework, allowed in ALLOWED_TEST_COMMANDS.items():
        for prefix in allowed:
            if command_lower.startswith(prefix.lower()):
                return True, None

    # Build list of allowed commands for error message
    all_allowed = []
    for allowed_list in ALLOWED_TEST_COMMANDS.values():
        all_allowed.extend(allowed_list[:2])  # First 2 from each framework

    return False, (
        f"Command not in test allow-list. Allowed commands: {', '.join(all_allowed[:8])}. "
        "Use an allowed test runner or leave empty to auto-detect."
    )


def parse_test_output(output: str, framework: TestFramework) -> dict[str, int | None]:
    """Parse test output to extract statistics.

    Args:
        output: Raw test output
        framework: Test framework used

    Returns:
        Dict with tests_run, tests_passed, tests_failed
    """
    result: dict[str, int | None] = {
        "tests_run": None,
        "tests_passed": None,
        "tests_failed": None,
    }

    if framework == TestFramework.PYTEST:
        # Pattern: "===== 1 failed, 9 passed in 1.23s ====="
        # Or: "===== 10 passed in 1.23s ====="
        match = re.search(
            r"=+\s*(?:(\d+)\s+failed,\s*)?(\d+)\s+passed(?:,\s*(\d+)\s+skipped)?.*?=+",
            output,
            re.IGNORECASE,
        )
        if match:
            failed = int(match.group(1)) if match.group(1) else 0
            passed = int(match.group(2))
            result["tests_passed"] = passed
            result["tests_failed"] = failed
            result["tests_run"] = passed + failed

        # Also check for "collected X items"
        collected_match = re.search(r"collected\s+(\d+)\s+items?", output, re.IGNORECASE)
        if collected_match and result["tests_run"] is None:
            result["tests_run"] = int(collected_match.group(1))

    elif framework in (TestFramework.NPM_TEST, TestFramework.JEST, TestFramework.VITEST):
        # Jest/Vitest pattern: "Tests: 1 failed, 9 passed, 10 total"
        match = re.search(
            r"Tests?:\s*(?:(\d+)\s+failed,\s*)?(\d+)\s+passed(?:,\s*(\d+)\s+total)?",
            output,
            re.IGNORECASE,
        )
        if match:
            failed = int(match.group(1)) if match.group(1) else 0
            passed = int(match.group(2))
            total = int(match.group(3)) if match.group(3) else passed + failed
            result["tests_passed"] = passed
            result["tests_failed"] = failed
            result["tests_run"] = total

    elif framework == TestFramework.GO_TEST:
        # Go pattern: "ok  	package	0.123s"
        # Or: "FAIL	package	0.123s"
        passed_count = len(re.findall(r"^ok\s+", output, re.MULTILINE))
        failed_count = len(re.findall(r"^FAIL\s+", output, re.MULTILINE))

        if passed_count > 0 or failed_count > 0:
            result["tests_passed"] = passed_count
            result["tests_failed"] = failed_count
            result["tests_run"] = passed_count + failed_count

    elif framework == TestFramework.CARGO_TEST:
        # Cargo pattern: "test result: ok. 10 passed; 0 failed"
        match = re.search(
            r"test result:.*?(\d+)\s+passed;\s*(\d+)\s+failed",
            output,
            re.IGNORECASE,
        )
        if match:
            passed = int(match.group(1))
            failed = int(match.group(2))
            result["tests_passed"] = passed
            result["tests_failed"] = failed
            result["tests_run"] = passed + failed

    return result


async def run_tests(
    command: str = "",
    working_dir: str = ".",
    timeout: int = 300,
    output_callback: Callable[[str], None] | None = None,
) -> TestResult:
    """Execute tests with real-time output streaming.

    This is the core implementation used by the tool.

    Args:
        command: Test command to run (auto-detected if empty)
        working_dir: Directory to run tests in
        timeout: Maximum execution time in seconds (default: 5 minutes)
        output_callback: Callback for streaming output lines

    Returns:
        TestResult with execution details
    """
    start_time = time.time()

    # Validate command
    is_valid, error = validate_test_command(command)
    if not is_valid:
        return TestResult(
            success=False,
            exit_code=-1,
            output="",
            framework=TestFramework.UNKNOWN,
            error=error,
        )

    # Detect framework and get default command if needed
    framework = detect_test_framework(working_dir)

    if not command.strip():
        command = get_default_test_command(framework)
        if not command:
            return TestResult(
                success=False,
                exit_code=-1,
                output="",
                framework=TestFramework.UNKNOWN,
                error=(
                    "Could not auto-detect test framework. "
                    "Please specify a test command explicitly."
                ),
            )

    # Default callback if none provided
    if output_callback is None:
        output_callback = lambda x: None

    # Run the tests
    try:
        exit_code, output = await stream_subprocess_output(
            command,
            working_dir=working_dir,
            callback=output_callback,
            timeout=float(timeout),
        )
    except asyncio.TimeoutError:
        duration = time.time() - start_time
        return TestResult(
            success=False,
            exit_code=-1,
            output=f"Tests timed out after {timeout} seconds.",
            framework=framework,
            duration_seconds=duration,
            error=f"Tests timed out after {timeout} seconds.",
        )
    except Exception as e:
        duration = time.time() - start_time
        return TestResult(
            success=False,
            exit_code=-1,
            output=str(e),
            framework=framework,
            duration_seconds=duration,
            error=str(e),
        )

    duration = time.time() - start_time

    # Parse test output for statistics
    stats = parse_test_output(output, framework)

    return TestResult(
        success=exit_code == 0,
        exit_code=exit_code,
        output=output,
        framework=framework,
        tests_run=stats.get("tests_run"),
        tests_passed=stats.get("tests_passed"),
        tests_failed=stats.get("tests_failed"),
        duration_seconds=duration,
    )


def run_tests_tool(
    command: str = "",
    working_dir: str = ".",
    timeout: int = 300,
) -> dict[str, Any]:
    """Run tests with real-time output streaming.

    Executes test commands safely with output streamed to the UI.
    Supports: pytest, npm test, go test, cargo test, jest, vitest.

    Args:
        command: Test command to run. If empty, auto-detects based on project files.
                 Examples: "pytest tests/", "npm test", "go test ./..."
        working_dir: Directory to run tests in (default: current directory)
        timeout: Maximum execution time in seconds (default: 300 = 5 minutes)

    Returns:
        Dictionary containing:
        - success: Whether all tests passed
        - exit_code: Process exit code
        - output: Captured test output (may be truncated if large)
        - framework: Detected test framework
        - tests_run: Number of tests executed
        - tests_passed: Number of passing tests
        - tests_failed: Number of failing tests
        - duration_seconds: Total execution time

    Safety:
        - Only allows known test commands (pytest, npm test, go test, cargo test)
        - Blocks dangerous patterns (sudo, rm -rf, pipes to shell)
        - Enforces timeout to prevent runaway processes
        - Runs in specified working directory only

    Examples:
        run_tests()  # Auto-detect and run
        run_tests(command="pytest tests/ -v")
        run_tests(command="npm test", working_dir="frontend")
    """
    # This is a sync wrapper - the actual tool will be async
    # For now, return a placeholder that will be replaced with actual tool registration
    return {
        "success": False,
        "error": "Tool must be called through agent framework",
        "command": command,
        "working_dir": working_dir,
        "timeout": timeout,
    }

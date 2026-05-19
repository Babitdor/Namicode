"""Code linting tools.

This module provides tools for linting code to find errors and style issues.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from langchain.tools import tool


def _detect_project_type(path: str | Path) -> dict[str, Any]:
    """Detect project type and available tools.

    Args:
        path: File or directory path

    Returns:
        Dict with project_type, linter, formatter, type_checker info
    """
    path = Path(path)
    if path.is_file():
        working_dir = path.parent
        file_ext = path.suffix.lower()
    else:
        working_dir = path
        file_ext = None

    result: dict[str, Any] = {
        "project_type": "unknown",
        "linter": None,
        "formatter": None,
        "type_checker": None,
        "working_dir": str(working_dir),
    }

    # Check for Python project
    python_indicators = [
        working_dir / "pyproject.toml",
        working_dir / "setup.py",
        working_dir / "requirements.txt",
        working_dir / "ruff.toml",
        working_dir / ".ruff.toml",
    ]

    for indicator in python_indicators:
        if indicator.exists():
            result["project_type"] = "python"
            # Check for ruff
            try:
                subprocess.run(
                    ["ruff", "--version"],
                    capture_output=True,
                    timeout=5,
                    check=True,
                )
                result["linter"] = "ruff"
                result["formatter"] = "ruff"
            except (FileNotFoundError, subprocess.CalledProcessError):
                pass

            # Check for mypy
            try:
                subprocess.run(
                    ["mypy", "--version"],
                    capture_output=True,
                    timeout=5,
                    check=True,
                )
                result["type_checker"] = "mypy"
            except (FileNotFoundError, subprocess.CalledProcessError):
                # Try pyright
                try:
                    subprocess.run(
                        ["pyright", "--version"],
                        capture_output=True,
                        timeout=5,
                        check=True,
                    )
                    result["type_checker"] = "pyright"
                except (FileNotFoundError, subprocess.CalledProcessError):
                    pass
            break

    # Check for Node.js project
    package_json = working_dir / "package.json"
    if package_json.exists() and result["project_type"] == "unknown":
        result["project_type"] = "javascript"
        try:
            pkg_content = json.loads(package_json.read_text())
            dev_deps = pkg_content.get("devDependencies", {})
            deps = pkg_content.get("dependencies", {})
            all_deps = {**deps, **dev_deps}

            # Check for ESLint
            if "eslint" in all_deps:
                result["linter"] = "eslint"

            # Check for Prettier
            if "prettier" in all_deps:
                result["formatter"] = "prettier"

            # Check for TypeScript
            if "typescript" in all_deps:
                result["project_type"] = "typescript"
                result["type_checker"] = "tsc"
        except (json.JSONDecodeError, OSError):
            pass

    # Detect by file extension if still unknown
    if file_ext and result["project_type"] == "unknown":
        if file_ext in (".py", ".pyi"):
            result["project_type"] = "python"
        elif file_ext in (".js", ".jsx", ".mjs"):
            result["project_type"] = "javascript"
        elif file_ext in (".ts", ".tsx"):
            result["project_type"] = "typescript"
        elif file_ext == ".go":
            result["project_type"] = "go"
            result["linter"] = "golangci-lint"
            result["formatter"] = "gofmt"
        elif file_ext == ".rs":
            result["project_type"] = "rust"
            result["linter"] = "clippy"
            result["formatter"] = "rustfmt"

    return result


def _lint_with_ruff(path: Path, fix: bool, show_fixes: bool) -> dict[str, Any]:
    """Run ruff linter on Python code."""
    cmd = ["ruff", "check", str(path), "--output-format", "json"]

    if fix:
        cmd.append("--fix")
    if show_fixes:
        cmd.append("--show-fixes")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            check=False,
        )

        errors: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []

        if result.stdout.strip():
            try:
                issues = json.loads(result.stdout)
                for issue in issues:
                    entry = {
                        "file": issue.get("filename", ""),
                        "line": issue.get("location", {}).get("row", 0),
                        "column": issue.get("location", {}).get("column", 0),
                        "code": issue.get("code", ""),
                        "message": issue.get("message", ""),
                        "fix": (issue.get("fix", {}).get("message") if issue.get("fix") else None),
                    }
                    # Treat E (error) and F (fatal/undefined) as errors
                    if entry["code"].startswith(("E", "F")):
                        errors.append(entry)
                    else:
                        warnings.append(entry)
            except json.JSONDecodeError:
                # Fallback to text output
                errors.append({"message": result.stdout})

        # Check for syntax errors in stderr
        if result.stderr and "SyntaxError" in result.stderr:
            errors.append(
                {
                    "file": str(path),
                    "code": "E999",
                    "message": result.stderr.strip(),
                }
            )

        total_issues = len(errors) + len(warnings)
        summary_parts = []
        if errors:
            summary_parts.append(f"{len(errors)} error(s)")
        if warnings:
            summary_parts.append(f"{len(warnings)} warning(s)")

        return {
            "success": len(errors) == 0,
            "linter": "ruff",
            "errors": errors,
            "warnings": warnings,
            "total_issues": total_issues,
            "summary": ", ".join(summary_parts) if summary_parts else "No issues found",
            "exit_code": result.returncode,
        }

    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Linting timed out after 120 seconds"}
    except FileNotFoundError:
        return {"success": False, "error": "ruff not found. Install with: uv add ruff"}
    except Exception as e:  # noqa: BLE001
        return {"success": False, "error": f"Linting failed: {e!s}"}


def _lint_with_eslint(path: Path, fix: bool) -> dict[str, Any]:
    """Run ESLint on JavaScript/TypeScript code."""
    cmd = ["npx", "eslint", str(path), "--format", "json"]

    if fix:
        cmd.append("--fix")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            check=False,
        )

        errors: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []

        if result.stdout.strip():
            try:
                files = json.loads(result.stdout)
                for file_result in files:
                    for msg in file_result.get("messages", []):
                        entry = {
                            "file": file_result.get("filePath", ""),
                            "line": msg.get("line", 0),
                            "column": msg.get("column", 0),
                            "code": msg.get("ruleId", ""),
                            "message": msg.get("message", ""),
                        }
                        if msg.get("severity", 0) == 2:
                            errors.append(entry)
                        else:
                            warnings.append(entry)
            except json.JSONDecodeError:
                errors.append({"message": result.stdout})

        return {
            "success": len(errors) == 0,
            "linter": "eslint",
            "errors": errors,
            "warnings": warnings,
            "total_issues": len(errors) + len(warnings),
            "summary": (
                f"{len(errors)} error(s), {len(warnings)} warning(s)"
                if errors or warnings
                else "No issues found"
            ),
        }

    except subprocess.TimeoutExpired:
        return {"success": False, "error": "ESLint timed out after 120 seconds"}
    except FileNotFoundError:
        return {
            "success": False,
            "error": "ESLint not found. Install with: npm install eslint",
        }
    except Exception as e:  # noqa: BLE001
        return {"success": False, "error": f"Linting failed: {e!s}"}


@tool
def lint_code(
    path: str = ".",
    fix: bool = False,
    show_fixes: bool = True,
) -> dict[str, Any]:
    """Lint code to find errors, style issues, and potential bugs.

    IMPORTANT: Use this tool AFTER writing or editing code to catch issues early.
    It detects undefined variables, unused imports, syntax errors, and style violations.

    Args:
        path: File or directory to lint (default: current directory)
        fix: Auto-fix issues where possible (default: False, only report)
        show_fixes: Show what fixes are available (default: True)

    Returns:
        Dictionary with:
        - success: bool - True if no errors found
        - linter: str - Tool used (ruff, eslint, etc.)
        - errors: list - List of errors found
        - warnings: list - List of warnings found
        - fixed: int - Number of issues auto-fixed (if fix=True)
        - summary: str - Human-readable summary

    Detects:
        - Undefined variables and names
        - Unused imports and variables
        - Syntax errors
        - Type annotation issues
        - Security vulnerabilities (SQL injection, etc.)
        - Style violations
    """
    path = Path(path).resolve()
    if not path.exists():
        return {
            "success": False,
            "error": f"Path not found: {path}",
        }

    project = _detect_project_type(path)

    if project["linter"] == "ruff":
        return _lint_with_ruff(path, fix, show_fixes)
    if project["linter"] == "eslint":
        return _lint_with_eslint(path, fix)
    if project["project_type"] == "python":
        # Try ruff anyway, it might be installed globally
        try:
            subprocess.run(["ruff", "--version"], capture_output=True, check=True, timeout=5)
            return _lint_with_ruff(path, fix, show_fixes)
        except (FileNotFoundError, subprocess.CalledProcessError):
            return {
                "success": False,
                "error": "No linter available. Install ruff: uv add ruff",
            }
    elif project["project_type"] in ("javascript", "typescript"):
        return _lint_with_eslint(path, fix)
    else:
        return {
            "success": False,
            "error": f"No linter configured for {project['project_type']} projects",
            "hint": "For Python: uv add ruff. For JS/TS: npm install eslint",
        }

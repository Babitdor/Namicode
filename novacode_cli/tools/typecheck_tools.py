"""Type checking tools.

This module provides tools for running type checkers on code.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

from langchain.tools import tool

from novacode_cli.tools.lint_tools import _detect_project_type


def _check_types_mypy(path: Path, strict: bool) -> dict[str, Any]:
    """Run mypy type checker."""
    cmd = ["mypy", str(path), "--no-color-output", "--show-column-numbers"]

    if strict:
        cmd.append("--strict")

    # Add common useful flags
    cmd.extend(
        [
            "--show-error-codes",
            "--no-error-summary",  # We'll generate our own summary
        ]
    )

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
            check=False,
        )

        errors: list[dict[str, Any]] = []

        # Parse mypy output: file:line:col: error: message [code]
        for line in result.stdout.split("\n"):
            if ": error:" in line or ": note:" in line:
                parts = line.split(":", 3)
                if len(parts) >= 4:
                    error_part = parts[3].strip()
                    code_match = None
                    message = error_part

                    # Extract error code if present [code]
                    code_match = re.search(r"\[([a-z-]+)\]$", error_part)
                    if code_match:
                        code = code_match.group(1)
                        message = error_part[: code_match.start()].strip()
                    else:
                        code = "error" if ": error:" in line else "note"

                    errors.append(
                        {
                            "file": parts[0],
                            "line": int(parts[1]) if parts[1].isdigit() else 0,
                            "column": int(parts[2]) if parts[2].isdigit() else 0,
                            "code": code,
                            "message": message.replace("error: ", "").replace("note: ", ""),
                        }
                    )

        return {
            "success": len(errors) == 0,
            "checker": "mypy",
            "errors": errors,
            "total_errors": len(errors),
            "summary": (f"{len(errors)} type error(s) found" if errors else "No type errors found"),
            "raw_output": result.stdout if errors else None,
        }

    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Type checking timed out after 5 minutes"}
    except FileNotFoundError:
        return {"success": False, "error": "mypy not found. Install with: uv add mypy"}
    except Exception as e:  # noqa: BLE001
        return {"success": False, "error": f"Type checking failed: {e!s}"}


def _check_types_pyright(path: Path, strict: bool) -> dict[str, Any]:
    """Run pyright type checker."""
    cmd = ["pyright", str(path), "--outputjson"]

    if strict:
        cmd.append("--strict")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
            check=False,
        )

        errors: list[dict[str, Any]] = []

        if result.stdout.strip():
            try:
                data = json.loads(result.stdout)
                for diag in data.get("generalDiagnostics", []):
                    errors.append(
                        {
                            "file": diag.get("file", ""),
                            "line": diag.get("range", {}).get("start", {}).get("line", 0),
                            "column": diag.get("range", {}).get("start", {}).get("character", 0),
                            "code": diag.get("rule", "error"),
                            "message": diag.get("message", ""),
                            "severity": diag.get("severity", "error"),
                        }
                    )
            except json.JSONDecodeError:
                errors.append({"message": result.stdout})

        return {
            "success": len(errors) == 0,
            "checker": "pyright",
            "errors": errors,
            "total_errors": len(errors),
            "summary": (f"{len(errors)} type error(s) found" if errors else "No type errors found"),
        }

    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Type checking timed out after 5 minutes"}
    except FileNotFoundError:
        return {
            "success": False,
            "error": "pyright not found. Install with: uv add pyright",
        }
    except Exception as e:  # noqa: BLE001
        return {"success": False, "error": f"Type checking failed: {e!s}"}


def _check_types_tsc(path: Path) -> dict[str, Any]:
    """Run TypeScript compiler for type checking."""
    cmd = ["npx", "tsc", "--noEmit", "--pretty", "false"]

    # If path is a specific file, check just that file
    if path.is_file():
        cmd.append(str(path))

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
            cwd=str(path.parent if path.is_file() else path),
            check=False,
        )

        errors: list[dict[str, Any]] = []

        # Parse tsc output: file(line,col): error TSxxxx: message
        for line in result.stdout.split("\n"):
            match = re.match(r"(.+)\((\d+),(\d+)\):\s+(error|warning)\s+(TS\d+):\s+(.+)", line)
            if match:
                errors.append(
                    {
                        "file": match.group(1),
                        "line": int(match.group(2)),
                        "column": int(match.group(3)),
                        "severity": match.group(4),
                        "code": match.group(5),
                        "message": match.group(6),
                    }
                )

        return {
            "success": len(errors) == 0,
            "checker": "tsc",
            "errors": errors,
            "total_errors": len(errors),
            "summary": (f"{len(errors)} type error(s) found" if errors else "No type errors found"),
        }

    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Type checking timed out after 5 minutes"}
    except FileNotFoundError:
        return {
            "success": False,
            "error": "TypeScript not found. Install with: npm install typescript",
        }
    except Exception as e:  # noqa: BLE001
        return {"success": False, "error": f"Type checking failed: {e!s}"}


@tool
def check_types(
    path: str = ".",
    strict: bool = False,
) -> dict[str, Any]:
    """Run type checking to detect undefined names, type errors, and missing imports.

    IMPORTANT: Use this tool to catch undefined variables, incorrect function calls,
    and type mismatches that linting alone cannot detect.

    Args:
        path: File or directory to check (default: current directory)
        strict: Enable strict type checking mode (more thorough but noisier)

    Returns:
        Dictionary with:
        - success: bool - True if no type errors found
        - checker: str - Tool used (mypy, pyright, tsc)
        - errors: list - List of type errors found
        - summary: str - Human-readable summary

    Detects:
        - Undefined names and variables
        - Missing imports
        - Type mismatches (wrong argument types, return types)
        - Missing function arguments
        - Invalid attribute access
        - Incompatible types in assignments
    """
    path = Path(path).resolve()
    if not path.exists():
        return {
            "success": False,
            "error": f"Path not found: {path}",
        }

    project = _detect_project_type(path)

    if project["type_checker"] == "mypy":
        return _check_types_mypy(path, strict)
    if project["type_checker"] == "pyright":
        return _check_types_pyright(path, strict)
    if project["type_checker"] == "tsc":
        return _check_types_tsc(path)
    if project["project_type"] == "python":
        # Try mypy, then pyright
        try:
            subprocess.run(["mypy", "--version"], capture_output=True, check=True, timeout=5)
            return _check_types_mypy(path, strict)
        except (FileNotFoundError, subprocess.CalledProcessError):
            try:
                subprocess.run(["pyright", "--version"], capture_output=True, check=True, timeout=5)
                return _check_types_pyright(path, strict)
            except (FileNotFoundError, subprocess.CalledProcessError):
                return {
                    "success": False,
                    "error": "No type checker available. Install mypy: uv add mypy",
                }
    elif project["project_type"] == "typescript":
        return _check_types_tsc(path)
    else:
        return {
            "success": False,
            "error": f"No type checker configured for {project['project_type']} projects",
        }

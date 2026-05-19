"""Code formatting tools.

This module provides tools for formatting code files.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from langchain.tools import tool

from novacode_cli.tools.lint_tools import _detect_project_type


def _format_with_ruff(path: Path, check_only: bool) -> dict[str, Any]:
    """Format Python code with ruff."""
    cmd = ["ruff", "format", str(path)]

    if check_only:
        cmd.append("--check")
        cmd.append("--diff")

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

        # Parse output for changed files
        files_changed: list[str] = []
        if check_only and result.stdout:
            # ruff format --check --diff shows file paths
            for line in result.stdout.split("\n"):
                if line.startswith(("---", "+++")):
                    # Extract filename from diff header
                    parts = line.split()
                    if len(parts) >= 2:
                        fname = parts[1].lstrip("a/").lstrip("b/")
                        if fname not in files_changed:
                            files_changed.append(fname)

        already_formatted = result.returncode == 0 and not files_changed

        return {
            "success": True,
            "formatter": "ruff",
            "files_changed": files_changed,
            "already_formatted": already_formatted,
            "diff": result.stdout if check_only and result.stdout else None,
            "message": (
                "Already formatted"
                if already_formatted
                else (
                    f"{len(files_changed)} file(s) would be changed"
                    if check_only
                    else "Formatted successfully"
                )
            ),
        }

    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Formatting timed out after 120 seconds"}
    except FileNotFoundError:
        return {"success": False, "error": "ruff not found. Install with: uv add ruff"}
    except Exception as e:  # noqa: BLE001
        return {"success": False, "error": f"Formatting failed: {e!s}"}


def _format_with_prettier(path: Path, check_only: bool) -> dict[str, Any]:
    """Format JS/TS code with Prettier."""
    cmd = ["npx", "prettier", str(path)]

    if check_only:
        cmd.append("--check")
    else:
        cmd.append("--write")

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

        # Parse output for changed files
        files_changed: list[str] = []
        for line in result.stdout.split("\n"):
            if line.strip() and Path(line.strip()).exists():
                files_changed.append(line.strip())

        already_formatted = result.returncode == 0 and "All matched files" not in result.stdout

        return {
            "success": result.returncode == 0 or check_only,
            "formatter": "prettier",
            "files_changed": files_changed,
            "already_formatted": already_formatted,
            "message": result.stdout or result.stderr,
        }

    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Formatting timed out after 120 seconds"}
    except FileNotFoundError:
        return {
            "success": False,
            "error": "Prettier not found. Install with: npm install prettier",
        }
    except Exception as e:  # noqa: BLE001
        return {"success": False, "error": f"Formatting failed: {e!s}"}


def _format_with_gofmt(path: Path, check_only: bool) -> dict[str, Any]:
    """Format Go code with gofmt."""
    cmd = ["gofmt"]
    if not check_only:
        cmd.append("-w")
    cmd.append(str(path))

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            check=False,
        )

        return {
            "success": result.returncode == 0,
            "formatter": "gofmt",
            "output": result.stdout or result.stderr,
            "already_formatted": not result.stdout,
        }

    except FileNotFoundError:
        return {"success": False, "error": "gofmt not found. Install Go."}
    except Exception as e:  # noqa: BLE001
        return {"success": False, "error": f"Formatting failed: {e!s}"}


def _format_with_rustfmt(path: Path, check_only: bool) -> dict[str, Any]:
    """Format Rust code with rustfmt."""
    cmd = ["rustfmt"]
    if check_only:
        cmd.append("--check")
    cmd.append(str(path))

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            check=False,
        )

        return {
            "success": result.returncode == 0,
            "formatter": "rustfmt",
            "output": result.stdout or result.stderr,
            "already_formatted": result.returncode == 0,
        }

    except FileNotFoundError:
        return {
            "success": False,
            "error": "rustfmt not found. Install with: rustup component add rustfmt",
        }
    except Exception as e:  # noqa: BLE001
        return {"success": False, "error": f"Formatting failed: {e!s}"}


@tool
def format_code_file(
    path: str,
    check_only: bool = False,
) -> dict[str, Any]:
    """Format a code file using the project's configured formatter.

    IMPORTANT: Use this tool to ensure consistent code style. Respects project
    configuration (pyproject.toml, .prettierrc, etc.).

    Args:
        path: File or directory to format
        check_only: If True, only check if formatting needed (don't modify files)

    Returns:
        Dictionary with:
        - success: bool - True if formatted successfully (or no changes needed)
        - formatter: str - Tool used (ruff, prettier, gofmt, etc.)
        - files_changed: list - Files that were/would be changed
        - already_formatted: bool - True if no changes needed

    Supported formatters:
        - Python: ruff format (or black fallback)
        - JavaScript/TypeScript: prettier
        - Go: gofmt
        - Rust: rustfmt
    """
    path = Path(path).resolve()
    if not path.exists():
        return {
            "success": False,
            "error": f"Path not found: {path}",
        }

    project = _detect_project_type(path)

    if project["formatter"] == "ruff":
        return _format_with_ruff(path, check_only)
    if project["formatter"] == "prettier":
        return _format_with_prettier(path, check_only)
    if project["formatter"] == "gofmt":
        return _format_with_gofmt(path, check_only)
    if project["formatter"] == "rustfmt":
        return _format_with_rustfmt(path, check_only)
    if project["project_type"] == "python":
        # Try ruff format anyway
        try:
            subprocess.run(["ruff", "--version"], capture_output=True, check=True, timeout=5)
            return _format_with_ruff(path, check_only)
        except (FileNotFoundError, subprocess.CalledProcessError):
            return {
                "success": False,
                "error": "No formatter available. Install ruff: uv add ruff",
            }
    elif project["project_type"] in ("javascript", "typescript"):
        return _format_with_prettier(path, check_only)
    else:
        return {
            "success": False,
            "error": f"No formatter configured for {project['project_type']} projects",
        }

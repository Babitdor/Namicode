"""Executable-package skills — run a skill's Python code directly, not just its markdown.

A skill is normally a ``SKILL.md`` the agent reads and follows. Some skills are
better expressed as *code*: a ``skill.py`` at the skill root, a ``package/``
directory with a ``__main__.py``, or a ``pyproject.toml`` declaring a
``[project.scripts]`` entry. This module resolves those executables and runs them
in a subprocess (cwd = the skill dir), capturing stdout/stderr with a timeout.

Convention (see ``docs/SKILL-EXECUTABLES.md``):

- ``<skill>/skill.py`` — a standalone script; run as ``python skill.py [args]``.
- ``<skill>/package/`` with ``__main__.py`` — a package; run as ``python -m package``.
- ``<skill>/pyproject.toml`` with ``[project.scripts]`` — a console entry point;
  run as ``python -m <module>`` (the first script's module).

The invoker (``/skill:<name> --run``) uses :func:`find_executable` to detect an
executable and :func:`run_executable` to run it.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SkillExecutable:
    """A resolved executable for a skill."""

    kind: str  # "script" | "package" | "entrypoint"
    command: list[str]  # argv to run (python + module/script + args)
    cwd: Path  # working directory (the skill dir)

    def describe(self) -> str:
        """A short human-readable description of the executable."""
        return f"{self.kind}: {' '.join(self.command)}"


def _find_script(skill_dir: Path) -> Path | None:
    """Return ``skill_dir/skill.py`` if it exists."""
    candidate = skill_dir / "skill.py"
    return candidate if candidate.is_file() else None


def _find_package(skill_dir: Path) -> Path | None:
    """Return ``skill_dir/package`` if it has a ``__main__.py``."""
    candidate = skill_dir / "package"
    if candidate.is_dir() and (candidate / "__main__.py").is_file():
        return candidate
    return None


def _find_entrypoint(skill_dir: Path) -> tuple[str, str] | None:
    """Return ``(module, script_name)`` from a ``pyproject.toml`` ``[project.scripts]``.

    Returns ``None`` if there's no pyproject or no scripts table.
    """
    pyproject = skill_dir / "pyproject.toml"
    if not pyproject.is_file():
        return None
    try:
        import tomllib
    except ImportError:  # pragma: no cover — Python < 3.11
        return None
    try:
        with pyproject.open("rb") as fh:
            data = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError):
        return None
    scripts = data.get("project", {}).get("scripts")
    if not isinstance(scripts, dict) or not scripts:
        return None
    # Take the first script entry; its value is "module:function".
    script_name, target = next(iter(scripts.items()))
    module = target.split(":", 1)[0]
    return module, script_name


def find_executable(skill_dir: Path) -> SkillExecutable | None:
    """Resolve a skill's executable, or ``None`` if it's markdown-only.

    Precedence: ``skill.py`` script → ``package/`` → ``pyproject.toml`` entrypoint.
    """
    skill_dir = Path(skill_dir)
    script = _find_script(skill_dir)
    if script is not None:
        return SkillExecutable(
            kind="script",
            command=[sys.executable, str(script)],
            cwd=skill_dir,
        )
    package = _find_package(skill_dir)
    if package is not None:
        return SkillExecutable(
            kind="package",
            command=[sys.executable, "-m", package.name],
            cwd=skill_dir,
        )
    entry = _find_entrypoint(skill_dir)
    if entry is not None:
        module, _script_name = entry
        return SkillExecutable(
            kind="entrypoint",
            command=[sys.executable, "-m", module],
            cwd=skill_dir,
        )
    return None


def is_executable(skill_dir: Path) -> bool:
    """Return True if the skill has a runnable executable."""
    return find_executable(skill_dir) is not None


def run_executable(
    skill_dir: Path,
    args: list[str] | None = None,
    timeout: float = 60.0,
) -> dict[str, Any]:
    """Run a skill's executable in a subprocess, capturing output.

    Args:
        skill_dir: The skill directory.
        args: Extra CLI args to pass after the executable.
        timeout: Max seconds before the subprocess is killed.

    Returns:
        A dict with ``ok``, ``output``, ``error``, and ``command``.
    """
    exe = find_executable(skill_dir)
    if exe is None:
        return {"ok": False, "output": "", "error": "skill has no executable", "command": []}
    command = exe.command + list(args or [])
    try:
        proc = subprocess.run(  # noqa: S603 — running a skill's own declared executable
            command,
            cwd=str(exe.cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {
            "ok": False,
            "output": "",
            "error": f"skill executable timed out after {timeout:.0f}s",
            "command": command,
        }
    except OSError as exc:
        return {"ok": False, "output": "", "error": f"failed to run: {exc}", "command": command}
    output = (proc.stdout or "") + (proc.stderr or "")
    return {
        "ok": proc.returncode == 0,
        "output": output,
        "error": None if proc.returncode == 0 else f"exit code {proc.returncode}",
        "command": command,
    }

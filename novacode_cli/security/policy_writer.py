"""Persist a confirmed approval rule into an approval-policy.json file.

Merges a :class:`ProposedRule` into the project or global policy file (creating
it if absent), writes atomically, and refreshes the cached policy so the rule
takes effect immediately. Best-effort and side-effecting; callers keep the rule
in the session layer too so a write failure still benefits the turn.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from novacode_cli.config.config import HOME_DIR
from novacode_cli.security.policy import get_policy

if TYPE_CHECKING:
    from novacode_cli.security.rule_synthesis import ProposedRule

_SECTION_BY_CATEGORY = {"shell": "shell", "paths": "paths", "domains": "domains"}


def _target_path(target: str, project_root: Path | None) -> Path:
    if target == "global":
        return HOME_DIR / "approval-policy.json"
    root = project_root or Path.cwd()
    return root / ".nova" / "approval-policy.json"


def _read_json(path: Path) -> dict:
    try:
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def _merge_rule(data: dict, rule: ProposedRule) -> dict:
    merged = dict(data)
    if rule.category == "tool":
        tools = dict(merged.get("tools") or {})
        tools[rule.tool_name] = "allow"
        merged["tools"] = tools
        return merged
    key = _SECTION_BY_CATEGORY[rule.category]
    section = dict(merged.get(key) or {})
    allow = list(section.get("allow") or [])
    if rule.value not in allow:
        allow.append(rule.value)
    section["allow"] = allow
    merged[key] = section
    return merged


def append_rule(rule: ProposedRule, *, target: str, project_root: Path | None = None) -> Path:
    """Merge ``rule`` into the target policy file and refresh the cache.

    Args:
        rule: The confirmed rule to persist.
        target: ``"project"`` or ``"global"``.
        project_root: Project root for ``"project"`` target (defaults to cwd).

    Returns:
        The path written.
    """
    path = _target_path(target, project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    merged = _merge_rule(_read_json(path), rule)

    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    os.close(fd)
    tmp_path = Path(tmp_name)
    try:
        tmp_path.write_text(json.dumps(merged, indent=2), encoding="utf-8")
        tmp_path.replace(path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()

    if target == "project":
        get_policy(project_root=project_root, refresh=True)
    else:
        get_policy(refresh=True)
    return path

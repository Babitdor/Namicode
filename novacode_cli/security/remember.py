"""UI-agnostic glue for applying a 'session' or 'always' remember decision.

Both front-ends (REPL + TUI) call this after the user picks "Allow for session"
or confirms "Always allow…", so the synthesize/persist logic lives in one place
and is testable without a terminal.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from novacode_cli.security import policy_writer
from novacode_cli.security.rule_synthesis import ProposedRule, synthesize_rule
from novacode_cli.security.session_allow import get_session_allow

if TYPE_CHECKING:
    from pathlib import Path


@dataclass
class RememberResult:
    """Outcome of :func:`apply_remember` for the UI to display."""

    rule: ProposedRule
    saved_path: Path | None  # None for session-only


def apply_remember(
    kind: str,
    tool_name: str,
    args: dict | None,
    *,
    target: str | None = None,
    project_root: Path | None = None,
    rule: ProposedRule | None = None,
) -> RememberResult:
    """Apply a remember decision.

    Args:
        kind: ``"session"`` (in-memory) or ``"always"`` (persist + in-memory).
        tool_name: The approved tool's name.
        args: The approved tool call's arguments (used to synthesize a rule).
        target: For ``"always"``, ``"project"`` (default) or ``"global"``.
        project_root: Project root for a project-target write.
        rule: An already-synthesized (possibly user-edited) rule; when given,
            synthesis is skipped.

    Returns:
        A :class:`RememberResult`.

    Raises:
        ValueError: If ``kind`` is not ``"session"`` or ``"always"``.
    """
    rule = rule or synthesize_rule(tool_name, args)
    if kind == "session":
        get_session_allow().add(rule)
        return RememberResult(rule=rule, saved_path=None)
    if kind == "always":
        path = policy_writer.append_rule(
            rule, target=target or "project", project_root=project_root
        )
        # Add to the session layer too so it takes effect even if a later policy
        # refresh races or the file write is slow to be picked up.
        get_session_allow().add(rule)
        return RememberResult(rule=rule, saved_path=path)
    msg = f"unknown remember kind: {kind!r}"
    raise ValueError(msg)

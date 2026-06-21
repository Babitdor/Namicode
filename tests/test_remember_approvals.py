"""Tests for the UI-agnostic apply_remember glue."""

from __future__ import annotations

import json

import pytest

from novacode_cli.security.policy import reset_policy_cache
from novacode_cli.security.remember import RememberResult, apply_remember
from novacode_cli.security.session_allow import get_session_allow, reset_session_allow


def test_session_adds_to_session_list_only():
    reset_session_allow()
    result = apply_remember("session", "shell", {"command": "npm run build"})
    assert isinstance(result, RememberResult)
    assert result.saved_path is None
    assert get_session_allow().matches("shell", {"command": "npm run build --prod"}) is True


def test_always_writes_file_and_session(tmp_path):  # noqa: ANN001
    reset_session_allow()
    reset_policy_cache()
    result = apply_remember(
        "always",
        "edit_file",
        {"file_path": "/src/app.py"},
        target="project",
        project_root=tmp_path,
    )
    assert result.saved_path == tmp_path / ".nova" / "approval-policy.json"
    data = json.loads(result.saved_path.read_text(encoding="utf-8"))
    assert "/src/**" in data["paths"]["allow"]
    assert get_session_allow().matches("edit_file", {"file_path": "/src/util.py"}) is True


def test_explicit_rule_overrides_synthesis(tmp_path):  # noqa: ANN001
    reset_session_allow()
    reset_policy_cache()
    from novacode_cli.security.rule_synthesis import ProposedRule

    edited = ProposedRule("paths", "/src/app.py", "exact file", "edit_file")
    result = apply_remember(
        "always",
        "edit_file",
        {"file_path": "/src/app.py"},
        target="project",
        project_root=tmp_path,
        rule=edited,
    )
    data = json.loads(result.saved_path.read_text(encoding="utf-8"))
    assert data["paths"]["allow"] == ["/src/app.py"]


def test_unknown_kind_raises():
    with pytest.raises(ValueError, match="unknown remember kind"):
        apply_remember("forever", "shell", {"command": "ls"})


def test_always_write_failure_degrades_to_session(tmp_path, monkeypatch):  # noqa: ANN001
    reset_session_allow()
    reset_policy_cache()
    from novacode_cli.security import policy_writer

    def _boom(*_args: object, **_kwargs: object) -> object:
        msg = "disk full"
        raise OSError(msg)

    monkeypatch.setattr(policy_writer, "append_rule", _boom)
    result = apply_remember(
        "always", "shell", {"command": "ls"}, target="project", project_root=tmp_path
    )
    # Persist failed, but the rule is still active for this session and no raise.
    assert result.saved_path is None
    assert result.error is not None
    assert "disk full" in result.error
    assert get_session_allow().matches("shell", {"command": "ls -la"}) is True
    reset_session_allow()

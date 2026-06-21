"""Tests for REPL interpretation of session/always remember decisions."""

from __future__ import annotations

import types

from novacode_cli.security.policy import reset_policy_cache
from novacode_cli.security.session_allow import get_session_allow, reset_session_allow


class _Status:
    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass


def _req(name, args):  # noqa: ANN001, ANN202
    return {"action_requests": [{"name": name, "args": args}]}


async def test_repl_session_marker_adds_rule(monkeypatch):  # noqa: ANN001
    import novacode_cli.ui.hitl_approval as h

    reset_session_allow()
    reset_policy_cache()
    monkeypatch.setattr(
        h,
        "prompt_for_batch_approval",
        lambda reqs, aid: [{"type": "allow_session"}],  # noqa: ARG005
    )
    session_state = types.SimpleNamespace(auto_approve=False, plan_mode_enabled=False)
    decisions, any_rejected, _ = await h.process_hitl_approval(
        _req("shell", {"command": "npm run build"}),
        session_state,
        "nova-agent",
        None,
        False,  # noqa: FBT003
        _Status(),
    )
    assert decisions[0]["type"] == "approve"
    assert any_rejected is False
    assert get_session_allow().matches("shell", {"command": "npm run build --prod"}) is True
    reset_session_allow()


async def test_repl_always_marker_writes_project(monkeypatch, tmp_path):  # noqa: ANN001
    import novacode_cli.ui.hitl_approval as h

    reset_session_allow()
    reset_policy_cache()
    monkeypatch.setattr(
        h,
        "prompt_for_batch_approval",
        lambda reqs, aid: [{"type": "allow_always"}],  # noqa: ARG005
    )
    monkeypatch.setattr(h, "_confirm_remember", lambda rule: ("project", None))  # noqa: ARG005
    monkeypatch.setattr(h.Path, "cwd", staticmethod(lambda: tmp_path))
    session_state = types.SimpleNamespace(auto_approve=False, plan_mode_enabled=False)
    decisions, _, _ = await h.process_hitl_approval(
        _req("edit_file", {"file_path": "/src/app.py"}),
        session_state,
        "nova-agent",
        None,
        False,  # noqa: FBT003
        _Status(),
    )
    assert decisions[0]["type"] == "approve"
    assert (tmp_path / ".nova" / "approval-policy.json").is_file()
    reset_session_allow()


async def test_repl_always_cancel_falls_back_to_approve_once(monkeypatch):  # noqa: ANN001
    import novacode_cli.ui.hitl_approval as h

    reset_session_allow()
    reset_policy_cache()
    monkeypatch.setattr(
        h,
        "prompt_for_batch_approval",
        lambda reqs, aid: [{"type": "allow_always"}],  # noqa: ARG005
    )
    monkeypatch.setattr(h, "_confirm_remember", lambda rule: (None, None))  # noqa: ARG005 — cancelled
    session_state = types.SimpleNamespace(auto_approve=False, plan_mode_enabled=False)
    decisions, _, _ = await h.process_hitl_approval(
        _req("shell", {"command": "ls"}),
        session_state,
        "nova-agent",
        None,
        False,  # noqa: FBT003
        _Status(),
    )
    assert decisions[0]["type"] == "approve"
    assert get_session_allow().matches("shell", {"command": "ls -la"}) is False
    reset_session_allow()

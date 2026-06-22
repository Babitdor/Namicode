"""Plan-approval offers exactly three outcomes: auto / manual / refine.

The old flow had four options (auto, manual, reject, edit) where reject and
edit did nearly the same thing. These tests pin the collapsed set and its
action mapping via the input-based fallback path (forced by making the raw-tty
branch fail), which is what runs on Windows / non-interactive shells anyway.
"""

from __future__ import annotations

import builtins
from typing import TYPE_CHECKING

import novacode_cli.ui.question_prompt as qp

if TYPE_CHECKING:
    import pytest

_TODOS = [{"content": "Do the thing", "status": "pending"}]


def _drive(monkeypatch: pytest.MonkeyPatch, *responses: str) -> None:
    """Force the non-tty fallback and feed scripted ``input()`` responses."""

    def _no_tty() -> int:
        raise OSError

    monkeypatch.setattr(qp.sys.stdin, "fileno", _no_tty)
    it = iter(responses)
    monkeypatch.setattr(builtins, "input", lambda *_a, **_k: next(it))


def test_auto_maps_to_proceed_auto(monkeypatch: pytest.MonkeyPatch) -> None:
    _drive(monkeypatch, "a")
    result = qp.prompt_for_plan_approval(todos=_TODOS)
    assert result["approved"] is True
    assert result["action"] == "proceed_auto"


def test_manual_maps_to_proceed_manual(monkeypatch: pytest.MonkeyPatch) -> None:
    _drive(monkeypatch, "m")
    result = qp.prompt_for_plan_approval(todos=_TODOS)
    assert result["approved"] is True
    assert result["action"] == "proceed_manual"


def test_refine_stays_in_plan_mode_with_feedback(monkeypatch: pytest.MonkeyPatch) -> None:
    # 'r' picks refine, then the follow-up input is the requested changes.
    _drive(monkeypatch, "r", "use a dataclass instead")
    result = qp.prompt_for_plan_approval(todos=_TODOS)
    assert result["approved"] is False
    assert result["action"] == "refine"
    assert result["feedback"] == "use a dataclass instead"


def test_invalid_choice_defaults_to_refine(monkeypatch: pytest.MonkeyPatch) -> None:
    # Unknown input must not approve the plan — default to the safe 'refine'.
    _drive(monkeypatch, "garbage", "")
    result = qp.prompt_for_plan_approval(todos=_TODOS)
    assert result["approved"] is False
    assert result["action"] == "refine"


def test_no_reject_or_edit_actions_remain(monkeypatch: pytest.MonkeyPatch) -> None:
    # The retired actions must never come back from the prompt.
    for key in ("a", "m"):
        _drive(monkeypatch, key)
        assert qp.prompt_for_plan_approval(todos=_TODOS)["action"] not in {"reject", "edit"}

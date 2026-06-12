"""Tests for adversarial skill debate — the critic pass before a skill is frozen."""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING

from novacode_cli.hermes.skill_debate import debate_skill_spec

if TYPE_CHECKING:
    import pytest

SPEC = {"name": "do-x", "description": "Use when X", "body": "## Procedure\n1. step"}


class FakeModel:
    def __init__(self, text: str) -> None:
        self._text = text

    async def ainvoke(self, messages: list, config: dict | None = None) -> SimpleNamespace:  # noqa: ARG002
        return SimpleNamespace(content=self._text)


class FakeModelError:
    async def ainvoke(self, messages: list, config: dict | None = None) -> SimpleNamespace:  # noqa: ARG002
        msg = "boom"
        raise RuntimeError(msg)


async def test_disabled_skips(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("NOVA_SKILL_DEBATE", "0")
    spec, verdict = await debate_skill_spec(SPEC)
    assert spec is SPEC
    assert verdict == "skipped"


async def test_approve_keeps_original(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("NOVA_SKILL_DEBATE", "1")
    spec, verdict = await debate_skill_spec(
        SPEC, model=FakeModel("<verdict>approve</verdict>")
    )
    assert verdict == "approved"
    assert spec == SPEC


async def test_reject_returns_none(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("NOVA_SKILL_DEBATE", "1")
    spec, verdict = await debate_skill_spec(
        SPEC, model=FakeModel("<verdict>reject</verdict>")
    )
    assert spec is None
    assert verdict == "rejected"


async def test_revise_returns_revised_spec(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("NOVA_SKILL_DEBATE", "1")
    revised = (
        "<verdict>revise</verdict>\n"
        "<skill><name>do-x</name><description>Use when X, sharper</description>"
        "<body>## Procedure\n1. better step</body></skill>"
    )
    spec, verdict = await debate_skill_spec(SPEC, model=FakeModel(revised))
    assert verdict == "revised"
    assert "better step" in spec["body"]


async def test_no_verdict_defaults_to_approve(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("NOVA_SKILL_DEBATE", "1")
    spec, verdict = await debate_skill_spec(SPEC, model=FakeModel("looks fine to me"))
    assert verdict == "approved"
    assert spec == SPEC


async def test_model_error_degrades_to_approve(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("NOVA_SKILL_DEBATE", "1")
    spec, verdict = await debate_skill_spec(SPEC, model=FakeModelError())
    assert spec is SPEC
    assert verdict == "error"

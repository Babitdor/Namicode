"""Tests for the ``/prompt evolve`` manual evolution lever.

Covers the command dispatch: unknown-template rejection, the already-under-test
guard, and the happy path that stages a candidate via ``run_evolution``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from novacode_cli.commands.prompt_handler import handle_prompt_command

if TYPE_CHECKING:
    from pathlib import Path


class _FakeEngine:
    """Minimal stand-in for PromptEvolutionEngine with the surface the handler uses."""

    def __init__(self, root: Path) -> None:
        self.calls: list[str] = []
        self.root = root
        self._normalise_result = "test_tpl.jinja"
        self._evolution_wrote_candidate = False

    def _normalise_name(self, name: str) -> str | None:
        self.calls.append(f"normalise:{name}")
        return self._normalise_result

    def _dir(self, name: str) -> Path:
        return self.root / name.removesuffix(".jinja")

    async def run_evolution(self, name: str, evidence: str) -> None:
        self.calls.append(f"evolve:{name}:{evidence}")
        if self._evolution_wrote_candidate:
            d = self._dir(name)
            d.mkdir(parents=True, exist_ok=True)
            (d / "candidate.jinja").write_text("NEW", encoding="utf-8")


class _FakeConsole:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def print(self, *parts: object) -> None:
        self.lines.append("".join(str(p) for p in parts))


@pytest.fixture
def fake_engine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> _FakeEngine:
    eng = _FakeEngine(tmp_path)
    monkeypatch.setattr("novacode_cli.commands.prompt_handler._engine", lambda: eng)
    return eng


async def _run(cmd: str, console: _FakeConsole) -> bool:
    return await handle_prompt_command(cmd, None, console)  # type: ignore[arg-type]


class TestPromptEvolve:
    async def test_evolve_stages_candidate(self, fake_engine: _FakeEngine):
        console = _FakeConsole()
        fake_engine._evolution_wrote_candidate = True
        handled = await _run("evolve test_tpl", console)
        assert handled is True
        assert "evolve:test_tpl.jinja:" in fake_engine.calls
        assert any("Candidate staged" in line for line in console.lines)

    async def test_evolve_unknown_template_rejected(self, fake_engine: _FakeEngine):
        console = _FakeConsole()
        fake_engine._normalise_result = None
        await _run("evolve nope", console)
        assert not any(c.startswith("evolve:") for c in fake_engine.calls)
        assert any("Unknown template" in line for line in console.lines)

    async def test_evolve_skips_when_candidate_under_test(self, fake_engine: _FakeEngine):
        console = _FakeConsole()
        d = fake_engine._dir("test_tpl.jinja")
        d.mkdir(parents=True, exist_ok=True)
        (d / "candidate.jinja").write_text("EXISTING", encoding="utf-8")
        await _run("evolve test_tpl", console)
        assert not any(c.startswith("evolve:") for c in fake_engine.calls)
        assert any("already under A/B test" in line for line in console.lines)

    async def test_evolve_requires_template_arg(self, fake_engine: _FakeEngine):
        console = _FakeConsole()
        await _run("evolve", console)
        assert not any(c.startswith("evolve:") for c in fake_engine.calls)
        assert any("Usage" in line for line in console.lines)

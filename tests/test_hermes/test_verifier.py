"""Tests for the inline verification loop (Loop-Engineering Enhancement 1).

Covers verdict parsing (incl. fail-open), grading via a fake model, outcome
logging, and the ``run_with_verification`` wrapper's pass / retry / exhaust /
error-passthrough behaviour over a faked ``iterate_agent_events``.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import novacode_cli.core.verification_loop as vl
from novacode_cli import ui_events as ev
from novacode_cli.hermes import config
from novacode_cli.hermes.verifier import (
    InlineVerifier,
    VerifierVerdict,
    _parse_verdict,
    _summarize_file_ops,
)


class FakeStore:
    """Minimal async ``BaseStore`` stand-in (same shape as other Hermes tests)."""

    def __init__(self) -> None:
        self.data: dict[tuple, dict] = {}

    async def aget(self, namespace, key):
        ns = self.data.get(tuple(namespace), {})
        return SimpleNamespace(value=dict(ns[key])) if key in ns else None

    async def aput(self, namespace, key, value):
        self.data.setdefault(tuple(namespace), {})[key] = dict(value)

    async def asearch(self, namespace):
        ns = self.data.get(tuple(namespace), {})
        return [SimpleNamespace(key=k, value=dict(v)) for k, v in ns.items()]


def _msg(text: str) -> ev.AssistantMessage:
    return ev.AssistantMessage(text=text, agent_name="Nova", agent_color="cyan")


def _fake_iterate(scripts: list[list]):
    """Return a stand-in for ``iterate_agent_events`` + a call recorder.

    ``scripts[i]`` is the event list the i-th invocation yields.
    """
    calls: dict = {"n": 0, "inputs": []}

    def _factory(user_input, agent, assistant_id, session_state, **kwargs):
        idx = calls["n"]
        calls["n"] += 1
        calls["inputs"].append(user_input)
        events = scripts[idx] if idx < len(scripts) else [ev.Done()]

        async def _gen():
            for e in events:
                yield e

        return _gen()

    return _factory, calls


class FakeVerifier:
    def __init__(self, verdicts, *, enabled=True, max_retries=3) -> None:
        self._verdicts = list(verdicts)
        self.enabled = enabled
        self.max_retries = max_retries
        self.graded: list = []
        self.logged: list = []

    async def grade(self, task, agent_output, file_ops, **kwargs):
        self.graded.append((task, agent_output, list(file_ops)))
        return self._verdicts.pop(0)

    async def log_outcome(self, thread_id, verdict, attempt):
        self.logged.append((thread_id, verdict.passed, attempt))


async def _collect(gen) -> list:
    return [e async for e in gen]


# ── verdict parsing ──────────────────────────────────────────────────────────


class TestParseVerdict:
    def test_pass(self):
        v = _parse_verdict(
            "<verdict><passed>true</passed><score>0.9</score><feedback></feedback></verdict>"
        )
        assert v.passed is True
        assert v.score == 0.9

    def test_fail_with_feedback(self):
        v = _parse_verdict(
            "<verdict><passed>false</passed><score>0.2</score>"
            "<feedback>add the missing test</feedback>"
            '<checks><check name="responsive" result="fail"/></checks></verdict>'
        )
        assert v.passed is False
        assert v.feedback == "add the missing test"
        assert "responsive:fail" in v.checks

    def test_missing_passed_is_fail_open(self):
        # Unparseable / missing <passed> must never block a turn.
        v = _parse_verdict("the model rambled without the verdict block")
        assert v.passed is True

    def test_score_clamped(self):
        v = _parse_verdict("<passed>true</passed><score>9.9</score>")
        assert v.score == 1.0


class TestSummariseFileOps:
    def test_success_and_error_lines(self):
        ok = SimpleNamespace(
            tool_name="write_file", display_path="/a.py", status="success", error=None
        )
        bad = SimpleNamespace(
            tool_name="edit_file", display_path="/b.py", status="error", error="boom"
        )
        lines = _summarize_file_ops([ok, bad])
        assert lines[0] == "write_file /a.py (success)"
        assert lines[1].startswith("edit_file /b.py (error)")
        assert "boom" in lines[1]


# ── grading ──────────────────────────────────────────────────────────────────


class TestGrade:
    async def test_grade_parses_model_output_and_tags_oob(self):
        model = SimpleNamespace()
        captured: dict = {}

        async def _ainvoke(messages, config=None):
            captured["config"] = config
            return SimpleNamespace(
                content="<verdict><passed>false</passed><score>0.1</score>"
                "<feedback>do better</feedback></verdict>"
            )

        model.ainvoke = _ainvoke
        verifier = InlineVerifier(model=model)
        verdict = await verifier.grade("task", "output", [])
        assert verdict.passed is False
        assert verdict.feedback == "do better"
        # OOB marker so the agent loop drops the streamed grading output.
        assert captured["config"]["metadata"]["nova_oob"] is True

    async def test_grade_fails_open_on_model_error(self):
        class BoomModel:
            async def ainvoke(self, *a, **k):
                raise RuntimeError("model down")

        verifier = InlineVerifier(model=BoomModel())
        verdict = await verifier.grade("task", "output", [])
        assert verdict.passed is True


class TestLogOutcome:
    async def test_writes_to_verification_log(self):
        store = FakeStore()
        verifier = InlineVerifier(store)
        await verifier.log_outcome("thread1", VerifierVerdict(False, 0.5, "x"), 2)
        items = await store.asearch(config.VERIFICATION_LOG_NS)
        assert len(items) == 1
        assert items[0].value["thread_id"] == "thread1"
        assert items[0].value["attempt"] == 2
        assert items[0].value["passed"] is False

    async def test_none_store_is_noop(self):
        verifier = InlineVerifier(None)
        await verifier.log_outcome("t", VerifierVerdict(True, 1.0, ""), 0)  # no raise


# ── the loop ─────────────────────────────────────────────────────────────────


class TestVerificationLoop:
    def _session(self):
        return SimpleNamespace(thread_id="t1")

    async def test_pass_yields_done_without_retry(self, monkeypatch):
        factory, calls = _fake_iterate([[_msg("answer"), ev.Done(had_response=True)]])
        monkeypatch.setattr(vl, "iterate_agent_events", factory)
        verifier = FakeVerifier([VerifierVerdict(True, 1.0, "")])
        out = await _collect(
            vl.run_with_verification("task", None, None, self._session(), verifier=verifier)
        )
        assert calls["n"] == 1
        assert sum(isinstance(e, ev.Done) for e in out) == 1
        assert not any(
            isinstance(e, ev.ContextMessage) and e.event_type == "nova_verification_retry"
            for e in out
        )

    async def test_fail_then_pass_retries_with_feedback(self, monkeypatch):
        factory, calls = _fake_iterate(
            [
                [_msg("bad"), ev.Done(had_response=True)],
                [_msg("good"), ev.Done(had_response=True)],
            ]
        )
        monkeypatch.setattr(vl, "iterate_agent_events", factory)
        verifier = FakeVerifier(
            [VerifierVerdict(False, 0.2, "fix it"), VerifierVerdict(True, 1.0, "")]
        )
        out = await _collect(
            vl.run_with_verification("task", None, None, self._session(), verifier=verifier)
        )
        assert calls["n"] == 2
        # The retry is re-driven with the labelled feedback prompt.
        assert calls["inputs"][1].startswith(f"{vl._RETRY_PREFIX} fix it")
        assert "Original task: task" in calls["inputs"][1]
        # Exactly one retry notice, one pass notice, one (final) Done.
        retry = [e for e in out if getattr(e, "event_type", "") == "nova_verification_retry"]
        passed = [e for e in out if getattr(e, "event_type", "") == "nova_verification_pass"]
        assert len(retry) == 1
        assert len(passed) == 1
        assert sum(isinstance(e, ev.Done) for e in out) == 1
        # Grading always scores against the ORIGINAL task, not the retry prompt.
        assert all(g[0] == "task" for g in verifier.graded)

    async def test_exhausts_retries_then_returns_best_effort(self, monkeypatch):
        script = [_msg("still bad"), ev.Done(had_response=True)]
        factory, calls = _fake_iterate([script, script, script])
        monkeypatch.setattr(vl, "iterate_agent_events", factory)
        verifier = FakeVerifier([VerifierVerdict(False, 0.1, "nope")] * 3, max_retries=1)
        out = await _collect(
            vl.run_with_verification("task", None, None, self._session(), verifier=verifier)
        )
        # initial attempt + exactly 1 retry == 2 agent runs.
        assert calls["n"] == 2
        fail = [e for e in out if getattr(e, "event_type", "") == "nova_verification_fail"]
        assert len(fail) == 1
        assert sum(isinstance(e, ev.Done) for e in out) == 1

    async def test_error_passes_through_without_grading(self, monkeypatch):
        factory, calls = _fake_iterate([[_msg("partial"), ev.Error("boom")]])
        monkeypatch.setattr(vl, "iterate_agent_events", factory)
        verifier = FakeVerifier([])  # grade must never be called
        out = await _collect(
            vl.run_with_verification("task", None, None, self._session(), verifier=verifier)
        )
        assert any(isinstance(e, ev.Error) for e in out)
        assert not any(isinstance(e, ev.Done) for e in out)
        assert verifier.graded == []

    async def test_disabled_verifier_skips_grading(self, monkeypatch):
        factory, calls = _fake_iterate([[_msg("answer"), ev.Done(had_response=True)]])
        monkeypatch.setattr(vl, "iterate_agent_events", factory)
        verifier = FakeVerifier([], enabled=False)
        out = await _collect(
            vl.run_with_verification("task", None, None, self._session(), verifier=verifier)
        )
        assert sum(isinstance(e, ev.Done) for e in out) == 1
        assert verifier.graded == []

    async def test_noop_turn_not_graded(self, monkeypatch):
        # No assistant text, no file ops -> nothing to verify.
        factory, calls = _fake_iterate([[ev.Done(had_response=False)]])
        monkeypatch.setattr(vl, "iterate_agent_events", factory)
        verifier = FakeVerifier([])
        out = await _collect(
            vl.run_with_verification("task", None, None, self._session(), verifier=verifier)
        )
        assert sum(isinstance(e, ev.Done) for e in out) == 1
        assert verifier.graded == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

"""Compaction: hierarchical summarization never overflows the summarizer, and
the summarizer budget tracks the model's context window."""

from __future__ import annotations

import asyncio

import pytest
from langchain_core.messages import AIMessage, HumanMessage

import novacode_cli.compaction as C


class _MockModel:
    """Records the input size of each summarization call."""

    model_name = "mock-model"

    def __init__(self) -> None:
        self.call_input_lens: list[int] = []

    async def ainvoke(self, msgs):
        self.call_input_lens.append(len(msgs[0].content))
        return AIMessage(content="SUMMARY")


def test_short_conversation_is_single_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(C, "_budget_chars", lambda _m, _cw=None: 2000)
    m = _MockModel()
    msgs = [HumanMessage(content="build X", id="h1"), AIMessage(content="done", id="a1")]
    out = asyncio.run(C.summarize_conversation(m, msgs))
    assert out == "SUMMARY"
    assert len(m.call_input_lens) == 1  # one LLM call


def test_long_conversation_summarizes_hierarchically(monkeypatch: pytest.MonkeyPatch) -> None:
    """A conversation far larger than the budget must be chunked (multiple calls)
    rather than sent in one overflowing call."""
    budget = 1500
    monkeypatch.setattr(C, "_budget_chars", lambda _m, _cw=None: budget)

    # Measure the fixed template overhead so we can assert each call's CONVERSATION
    # portion stays within budget (template + chunk <= template + budget).
    tmpl_only = len(C.render_template("summarization.jinja", focus_instructions="", conversation=""))

    m = _MockModel()
    msgs = [HumanMessage(content="x" * 400, id=f"h{i}") for i in range(30)]  # ~12k chars >> budget
    out = asyncio.run(C.summarize_conversation(m, msgs))

    assert isinstance(out, str) and out
    assert len(m.call_input_lens) > 1, "long conversation should be chunked, not one call"
    # No single call's conversation payload exceeds the budget.
    assert max(m.call_input_lens) <= tmpl_only + budget + 64


def test_budget_uses_explicit_window_then_falls_back() -> None:
    """An explicit context_window (the TUI passes the tracker's) is honored; a
    smaller window yields a smaller budget; a floor keeps tiny windows usable."""
    small = C._budget_chars(_MockModel(), context_window=8192)
    large = C._budget_chars(_MockModel(), context_window=200_000)
    assert small < large
    assert small >= 8000  # floor so tiny windows still summarize something


def test_explicit_small_window_forces_hierarchical(monkeypatch: pytest.MonkeyPatch) -> None:
    """A conversation bigger than the (small) window is chunked — no monkeypatching
    of _budget_chars, so this exercises the real window→budget path."""
    m = _MockModel()
    # 8192-token window → ~18k-char budget; make the convo clearly larger.
    msgs = [HumanMessage(content="z" * 1500, id=f"h{i}") for i in range(40)]  # ~60k chars
    out = asyncio.run(C.summarize_conversation(m, msgs, context_window=8192))
    assert out and len(m.call_input_lens) > 1  # hierarchical kicked in


# ── Q&A gap-filling (Meta-Harness port) ────────────────────────────────────
class _QAModel:
    """Template-aware mock: summaries → 'SUMMARY', the questions pass → two
    questions, the answer pass → two answers. Records every call's input."""

    model_name = "mock-model"

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.questions_calls = 0
        self.answer_calls = 0

    async def ainvoke(self, msgs):
        content = msgs[0].content
        self.calls.append(content)
        if "critical reviewer" in content:  # summarization_questions.jinja
            self.questions_calls += 1
            return AIMessage(content="Q1: What files were changed?\nQ2: What is pending?")
        if "context restorer" in content:  # summarization_answers.jinja
            self.answer_calls += 1
            return AIMessage(content="A1: src/main.py\nA2: tests are pending")
        return AIMessage(content="SUMMARY")


def test_qa_refinement_gapfills_long_conversation(monkeypatch: pytest.MonkeyPatch) -> None:
    """The hierarchical (lossy) path runs the Q&A gap-filling pass: questions are
    asked about the summary and answered from the conversation."""
    monkeypatch.setattr(C, "_budget_chars", lambda _m, _cw=None: 4000)
    m = _QAModel()
    msgs = [HumanMessage(content="x" * 400, id=f"h{i}") for i in range(30)]  # ~12k chars
    out = asyncio.run(C.summarize_conversation(m, msgs))

    assert "## Clarifying Q&A" in out
    assert "A1: src/main.py" in out
    assert m.questions_calls == 1
    assert m.answer_calls >= 1  # per-chunk answers + merge


def test_qa_refinement_skipped_when_nothing_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """When the questions pass reports nothing missing (NONE), the summary is
    returned unchanged — no Q&A block, no answer calls."""
    monkeypatch.setattr(C, "_budget_chars", lambda _m, _cw=None: 4000)

    class _NoneModel:
        model_name = "mock-model"

        async def ainvoke(self, msgs):
            if "critical reviewer" in msgs[0].content:
                return AIMessage(content="NONE")
            return AIMessage(content="SUMMARY")

    m = _NoneModel()
    msgs = [HumanMessage(content="x" * 400, id=f"h{i}") for i in range(30)]
    out = asyncio.run(C.summarize_conversation(m, msgs))
    assert out == "SUMMARY"
    assert "Clarifying Q&A" not in out


def test_qa_refinement_best_effort_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """A failure in the Q&A pass must never break compaction — the plain summary
    is returned."""
    monkeypatch.setattr(C, "_budget_chars", lambda _m, _cw=None: 4000)

    class _FailModel:
        model_name = "mock-model"

        async def ainvoke(self, msgs):
            if "critical reviewer" in msgs[0].content:
                raise RuntimeError("boom")
            return AIMessage(content="SUMMARY")

    m = _FailModel()
    msgs = [HumanMessage(content="x" * 400, id=f"h{i}") for i in range(30)]
    out = asyncio.run(C.summarize_conversation(m, msgs))
    assert out == "SUMMARY"
    assert "Clarifying Q&A" not in out

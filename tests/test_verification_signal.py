"""run_agent_stream grades the finished turn out-of-band when learning is on —
generating the verification_log + prompt-A/B quality signal in the TUI path
(previously only the CLI path produced it, so /prompt evolution had no data)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import novacode_cli.agent_stream as A
from novacode_cli import ui_events as ev


class _FakeVerifier:
    def __init__(self):
        self.graded: tuple | None = None
        self.logged = False

    async def grade(self, user_input, agent_output, file_ops):
        self.graded = (user_input, agent_output, list(file_ops))
        return SimpleNamespace(passed=True, feedback="")

    async def log_outcome(self, thread_id, verdict, retries):
        self.logged = True


def _fake_iterate_factory(events):
    async def _fake_iterate(*_args, **_kwargs):
        for e in events:
            yield e

    return _fake_iterate


async def _drain(agen):
    return [e async for e in agen]


@pytest.fixture(autouse=True)
def _no_ab_write(monkeypatch):
    # The prompt-A/B write hits the durable store; stub it in these unit tests.
    import novacode_cli.core.verification_loop as VL

    async def _noop(*, passed):  # noqa: ANN001
        return None

    monkeypatch.setattr(VL, "_record_prompt_ab_outcome", _noop)


async def test_turn_is_graded_when_learning_enabled(monkeypatch):
    fake = _FakeVerifier()
    monkeypatch.setattr(A, "_maybe_verifier", lambda: fake)
    monkeypatch.setattr(
        A,
        "run_with_goal",
        _fake_iterate_factory(
            [
                ev.AssistantMessage(text="the answer is 42", agent_name="Nova", agent_color="cyan"),
                ev.Done(had_response=True),
            ]
        ),
    )

    events = await _drain(
        A.run_agent_stream("what is 6x7?", object(), "nova-agent", SimpleNamespace(thread_id="t1"))
    )
    assert any(isinstance(e, ev.Done) for e in events)  # turn streamed normally
    # Drain the fire-and-forget grade task.
    for task in list(A._verification_tasks):
        await task

    assert fake.graded is not None
    assert fake.graded[0] == "what is 6x7?"
    assert fake.graded[1] == "the answer is 42"  # graded on the assistant output
    assert fake.logged is True


async def test_no_grading_when_learning_disabled(monkeypatch):
    monkeypatch.setattr(A, "_maybe_verifier", lambda: None)
    called = {"iterate": False}

    def _factory():
        async def _it(*_a, **_k):
            called["iterate"] = True
            yield ev.Done(had_response=True)

        return _it

    monkeypatch.setattr(A, "run_with_goal", _factory())
    events = await _drain(
        A.run_agent_stream("hi", object(), "nova-agent", SimpleNamespace(thread_id="t2"))
    )
    assert called["iterate"] is True
    assert any(isinstance(e, ev.Done) for e in events)
    assert not A._verification_tasks  # nothing spawned


async def test_noop_turn_is_not_graded(monkeypatch):
    fake = _FakeVerifier()
    monkeypatch.setattr(A, "_maybe_verifier", lambda: fake)
    monkeypatch.setattr(
        A, "run_with_goal", _fake_iterate_factory([ev.Done(had_response=False)])
    )
    await _drain(A.run_agent_stream("", object(), "nova-agent", SimpleNamespace(thread_id="t3")))
    for task in list(A._verification_tasks):
        await task
    assert fake.graded is None  # nothing produced → nothing to grade

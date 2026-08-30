"""The planning council: anonymity, ranked voting, and the approval gate.

Three properties are load-bearing and the rest of the feature is decoration
without them: evaluators must not learn who wrote a plan, the vote must reward
broad support rather than a loud plurality, and nothing may reach the coding
agent that the user did not explicitly approve. Most of this file pins those.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from novacode_cli import council_planner as cp


# ── Fakes ───────────────────────────────────────────────────────────────────


class _Reply:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeModel:
    """Answers each phase with canned JSON, and records what it was shown.

    Phase is detected from the system prompt, so the fake exercises the real
    prompt-building path rather than being handed a phase name.
    """

    def __init__(self, *, fail_agents: set[str] | None = None, judge_ok: bool = True):
        self.fail_agents = fail_agents or set()
        self.judge_ok = judge_ok
        self.seen: list[tuple[str, str]] = []  # (system, user)
        self._n = 0

    async def ainvoke(self, messages):
        system = messages[0][1]
        user = messages[1][1]
        self.seen.append((system, user))

        if "Judge of a planning council" in system:
            if not self.judge_ok:
                raise RuntimeError("judge offline")
            ids = sorted(set(_ids_in(user)))
            return _Reply(
                json.dumps(
                    {
                        "selected_plans": [
                            {
                                "proposal_id": pid,
                                "rank": i,
                                "score": 9.0 - i,
                                "reasoning": "Ranks on correctness and testability.",
                                "required_changes": ["Add a regression test."],
                            }
                            for i, pid in enumerate(ids[:3], 1)
                        ],
                        "rejected_proposals": [
                            {"proposal_id": p, "reason": "higher migration risk"}
                            for p in ids[3:]
                        ],
                        "confidence": 0.8,
                    }
                )
            )

        if '"ranking"' in system:
            return _Reply(json.dumps({"ranking": sorted(set(_ids_in(user)))}))

        if '"evaluations"' in system:
            return _Reply(
                json.dumps(
                    {
                        "evaluations": [
                            {
                                "proposal_id": pid,
                                "strengths": ["clear"],
                                "weaknesses": ["ignores retries"],
                                "missing_information": [],
                                "technical_risks": ["race on shutdown"],
                                "recommended_changes": ["bound the queue"],
                                "score": 7.5,
                            }
                            for pid in sorted(set(_ids_in(user)))
                        ]
                    }
                )
            )

        # Brainstorm. Fail for personas the test asked to fail.
        for agent in self.fail_agents:
            if agent in system or agent.lower() in system.lower():
                raise RuntimeError("provider down")
        self._n += 1
        return _Reply(
            json.dumps(
                {
                    "title": f"Plan {self._n}",
                    "summary": f"Approach number {self._n}.",
                    "problem_understanding": ["needs background execution"],
                    "approach": ["add a registry"],
                    "implementation_steps": ["create model", "wire the key"],
                    "files_likely_affected": ["novacode_cli/shell/jobs.py"],
                    "dependencies": [],
                    "tradeoffs": {"pros": ["small diff"], "cons": ["one global"]},
                    "risks": ["leaks a thread on cancel"],
                    "assumptions": ["single session"],
                    "testing_strategy": ["unit test the registry"],
                    "confidence": 0.7,
                }
            )
        )


def _ids_in(text: str) -> list[str]:
    import re

    return re.findall(r"proposal-\d+", text)


def _proposal(pid: str, agent: str = "architect", **kw) -> cp.Proposal:
    return cp.Proposal(id=pid, agent_id=agent, title=f"T{pid}", summary="s", **kw)


# ── Anonymity ───────────────────────────────────────────────────────────────


def test_anonymize_strips_the_authoring_agent():
    """The identity field must not survive into what an evaluator reads."""
    text = cp.anonymize([_proposal("proposal-01", "architect")])
    assert "proposal-01" in text
    assert "architect" not in text
    assert "agent_id" not in text


def test_anonymize_does_not_preserve_generation_order():
    """Fixed persona order would otherwise identify authors by position alone."""
    proposals = [_proposal(f"proposal-{i:02d}") for i in range(1, 9)]
    orders = {tuple(_ids_in(cp.anonymize(proposals))) for _ in range(40)}
    assert len(orders) > 1, "proposal order is deterministic — authorship leaks"


@pytest.mark.asyncio
async def test_no_persona_name_reaches_critics_or_voters():
    """End-to-end anonymity: the real prompts, not a unit-tested helper."""
    model = _FakeModel()
    async for _ in cp.run_planning_council("add background jobs", model):
        pass

    names = [p.name for p in cp.PLANNING_PERSONAS]
    for system, user in model.seen:
        if '"ranking"' in system or '"evaluations"' in system:
            for name in names:
                assert name not in user, f"{name} leaked into an evaluation prompt"


@pytest.mark.asyncio
async def test_vote_events_do_not_reveal_ballots():
    """A ballot leaked as it lands would let a viewer reconstruct who voted how."""
    events = [
        e
        async for e in cp.run_planning_council("t", _FakeModel())
        if e["event"] == "vote.submitted"
    ]
    assert events
    for event in events:
        assert "voter_id" not in event["payload"]
        assert "ranking" not in event["payload"]


# ── Ranked voting ───────────────────────────────────────────────────────────


def test_borda_rewards_broad_support_over_a_polarized_plurality():
    """The reason this is not first-past-the-post.

    B is nobody's favourite but everyone's solid second; A is half the council's
    first choice and half's last. A wins a plurality vote; B is the better
    candidate to hand a judge, and must win here.
    """
    candidates = ["A", "B", "C"]
    ballots = [
        cp.Ballot("v1", ["A", "B", "C"]),
        cp.Ballot("v2", ["A", "B", "C"]),
        cp.Ballot("v3", ["C", "B", "A"]),
        cp.Ballot("v4", ["C", "B", "A"]),
        cp.Ballot("v5", ["B", "C", "A"]),
    ]
    tally = cp.tally_ranked(ballots, candidates)
    assert tally["order"][0] == "B"
    assert tally["first_choice"] == {"A": 2, "B": 1, "C": 2}


def test_tally_ignores_unknown_and_duplicate_entries():
    """A malformed ballot loses its bad entries, not the whole vote."""
    tally = cp.tally_ranked(
        [cp.Ballot("v1", ["A", "A", "nope", "B"])], ["A", "B"]
    )
    assert tally["scores"]["A"] == 2  # first place of 2 candidates
    assert tally["scores"]["B"] == 1  # counted second, not fourth
    assert tally["first_choice"]["A"] == 1


def test_entropy_separates_consensus_from_a_dead_split():
    unanimous = cp.tally_ranked(
        [cp.Ballot(f"v{i}", ["A", "B"]) for i in range(4)], ["A", "B"]
    )
    split = cp.tally_ranked(
        [cp.Ballot("v1", ["A"]), cp.Ballot("v2", ["B"])], ["A", "B"]
    )
    assert unanimous["entropy"] == 0.0
    assert split["entropy"] == pytest.approx(1.0)


def test_tally_survives_zero_ballots():
    tally = cp.tally_ranked([], ["A", "B"])
    assert tally["entropy"] == 0.0
    assert tally["ballots"] == 0


# ── Approval gate ───────────────────────────────────────────────────────────


def _awaiting_run() -> cp.CouncilRun:
    run = cp.CouncilRun(id="council-test", prompt="do a thing")
    run.proposals = [_proposal("proposal-01"), _proposal("proposal-02")]
    run.judgment = cp.Judgment(
        selected_plans=[
            cp.SelectedPlan("proposal-02", 1, 9.0, "correctness"),
            cp.SelectedPlan("proposal-01", 2, 8.0, "feasibility"),
        ]
    )
    run.status = cp.AWAITING_APPROVAL
    return run


@pytest.mark.parametrize(
    "status", [cp.BRAINSTORMING, cp.CANCELLED, cp.REJECTED, cp.FAILED, cp.APPROVED]
)
def test_approve_refuses_any_state_but_awaiting_approval(status):
    """The authorization boundary: no replaying a dead run into an execution."""
    run = _awaiting_run()
    run.status = status
    with pytest.raises(cp.CouncilApprovalError):
        cp.approve(run, 1)


def test_approve_rejects_an_out_of_range_choice():
    for choice in (0, 3, -1):
        with pytest.raises(cp.CouncilApprovalError):
            cp.approve(_awaiting_run(), choice)


def test_approve_selects_by_presented_rank_not_proposal_number():
    """The user picks '1' meaning the top-ranked plan, not proposal-01."""
    run = _awaiting_run()
    cp.approve(run, 1)
    assert run.approved_proposal_id == "proposal-02"
    assert run.status == cp.APPROVED


def test_run_ends_awaiting_approval_and_produces_no_plan_on_its_own():
    """Nothing is handed off until a human calls approve()."""
    run = _awaiting_run()
    assert run.approved_plan == ""
    assert run.approved_proposal_id is None


@pytest.mark.asyncio
async def test_council_never_executes_and_stops_for_the_user():
    events = [e async for e in cp.run_planning_council("t", _FakeModel())]
    assert events[-1]["event"] == "approval.requested"
    assert events[-1]["status"] == cp.AWAITING_APPROVAL
    assert not any(e["event"].startswith("coding.") for e in events)


# ── Read-only by construction ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_council_binds_no_tools_to_the_model():
    """Read-only is enforced by never handing the agents a tool, not by asking.

    A model with bind_tools available must still never have it called; if this
    fails, a council agent could gain a file-write or shell tool.
    """
    calls = []

    class _ToolModel(_FakeModel):
        def bind_tools(self, *a, **k):  # pragma: no cover — must not run
            calls.append(a)
            return self

    async for _ in cp.run_planning_council("t", _ToolModel()):
        pass
    assert calls == []


# ── Failure handling ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_one_failed_agent_does_not_kill_the_council():
    model = _FakeModel(fail_agents={"The Architect"})
    events = [e async for e in cp.run_planning_council("t", model)]
    kinds = [e["event"] for e in events]
    assert "agent.failed" in kinds
    assert kinds[-1] == "approval.requested"


@pytest.mark.asyncio
async def test_too_few_proposals_fails_loudly_instead_of_rubber_stamping():
    """With one plan there is nothing to compare, and a 'winner' would be a lie."""
    single = [cp.PLANNING_PERSONAS[0], cp.PLANNING_PERSONAS[1]]
    model = _FakeModel(fail_agents={"The Pragmatist"})
    events = [
        e async for e in cp.run_planning_council("t", model, members=single)
    ]
    assert events[-1]["event"] == "council.failed"
    assert "at least" in events[-1]["payload"]["reason"]


@pytest.mark.asyncio
async def test_judge_failure_falls_back_to_the_vote_and_says_so():
    model = _FakeModel(judge_ok=False)
    run_events = [e async for e in cp.run_planning_council("t", model)]
    done = run_events[-1]
    assert done["event"] == "approval.requested"
    assert done["payload"]["count"] > 0
    judged = next(e for e in run_events if e["event"] == "judge.completed")
    assert judged["payload"]["fell_back_to_vote"] is True


@pytest.mark.asyncio
async def test_malformed_json_is_retried_once_then_the_agent_is_dropped():
    class _Garbage(_FakeModel):
        def __init__(self):
            super().__init__()
            self.attempts = 0

        async def ainvoke(self, messages):
            if "planning council" in messages[0][1] and "Judge" not in messages[0][1]:
                self.attempts += 1
                return _Reply("no json here, sorry")
            return await super().ainvoke(messages)

    model = _Garbage()
    events = [e async for e in cp.run_planning_council("t", model)]
    assert events[-1]["event"] == "council.failed"
    # Two attempts per agent, and no third.
    assert model.attempts == 2 * len(cp.PLANNING_PERSONAS)


# ── Artifacts ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_is_persisted_and_reloads_intact(tmp_path):
    store = cp.CouncilArtifactStore(tmp_path)
    run_id = None
    async for event in cp.run_planning_council("t", _FakeModel(), store=store):
        run_id = event["run_id"]

    directory = store.run_dir(run_id)
    for name in (
        "prompt.md",
        "council-state.json",
        "proposals.json",
        "critiques.json",
        "votes.json",
        "judgment.json",
        "selected-plans.md",
    ):
        assert (directory / name).is_file(), f"missing artifact: {name}"

    reloaded = store.load(run_id)
    assert reloaded is not None
    assert reloaded.status == cp.AWAITING_APPROVAL
    assert len(reloaded.proposals) == len(cp.PLANNING_PERSONAS)
    assert reloaded.judgment is not None
    assert reloaded.ranked_plans()[0].rank == 1


def test_a_reloaded_run_can_still_be_approved(tmp_path):
    """State survives an interruption — the point of writing every phase."""
    store = cp.CouncilArtifactStore(tmp_path)
    store.save(_awaiting_run())
    reloaded = store.load("council-test")
    assert reloaded is not None
    plan = cp.approve(reloaded, 1, store=store)
    assert "# Implementation Plan" in plan
    assert (store.run_dir("council-test") / "approved-plan.md").is_file()


def test_load_of_a_missing_or_corrupt_run_returns_none(tmp_path):
    store = cp.CouncilArtifactStore(tmp_path)
    assert store.load("nope") is None
    directory = store.run_dir("broken")
    directory.mkdir(parents=True)
    (directory / "council-state.json").write_text("{not json", encoding="utf-8")
    assert store.load("broken") is None


def test_history_is_newest_first(tmp_path):
    store = cp.CouncilArtifactStore(tmp_path)
    for rid in ("council-20260101-000000-aaaa", "council-20260830-120000-bbbb"):
        run = cp.CouncilRun(id=rid, prompt="p")
        store.save(run)
    assert store.history()[0] == "council-20260830-120000-bbbb"
    assert store.latest().id == "council-20260830-120000-bbbb"


# ── Handoff ─────────────────────────────────────────────────────────────────


def test_handoff_states_it_was_approved_and_carries_the_conditions():
    run = _awaiting_run()
    run.proposals[1].implementation_steps = ["step one", "step two"]
    run.proposals[1].risks = ["may deadlock"]
    run.judgment.selected_plans[0].required_changes = ["bound the queue"]
    plan = cp.approve(run, 1)

    assert "Approved by the user" in plan
    assert run.id in plan
    assert "- [ ] step one" in plan  # actionable checklist, not prose
    assert "bound the queue" in plan
    assert "may deadlock" in plan


def test_handoff_excludes_the_rejected_alternatives():
    """The executor gets the decision, not the debate it would relitigate."""
    run = _awaiting_run()
    run.proposals[0].title = "REJECTED ALTERNATIVE TITLE"
    run.proposals[0].summary = "an approach the council did not pick"
    plan = cp.approve(run, 1)
    assert "REJECTED ALTERNATIVE TITLE" not in plan
    assert "did not pick" not in plan


def test_revision_notes_reach_the_next_round_and_the_final_plan():
    run = _awaiting_run()
    cp.request_revision(run, "use the simpler state machine from plan 3")
    assert run.status == cp.INITIALIZING
    assert run.revision_notes == ["use the simpler state machine from plan 3"]

    run.status = cp.AWAITING_APPROVAL
    plan = cp.approve(run, 1)
    assert "simpler state machine" in plan


# ── Presentation ────────────────────────────────────────────────────────────


def test_disagreement_is_surfaced_not_smoothed_over():
    run = _awaiting_run()
    run.tally = {"entropy": 1.0}
    assert "did not converge" in cp.render_plans(run)


def test_a_vote_fallback_is_labelled_as_a_preference_not_a_verdict():
    run = _awaiting_run()
    run.judgment.fell_back_to_vote = True
    assert "not a verdict" in cp.render_plans(run)


def test_confident_consensus_gets_no_warning_banner():
    run = _awaiting_run()
    run.tally = {"entropy": 0.1}
    rendered = cp.render_plans(run)
    assert "did not converge" not in rendered
    assert "#1 Recommended" in rendered


# ── Failure reporting ───────────────────────────────────────────────────────


def test_timeout_is_configurable_and_ignores_nonsense(monkeypatch):
    monkeypatch.delenv("NOVA_COUNCIL_TIMEOUT", raising=False)
    assert cp.agent_timeout() == cp.AGENT_TIMEOUT
    monkeypatch.setenv("NOVA_COUNCIL_TIMEOUT", "45")
    assert cp.agent_timeout() == 45.0
    for bad in ("banana", "0", "-5", ""):
        monkeypatch.setenv("NOVA_COUNCIL_TIMEOUT", bad)
        assert cp.agent_timeout() == cp.AGENT_TIMEOUT, f"accepted {bad!r}"


@pytest.mark.asyncio
async def test_a_slow_model_is_reported_as_a_timeout_not_a_mystery(monkeypatch):
    """The council must say WHY an agent produced nothing.

    A timeout and a model that cannot emit JSON look identical to the user
    otherwise, and they need different fixes — so the reason names the knob.
    """
    monkeypatch.setenv("NOVA_COUNCIL_TIMEOUT", "0.05")

    class _Slow:
        async def ainvoke(self, messages):
            await asyncio.sleep(5)

    events = [
        e
        async for e in cp.run_planning_council("t", _Slow())
        if e["event"] in ("agent.failed", "council.failed")
    ]
    failed = [e for e in events if e["event"] == "agent.failed"]
    assert failed, "no agent.failed event carried the reason"
    assert "timed out" in failed[0]["payload"]["reason"]
    assert "NOVA_COUNCIL_TIMEOUT" in failed[0]["payload"]["reason"]
    # And the run-level failure repeats it rather than guessing.
    final = [e for e in events if e["event"] == "council.failed"][0]
    assert "timed out" in final["payload"]["reason"]


@pytest.mark.asyncio
async def test_a_model_that_never_emits_json_says_so():
    class _Prose:
        async def ainvoke(self, messages):
            return _Reply("Certainly! Here is my plan, in prose, at length.")

    events = [
        e
        async for e in cp.run_planning_council("t", _Prose())
        if e["event"] == "agent.failed"
    ]
    assert events
    assert "without JSON" in events[0]["payload"]["reason"]


@pytest.mark.asyncio
async def test_an_empty_reply_is_distinguished_from_a_non_json_one():
    class _Empty:
        async def ainvoke(self, messages):
            return _Reply("")

    events = [
        e
        async for e in cp.run_planning_council("t", _Empty())
        if e["event"] == "agent.failed"
    ]
    assert "empty content" in events[0]["payload"]["reason"]


def test_failure_summary_names_the_dominant_cause():
    run = cp.CouncilRun(id="r", prompt="p")
    run.failures = [
        {"agent_id": "a", "phase": "brainstorming", "reason": "timed out after 60s"},
        {"agent_id": "b", "phase": "brainstorming", "reason": "timed out after 60s"},
        {"agent_id": "c", "phase": "brainstorming", "reason": "replied without JSON"},
    ]
    summary = cp._failure_summary(run)
    assert "2 of 3" in summary
    assert "timed out" in summary


def test_failure_summary_is_honest_when_nothing_was_recorded():
    assert "No agent reported" in cp._failure_summary(cp.CouncilRun(id="r", prompt="p"))


@pytest.mark.asyncio
async def test_reasons_are_recorded_on_the_run_for_later_inspection():
    class _Prose:
        async def ainvoke(self, messages):
            return _Reply("no json")

    store_run = None
    async for event in cp.run_planning_council("t", _Prose()):
        store_run = event
    assert store_run["event"] == "council.failed"
    assert "without JSON" in store_run["payload"]["reason"]


# ── Judge output normalisation (both seen in a live run) ────────────────────


@pytest.mark.asyncio
async def test_a_judge_that_returns_one_plan_is_backfilled_to_a_full_slate():
    """Observed live. One pick defeats a feature about choosing BETWEEN plans."""

    class _StingyJudge(_FakeModel):
        async def ainvoke(self, messages):
            if "Judge of a planning council" in messages[0][1]:
                pid = sorted(set(_ids_in(messages[1][1])))[0]
                return _Reply(
                    json.dumps(
                        {
                            "selected_plans": [
                                {"proposal_id": pid, "rank": 1, "score": 9.0,
                                 "reasoning": "best on correctness"}
                            ],
                            "confidence": 0.9,
                        }
                    )
                )
            return await super().ainvoke(messages)

    events = [e async for e in cp.run_planning_council("t", _StingyJudge())]
    plans = events[-1]["payload"]["count"]
    assert plans == 3, f"user was offered {plans} plan(s) to choose between"


@pytest.mark.asyncio
async def test_backfilled_plans_say_they_came_from_the_vote_not_the_judge():
    """A filler plan must not masquerade as a rubric assessment."""

    class _StingyJudge(_FakeModel):
        async def ainvoke(self, messages):
            if "Judge of a planning council" in messages[0][1]:
                pid = sorted(set(_ids_in(messages[1][1])))[0]
                return _Reply(json.dumps({"selected_plans": [
                    {"proposal_id": pid, "rank": 1, "score": 9.0,
                     "reasoning": "best on correctness"}]}))
            return await super().ainvoke(messages)

    events = [e async for e in cp.run_planning_council("t", _StingyJudge())]
    plans = events[-1 - 1]["payload"]["plans"]  # plans.selected
    assert "did not rank this plan" in plans[1]["reasoning"]


def test_a_zero_to_one_judge_score_is_rescaled_not_shown_as_nine_percent():
    """A live judge returned 0.88 meaning excellent; 0.9/10 reads as terrible."""
    plans = [
        cp.SelectedPlan("proposal-01", 1, 0.88),
        cp.SelectedPlan("proposal-02", 2, 0.71),
    ]
    cp._rescale_scores(plans)
    assert plans[0].score == 8.8
    assert plans[1].score == 7.1


def test_an_already_ten_point_score_is_left_alone():
    plans = [cp.SelectedPlan("proposal-01", 1, 8.8)]
    cp._rescale_scores(plans)
    assert plans[0].score == 8.8


def test_rescaling_survives_an_all_zero_slate():
    plans = [cp.SelectedPlan("proposal-01", 1, 0.0)]
    cp._rescale_scores(plans)
    assert plans[0].score == 0.0

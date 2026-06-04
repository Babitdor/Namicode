"""Tests for subagent resilience hardening.

Subagents get no retry middleware from deepagents, so a transient provider
5xx/429 during a subagent's model call kills it (this is what broke /init's
semantic-extraction subagents). ``_harden_subagent_specs`` returns resilient
copies of the specs: each declarative subagent gets a ModelRetryMiddleware and
its ``interrupt_on`` cleared. It must NOT mutate the (cached) input specs, or a
second ``create_agent_with_config`` build would accumulate a duplicate retry
middleware and langchain aborts with "duplicate middleware instances".
"""

from langchain.agents.middleware import ModelRetryMiddleware

from novacode_cli.agents.core_agent import _harden_subagent_specs


def test_declarative_specs_get_retry_first_and_no_interrupts():
    specs = [
        {"name": "bug-fix", "description": "d", "system_prompt": "p", "tools": []},
        {"name": "general-purpose", "description": "d", "system_prompt": "p"},
    ]
    out = _harden_subagent_specs(specs)

    for s in out:
        # interrupt_on cleared (subagents never raise nested HITL).
        assert s["interrupt_on"] == {}
        # A ModelRetryMiddleware is present and FIRST (outermost of the user mw).
        mw = s["middleware"]
        assert isinstance(mw[0], ModelRetryMiddleware)


def test_existing_subagent_middleware_is_preserved_after_retry():
    sentinel = object()
    specs = [{"name": "x", "system_prompt": "p", "middleware": [sentinel]}]
    out = _harden_subagent_specs(specs)
    mw = out[0]["middleware"]
    assert isinstance(mw[0], ModelRetryMiddleware)
    assert mw[1] is sentinel


def test_fresh_retry_instance_per_spec_not_shared():
    specs = [
        {"name": "a", "system_prompt": "p"},
        {"name": "b", "system_prompt": "p"},
    ]
    out = _harden_subagent_specs(specs)
    # Middleware binds to a graph; each spec must get its own instance.
    assert out[0]["middleware"][0] is not out[1]["middleware"][0]


def test_does_not_mutate_input_specs():
    # The inputs may be cached/shared dicts reused across builds — leave them be.
    specs = [{"name": "a", "system_prompt": "p"}]
    original = specs[0]
    _harden_subagent_specs(specs)
    assert "middleware" not in original
    assert "interrupt_on" not in original


def test_repeated_hardening_never_accumulates_retry_middleware():
    # Simulate two create_agent_with_config builds reusing the SAME cached spec.
    cached = {"name": "a", "system_prompt": "p"}
    cache = [cached]
    first = _harden_subagent_specs(cache)
    second = _harden_subagent_specs(cache)
    for built in (first, second):
        retries = [
            m for m in built[0]["middleware"]
            if isinstance(m, ModelRetryMiddleware)
        ]
        # Exactly one retry middleware — never two (the duplicate-name crash).
        assert len(retries) == 1
    # And the two builds get distinct instances (not a shared/bound one).
    assert first[0]["middleware"][0] is not second[0]["middleware"][0]


def test_spec_already_carrying_retry_is_not_doubled():
    specs = [{"name": "a", "system_prompt": "p", "middleware": [ModelRetryMiddleware()]}]
    out = _harden_subagent_specs(specs)
    retries = [m for m in out[0]["middleware"] if isinstance(m, ModelRetryMiddleware)]
    assert len(retries) == 1


def test_compiled_and_remote_subagents_untouched():
    runnable = object()
    specs = [
        {"name": "compiled", "runnable": runnable},
        {"name": "remote", "url": "http://example/agent"},
    ]
    out = _harden_subagent_specs(specs)
    # Passed through unchanged — these own their own config.
    assert out[0] is specs[0]
    assert "middleware" not in out[0]
    assert out[1] is specs[1]
    assert "middleware" not in out[1]


def test_non_dict_entries_are_skipped():
    specs = ["not-a-dict", 123]
    out = _harden_subagent_specs(specs)  # must not raise
    assert out == ["not-a-dict", 123]

"""Tests for seeding the model profile so deepagents' built-in
SummarizationMiddleware triggers on the real context window.

Without a profile, deepagents falls back to a fixed 170k-token trigger that
never fires for local/Ollama models (their window is smaller), so context just
grows until the model overflows. Seeding ``max_input_tokens`` makes it summarize
at a fraction of the actual window.
"""

from __future__ import annotations

from novacode_cli.agents.core_agent import _seed_summarization_profile


def test_seeds_profile_for_ollama_model():
    from langchain_ollama import ChatOllama

    model = ChatOllama(model="qwen3-coder:480b-cloud")
    assert model.profile is None  # ChatOllama ships without a profile

    _seed_summarization_profile(model, "qwen3-coder:480b-cloud")

    assert isinstance(model.profile, dict)
    assert model.profile["max_input_tokens"] > 0


def test_deepagents_trigger_becomes_window_fraction():
    """After seeding, deepagents computes a fraction-based trigger (not 170k)."""
    from deepagents.middleware.summarization import compute_summarization_defaults
    from langchain_ollama import ChatOllama

    model = ChatOllama(model="qwen3-coder:480b-cloud")
    # Before: no profile -> fixed-token fallback trigger.
    before = compute_summarization_defaults(model)
    assert before["trigger"] == ("tokens", 170000)

    _seed_summarization_profile(model, "qwen3-coder:480b-cloud")
    after = compute_summarization_defaults(model)
    assert after["trigger"][0] == "fraction"  # now tied to the real window


def test_does_not_clobber_existing_profile():
    from langchain_ollama import ChatOllama

    model = ChatOllama(model="qwen3-coder:480b-cloud")
    model.profile = {"max_input_tokens": 999}  # type: ignore[assignment]
    _seed_summarization_profile(model, "qwen3-coder:480b-cloud")
    assert model.profile["max_input_tokens"] == 999  # untouched


def test_no_op_for_non_model():
    # A non-chat-model object must be ignored without raising.
    obj = object()
    _seed_summarization_profile(obj, "whatever")  # should not raise

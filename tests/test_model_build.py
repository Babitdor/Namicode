"""build_chat_model is THE model constructor — pin its kwargs per provider.

Guards the consolidation of 20 drifted ChatX(...) construction sites into one
module: the drift-prone kwargs (retries, effort, num_ctx, base URL) are pinned
here, and the ModelManager path is pinned to equivalence with the direct path.
"""

import pytest

from novacode_cli.config.model_create import (
    PROVIDER_KEY_ENV,
    build_chat_model,
    create_model_from_config,
)


class _StubNovaConfig:
    """NovaConfig stub: no reasoning effort, no thinking budget."""

    def __init__(self, *a, **k):
        pass

    def get(self, key, default=None):
        return None if key == "reasoning_effort" else (default if default is not None else 0)

    def get_model_config(self):
        return None


@pytest.fixture(autouse=True)
def _deterministic_env(monkeypatch):
    monkeypatch.setattr("novacode_cli.config.nova_config.NovaConfig", _StubNovaConfig)
    monkeypatch.setattr("novacode_cli.context._dynamic.get_ollama_num_ctx", lambda: 8192)
    for var in PROVIDER_KEY_ENV.values():
        monkeypatch.setenv(var, "test-key")
    monkeypatch.setenv("Nova_THINKING_BUDGET", "0")


def test_openai_kwargs_pinned():
    m = build_chat_model("openai", "gpt-5-mini")
    assert type(m).__name__ == "ChatOpenAI"
    assert m.max_retries == 5


def test_openrouter_kwargs_pinned():
    m = build_chat_model("openrouter", "z-ai/glm-5.2")
    assert type(m).__name__ == "ChatOpenAI"
    assert m.max_retries == 5
    assert "openrouter" in (m.openai_api_base or "")


def test_anthropic_kwargs_pinned():
    m = build_chat_model("anthropic", "claude-sonnet-4-5-20250929")
    assert type(m).__name__ == "ChatAnthropic"
    assert m.max_tokens == 20_000
    assert m.max_retries == 5


def test_google_kwargs_pinned():
    m = build_chat_model("google", "gemini-3-pro-preview")
    assert type(m).__name__ == "ChatGoogleGenerativeAI"
    assert m.max_retries == 5


def test_ollama_kwargs_pinned():
    m = build_chat_model("ollama", "llama3")
    assert type(m).__name__ == "ChatOllama"
    # Streaming is enabled so the agent loop's astream emits tokens as they're
    # generated (perceived-latency win) instead of buffering the whole response.
    assert m.disable_streaming is False
    # Model kept resident for 2 min after last use (was 600s) to free VRAM/RAM.
    assert m.keep_alive == 120
    assert m.num_ctx == 8192


def test_unknown_provider_raises():
    with pytest.raises(ValueError):
        build_chat_model("nonsense", "x")


def test_from_config_returns_none_without_key(monkeypatch):
    # "No key" means neither env NOR keychain. Deleting the env var alone left a
    # developer's real keyring entry visible, so the gate passed and the client
    # raised instead of returning None.
    from novacode_cli.config import model_create

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(model_create.settings, "openai_api_key", None, raising=False)
    assert create_model_from_config("openai", "gpt-5-mini") is None


@pytest.mark.parametrize("provider,model", [
    ("openai", "gpt-5-mini"),
    ("anthropic", "claude-sonnet-4-5-20250929"),
    ("ollama", "llama3"),
])
def test_model_manager_path_matches_direct_path(provider, model):
    """The drift that motivated this refactor: ModelManager's copies had lost
    max_retries/effort. Both paths must now construct identically."""
    from novacode_cli.config.model_manager import ModelManager

    direct = create_model_from_config(provider, model)
    managed = ModelManager().create_model_for_provider(provider, model)
    assert type(direct) is type(managed)
    for attr in ("max_retries", "max_tokens", "num_ctx", "keep_alive"):
        assert getattr(direct, attr, None) == getattr(managed, attr, None), attr

"""/model command core — ModelManager is the shared seam for both UI adapters.

The console handler (commands/model_handler.py) and the native TUI path
(NovaApp._run_model + ModelScreen) must route through the same ModelManager
methods: availability, current-provider id, key resolution, and set_provider
persistence. Pins those behaviors plus a structural check that neither adapter
grows a private copy again.
"""

import inspect
import os

import pytest

from novacode_cli.config.model_manager import MODEL_PRESETS, ModelManager

KEY_VARS = [p["api_key_var"] for p in MODEL_PRESETS.values() if p["api_key_var"]]


class _RecordingNovaConfig:
    """NovaConfig stand-in: records set_model_config, serves a canned config."""

    saved = None
    model_config = None

    def __init__(self, *a, **k):
        pass

    def get_model_config(self):
        return type(self).model_config

    def set_model_config(self, provider, model, base_url=None):
        type(self).saved = (provider, model)

    def get(self, key, default=None):
        return default


class _StubSecrets:
    """SecretManager stand-in backed by a plain dict."""

    store: dict = {}

    def __init__(self, *a, **k):
        pass

    def get_secret(self, name):
        return type(self).store.get(name)


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    _RecordingNovaConfig.saved = None
    _RecordingNovaConfig.model_config = None
    _StubSecrets.store = {}
    monkeypatch.setattr(
        "novacode_cli.config.model_manager.NovaConfig", _RecordingNovaConfig
    )
    monkeypatch.setattr("novacode_cli.onboarding.SecretManager", _StubSecrets)
    for var in KEY_VARS:
        monkeypatch.delenv(var, raising=False)
    for preset in MODEL_PRESETS.values():
        monkeypatch.delenv(preset["env_var"], raising=False)


# ---------------------------------------------------------------------------
# Provider availability respects env keys
# ---------------------------------------------------------------------------

def test_availability_without_keys_is_ollama_only():
    available = [pid for pid, _ in ModelManager().get_available_providers()]
    assert available == ["ollama"]


def test_availability_respects_env_keys(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    available = {pid for pid, _ in ModelManager().get_available_providers()}
    assert "openai" in available
    assert "anthropic" not in available


# ---------------------------------------------------------------------------
# Switch persistence
# ---------------------------------------------------------------------------

def test_set_provider_persists_config_and_env():
    ModelManager().set_provider("anthropic")
    default = MODEL_PRESETS["anthropic"]["default_model"]
    assert _RecordingNovaConfig.saved == ("anthropic", default)
    assert os.environ["ANTHROPIC_MODEL"] == default


def test_set_provider_unknown_raises():
    with pytest.raises(ValueError):
        ModelManager().set_provider("nonsense")


# ---------------------------------------------------------------------------
# get_current_provider_id (reverse name -> id lookup, shared by both UIs)
# ---------------------------------------------------------------------------

def test_current_provider_id_from_saved_config():
    _RecordingNovaConfig.model_config = {"provider": "google", "model": "g"}
    assert ModelManager().get_current_provider_id() == "google"


def test_current_provider_id_defaults_to_ollama():
    assert ModelManager().get_current_provider_id() == "ollama"


# ---------------------------------------------------------------------------
# resolve_api_key (keychain-or-env, shared by both UIs)
# ---------------------------------------------------------------------------

def test_resolve_api_key_from_env(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")
    assert ModelManager().resolve_api_key("openai") == "env-key"


def test_resolve_api_key_from_keychain_exports_env():
    _StubSecrets.store = {"openai_api_key": "kc-key"}
    assert ModelManager().resolve_api_key("openai") == "kc-key"
    assert os.environ["OPENAI_API_KEY"] == "kc-key"


def test_resolve_api_key_missing_returns_none():
    assert ModelManager().resolve_api_key("openai") is None
    assert ModelManager().resolve_api_key("ollama") is None  # keyless provider


# ---------------------------------------------------------------------------
# Both adapters route through the shared core (structural)
# ---------------------------------------------------------------------------

def test_both_adapters_route_through_model_manager_core():
    from novacode_cli.commands import model_handler
    from novacode_cli.tui.app import NovaApp

    console_src = inspect.getsource(model_handler)
    tui_src = inspect.getsource(NovaApp._run_model)
    for src in (console_src, tui_src):
        assert ".resolve_api_key(" in src
        assert ".set_provider(" in src
        assert ".get_current_provider_id(" in src
        assert ".get_available_providers(" in src

"""OpenCode / OpenRouter key resolution: a key saved to the system keychain
(settings.<provider>_api_key) must reach the model even when it isn't in
os.environ — otherwise the provider silently 401s on every restart."""

from __future__ import annotations

import pytest

from novacode_cli.config import model_create as mc
from novacode_cli.config.config import settings


@pytest.fixture
def _clean_env(monkeypatch):
    # Simulate a fresh session: no provider keys in the environment.
    for var in ("OPENCODE_API_KEY", "OPENROUTER_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    # Restore the real settings values after the test.
    oc, orr = settings.opencode_api_key, settings.openrouter_api_key
    yield
    settings.opencode_api_key, settings.openrouter_api_key = oc, orr


def test_opencode_key_from_keyring_reaches_model(_clean_env):
    settings.opencode_api_key = "sk-keyring-oc"
    m = mc.create_model_from_config("opencode", "glm-5.3")
    assert m is not None  # not rejected despite empty env
    assert m.openai_api_key.get_secret_value() == "sk-keyring-oc"
    assert "opencode.ai" in str(m.root_client.base_url)


def test_openrouter_key_from_keyring_reaches_model(_clean_env):
    settings.openrouter_api_key = "sk-keyring-or"
    m = mc.create_model_from_config("openrouter", "deepseek/deepseek-chat")
    assert m is not None
    assert m.openai_api_key.get_secret_value() == "sk-keyring-or"


def test_no_key_anywhere_returns_none(_clean_env):
    settings.opencode_api_key = None
    assert mc.create_model_from_config("opencode", "glm-5.3") is None

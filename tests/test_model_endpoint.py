"""A custom OpenAI-compatible endpoint can be set from /model.

The `openai` provider always went to api.openai.com — there was no way to point
Nova at Azure, LM Studio, vLLM or a LiteLLM proxy from the TUI, and
``create_model`` never passed ``base_url`` for plain OpenAI at all.
"""

from __future__ import annotations

import asyncio

import pytest

try:
    import textual  # noqa: F401

    _HAS_TEXTUAL = True
except ImportError:  # pragma: no cover
    _HAS_TEXTUAL = False


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    """Keep config writes out of the real ~/.nova."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    from novacode_cli.config.nova_config import NovaConfig

    return NovaConfig


def test_endpoint_is_saved_and_read_back(isolated_config):
    cfg = isolated_config()
    cfg.set_model_config("openai", "gpt-4o", "http://localhost:1234/v1")
    assert isolated_config().get_model_base_url() == "http://localhost:1234/v1"


def test_blank_endpoint_clears_the_override(isolated_config):
    """Switching back to stock OpenAI must not leave a stale URL behind."""
    cfg = isolated_config()
    cfg.set_model_config("openai", "gpt-4o", "http://localhost:1234/v1")
    cfg.set_model_config("openai", "gpt-4o", None)
    assert isolated_config().get_model_base_url() is None


def test_model_manager_persists_the_endpoint(isolated_config):
    from novacode_cli.config.model_manager import ModelManager

    ModelManager().set_provider("openai", "gpt-4o", "http://127.0.0.1:8000/v1")
    assert isolated_config().get_model_base_url() == "http://127.0.0.1:8000/v1"


def test_create_model_actually_uses_the_endpoint(isolated_config, monkeypatch):
    """The point of the feature: ChatOpenAI must be built against the URL."""
    from novacode_cli.config.model_manager import ModelManager

    ModelManager().set_provider("openai", "gpt-4o", "http://127.0.0.1:8000/v1")
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    from novacode_cli.config.model_create import create_model

    model = create_model()
    base = getattr(model, "openai_api_base", None) or getattr(model, "base_url", None)
    assert str(base).rstrip("/") == "http://127.0.0.1:8000/v1"


async def _drive_screen():
    from textual.app import App, ComposeResult
    from textual.widgets import Input, Select

    from novacode_cli.tui.screens import ModelScreen

    class Host(App):
        def compose(self) -> ComposeResult:
            return []

    out: dict = {}
    app = Host()
    async with app.run_test(size=(100, 40)) as pilot:
        screen = ModelScreen(
            "openai", {"openai", "anthropic"}, current_base_url="http://saved:1234/v1"
        )
        app.push_screen(screen)
        for _ in range(4):
            await pilot.pause()

        box = screen.query_one("#baseurl", Input)
        out["openai_visible"] = bool(box.display)
        out["prefilled"] = box.value

        screen._refresh_info("anthropic")
        await pilot.pause()
        out["anthropic_visible"] = bool(box.display)

        screen._refresh_info("openai")
        await pilot.pause()
        box.value = "http://localhost:11434/v1"
        screen.query_one("#provider", Select).value = "openai"
        screen.query_one("#model", Input).value = "local-model"
        got: dict = {}
        screen.dismiss = lambda p: got.update(p or {})  # type: ignore[assignment]
        screen._submit()
        out["submitted"] = got

        # A gateway pins its own base URL; offering one would only break it.
        screen._refresh_info("openrouter")
        await pilot.pause()
        got2: dict = {}
        screen.dismiss = lambda p: got2.update(p or {})  # type: ignore[assignment]
        screen.query_one("#provider", Select).value = "openrouter"
        screen._submit()
        out["openrouter_base_url"] = got2.get("base_url")
    return out


def test_endpoint_box_is_scoped_to_openai_and_returned_on_submit():
    if not _HAS_TEXTUAL:
        return
    out = asyncio.run(_drive_screen())
    assert out["openai_visible"], "endpoint box hidden for OpenAI"
    assert out["prefilled"] == "http://saved:1234/v1", "saved endpoint not prefilled"
    assert not out["anthropic_visible"], "Anthropic does not take an endpoint"
    assert out["submitted"]["base_url"] == "http://localhost:11434/v1"
    assert out["submitted"]["provider"] == "openai"
    assert not out["openrouter_base_url"], "a gateway must not carry an endpoint"

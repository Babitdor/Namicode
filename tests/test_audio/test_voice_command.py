"""Tests for the /voice command + voice config round-trip (hermetic).

Audio deps are not installed in CI, so these exercise the config persistence and
the graceful-degradation path (install hint), not real audio.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from novacode_cli.commands.voice_handler import handle_voice_command
from novacode_cli.config.nova_config import NovaConfig


class _Console:
    """Captures console.print output for assertions."""

    def __init__(self) -> None:
        self.lines: list[str] = []

    def print(self, *args: object, **_kwargs: object) -> None:
        self.lines.append(" ".join(str(a) for a in args))

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    """Point NovaConfig at a temp dir so tests never touch the real config."""
    cfg = NovaConfig()
    monkeypatch.setattr(cfg, "config_dir", tmp_path)
    monkeypatch.setattr(cfg, "config_path", tmp_path / "Nova.config.json")
    monkeypatch.setattr(cfg, "_config", {})
    # The handler does `from novacode_cli.config.nova_config import NovaConfig`
    # at call time, so patch the class at its source to return this instance.
    monkeypatch.setattr("novacode_cli.config.nova_config.NovaConfig", lambda: cfg)
    return cfg


class TestVoiceConfig:
    def test_defaults_merge(self):
        cfg = NovaConfig()
        cfg._config = {}
        vc = cfg.get_voice_config()
        assert vc["enabled"] is False
        assert vc["mode"] == "push_to_talk"
        assert vc["tts_voice"] == "en_US-lessac-medium"

    def test_set_merges_known_keys_only(self):
        cfg = NovaConfig()
        cfg._config = {}
        monkeypatched = []
        cfg._save = lambda: monkeypatched.append(True)  # avoid disk write
        out = cfg.set_voice_config(mode="listen", bogus="x")
        assert out["mode"] == "listen"
        assert "bogus" not in out
        assert monkeypatched  # persisted


class TestVoiceCommand:
    async def test_status_runs(self, isolated_config):
        console = _Console()
        ok = await handle_voice_command("status", SimpleNamespace(), console)
        assert ok is True
        assert "mode=" in console.text

    async def test_on_off_persists(self, isolated_config):
        console = _Console()
        await handle_voice_command("on", SimpleNamespace(), console)
        assert isolated_config.get_voice_config()["enabled"] is True
        await handle_voice_command("off", SimpleNamespace(), console)
        assert isolated_config.get_voice_config()["enabled"] is False

    async def test_mode_alias(self, isolated_config):
        await handle_voice_command("mode listen", SimpleNamespace(), _Console())
        assert isolated_config.get_voice_config()["mode"] == "listen"
        await handle_voice_command("mode ptt", SimpleNamespace(), _Console())
        assert isolated_config.get_voice_config()["mode"] == "push_to_talk"

    async def test_bad_mode_usage(self, isolated_config):
        console = _Console()
        await handle_voice_command("mode bogus", SimpleNamespace(), console)
        assert "Usage" in console.text

    async def test_unknown_subcommand(self, isolated_config):
        console = _Console()
        await handle_voice_command("frobnicate", SimpleNamespace(), console)
        assert "Unknown" in console.text

    async def test_test_degrades_without_deps(self, isolated_config, monkeypatch):
        # Force "not available" and confirm we get the install hint, not a crash.
        monkeypatch.setattr(
            "novacode_cli.commands.voice_handler.audio.is_voice_available", lambda: False
        )
        console = _Console()
        await handle_voice_command("test", SimpleNamespace(), console)
        assert "voice" in console.text.lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

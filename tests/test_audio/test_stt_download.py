"""Tests for Faster-Whisper download detection (hermetic — HF cache mocked)."""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from novacode_cli.audio.stt import Transcriber, _hf_repo_for


class TestRepoMapping:
    def test_bare_size_maps_to_systran(self):
        assert _hf_repo_for("base") == "Systran/faster-whisper-base"
        assert _hf_repo_for("small") == "Systran/faster-whisper-small"

    def test_distil_prefix(self):
        assert _hf_repo_for("distil-large-v3") == "Systran/faster-distil-whisper-large-v3"

    def test_full_repo_passthrough(self):
        assert _hf_repo_for("org/custom-model") == "org/custom-model"


def _patch_hf(monkeypatch, return_value):
    """Inject a fake huggingface_hub.try_to_load_from_cache."""
    fake = SimpleNamespace(try_to_load_from_cache=lambda *_a, **_k: return_value)
    monkeypatch.setitem(sys.modules, "huggingface_hub", fake)


class TestNeedsDownload:
    def test_true_when_not_cached(self, monkeypatch):
        _patch_hf(monkeypatch, None)  # cache miss
        assert Transcriber(model_size="base").needs_download is True

    def test_false_when_cached(self, monkeypatch):
        _patch_hf(monkeypatch, "/cache/path/model.bin")  # cache hit
        assert Transcriber(model_size="base").needs_download is False

    def test_fail_open_on_error(self, monkeypatch):
        # If the probe itself raises, assume present (never block / never spin).
        def _boom(*_a, **_k):
            raise RuntimeError("hub down")

        monkeypatch.setitem(
            sys.modules,
            "huggingface_hub",
            SimpleNamespace(try_to_load_from_cache=_boom),
        )
        assert Transcriber(model_size="base").needs_download is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

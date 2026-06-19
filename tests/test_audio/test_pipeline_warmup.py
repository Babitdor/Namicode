"""Tests for VoicePipeline.warmup() — pre-loading models off the event loop.

Hermetic: the pipeline's components are replaced with fakes, so no torch /
sounddevice / network is needed. Verifies warmup loads each available provider
and degrades gracefully when a provider exposes no eager loader or one fails.
"""

from __future__ import annotations

import pytest

from novacode_cli.audio.pipeline import VoicePipeline


class FakeVad:
    def __init__(self) -> None:
        self.loaded = False

    async def ensure_model_async(self) -> None:
        self.loaded = True


class FakeLocalSTT:
    def __init__(self) -> None:
        self.loaded = False

    def _ensure_model(self) -> None:
        self.loaded = True


class FakeLocalTTS:
    def __init__(self) -> None:
        self.loaded = False

    def _ensure_voice(self) -> None:
        self.loaded = True


class FakeCloudProvider:
    """A cloud provider with no eager-load method (warmup must skip it)."""


class BoomSTT:
    def _ensure_model(self) -> None:
        msg = "load failed"
        raise RuntimeError(msg)


def _wire(pipeline: VoicePipeline, *, vad, stt, tts) -> None:
    """Inject fakes and stub _ensure_components so warmup uses them as-is."""
    pipeline._vad = vad
    pipeline._stt = stt
    pipeline._tts = tts
    pipeline._capture = object()  # non-None so _ensure_components is a no-op
    pipeline._ensure_components = lambda: None


class TestWarmup:
    async def test_loads_all_local_providers(self):
        pipeline = VoicePipeline()
        vad, stt, tts = FakeVad(), FakeLocalSTT(), FakeLocalTTS()
        _wire(pipeline, vad=vad, stt=stt, tts=tts)
        await pipeline.warmup()
        assert vad.loaded is True
        assert stt.loaded is True
        assert tts.loaded is True

    async def test_skips_cloud_providers_without_loaders(self):
        pipeline = VoicePipeline()
        vad = FakeVad()
        # Cloud STT + TTS have no _ensure_* — warmup must not crash.
        _wire(pipeline, vad=vad, stt=FakeCloudProvider(), tts=FakeCloudProvider())
        await pipeline.warmup()  # no AttributeError
        assert vad.loaded is True

    async def test_one_provider_failing_does_not_block_others(self):
        pipeline = VoicePipeline()
        vad, tts = FakeVad(), FakeLocalTTS()
        _wire(pipeline, vad=vad, stt=BoomSTT(), tts=tts)
        await pipeline.warmup()  # BoomSTT raises, but warmup swallows it
        # VAD (before) and TTS (after) still loaded despite the STT failure.
        assert vad.loaded is True
        assert tts.loaded is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

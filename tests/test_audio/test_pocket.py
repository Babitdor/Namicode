"""Tests for the Kyutai Pocket-TTS provider."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from novacode_cli.audio.pipeline import VoicePipeline


def test_pocket_raises_import_error_when_pocket_tts_missing(monkeypatch):
    """Confirm the provider raises a helpful ImportError when pocket-tts is not installed."""
    # Temporarily hide pocket_tts from sys.modules
    monkeypatch.setitem(sys.modules, "pocket_tts", None)

    pipeline = VoicePipeline(tts_provider="pocket")
    with pytest.raises(ImportError) as exc_info:
        pipeline._build_tts()
    assert "pocket-tts" in str(exc_info.value)
    assert "pip install" in str(exc_info.value)


def test_pocket_speaker_lifecycle(monkeypatch):
    """Test PocketSpeaker initialization, download checks, and mock synthesis playback."""
    mock_pocket = MagicMock()
    monkeypatch.setitem(sys.modules, "pocket_tts", mock_pocket)

    mock_model = MagicMock()
    mock_pocket.TTSModel.load_model.return_value = mock_model
    mock_model.sample_rate = 24000
    mock_model.get_state_for_audio_prompt.return_value = "fake_voice_state"

    # Mock audio output tensor from pocket-tts
    mock_audio = MagicMock()
    mock_audio.numpy.return_value = np.array([1, 2, 3], dtype=np.float32)
    mock_model.generate_audio.return_value = mock_audio

    from novacode_cli.audio.tts_pocket import PocketSpeaker

    speaker = PocketSpeaker(voice="marius")
    assert speaker._voice_name == "marius"

    # Test needs_download checks correctly (checking cache path exists)
    with patch("pathlib.Path.exists") as mock_exists:
        mock_exists.return_value = False
        assert speaker.needs_download is True

        mock_exists.return_value = True
        assert speaker.needs_download is False

    # Check synthesis and playback flow
    played: dict = {}

    def _fake_play(pcm, sr):
        played["pcm"] = pcm
        played["sr"] = sr

    # Mock sounddevice calls
    monkeypatch.setattr("sounddevice.play", _fake_play)
    monkeypatch.setattr("sounddevice.wait", lambda: None)

    import asyncio

    asyncio.run(speaker.speak("test sentence"))

    mock_pocket.TTSModel.load_model.assert_called_once()
    mock_model.get_state_for_audio_prompt.assert_called_with("marius")
    mock_model.generate_audio.assert_called_with("fake_voice_state", "test sentence")

    assert played["sr"] == 24000
    # The returned float array is concatenated with 0.25s of silence padding
    # 0.25 * 24000 = 6000 silence samples (zeros)
    assert len(played["pcm"]) == 3 + 6000
    assert played["pcm"][0] == 1.0

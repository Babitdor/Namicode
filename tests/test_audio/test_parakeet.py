"""Tests for the Parakeet STT provider."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from novacode_cli.audio.pipeline import VoicePipeline


def test_parakeet_raises_import_error_when_sherpa_onnx_missing(monkeypatch):
    """Confirm the provider raises a helpful ImportError when sherpa-onnx is not installed."""
    # Temporarily hide sherpa_onnx from sys.modules
    monkeypatch.setitem(sys.modules, "sherpa_onnx", None)

    pipeline = VoicePipeline(stt_provider="parakeet")
    with pytest.raises(ImportError) as exc_info:
        pipeline._build_stt()
    assert "sherpa-onnx" in str(exc_info.value)
    assert "pip install" in str(exc_info.value)


@patch("novacode_cli.audio.stt_parakeet.ensure_parakeet_model")
def test_parakeet_transcriber_lifecycle(mock_ensure, monkeypatch):
    """Test ParakeetTranscriber initialization and mock transcription."""
    mock_sherpa = MagicMock()
    monkeypatch.setitem(sys.modules, "sherpa_onnx", mock_sherpa)

    # Mock OfflineRecognizer and its configuration
    mock_recognizer = MagicMock()
    mock_sherpa.OfflineRecognizer.from_transducer.return_value = mock_recognizer
    mock_stream = MagicMock()
    mock_recognizer.create_stream.return_value = mock_stream
    mock_stream.result.text = "test transcription"

    from novacode_cli.audio.stt_parakeet import ParakeetTranscriber

    transcriber = ParakeetTranscriber(num_threads=4)
    assert transcriber._num_threads == 4

    # Needs download checks correctly
    with patch("novacode_cli.audio.stt_parakeet._VOICE_DIR") as mock_dir:
        mock_file = MagicMock()
        mock_file.exists.return_value = False
        mock_dir.__truediv__.return_value = mock_file
        assert transcriber.needs_download is True

        mock_file.exists.return_value = True
        assert transcriber.needs_download is False

    # Check transcription flow
    pcm = np.zeros(16000, dtype=np.int16)

    # We must patch sys.modules inside transcribe_sync as well
    monkeypatch.setitem(sys.modules, "sherpa_onnx", mock_sherpa)

    import asyncio

    res = asyncio.run(transcriber.transcribe(pcm))
    assert res == "test transcription"
    mock_sherpa.OfflineRecognizer.from_transducer.assert_called_once()
    mock_recognizer.create_stream.assert_called_once()
    mock_stream.accept_waveform.assert_called_once()
    mock_recognizer.decode_stream.assert_called_once()
    mock_ensure.assert_called_once()

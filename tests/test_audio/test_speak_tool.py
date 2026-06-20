"""Tests for the speak tool."""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from novacode_cli.tools.speak_tool import speak


def test_speak_tool_no_pipeline():
    """Verify tool returns warning message when no active pipeline is registered."""
    with patch("novacode_cli.tools.speak_tool.get_active_pipeline", return_value=None):
        res = speak.invoke({"summary": "test message"})
        assert "no active voice pipeline" in res


def test_speak_tool_disabled_none_provider():
    """Verify tool returns warning when active pipeline's TTS provider is set to 'none'."""
    mock_pipeline = MagicMock()
    mock_pipeline._tts_provider = "none"

    with patch("novacode_cli.tools.speak_tool.get_active_pipeline", return_value=mock_pipeline):
        res = speak.invoke({"summary": "test message"})
        assert "voice output is disabled" in res


def test_speak_tool_successful_speak():
    """Verify tool successfully schedules or runs pipeline.speak."""
    mock_pipeline = MagicMock()
    mock_pipeline._tts_provider = "piper"

    # Async mock for pipeline.speak
    async def fake_speak(text):
        pass

    mock_pipeline.speak = fake_speak

    with patch("novacode_cli.tools.speak_tool.get_active_pipeline", return_value=mock_pipeline):
        res = speak.invoke({"summary": "hello world"})
        assert "Spoken summary played: hello world" in res

"""Voice provider registry — discoverable STT and TTS backends.

Every provider is declared in :data:`STT_PROVIDERS` or :data:`TTS_PROVIDERS` so
the ``/voice settings`` command can enumerate choices without importing anything.
Actual implementation classes are loaded lazily when the provider is selected.

The :class:`VoiceSTT` and :class:`VoiceTTS` Protocols define the interface each
backend must satisfy.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    import numpy as np

# ---------------------------------------------------------------------------
# Protocols
# ---------------------------------------------------------------------------


@runtime_checkable
class VoiceSTT(Protocol):
    """Speech-to-text. Transcribes raw 16 kHz mono int16 audio to a string."""

    async def transcribe(self, pcm_int16: np.ndarray) -> str:
        """Transcribe a spoken utterance.

        Args:
            pcm_int16: 16 kHz mono int16 numpy array of the utterance.

        Returns:
            The transcribed text, or ``""`` on silence / failure.
        """
        ...


@runtime_checkable
class VoiceTTS(Protocol):
    """Text-to-speech. Synthesises text and plays audio through speakers."""

    async def speak(self, text: str) -> None:
        """Speak ``text`` aloud. No-op for empty / whitespace-only text."""
        ...


# ---------------------------------------------------------------------------
# Provider registry
# ---------------------------------------------------------------------------

STT_PROVIDERS: dict[str, dict[str, Any]] = {
    "faster-whisper": {
        "name": "Faster-Whisper",
        "description": "Local, open-source (CUDA/CPU)",
        "local": True,
        "requires_key": False,
        "default_model": "base",
    },
    "deepgram": {
        "name": "Deepgram",
        "description": "Cloud API — high-accuracy STT",
        "local": False,
        "requires_key": True,
        "default_model": "nova-2",
    },
    "parakeet": {
        "name": "Parakeet (NVIDIA)",
        "description": "NVIDIA Parakeet-TDT-0.6B-v2 via sherpa-onnx (CPU/CUDA)",
        "local": True,
        "requires_key": False,
        "default_model": "parakeet-tdt-0.6b-v2",
    },
}

TTS_PROVIDERS: dict[str, dict[str, Any]] = {
    "piper": {
        "name": "Piper",
        "description": "Local, low-latency TTS (CPU)",
        "local": True,
        "requires_key": False,
        "default_voice": "en_US-lessac-medium",
    },
    "elevenlabs": {
        "name": "ElevenLabs",
        "description": "Cloud API — premium voice quality",
        "local": False,
        "requires_key": True,
        "default_voice": "21m00Tcm4TlvDq8ikWAM",
    },
    "orpheus": {
        "name": "Orpheus (local, natural)",
        "description": "LLM-based, very natural — heavy (~2GB, slow on CPU)",
        "local": True,
        "requires_key": False,
        "default_voice": "tara",
    },
    "none": {
        "name": "Off",
        "description": "Silence — no spoken output",
        "local": True,
        "requires_key": False,
        "default_voice": "",
    },
}


def stt_provider_names() -> list[str]:
    """Sorted list of STT provider keys."""
    return sorted(STT_PROVIDERS)


def tts_provider_names() -> list[str]:
    """Sorted list of TTS provider keys."""
    return sorted(TTS_PROVIDERS)


# ---------------------------------------------------------------------------
# Null provider (TTS off)
# ---------------------------------------------------------------------------


class _NullTTS:
    """No-op TTS provider for when speech output is disabled."""

    async def speak(self, text: str) -> None:
        """Silently drop the text — no synthesis or playback."""

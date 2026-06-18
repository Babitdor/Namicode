"""Piper text-to-speech wrapper.

Synthesises speech with Piper (CPU, low latency) and plays it through
sounddevice. The voice model (``.onnx`` + ``.onnx.json``) is fetched once into
``~/.nova/voice/piper/`` on first use. Synthesis is blocking, so :meth:`Speaker.speak`
offloads to a worker thread. Imports cleanly without ``piper-tts`` installed.
"""

from __future__ import annotations

import asyncio
import logging
import urllib.request
from typing import TYPE_CHECKING, Any

from novacode_cli.config.config import HOME_DIR

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger("nova.audio.tts")

_DEFAULT_VOICE = "en_US-lessac-medium"
_VOICE_DIR = HOME_DIR / "voice" / "piper"
#: Piper voices are published on HuggingFace under rhasspy/piper-voices.
_VOICE_BASE_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/main"


def _voice_url_path(voice: str) -> str:
    """Map ``en_US-lessac-medium`` → ``en/en_US/lessac/medium/<file>`` URL stem."""
    lang_region, name, quality = voice.split("-", 2)
    lang = lang_region.split("_")[0]
    return f"{lang}/{lang_region}/{name}/{quality}/{voice}"


def _download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    logger.info("Downloading Piper asset %s", url)
    with urllib.request.urlopen(url) as resp, dest.open("wb") as out:  # noqa: S310 — fixed HTTPS host
        out.write(resp.read())


def ensure_voice_model(voice: str = _DEFAULT_VOICE) -> Path:
    """Return the local ``.onnx`` path for ``voice``, downloading it if missing."""
    onnx = _VOICE_DIR / f"{voice}.onnx"
    config = _VOICE_DIR / f"{voice}.onnx.json"
    stem = _voice_url_path(voice)
    if not onnx.exists():
        _download(f"{_VOICE_BASE_URL}/{stem}.onnx", onnx)
    if not config.exists():
        _download(f"{_VOICE_BASE_URL}/{stem}.onnx.json", config)
    return onnx


class Speaker:
    """Synthesises and plays speech with Piper."""

    def __init__(self, *, voice: str = _DEFAULT_VOICE) -> None:
        """Configure the voice; the model loads/downloads on first use."""
        self._voice_name = voice
        self._voice: Any = None
        self._samplerate = 22_050

    def _ensure_voice(self) -> None:
        if self._voice is None:
            from piper import PiperVoice

            model_path = ensure_voice_model(self._voice_name)
            self._voice = PiperVoice.load(str(model_path))
            self._samplerate = getattr(self._voice.config, "sample_rate", self._samplerate)

    async def speak(self, text: str) -> None:
        """Synthesise ``text`` and play it (off the event loop). No-op if empty."""
        if not text.strip():
            return
        await asyncio.to_thread(self._speak_sync, text)

    def _speak_sync(self, text: str) -> None:
        import numpy as np
        import sounddevice as sd

        self._ensure_voice()
        chunks = [
            np.frombuffer(audio_bytes, dtype="int16")
            for audio_bytes in self._voice.synthesize_stream_raw(text)
        ]
        if not chunks:
            return
        sd.play(np.concatenate(chunks), self._samplerate)
        sd.wait()

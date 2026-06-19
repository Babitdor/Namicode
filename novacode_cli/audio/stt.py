"""Faster-Whisper speech-to-text wrapper.

The model is loaded lazily and cached; transcription is blocking, so callers use
:meth:`Transcriber.transcribe`, which offloads to a worker thread via
``asyncio.to_thread`` to keep the event loop responsive. Imports cleanly without
``faster-whisper`` installed.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import numpy as np

logger = logging.getLogger("nova.audio.stt")

#: distil-large-v3 — near-large-v3 accuracy, much faster (good even on CPU).
_DEFAULT_MODEL = "distil-large-v3"
#: Default transcription language. Forcing a language avoids per-utterance
#: language mis-detection that garbles short push-to-talk clips.
_DEFAULT_LANGUAGE = "en"


def _resolve_device(device: str) -> tuple[str, str]:
    """Map a requested device to a concrete ``(device, compute_type)`` pair.

    ``"auto"`` uses CUDA (float16) when available, else CPU (int8).
    """
    if device in ("cuda", "gpu"):
        return "cuda", "float16"
    if device == "cpu":
        return "cpu", "int8"
    # auto
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda", "float16"
    except Exception:  # noqa: BLE001 — best-effort hardware probe; any failure ⇒ CPU
        logger.debug("CUDA probe failed; using CPU", exc_info=True)
    return "cpu", "int8"


class Transcriber:
    """Transcribes 16 kHz int16 audio to text with Faster-Whisper."""

    def __init__(
        self,
        *,
        model_size: str = _DEFAULT_MODEL,
        device: str = "auto",
        language: str | None = _DEFAULT_LANGUAGE,
    ) -> None:
        """Configure the model; loading is deferred to first transcription.

        ``language`` forces the decode language (e.g. ``"en"``); pass ``None`` to
        auto-detect (less reliable on short utterances).
        """
        self._model_size = model_size
        self._device_pref = device
        self._language = language or None
        self._model: Any = None

    def _ensure_model(self) -> None:
        if self._model is None:
            from faster_whisper import WhisperModel

            device, compute_type = _resolve_device(self._device_pref)
            logger.info(
                "Loading Faster-Whisper '%s' on %s (%s)",
                self._model_size,
                device,
                compute_type,
            )
            self._model = WhisperModel(self._model_size, device=device, compute_type=compute_type)

    async def transcribe(self, pcm_int16: np.ndarray) -> str:
        """Return the transcript of an int16 utterance (off the event loop)."""
        return await asyncio.to_thread(self._transcribe_sync, pcm_int16)

    def _transcribe_sync(self, pcm_int16: np.ndarray) -> str:
        self._ensure_model()
        audio = pcm_int16.astype("float32") / 32768.0
        segments, _info = self._model.transcribe(
            audio,
            language=self._language,
            # Whisper's own VAD trims silence and suppresses phantom transcripts
            # it otherwise hallucinates from breath / room noise.
            vad_filter=True,
            # Wider beam = better accuracy on short clips (negligible cost here).
            beam_size=5,
            # One-shot utterances: don't let a prior segment bias the decode.
            condition_on_previous_text=False,
        )
        return " ".join(seg.text.strip() for seg in segments).strip()

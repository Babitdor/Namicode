"""Deepgram cloud STT — sends 16 kHz int16 audio via aiohttp.

Requires a Deepgram API key (stored in config). See
https://developers.deepgram.com/reference/pre-recorded-audio
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import aiohttp

if TYPE_CHECKING:
    import numpy as np

logger = logging.getLogger("nova.audio.stt_deepgram")

_DEEPGRAM_BASE = "https://api.deepgram.com/v1"
_STATUS_OK = 200


class DeepgramTranscriber:
    """Transcribes 16 kHz int16 audio via the Deepgram REST API."""

    def __init__(self, *, api_key: str = "", model: str = "nova-2") -> None:
        """Store the API key and model name."""
        self._api_key = api_key
        self._model = model

    async def transcribe(self, pcm_int16: np.ndarray) -> str:
        """Send PCM audio to Deepgram and return the transcript."""
        if not self._api_key:
            msg = "Deepgram API key is not set."
            raise RuntimeError(msg)
        audio_bytes = pcm_int16.tobytes()
        headers = {
            "Authorization": f"Token {self._api_key}",
            "Content-Type": "audio/l16;rate=16000;channels=1",
        }
        params = {
            "model": self._model,
            "punctuate": "true",
            "encoding": "linear16",
            "sample_rate": "16000",
        }

        async with (
            aiohttp.ClientSession(headers=headers) as session,
            session.post(
                f"{_DEEPGRAM_BASE}/listen",
                params=params,
                data=audio_bytes,
                timeout=aiohttp.ClientTimeout(total=60),
            ) as resp,
        ):
            if resp.status != _STATUS_OK:
                text = await resp.text()
                err_msg = f"Deepgram API error ({resp.status}): {text[:200]}"
                raise RuntimeError(err_msg)
            result = await resp.json()

        try:
            alternatives = result["results"]["channels"][0]["alternatives"]
            transcript = alternatives[0].get("transcript", "")
            return transcript.strip()
        except (KeyError, IndexError, TypeError):
            logger.warning("Unexpected Deepgram response structure: %s", str(result)[:300])
            return ""

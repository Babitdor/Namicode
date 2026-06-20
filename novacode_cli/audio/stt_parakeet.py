"""NVIDIA Parakeet-TDT ASR wrapper via sherpa-onnx.

Runs local ASR with Parakeet-TDT-0.6B-v2. The model is fetched from Hugging Face
into `~/.nova/voice/parakeet/` on first use.
"""

from __future__ import annotations

import asyncio
import logging
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING, Any

from novacode_cli.config.config import HOME_DIR

if TYPE_CHECKING:
    import numpy as np

logger = logging.getLogger("nova.audio.stt_parakeet")

_VOICE_DIR = HOME_DIR / "voice" / "parakeet"
_HF_BASE_URL = "https://huggingface.co/csukuangfj/sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8/resolve/main"

_MODEL_FILES = [
    "encoder.int8.onnx",
    "decoder.int8.onnx",
    "joiner.int8.onnx",
    "tokens.txt",
]


def _download(url: str, dest: Path) -> None:
    import os
    import tempfile

    dest.parent.mkdir(parents=True, exist_ok=True)
    logger.info("Downloading Parakeet asset %s", url)
    # Download to a temp file in the same folder to guarantee atomic replacement on the same drive.
    tmp_fd, tmp_path_str = tempfile.mkstemp(dir=str(dest.parent), suffix=".tmp")
    tmp_path = Path(tmp_path_str)
    try:
        with os.fdopen(tmp_fd, "wb") as out, urllib.request.urlopen(url) as resp:  # noqa: S310
            out.write(resp.read())
        tmp_path.replace(dest)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def ensure_parakeet_model() -> None:
    """Download the Parakeet model files if they do not exist locally."""
    for filename in _MODEL_FILES:
        dest = _VOICE_DIR / filename
        if not dest.exists():
            _download(f"{_HF_BASE_URL}/{filename}", dest)


class ParakeetTranscriber:
    """Transcribes 16 kHz int16 audio with NVIDIA Parakeet TDT via sherpa-onnx."""

    def __init__(self, *, num_threads: int = 2) -> None:
        self._num_threads = num_threads
        self._recognizer: Any = None

    @property
    def needs_download(self) -> bool:
        """Whether the model files are missing and need to be downloaded."""
        return any(not (_VOICE_DIR / f).exists() for f in _MODEL_FILES)

    def _ensure_model(self) -> None:
        if self._recognizer is None:
            import sherpa_onnx

            ensure_parakeet_model()

            self._recognizer = sherpa_onnx.OfflineRecognizer.from_transducer(
                encoder=str(_VOICE_DIR / "encoder.int8.onnx"),
                decoder=str(_VOICE_DIR / "decoder.int8.onnx"),
                joiner=str(_VOICE_DIR / "joiner.int8.onnx"),
                tokens=str(_VOICE_DIR / "tokens.txt"),
                num_threads=self._num_threads,
                provider=self._get_provider(),
                model_type="nemo_transducer",
            )

    def _get_provider(self) -> str:
        try:
            import torch

            if torch.cuda.is_available():
                return "cuda"
        except Exception:  # noqa: BLE001
            pass
        return "cpu"

    async def transcribe(self, pcm_int16: np.ndarray) -> str:
        """Return the transcript of an int16 utterance (off the event loop)."""
        return await asyncio.to_thread(self._transcribe_sync, pcm_int16)

    def _transcribe_sync(self, pcm_int16: np.ndarray) -> str:
        import numpy as np

        self._ensure_model()
        # Normalise input waveform to float32 between [-1, 1] as expected by sherpa-onnx
        audio = pcm_int16.astype(np.float32) / 32768.0

        stream = self._recognizer.create_stream()
        stream.accept_waveform(sample_rate=16000, waveform=audio)
        self._recognizer.decode_stream(stream)
        return stream.result.text.strip()

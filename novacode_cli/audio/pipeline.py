"""VoicePipeline — orchestrates capture → VAD → STT, and TTS playback.

UI-agnostic: the TUI constructs one of these and drives it via callbacks, so the
audio logic stays testable and reusable. All heavy work runs off the event loop
(``asyncio.to_thread``). The ``tts_active`` flag lets the always-listening loop
**pause while Nova is speaking**, so it never transcribes its own output.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

logger = logging.getLogger("nova.audio.pipeline")

_TTS_POLL_S = 0.1


class VoicePipeline:
    """High-level voice I/O: one-shot capture, continuous listen, and speak."""

    def __init__(
        self,
        *,
        stt_model: str = "base",
        stt_device: str = "auto",
        tts_voice: str = "en_US-lessac-medium",
    ) -> None:
        """Record component config; nothing is loaded until first use."""
        self._stt_model = stt_model
        self._stt_device = stt_device
        self._tts_voice = tts_voice
        self._capture: Any = None
        self._vad: Any = None
        self._stt: Any = None
        self._tts: Any = None
        self._tts_active = False

    @property
    def tts_active(self) -> bool:
        """Whether TTS is currently playing (listen loop pauses while True)."""
        return self._tts_active

    def _ensure_components(self) -> None:
        from novacode_cli.audio.capture import AudioCapture
        from novacode_cli.audio.stt import Transcriber
        from novacode_cli.audio.tts import Speaker
        from novacode_cli.audio.vad import SileroVad

        if self._capture is None:
            self._capture = AudioCapture()
        if self._vad is None:
            self._vad = SileroVad()
        if self._stt is None:
            self._stt = Transcriber(model_size=self._stt_model, device=self._stt_device)
        if self._tts is None:
            self._tts = Speaker(voice=self._tts_voice)

    async def warmup(self) -> None:
        """Pre-load the STT model and TTS voice so first use isn't laggy."""
        self._ensure_components()
        await asyncio.to_thread(self._stt._ensure_model)
        await asyncio.to_thread(self._tts._ensure_voice)

    async def capture_utterance(
        self, *, should_stop: Callable[[], bool] | None = None
    ) -> str | None:
        """Push-to-talk: record one utterance, return its transcript (or ``None``)."""
        self._ensure_components()
        self._capture.start()
        self._capture.drain()
        try:
            pcm = await asyncio.to_thread(
                self._vad.collect_utterance, self._capture.read, should_stop=should_stop
            )
        finally:
            self._capture.stop()  # PTT releases the mic between utterances
        if pcm is None or len(pcm) == 0:
            return None
        return (await self._stt.transcribe(pcm)) or None

    async def speak(self, text: str) -> None:
        """Speak ``text`` aloud, flagging ``tts_active`` for the duration."""
        if not text.strip():
            return
        self._ensure_components()
        self._tts_active = True
        try:
            await self._tts.speak(text)
        finally:
            self._tts_active = False

    async def listen_loop(
        self,
        on_transcript: Callable[[str], Awaitable[None] | None],
        *,
        should_stop: Callable[[], bool] | None = None,
    ) -> None:
        """Always-listening: capture utterances continuously, emit each transcript.

        Pauses capture while ``tts_active`` so Nova never hears itself.
        """
        self._ensure_components()
        self._capture.start()
        try:
            while True:
                if should_stop is not None and should_stop():
                    return
                if self._tts_active:
                    self._capture.drain()
                    await asyncio.sleep(_TTS_POLL_S)
                    continue

                pcm = await asyncio.to_thread(
                    self._vad.collect_utterance,
                    self._capture.read,
                    should_stop=lambda: self._tts_active or bool(should_stop and should_stop()),
                )
                # Discard anything captured if TTS started or we were cancelled.
                if pcm is None or len(pcm) == 0 or self._tts_active:
                    continue
                text = await self._stt.transcribe(pcm)
                if not text:
                    continue
                result = on_transcript(text)
                if asyncio.iscoroutine(result):
                    await result
        finally:
            self._capture.stop()

    def stop(self) -> None:
        """Release the microphone."""
        if self._capture is not None:
            self._capture.stop()

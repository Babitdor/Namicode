"""Local, open-source voice I/O for Nova — STT + VAD + TTS.

Speak prompts and hear Nova's prose replies with **no cloud dependency**:

- STT  : Faster-Whisper (CUDA when available, CPU fallback)
- VAD  : Silero VAD (utterance endpointing)
- TTS  : Piper (CPU, low latency)
- Audio: sounddevice (PortAudio capture + playback)

Every heavy dependency is **optional**. This package imports cleanly without any
of them installed; :func:`is_voice_available` reports what's missing so the
``/voice`` command can print an install hint instead of crashing.

Install with::

    uv pip install -e '.[voice]'
"""

from __future__ import annotations

import importlib.util


def _has(module: str) -> bool:
    """Return whether ``module`` is importable, without importing it."""
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


# Probed at import time (cheap — find_spec doesn't execute the module).
_HAS_SOUNDDEVICE = _has("sounddevice")
_HAS_FASTER_WHISPER = _has("faster_whisper")
_HAS_SILERO_VAD = _has("silero_vad")
_HAS_PIPER = _has("piper")  # the `piper-tts` distribution imports as `piper`

#: Distribution name -> present? (distribution names are what users `pip install`).
_REQUIRED: dict[str, bool] = {
    "sounddevice": _HAS_SOUNDDEVICE,
    "faster-whisper": _HAS_FASTER_WHISPER,
    "silero-vad": _HAS_SILERO_VAD,
    "piper-tts": _HAS_PIPER,
}


def missing_deps() -> list[str]:
    """Return the pip-install names of any voice dependencies that are absent."""
    return [name for name, present in _REQUIRED.items() if not present]


def is_voice_available() -> bool:
    """Return whether the full local voice stack is importable."""
    return not missing_deps()


def install_hint() -> str:
    """A one-line, user-facing hint for enabling voice."""
    missing = ", ".join(missing_deps())
    return (
        "Install voice deps with one command:\n"
        f"  uv tool install -e .[voice]     # global 'nova' command\n"
        f"  uv pip install -e '.[voice]'    # uv run nova\n"
        f"Missing: {missing}"
    )


__all__ = [
    "install_hint",
    "is_voice_available",
    "missing_deps",
]

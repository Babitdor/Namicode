"""Speak tool for the agent.

Allows the agent to speak directly to the user via TTS by providing a summary.
"""

from __future__ import annotations

import asyncio
from langchain.tools import tool

from novacode_cli.audio.pipeline import get_active_pipeline


@tool
def speak(summary: str) -> str:
    """Speak a short, casual summary of your action or response directly to the user via TTS.

    Use this tool when you want to provide real-time spoken feedback or keep the user
    informed of what you are doing in a friendly, conversational manner. Speak in
    a casual, conversational way (e.g. "I'm downloading the files now", "All done!").

    Args:
        summary: A short, casual summary of the response or action to speak aloud.

    Returns:
        Status message indicating whether the speech was played.
    """
    pipeline = get_active_pipeline()
    if pipeline is None:
        return f"Speech not played (no active voice pipeline): {summary}"

    # Check if voice output is enabled (NullTTS is the 'none' provider)
    if pipeline._tts_provider == "none":
        return f"Speech not played (voice output is disabled): {summary}"

    try:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop is not None and loop.is_running():
            # Run the coroutine in the running loop and wait for it to complete
            fut = asyncio.run_coroutine_threadsafe(pipeline.speak(summary), loop)
            fut.result()  # block until done
        else:
            asyncio.run(pipeline.speak(summary))

        return f"Spoken summary played: {summary}"
    except Exception as e:
        return f"Failed to speak summary: {e}"

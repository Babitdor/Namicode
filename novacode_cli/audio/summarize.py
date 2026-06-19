"""Spoken-summary generation for TTS — a natural 1-2 sentence gist.

Reading a whole assistant reply aloud is tiring. Instead, before speaking, we
rewrite the reply into a short, conversational summary via an out-of-band model
call (tagged ``nova_oob`` so the agent loop drops its streamed output, exactly
like :mod:`novacode_cli.hermes.verifier`).

Fail-open everywhere: a missing model, an error, or an empty result all fall
back to a short :func:`speakable_text` slice, so speech still happens.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from langchain_core.messages import HumanMessage

from novacode_cli.audio.speakable import speakable_text
from novacode_cli.prompts import render_template

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

logger = logging.getLogger("nova.audio.summarize")

#: Replies whose speakable form is already this short skip the LLM call — a
#: one-line "Done." ack shouldn't pay a model round-trip before speaking.
_SHORT_REPLY_CHARS = 200
#: Hard cap on the spoken summary (a paragraph; defence against a chatty model).
#: ~90 words ≈ 600 chars, with headroom so a full paragraph isn't cut mid-sentence.
_SUMMARY_MAX_CHARS = 700


async def summarize_for_speech(text: str, *, model: BaseChatModel | None = None) -> str:
    """Return a 1-2 sentence spoken summary of an assistant reply (fail-open).

    Short replies are returned as-is (no model call). Any failure falls back to
    a trimmed :func:`speakable_text` slice so TTS always has something to say.
    """
    base = speakable_text(text)
    if not base:
        return ""
    if len(base) <= _SHORT_REPLY_CHARS:
        return base

    try:
        chat = model
        if chat is None:
            from novacode_cli.config.model_create import create_model

            chat = create_model()
        prompt = render_template("voice_summary.jinja", response=base)
        resp = await chat.ainvoke(
            [HumanMessage(content=prompt)],
            config={
                "run_name": "nova_voice_summary",
                "tags": ["nova", "voice"],
                # nova_oob: drop this call's streamed output in the agent loop.
                "metadata": {"nova_oob": True},
            },
        )
        raw = getattr(resp, "content", "")
        summary = (raw if isinstance(raw, str) else str(raw)).strip()
    except Exception:
        logger.exception("Voice summary failed; speaking a short slice instead")
        return speakable_text(text, max_chars=_SUMMARY_MAX_CHARS)

    if not summary:
        return speakable_text(text, max_chars=_SUMMARY_MAX_CHARS)
    # The summary is already plain prose, but run it through the filter to strip
    # any stray markdown the model added, and to enforce the hard length cap.
    return speakable_text(summary, max_chars=_SUMMARY_MAX_CHARS)

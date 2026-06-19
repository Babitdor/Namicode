"""Tests for spoken-summary generation (hermetic — fake model, no network)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from novacode_cli.audio.summarize import _SHORT_REPLY_CHARS, summarize_for_speech


class FakeModel:
    """Records the OOB config and returns a canned summary."""

    def __init__(self, content: str) -> None:
        self._content = content
        self.config: dict | None = None
        self.calls = 0

    async def ainvoke(self, _messages, config=None):
        self.calls += 1
        self.config = config
        return SimpleNamespace(content=self._content)


class BoomModel:
    async def ainvoke(self, *_a, **_k):
        raise RuntimeError("model down")


def _long_reply() -> str:
    # Comfortably above _SHORT_REPLY_CHARS so the LLM path is taken.
    return "I refactored the parser. " * 20


class TestSummarize:
    async def test_long_reply_uses_model_summary(self):
        model = FakeModel("Refactored the parser and fixed two bugs.")
        out = await summarize_for_speech(_long_reply(), model=model)
        assert out == "Refactored the parser and fixed two bugs."
        assert model.calls == 1
        # Tagged OOB so the agent loop drops the streamed output.
        assert model.config["metadata"]["nova_oob"] is True

    async def test_short_reply_skips_model(self):
        model = FakeModel("should not be used")
        out = await summarize_for_speech("Done.", model=model)
        assert out == "Done."
        assert model.calls == 0

    async def test_just_under_threshold_skips_model(self):
        model = FakeModel("nope")
        text = "x" * (_SHORT_REPLY_CHARS - 1)
        out = await summarize_for_speech(text, model=model)
        assert model.calls == 0
        assert out == text

    async def test_model_error_fails_open(self):
        out = await summarize_for_speech(_long_reply(), model=BoomModel())
        # Falls back to a speakable slice — non-empty, so TTS still speaks.
        assert out
        assert "parser" in out

    async def test_empty_summary_falls_back(self):
        model = FakeModel("   ")  # whitespace-only → treated as empty
        out = await summarize_for_speech(_long_reply(), model=model)
        assert out  # fell back to a slice
        assert model.calls == 1

    async def test_empty_input_returns_empty(self):
        model = FakeModel("x")
        assert await summarize_for_speech("", model=model) == ""
        assert model.calls == 0

    async def test_all_code_input_returns_empty(self):
        model = FakeModel("x")
        out = await summarize_for_speech("```python\nx = 1\n```", model=model)
        assert out == ""
        assert model.calls == 0

    async def test_summary_strips_stray_markdown(self):
        model = FakeModel("**Done** — updated the `README`.")
        out = await summarize_for_speech(_long_reply(), model=model)
        assert "*" not in out
        assert "`" not in out
        assert "Done" in out


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

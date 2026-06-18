"""Tests for the speakable-text filter and voice capability detection."""

from __future__ import annotations

import pytest

from novacode_cli import audio
from novacode_cli.audio.speakable import is_all_code, speakable_text


class TestSpeakableText:
    def test_strips_fenced_code(self):
        md = "Here is the fix:\n\n```python\nprint('hi')\n```\n\nThat's all."
        out = speakable_text(md)
        assert "print" not in out
        assert "Here is the fix" in out
        assert "That's all." in out

    def test_keeps_inline_code_words_without_backticks(self):
        out = speakable_text("Run `pytest` to check.")
        assert out == "Run pytest to check."

    def test_link_label_kept_url_dropped(self):
        out = speakable_text("See [the docs](https://example.com/x) for more.")
        assert "the docs" in out
        assert "example.com" not in out

    def test_bare_url_removed(self):
        out = speakable_text("Visit https://example.com/page now")
        assert "example.com" not in out

    def test_markdown_markup_removed(self):
        out = speakable_text("## Heading\n\n- **bold** and _italic_ point")
        assert "#" not in out
        assert "*" not in out
        assert "_" not in out
        assert "bold and italic point" in out

    def test_table_rows_dropped(self):
        md = "Summary:\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\nDone."
        out = speakable_text(md)
        assert "|" not in out
        assert "Summary:" in out
        assert "Done." in out

    def test_truncates_at_sentence_boundary(self):
        md = "First sentence. " + ("Filler words here. " * 200)
        out = speakable_text(md, max_chars=100)
        assert len(out) <= 100
        assert out.endswith(".")

    def test_truncates_with_ellipsis_when_no_sentence_end(self):
        out = speakable_text("word " * 100, max_chars=40)
        assert len(out) <= 41
        assert out.endswith("…")

    def test_empty_input(self):
        assert speakable_text("") == ""

    def test_is_all_code(self):
        assert is_all_code("```python\nx = 1\n```") is True
        assert is_all_code("Here's why:\n```\nx=1\n```") is False
        assert is_all_code("") is True


class TestCapability:
    def test_missing_deps_lists_pip_names(self):
        # In CI the audio extras aren't installed, so all are reported missing.
        missing = audio.missing_deps()
        assert isinstance(missing, list)
        # Whatever is missing must be a subset of the known pip names.
        assert set(missing) <= {"sounddevice", "faster-whisper", "silero-vad", "piper-tts"}

    def test_available_matches_missing(self):
        assert audio.is_voice_available() == (audio.missing_deps() == [])

    def test_install_hint_mentions_extra(self):
        if not audio.is_voice_available():
            assert "voice" in audio.install_hint()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

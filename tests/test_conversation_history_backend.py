"""The offloaded conversation history must be write-only to the agent.

Summarization evicts old turns to ``/conversation_history/<uuid>.md`` and the
summarizer tells the model it can "recover the full text by reading the
offloaded file". Following that advice re-inhales exactly the context eviction
just cleared, pushing usage back over the summarization threshold and
summarizing again — the repeating "SESSION INTENT / task not recoverable" loop
the user hit.

So: writes still land on disk (the transcript stays available to the user and to
/resume), but the agent-facing read is refused. These tests pin both halves —
the refusal is what breaks the cycle, the write is what keeps the data.

Runnable directly (``python tests/test_conversation_history_backend.py``).
"""

from __future__ import annotations

from novacode_cli.backends import ConversationHistoryBackend, OptimizedFilesystemBackend

_TRANSCRIPT = "user: build a parser\nassistant: ok, starting\n" * 50


def _backend(tmp_path) -> ConversationHistoryBackend:
    return ConversationHistoryBackend(root_dir=str(tmp_path), virtual_mode=True)


# ── the loop break ───────────────────────────────────────────────────────────


def test_read_is_refused(tmp_path):
    b = _backend(tmp_path)
    b.write("/hist.md", _TRANSCRIPT)
    result = b.read("/hist.md")
    assert result.error is not None
    # The transcript itself must NOT come back — that is the whole point.
    assert "build a parser" not in (result.error or "")
    assert result.file_data is None


def test_refusal_tells_the_model_what_to_do_instead(tmp_path):
    b = _backend(tmp_path)
    b.write("/hist.md", _TRANSCRIPT)
    err = (b.read("/hist.md").error or "").lower()
    # Must steer to the summary + asking the user, not to reconstruction.
    assert "summar" in err
    assert "ask the user" in err


def test_read_refused_even_with_offset_and_limit(tmp_path):
    # Paging is how the model would work around a blanket refusal.
    b = _backend(tmp_path)
    b.write("/hist.md", _TRANSCRIPT)
    result = b.read("/hist.md", offset=10, limit=5)
    assert result.error is not None
    assert result.file_data is None


def test_read_refused_for_missing_file_too(tmp_path):
    # Uniform refusal: no probing which history files exist via error shape.
    b = _backend(tmp_path)
    assert b.read("/never-written.md").error is not None


# ── the data is still kept ───────────────────────────────────────────────────


def test_write_still_persists_to_disk(tmp_path):
    b = _backend(tmp_path)
    b.write("/hist.md", _TRANSCRIPT)
    on_disk = tmp_path / "hist.md"
    assert on_disk.exists()
    assert "build a parser" in on_disk.read_text(encoding="utf-8")


def test_ordinary_backend_still_reads(tmp_path):
    # Only the conversation-history route is write-only; normal file reads (and
    # the /large_tool_results/ route, which uses the ordinary backend) are not
    # affected by this change.
    (tmp_path / "notes.md").write_text("hello", encoding="utf-8")
    ordinary = OptimizedFilesystemBackend(root_dir=str(tmp_path), virtual_mode=True)
    result = ordinary.read("/notes.md")
    assert result.error is None
    assert result.file_data is not None


if __name__ == "__main__":
    import sys

    import pytest

    sys.exit(pytest.main([__file__, "-v", "--assert=plain"]))

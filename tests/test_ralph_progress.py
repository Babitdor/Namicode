"""Tests for Ralph's cross-iteration progress.md tracking."""

import os
from pathlib import Path

from novacode_cli.commands.ralph_handler import (
    RALPH_PROGRESS_PATH,
    _ensure_ralph_dir,
    _read_ralph_progress,
)
from novacode_cli.prompts import render_template


def test_progress_path_is_posix_nova_ralph():
    assert RALPH_PROGRESS_PATH == ".nova/ralph/progress.md"


def test_ensure_dir_and_read_roundtrip(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # No file yet -> empty.
    assert _read_ralph_progress() == ""
    _ensure_ralph_dir()
    assert (tmp_path / ".nova" / "ralph").is_dir()
    # Write progress, read it back.
    p = tmp_path / ".nova" / "ralph" / "progress.md"
    p.write_text("## Iteration 1\n- Implemented: parser\n", encoding="utf-8")
    out = _read_ralph_progress()
    assert "Implemented: parser" in out


def test_read_progress_is_bounded(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _ensure_ralph_dir()
    p = tmp_path / ".nova" / "ralph" / "progress.md"
    p.write_text("x" * 20000, encoding="utf-8")
    out = _read_ralph_progress()
    assert len(out) <= 6100  # bounded (~6000 + trim marker)
    assert "trimmed" in out


def test_template_shows_progress_and_requires_update():
    r = render_template(
        "ralph_iteration.jinja",
        iteration_display="2",
        task="do it",
        conversation_context="",
        progress_notes="## Iteration 1\n- Implemented: parser",
        progress_path=RALPH_PROGRESS_PATH,
    )
    assert "Progress Log" in r and "READ FIRST" in r
    assert "Implemented: parser" in r
    assert "update" in r
    assert ".nova/ralph/progress.md" in r


def test_template_first_iteration_has_no_prior_notes():
    r = render_template(
        "ralph_iteration.jinja",
        iteration_display="1",
        task="do it",
        conversation_context="",
        progress_notes="",
        progress_path=RALPH_PROGRESS_PATH,
    )
    assert "first iteration" in r

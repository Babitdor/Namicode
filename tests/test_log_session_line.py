"""/log list summarizes recent SESSIONS (interactive activity lives under
~/.nova/sessions; the .nova/runs turn format is eval-harness-only)."""

from __future__ import annotations

from types import SimpleNamespace

from novacode_cli.tui.app import NovaApp


def _sess(**kw):
    base = dict(
        session_id="f0ecd48c-1234", model_name="deepseek-v4-flash:cloud",
        message_count=172, task_status="active", last_active="2026-08-19T10:51:03+00:00",
        current_task=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_session_line_has_key_fields():
    line = NovaApp._session_log_line(_sess())
    assert line.startswith("f0ecd48c")          # short id
    assert "msgs=172" in line
    assert "active" in line
    assert "deepseek-v4-flash:cloud" in line
    assert "08-19 10:51" in line                 # ISO formatted


def test_session_line_includes_task_when_present():
    line = NovaApp._session_log_line(_sess(current_task="fix the /log command"))
    assert "· fix the /log command" in line


def test_session_line_survives_bad_timestamp():
    line = NovaApp._session_log_line(_sess(last_active="not-a-date"))
    assert "not-a-date"[:16] in line             # falls back to truncation, no crash

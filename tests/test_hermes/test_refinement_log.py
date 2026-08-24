"""Tests for the unified refinement audit trail (hermes/refinement_log.py).

Covers:
- ``append_refinement_event`` writes a timestamped event and caps the log.
- ``read_refinement_events`` returns the most recent events.
- ``rollback_refinement`` maps skill events to the versioning restore path and
  returns a clear message for prompt/memory events.
"""

import json
from pathlib import Path

import pytest

from novacode_cli.hermes.refinement_log import (
    _MAX_EVENTS,
    append_refinement_event,
    read_refinement_events,
    rollback_refinement,
)


@pytest.fixture
def nova_root(tmp_path: Path) -> Path:
    """A temporary ``~/.nova`` root."""
    root = tmp_path / ".nova"
    root.mkdir(parents=True, exist_ok=True)
    return root


class TestAppend:
    def test_appends_event(self, nova_root):
        event_id = append_refinement_event(
            nova_root,
            domain="skill",
            action="create",
            target="alpha",
        )
        assert event_id is not None
        events = read_refinement_events(nova_root)
        assert len(events) == 1
        assert events[0]["domain"] == "skill"
        assert events[0]["action"] == "create"
        assert events[0]["target"] == "alpha"

    def test_caps_log(self, nova_root):
        # Seed the log with more than the cap by writing directly (fast), then
        # append one more via the public API to confirm the cap trims oldest.
        path = nova_root / "refinement_events.json"
        seed = [
            {
                "id": f"seed{i}",
                "ts": float(i),
                "domain": "memory",
                "action": "record_lesson",
                "target": f"topic{i}",
                "detail": "",
                "outcome": "applied",
            }
            for i in range(_MAX_EVENTS)
        ]
        path.write_text(json.dumps(seed), encoding="utf-8")

        append_refinement_event(
            nova_root,
            domain="memory",
            action="record_lesson",
            target="newest",
        )
        events = read_refinement_events(nova_root, limit=_MAX_EVENTS + 100)
        assert len(events) == _MAX_EVENTS
        # Oldest (seed0) dropped; the newest append is retained.
        assert events[0]["target"] == "topic1"
        assert events[-1]["target"] == "newest"


class TestRead:
    def test_empty_when_no_log(self, nova_root):
        assert read_refinement_events(nova_root) == []

    def test_limit(self, nova_root):
        for i in range(5):
            append_refinement_event(nova_root, domain="memory", action="x", target=f"t{i}")
        events = read_refinement_events(nova_root, limit=2)
        assert len(events) == 2
        assert events[-1]["target"] == "t4"


class TestRollback:
    def test_unknown_event(self, nova_root):
        ok, message = rollback_refinement(nova_root, "nope")
        assert ok is False
        assert "no refinement event" in message

    def test_memory_has_no_rollback(self, nova_root):
        append_refinement_event(nova_root, domain="memory", action="record_lesson", target="t")
        event_id = read_refinement_events(nova_root)[0]["id"]
        ok, message = rollback_refinement(nova_root, event_id)
        assert ok is False
        assert "append-only" in message

    def test_prompt_points_to_prompt_system(self, nova_root):
        append_refinement_event(nova_root, domain="prompt", action="promote", target="core")
        event_id = read_refinement_events(nova_root)[0]["id"]
        ok, message = rollback_refinement(nova_root, event_id)
        assert ok is False
        assert "/prompt rollback" in message

    def test_skill_missing_dir(self, nova_root):
        append_refinement_event(nova_root, domain="skill", action="create", target="ghost")
        event_id = read_refinement_events(nova_root)[0]["id"]
        ok, message = rollback_refinement(nova_root, event_id)
        assert ok is False
        assert "not found" in message

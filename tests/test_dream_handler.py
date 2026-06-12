"""Tests for /dream memory consolidation.

Covers the bug where /dream looked in ~/.nova (root) instead of the real agent
memory dir, operating on the semantic surface (agent.md + memories/ topic
files), plus the legacy-UI → emit conversion.
"""

from __future__ import annotations

import types

from novacode_cli.commands.dream_handler import handle_dream_command


def _sink():
    lines: list[str] = []
    return lines, lines.append


async def test_no_memory_returns_true_and_emits(tmp_path, capsys):
    lines, emit = _sink()
    result = await handle_dream_command(
        types.SimpleNamespace(), "nova-agent", agent_dir=tmp_path, emit=emit
    )
    assert result is True
    assert any("No memory files found" in ln for ln in lines)
    # Output goes to the emit sink, not stdout (TUI-safe).
    assert capsys.readouterr().out == ""


async def test_with_tier_files_returns_virtual_path_prompt(tmp_path):
    (tmp_path / "agent.md").write_text("# Agent Memory\nLikes terse answers.\n", encoding="utf-8")
    lines, emit = _sink()

    result = await handle_dream_command(
        types.SimpleNamespace(), "nova-agent", agent_dir=tmp_path, emit=emit
    )
    assert isinstance(result, str)
    # The prompt targets the virtual /memories/ route (not a raw OS path) and
    # names the real tier file.
    assert "/memories/" in result
    assert "/memories/agent.md" in result
    assert any("Memory Consolidation" in ln for ln in lines)


async def test_index_uses_full_virtual_path(tmp_path):
    mem = tmp_path / "memories"
    mem.mkdir()
    (mem / "INDEX.md").write_text("- [A](a.md) — hook", encoding="utf-8")
    (tmp_path / "agent.md").write_text("u", encoding="utf-8")
    lines, emit = _sink()

    result = await handle_dream_command(
        types.SimpleNamespace(), "nova-agent", agent_dir=tmp_path, emit=emit
    )
    assert isinstance(result, str)
    # The consolidation references the index at its real virtual location.
    assert "/memories/memories/INDEX.md" in result


async def test_topic_files_are_listed(tmp_path):
    mem = tmp_path / "memories"
    mem.mkdir()
    (mem / "auth-design.md").write_text("notes", encoding="utf-8")
    lines, emit = _sink()

    result = await handle_dream_command(
        types.SimpleNamespace(), "nova-agent", agent_dir=tmp_path, emit=emit
    )
    assert isinstance(result, str)
    assert "/memories/memories/" in result
    assert "auth-design.md" in result

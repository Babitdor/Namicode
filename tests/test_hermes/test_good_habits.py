"""Render tests for the good-habits prompt + injection blocks."""

from __future__ import annotations

from novacode_cli.prompts import render_template


def test_review_prompt_shows_habit_section_on_clean_win():
    out = render_template(
        "nova_review.jinja",
        tool_call_count=10,
        prior_lessons="",
        recovered_from_error=False,
        clean_win=True,
    )
    assert "<habit>" in out
    assert "notably well" in out.lower()


def test_review_prompt_omits_habit_section_without_clean_win():
    out = render_template(
        "nova_review.jinja",
        tool_call_count=10,
        prior_lessons="",
        recovered_from_error=False,
        clean_win=False,
    )
    assert "notably well" not in out.lower()


def test_longterm_memory_renders_good_habits_when_present():
    out = render_template(
        "longterm_memory.jinja",
        agent_dir_absolute="/x",
        agent_dir_display="x",
        project_memory_info="None",
        project_deepagents_dir="/project-memory/",
        memory_index="",
        habits_memory="- Test-first for races.",
    )
    assert "Test-first for races" in out
    assert "good_habits" in out.lower()


def test_longterm_memory_omits_good_habits_when_absent():
    out = render_template(
        "longterm_memory.jinja",
        agent_dir_absolute="/x",
        agent_dir_display="x",
        project_memory_info="None",
        project_deepagents_dir="/project-memory/",
        memory_index="",
        habits_memory="",
    )
    assert "good_habits" not in out.lower()

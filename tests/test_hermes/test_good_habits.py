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

"""Standalone plan-mode tools for the main agent tool list.

Provides AskUserQuestion, EnterPlanMode, and ExitPlanMode as @tool-decorated
functions so they can be registered directly without requiring middleware.

| Tool             | interrupt() | Permission Required |
|------------------|-------------|---------------------|
| ask_user_question| Yes         | No                  |
| enter_plan_mode  | No          | No                  |
| exit_plan_mode   | Yes         | Yes                 |
"""

from __future__ import annotations

import contextvars
from typing import Any

from langchain.tools import tool
from langgraph.types import interrupt

from novacode_cli.prompts import render_template


_PLAN_MODE_PROMPT = render_template("planning.jinja")

_auto_approve_var: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "_auto_approve_var", default=False
)


# ---------------------------------------------------------------------------
# AskUserQuestion
# ---------------------------------------------------------------------------


def _normalize_options(
    raw: list[str | dict[str, Any]],
) -> tuple[list[str], dict[str, str]]:
    """Normalise options to display strings and build a label→value mapping."""
    display_options: list[str] = []
    value_map: dict[str, str] = {}
    for opt in raw:
        if isinstance(opt, dict):
            label = str(opt.get("label") or opt.get("value") or opt)
            description = opt.get("description", "")
            display = f"{label} — {description}" if description else label
            return_value = str(opt.get("value") or label)
        else:
            display = str(opt)
            return_value = str(opt)
        display_options.append(display)
        value_map[display] = return_value
    return display_options, value_map


@tool
def ask_user_question(
    question: str,
    options: list[str | dict[str, Any]],
    context: str | None = None,
) -> str:
    """Ask the user a multiple-choice question and wait for their response.

    Use this when you need clarification or a decision before proceeding.
    Provide at least 2 options — an "Other / free text" option is shown automatically.

    Args:
        question: The question to ask.
        options: At least 2 choices for the user. Each may be a plain string or a
            dict with "label", "value", and optional "description" keys.
        context: Optional one-sentence explanation of why you're asking.

    Returns:
        The user's selected option as a string.
    """
    if not options or len(options) < 2:
        return "Error: At least 2 options are required for ask_user_question."

    display_options, value_map = _normalize_options(options)

    request: dict[str, Any] = {
        "question": question,
        "options": display_options,
        "question_type": "structured",
    }
    if context:
        request["context"] = context

    response = interrupt({"type": "question", "request": request})

    raw_answer = (
        response["answer"] if isinstance(response, dict) and "answer" in response else str(response)
    )
    return value_map.get(raw_answer, raw_answer)


# ---------------------------------------------------------------------------
# EnterPlanMode
# ---------------------------------------------------------------------------


@tool
def enter_plan_mode(reason: str = "") -> str:
    """Switch to plan mode to investigate the codebase and design an approach before coding.

    Call this before any multi-step, complex, or hard-to-reverse task.
    Returns the full planning instructions — read them carefully and follow every phase.

    Args:
        reason: Optional one-sentence description of why planning is needed.

    Returns:
        Planning instructions to follow for the rest of this task.
    """
    header = f"Plan mode activated. Reason: {reason}\n\n" if reason else "Plan mode activated.\n\n"
    return header + _PLAN_MODE_PROMPT


# ---------------------------------------------------------------------------
# ExitPlanMode
# ---------------------------------------------------------------------------


@tool
def exit_plan_mode(plan: str = "") -> str:
    """Present your completed plan for user approval and exit plan mode.

    Pass your full implementation plan as Markdown in ``plan`` — it is shown to
    the user inline for review (Claude Code plan-mode style), so you do not need
    to write it to a file first. Execution pauses while the user reviews.

    Args:
        plan: The implementation plan as Markdown to present for approval.
            If omitted, the most recent plan written under ``.nova/plans/`` is
            used as a fallback.

    Returns:
        "Plan approved. Proceed with implementation." or
        "Plan rejected. Revise the plan based on user feedback."
    """
    response = interrupt(
        {
            "type": "plan_approval",
            "message": "Plan is ready for review.",
            "plan": plan or "",
        }
    )

    if isinstance(response, dict):
        if response.get("approved"):
            return "Plan approved. Proceed with implementation."
        action = response.get("action", "refine")
        feedback = response.get("feedback", "")
        feedback_suffix = f"\n\nUser feedback: {feedback}" if feedback else ""
        if action == "refine":
            return f"Plan needs refinement. Continue iterating on the plan.{feedback_suffix}"
        return f"Plan rejected. Revise the plan based on user feedback.{feedback_suffix}"
    return str(response)


__all__ = [
    "ask_user_question",
    "enter_plan_mode",
    "exit_plan_mode",
]

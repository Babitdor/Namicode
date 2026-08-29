"""The resume briefing must never reach the transcript.

``build_continuation_prompt`` seeds a resumed session with a SystemMessage
containing the identity block, workspace state, task state and continuation
instructions. It is context for the model alone — but on a resumed session the
model sometimes recites it back as its first reply, which reads to the user as
the assistant dumping its own system prompt.

Two layers guard this: the instruction tells the model not to echo it, and the
display filter drops it if the model does anyway. These pin the second layer,
which is the one that holds when the model ignores the instruction.
"""

from __future__ import annotations

from novacode_cli.core.streaming import (
    is_internal_context_text,
    looks_like_continuation_briefing,
)

NL = chr(10)


def test_identity_block_is_suppressed():
    assert looks_like_continuation_briefing("<identity>" + NL + "You are **Nova**")


def test_each_briefing_section_is_suppressed():
    """Any ONE of these headings is conclusive — no real answer writes them."""
    for heading in (
        "## Continuation Mode",
        "## Current Workspace State",
        "## Session Memory",
        "## Task State",
    ):
        body = heading + NL * 2 + "some content"
        assert is_internal_context_text(body), heading


def test_briefing_is_caught_after_a_lead_in():
    """Models prepend prose; a prefix-only check would miss that."""
    body = "Sure, here is where things stand." + NL * 2 + "## Continuation Mode" + NL + "x"
    assert is_internal_context_text(body)


def test_real_answers_with_similar_headings_survive():
    """The over-reach guard.

    "Summary" and "Next steps" are headings genuine answers use, and prose may
    mention "workspace state" or "session memory" without being the briefing.
    Suppressing a real answer is worse than the leak.
    """
    keep = (
        "I fixed the glob bug in filesystem.py.",
        "Done." + NL * 2 + "## Summary" + NL * 2 + "Pruning happens during the walk.",
        "Ok." + NL * 2 + "## Next steps" + NL * 2 + "- ship it",
        "The workspace state looks clean; git is on main.",
        "I saved that to session memory for you.",
    )
    for text in keep:
        assert not is_internal_context_text(text), text


def test_continuation_instruction_tells_the_model_not_to_echo():
    """Layer one: the prompt itself must forbid reciting the briefing."""
    from novacode_cli.session.session_prompt_builder import CONTINUATION_INSTRUCTION

    lowered = CONTINUATION_INSTRUCTION.lower()
    assert "never quote, echo" in lowered, CONTINUATION_INSTRUCTION[-400:]

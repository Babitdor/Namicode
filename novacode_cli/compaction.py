"""Conversation compaction and summarization for NovaCode-cli.

This module provides functionality to compress conversation history
by generating an intelligent summary that preserves key context.
"""

from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, RemoveMessage, ToolMessage

from novacode_cli.context import CompactionResult
from novacode_cli.prompts import render_template

# Summarization prompt template (loaded from Jinja)
# Template file: NovaCode_cli/prompts/summarization.jinja


def _format_message_content(content: Any) -> str:
    """Format message content to a string.

    Handles both string content and content blocks (list of dicts).

    Args:
        content: The message content (str or list of content blocks)

    Returns:
        Formatted string representation
    """
    if isinstance(content, str):
        return content

    if isinstance(content, list):
        # Handle content blocks (e.g., from Claude)
        text_parts = []
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    text_parts.append(block.get("text", ""))
                elif block.get("type") == "tool_use":
                    tool_name = block.get("name", "unknown_tool")
                    text_parts.append(f"[Called tool: {tool_name}]")
            elif isinstance(block, str):
                text_parts.append(block)
        return " ".join(text_parts)

    return str(content)


def _message_parts(messages: list[BaseMessage]) -> list[str]:
    """Render each message to a compact ``ROLE: text`` line (per-message truncation)."""
    parts: list[str] = []
    for msg in messages:
        if isinstance(msg, HumanMessage):
            content = _format_message_content(msg.content)
            if len(content) > 2000:
                content = content[:2000] + "... [truncated]"
            parts.append(f"USER: {content}")
        elif isinstance(msg, AIMessage):
            content = _format_message_content(msg.content)
            if len(content) > 2000:
                content = content[:2000] + "... [truncated]"
            parts.append(f"ASSISTANT: {content}")
        elif isinstance(msg, ToolMessage):
            content = _format_message_content(msg.content)
            if len(content) > 500:
                content = content[:500] + "... [truncated]"
            parts.append(f"TOOL({msg.name}): {content}")
    return parts


def _budget_chars(model: BaseChatModel, context_window: int | None = None) -> int:
    """Character budget for the summarizer's input, sized to the model's context
    window so a long conversation never overflows the summarization call itself.

    Prefers the caller-supplied ``context_window`` (the TUI passes the token
    tracker's effective window, which already accounts for Ollama ``num_ctx``);
    otherwise falls back to the static table (``use_dynamic=False`` — no slow/
    flaky live query here). Reserves ~45% of the window for the prompt template +
    generated summary; rough 4-chars/token.
    """
    window = context_window
    if not window or window <= 0:
        name = getattr(model, "model_name", None) or getattr(model, "model", None) or ""
        try:
            from novacode_cli.context._analysis import get_context_window_size

            window = get_context_window_size(str(name), use_dynamic=False)
        except Exception:  # noqa: BLE001
            window = 8192
    return max(8000, int(window * 0.55) * 4)


def _chunk_parts(parts: list[str], max_chars: int) -> list[list[str]]:
    """Group formatted parts into chunks each within ``max_chars``."""
    chunks: list[list[str]] = []
    cur: list[str] = []
    cur_len = 0
    for p in parts:
        if len(p) > max_chars:  # a single oversized part — hard-truncate it
            p = p[:max_chars] + "... [truncated]"
        if cur and cur_len + len(p) + 2 > max_chars:
            chunks.append(cur)
            cur, cur_len = [], 0
        cur.append(p)
        cur_len += len(p) + 2
    if cur:
        chunks.append(cur)
    return chunks


async def _summarize_text(
    model: BaseChatModel, conversation_text: str, focus_instructions: str | None
) -> str:
    """One summarization LLM call over ``conversation_text``."""
    if focus_instructions:
        focus_text = (
            f"\n**IMPORTANT - User requested focus on**: {focus_instructions}\n\n"
            "Make sure to especially preserve information related to this focus area.\n"
        )
    else:
        focus_text = ""
    prompt = render_template(
        "summarization.jinja",
        focus_instructions=focus_text,
        conversation=conversation_text,
    )
    response = await model.ainvoke([HumanMessage(content=prompt)])
    return _format_message_content(response.content)


def _answer_budget(budget: int, questions: str) -> int:
    """Conversation budget for the answer pass (reserve room for questions + template)."""
    return max(1000, budget - len(questions) - 500)


async def _generate_questions(model: BaseChatModel, summary: str) -> str:
    """One LLM call: read the summary and ask what important details are missing."""
    prompt = render_template("summarization_questions.jinja", summary=summary)
    response = await model.ainvoke([HumanMessage(content=prompt)])
    return _format_message_content(response.content).strip()


async def _answer_questions(
    model: BaseChatModel, questions: str, parts: list[str], budget: int
) -> str:
    """Answer the clarifying questions from the full conversation.

    Fits in one call when the conversation does; otherwise answers per chunk
    and merges the per-chunk answers into one consolidated Q&A block.
    """
    text = "\n\n".join(parts)
    q_budget = _answer_budget(budget, questions)
    if len(text) <= q_budget:
        prompt = render_template(
            "summarization_answers.jinja", questions=questions, conversation=text
        )
        response = await model.ainvoke([HumanMessage(content=prompt)])
        return _format_message_content(response.content).strip()

    per_chunk: list[str] = []
    for chunk in _chunk_parts(parts, q_budget):
        prompt = render_template(
            "summarization_answers.jinja",
            questions=questions,
            conversation="\n\n".join(chunk),
        )
        response = await model.ainvoke([HumanMessage(content=prompt)])
        per_chunk.append(_format_message_content(response.content).strip())

    # Merge: consolidate the per-chunk answers into one Q&A block (bounded).
    merged = "\n\n".join(
        f"## Excerpt {i + 1} of {len(per_chunk)}\n{a}" for i, a in enumerate(per_chunk)
    )
    prompt = render_template(
        "summarization_answers.jinja",
        questions=questions,
        conversation=merged[:q_budget],
    )
    response = await model.ainvoke([HumanMessage(content=prompt)])
    return _format_message_content(response.content).strip()


async def _qa_refine(
    model: BaseChatModel, summary: str, parts: list[str], budget: int
) -> str:
    """Gap-fill a lossy summary: ask what it missed, restore it from the source.

    Best-effort — any failure returns ``""`` so compaction falls back to the
    plain summary. Returns the Q&A block to append, or ``""`` when nothing
    is missing.
    """
    try:
        questions = await _generate_questions(model, summary)
        if not questions or "NONE" in questions.upper():
            return ""
        answers = await _answer_questions(model, questions, parts, budget)
        if not answers.strip():
            return ""
        return f"## Clarifying Q&A\n\n{answers.strip()}"
    except Exception:  # noqa: BLE001 — refinement must never break compaction
        return ""


async def summarize_conversation(
    model: BaseChatModel,
    messages: list[BaseMessage],
    focus_instructions: str | None = None,
    context_window: int | None = None,
) -> str:
    """Summarize a conversation, budgeted to the model's context window.

    Short conversations are summarized in a single call. Long ones (that would
    overflow the summarizer's own window — exactly when compaction matters most)
    are summarized **hierarchically**: chunk → summarize each chunk → summarize
    the chunk-summaries into one cohesive summary, recursing if still too large.
    The hierarchical path then runs a **Q&A gap-filling pass** (Meta-Harness
    port): a second call reads the summary and asks what important details are
    missing, and a third answers those questions from the full conversation —
    recovering details a single lossy pass drops. Best-effort: any failure falls
    back to the plain summary.

    Args:
        model: The LLM to use for summarization
        messages: The conversation messages to summarize
        focus_instructions: Optional focus instructions from the user
        context_window: Optional explicit context window (tokens); the TUI passes
            the token tracker's effective window.

    Returns:
        The summarized conversation as a string

    Raises:
        Exception: If the LLM call fails
    """
    parts = _message_parts(messages)
    budget = _budget_chars(model, context_window)
    text = "\n\n".join(parts)

    if len(text) <= budget:
        return await _summarize_text(model, text, focus_instructions)

    # Too big for one call → hierarchical summarization.
    chunks = _chunk_parts(parts, budget)
    summaries: list[str] = []
    for i, chunk in enumerate(chunks):
        s = await _summarize_text(model, "\n\n".join(chunk), focus_instructions)
        summaries.append(f"## Part {i + 1} of {len(chunks)}\n{s}")
    combined = "\n\n".join(summaries)

    # If even the combined chunk-summaries are too large, collapse them further.
    depth = 0
    while len(combined) > budget and depth < 3:
        depth += 1
        summaries = [
            await _summarize_text(model, "\n\n".join(group), focus_instructions)
            for group in _chunk_parts(combined.split("\n\n"), budget)
        ]
        combined = "\n\n".join(summaries)

    # Final pass: one cohesive summary from the collapsed material.
    final = await _summarize_text(model, combined[:budget], focus_instructions)

    # Q&A gap-filling (Meta-Harness port): the hierarchical path is lossy — ask
    # what the summary missed and restore it from the full conversation. Only
    # here: short single-pass summaries are already high-fidelity.
    qa = await _qa_refine(model, final, parts, budget)
    if qa:
        final = f"{final}\n\n{qa}"
    return final


async def compact_conversation(
    agent: Any,
    model: BaseChatModel,
    thread_id: str,
    focus_instructions: str | None = None,
    context_window: int | None = None,
) -> CompactionResult:
    """Compact a conversation by summarizing and replacing history.

    This function:
    1. Retrieves the current conversation history
    2. Generates a summary using the LLM
    3. Replaces the conversation with a single summary message

    Args:
        agent: The LangGraph agent
        model: The LLM model for summarization
        thread_id: The thread/session ID
        focus_instructions: Optional user instructions for what to preserve

    Returns:
        CompactionResult with details of the compaction operation
    """
    config = {"configurable": {"thread_id": thread_id}}

    try:
        # Get current state
        state = await agent.aget_state(config)
        messages = state.values.get("messages", [])

        if not messages:
            return CompactionResult(
                success=False,
                original_tokens=0,
                new_tokens=0,
                tokens_saved=0,
                messages_before=0,
                messages_after=0,
                summary="",
                error="No conversation history to compact.",
            )

        messages_before = len(messages)

        # Count original tokens using the model's tokenizer when available,
        # falling back to the rough 4-chars-per-token approximation.
        original_text = " ".join(
            _format_message_content(msg.content) for msg in messages if hasattr(msg, "content")
        )
        try:
            _orig = model.get_num_tokens_from_messages([HumanMessage(content=original_text)])
            original_tokens = _orig if isinstance(_orig, int) else len(original_text) // 4
        except Exception:
            original_tokens = len(original_text) // 4

        # Generate summary (budgeted to the model's context window)
        summary = await summarize_conversation(
            model, messages, focus_instructions, context_window=context_window
        )

        # Replace all existing messages with the summary in a single atomic update.
        # LangGraph's messages reducer uses add_messages semantics — passing
        # RemoveMessage + new message together ensures the state never passes
        # through an invalid intermediate (e.g. ToolMessages with no AIMessage),
        # which would cause langchain's _fetch_last_ai_and_tool_messages to crash.
        summary_message = HumanMessage(
            content=f"[Conversation context — previous session summarized]\n\n{summary}"
        )
        remove_ops = [RemoveMessage(id=msg.id) for msg in messages if msg.id]
        # Also clear any prior auto-summarization event. deepagents'
        # SummarizationMiddleware reconstructs the effective message list from
        # `_summarization_event` (a cutoff index into the OLD message list); if we
        # rewrite messages without clearing it, the next turn would slice the new
        # list at a stale index and corrupt context. Resetting it makes the fresh
        # summary the whole context.
        update_values: dict[str, Any] = {
            "messages": remove_ops + [summary_message],
            "_summarization_event": None,
        }
        try:
            await agent.aupdate_state(config=config, values=update_values, as_node="model")
        except Exception:
            # Older graphs without the summarization state key reject the extra
            # field; retry with just the message rewrite.
            await agent.aupdate_state(
                config=config,
                values={"messages": remove_ops + [summary_message]},
                as_node="model",
            )

        # Count new tokens using the model's tokenizer when available.
        try:
            _new = model.get_num_tokens_from_messages([HumanMessage(content=summary)])
            new_tokens = _new if isinstance(_new, int) else len(summary) // 4
        except Exception:
            new_tokens = len(summary) // 4

        return CompactionResult(
            success=True,
            original_tokens=original_tokens,
            new_tokens=new_tokens,
            tokens_saved=max(0, original_tokens - new_tokens),
            messages_before=messages_before,
            messages_after=1,
            summary=summary,
        )

    except Exception as e:
        return CompactionResult(
            success=False,
            original_tokens=0,
            new_tokens=0,
            tokens_saved=0,
            messages_before=0,
            messages_after=0,
            summary="",
            error=str(e),
        )

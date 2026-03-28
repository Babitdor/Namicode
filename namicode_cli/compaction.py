"""Conversation compaction and summarization for namicode-cli.

This module provides functionality to compress conversation history
by generating an intelligent summary that preserves key context.
"""

from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, RemoveMessage, ToolMessage

from namicode_cli.context.context_manager import CompactionResult

# Summarization prompt template
SUMMARIZATION_PROMPT = """You are summarizing a conversation between a user and an AI coding assistant.

Create a concise summary that preserves:
1. **Key decisions made** - architectural choices, design patterns selected
2. **Files modified** - list any files that were created, edited, or deleted
3. **Problems solved** - bugs fixed, features implemented
4. **Important context** - project structure understood, conventions established
5. **Pending tasks** - any incomplete work or next steps mentioned

{focus_instructions}

Format the summary as:

## Conversation Summary

### Files Modified
- [List of files with brief description of changes]

### Key Decisions
- [Important architectural/design decisions]

### Work Completed
- [Summary of what was accomplished]

### Outstanding Items
- [Any pending tasks or unresolved issues]

### Important Context
- [Key information that should be preserved for future reference]

### User Preferences & Conventions
- [Any user preferences, coding style, naming conventions, or workflow patterns established]
- [Active working directory and key file paths referenced]

Be thorough but concise. This summary will replace the full conversation history.
Keep it under 5000 tokens. Prioritize completeness for Files Modified and Outstanding Items.

---

CONVERSATION TO SUMMARIZE:

{conversation}
"""


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


async def summarize_conversation(
    model: BaseChatModel,
    messages: list[BaseMessage],
    focus_instructions: str | None = None,
) -> str:
    """Summarize a conversation using the LLM.

    Args:
        model: The LLM to use for summarization
        messages: The conversation messages to summarize
        focus_instructions: Optional focus instructions from user
            (e.g., "Focus on authentication changes")

    Returns:
        The summarized conversation as a string

    Raises:
        Exception: If the LLM call fails
    """
    # Build conversation text
    conversation_parts = []
    for msg in messages:
        if isinstance(msg, HumanMessage):
            content = _format_message_content(msg.content)
            # Truncate very long messages
            if len(content) > 2000:
                content = content[:2000] + "... [truncated]"
            conversation_parts.append(f"USER: {content}")
        elif isinstance(msg, AIMessage):
            content = _format_message_content(msg.content)
            if len(content) > 2000:
                content = content[:2000] + "... [truncated]"
            conversation_parts.append(f"ASSISTANT: {content}")
        elif isinstance(msg, ToolMessage):
            content = _format_message_content(msg.content)
            if len(content) > 500:
                content = content[:500] + "... [truncated]"
            conversation_parts.append(f"TOOL({msg.name}): {content}")

    conversation_text = "\n\n".join(conversation_parts)

    # Build focus instructions section
    if focus_instructions:
        focus_text = f"\n**IMPORTANT - User requested focus on**: {focus_instructions}\n\nMake sure to especially preserve information related to this focus area.\n"
    else:
        focus_text = ""

    # Create summarization prompt
    prompt = SUMMARIZATION_PROMPT.format(
        focus_instructions=focus_text,
        conversation=conversation_text,
    )

    # Get summary from model
    response = await model.ainvoke([HumanMessage(content=prompt)])

    return _format_message_content(response.content)


async def compact_conversation(
    agent: Any,
    model: BaseChatModel,
    thread_id: str,
    focus_instructions: str | None = None,
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

        # Generate summary
        summary = await summarize_conversation(model, messages, focus_instructions)

        # Replace all existing messages with the summary in a single atomic update.
        # LangGraph's messages reducer uses add_messages semantics — passing
        # RemoveMessage + new message together ensures the state never passes
        # through an invalid intermediate (e.g. ToolMessages with no AIMessage),
        # which would cause langchain's _fetch_last_ai_and_tool_messages to crash.
        summary_message = HumanMessage(
            content=f"[Conversation context — previous session summarized]\n\n{summary}"
        )
        remove_ops = [RemoveMessage(id=msg.id) for msg in messages if msg.id]
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

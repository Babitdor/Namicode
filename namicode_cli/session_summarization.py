"""Session summarization for creating declarative memory.md files.

This module generates long-term declarative memory from conversation history,
focusing on outcomes rather than dialogue.
"""

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

SUMMARIZATION_SYSTEM_PROMPT = """You are a session summarizer. Your job is to create a concise, declarative memory.md file from a conversation history.

## Rules for memory.md

**MUST INCLUDE:**
- Current goal/objective
- Key decisions made
- Constraints discovered during the session
- Files that were created, modified, or examined
- Rejected approaches and why (outcome only, not reasoning)
- Pending TODOs or next steps

**MUST NOT INCLUDE:**
- Conversational dialogue or back-and-forth
- Tool execution logs or stdout
- Reasoning, thinking, or chain-of-thought
- Restatements of rules from NAMI.md (those are already injected separately)
- Verbatim code unless it's a critical snippet for context

## Format

Use markdown with clear sections:

```markdown
# Session Memory

## Current Goal
[What is the user trying to achieve?]

## Key Decisions
- [Decision 1]
- [Decision 2]

## Files Modified
- `path/to/file.py` - [what changed]
- `another/file.ts` - [what changed]

## Constraints & Discoveries
- [Constraint or discovery 1]
- [Constraint or discovery 2]

## Rejected Approaches
- [Approach X] - didn't work because [outcome]

## Next Steps
- [ ] [TODO 1]
- [ ] [TODO 2]
```

Focus on **what happened** and **what was learned**, not **how** or **why** in detail."""


def summarize_messages_to_memory(
    messages: list[BaseMessage],
    model: BaseChatModel,
    current_task: str | None = None,
) -> str:
    """Summarize conversation messages into declarative memory.md content.

    Args:
        messages: List of conversation messages to summarize
        model: LLM to use for summarization
        current_task: Optional current task description

    Returns:
        memory.md content as a string
    """
    if not messages:
        return "# Session Memory\n\n(No activity yet)\n"

    # Build conversation summary for the LLM
    conversation_summary = _build_conversation_summary(messages)

    # Create prompt for summarization
    user_prompt = f"""Summarize this conversation into a declarative memory.md file.

Current task: {current_task or "No specific task set"}

Conversation summary:
{conversation_summary}

Generate the memory.md content following the format specified in your instructions."""

    # Call the LLM
    summary_messages = [
        SystemMessage(content=SUMMARIZATION_SYSTEM_PROMPT),
        HumanMessage(content=user_prompt),
    ]

    try:
        response = model.invoke(summary_messages)
        memory_content = response.content if hasattr(response, 'content') else str(response)
        return memory_content.strip()
    except Exception as e:
        # Fallback to basic summary if LLM fails
        return f"""# Session Memory

## Error
Failed to generate summary: {e}

## Message Count
{len(messages)} messages in conversation

## Current Task
{current_task or "Not specified"}
"""


def _build_conversation_summary(messages: list[BaseMessage], max_length: int = 10000) -> str:
    """Build a textual summary of the conversation for the summarizer.

    Args:
        messages: Messages to summarize
        max_length: Maximum character length

    Returns:
        Formatted conversation summary
    """
    lines = []

    for i, msg in enumerate(messages):
        msg_type = msg.__class__.__name__
        content = str(msg.content) if msg.content else "(empty)"

        # Truncate very long messages
        if len(content) > 500:
            content = content[:497] + "..."

        # Format based on message type
        if msg_type == "HumanMessage":
            lines.append(f"[{i+1}] User: {content}")
        elif msg_type == "AIMessage":
            # Check for tool calls
            if hasattr(msg, 'tool_calls') and msg.tool_calls:
                tool_names = [tc.get('name', 'unknown') for tc in msg.tool_calls]
                lines.append(f"[{i+1}] Assistant: (called tools: {', '.join(tool_names)})")
            if content and not content.startswith("[") and len(content) > 10:
                lines.append(f"[{i+1}] Assistant: {content}")
        elif msg_type == "ToolMessage":
            tool_name = getattr(msg, 'name', 'unknown')
            # Include tool result if it's not too long
            if len(content) < 200:
                lines.append(f"[{i+1}] Tool({tool_name}): {content}")
            else:
                lines.append(f"[{i+1}] Tool({tool_name}): (output length: {len(content)} chars)")

    summary = "\n".join(lines)

    # Truncate if too long
    if len(summary) > max_length:
        summary = summary[:max_length] + "\n...(truncated)"

    return summary


def should_trigger_summarization(
    message_count: int,
    recent_limit: int = 8,
    task_status: str | None = None,
) -> bool:
    """Determine if summarization should be triggered.

    Triggers when:
    - Message count exceeds recent limit significantly
    - Task status changed to 'complete'

    Args:
        message_count: Total number of messages in session
        recent_limit: Number of recent messages to keep
        task_status: Current task status

    Returns:
        True if summarization should be triggered
    """
    # Trigger if we have way more messages than the recent limit
    if message_count > recent_limit * 2:
        return True

    # Trigger when task is marked complete
    if task_status == "complete":
        return True

    return False

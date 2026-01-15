"""Tests for compaction module."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from namicode_cli.compaction import (
    SUMMARIZATION_PROMPT,
    _format_message_content,
    compact_conversation,
    summarize_conversation,
)
from namicode_cli.context.context_manager import CompactionResult


class TestSummarizationPrompt:
    """Test SUMMARIZATION_PROMPT constant."""

    def test_prompt_contains_key_sections(self) -> None:
        """Test that prompt contains expected sections."""
        assert "Files Modified" in SUMMARIZATION_PROMPT
        assert "Key Decisions" in SUMMARIZATION_PROMPT
        assert "Work Completed" in SUMMARIZATION_PROMPT
        assert "Outstanding Items" in SUMMARIZATION_PROMPT

    def test_prompt_has_focus_placeholder(self) -> None:
        """Test that prompt has placeholder for focus instructions."""
        assert "{focus_instructions}" in SUMMARIZATION_PROMPT


class TestFormatMessageContent:
    """Test _format_message_content helper function."""

    def test_string_content(self) -> None:
        """Test formatting string content."""
        result = _format_message_content("Hello world")
        assert result == "Hello world"

    def test_list_with_text_blocks(self) -> None:
        """Test formatting list with text content blocks."""
        content = [
            {"type": "text", "text": "Hello"},
            {"type": "text", "text": "World"},
        ]
        result = _format_message_content(content)
        assert "Hello" in result
        assert "World" in result

    def test_list_with_tool_use_blocks(self) -> None:
        """Test formatting list with tool use blocks."""
        content = [
            {"type": "tool_use", "name": "read_file"},
            {"type": "text", "text": "Here is the content"},
        ]
        result = _format_message_content(content)
        assert "[Called tool: read_file]" in result
        assert "Here is the content" in result

    def test_other_types(self) -> None:
        """Test formatting other types."""
        result = _format_message_content(12345)
        assert result == "12345"


class TestSummarizeConversation:
    """Test summarize_conversation function."""

    @pytest.mark.asyncio
    async def test_basic_summarization(self) -> None:
        """Test basic conversation summarization."""
        mock_model = AsyncMock()
        mock_model.ainvoke.return_value = AIMessage(content="## Summary\nTest summary")

        messages = [
            HumanMessage(content="Hello"),
            AIMessage(content="Hi there!"),
        ]

        result = await summarize_conversation(mock_model, messages)

        assert result == "## Summary\nTest summary"
        mock_model.ainvoke.assert_called_once()

    @pytest.mark.asyncio
    async def test_summarization_with_focus(self) -> None:
        """Test summarization with focus instructions."""
        mock_model = AsyncMock()
        mock_model.ainvoke.return_value = AIMessage(content="## Summary\nFocused summary")

        messages = [
            HumanMessage(content="Let's work on auth"),
            AIMessage(content="Sure, I'll help with authentication"),
        ]

        result = await summarize_conversation(
            mock_model, messages, focus_instructions="Focus on authentication changes"
        )

        assert result == "## Summary\nFocused summary"
        # Verify focus instructions were included in the prompt
        call_args = mock_model.ainvoke.call_args
        prompt_messages = call_args[0][0]
        # The prompt should contain the focus instructions
        assert len(prompt_messages) == 1
        assert "Focus on authentication changes" in prompt_messages[0].content

    @pytest.mark.asyncio
    async def test_summarization_empty_messages(self) -> None:
        """Test summarization with empty messages list."""
        mock_model = AsyncMock()
        mock_model.ainvoke.return_value = AIMessage(content="## Summary\nNo conversation")

        result = await summarize_conversation(mock_model, [])

        assert "No conversation" in result

    @pytest.mark.asyncio
    async def test_summarization_with_system_messages(self) -> None:
        """Test that system messages are filtered out of conversation."""
        mock_model = AsyncMock()
        mock_model.ainvoke.return_value = AIMessage(content="## Summary\nTest")

        messages = [
            SystemMessage(content="You are a helpful assistant"),
            HumanMessage(content="Hello"),
            AIMessage(content="Hi!"),
        ]

        await summarize_conversation(mock_model, messages)

        # Verify only user/assistant messages are in conversation
        call_args = mock_model.ainvoke.call_args
        prompt_messages = call_args[0][0]
        # Should have single HumanMessage with the prompt
        assert len(prompt_messages) == 1
        prompt_content = prompt_messages[0].content
        # System message should NOT be in the conversation
        assert "You are a helpful assistant" not in prompt_content
        # User and assistant messages SHOULD be there
        assert "USER: Hello" in prompt_content
        assert "ASSISTANT: Hi!" in prompt_content


class TestCompactConversation:
    """Test compact_conversation function."""

    @pytest.mark.asyncio
    async def test_compact_empty_conversation(self) -> None:
        """Test compacting an empty conversation."""
        mock_agent = AsyncMock()
        mock_agent.aget_state.return_value = MagicMock(values={"messages": []})

        mock_model = AsyncMock()

        result = await compact_conversation(
            agent=mock_agent,
            model=mock_model,
            thread_id="test-thread",
        )

        assert result is not None
        assert result.success is False
        assert result.error == "No conversation history to compact."
        mock_model.ainvoke.assert_not_called()

    @pytest.mark.asyncio
    async def test_compact_success(self) -> None:
        """Test successful conversation compaction."""
        messages = [
            HumanMessage(content="Hello"),
            AIMessage(content="Hi! How can I help?"),
            HumanMessage(content="Write code"),
            AIMessage(content="Sure, here's the code..."),
        ]

        mock_agent = AsyncMock()
        mock_agent.aget_state.return_value = MagicMock(values={"messages": messages})

        mock_model = AsyncMock()
        mock_model.ainvoke.return_value = AIMessage(
            content="## Summary\nUser requested code, assistant provided it."
        )

        result = await compact_conversation(
            agent=mock_agent,
            model=mock_model,
            thread_id="test-thread",
        )

        assert result is not None
        assert isinstance(result, CompactionResult)
        assert result.success is True
        assert "Summary" in result.summary
        assert result.messages_before == 4
        assert result.messages_after == 1
        mock_agent.aupdate_state.assert_called_once()

    @pytest.mark.asyncio
    async def test_compact_with_focus_instructions(self) -> None:
        """Test compaction with focus instructions."""
        messages = [
            HumanMessage(content="Let's fix the auth bug"),
            AIMessage(content="I'll look at the authentication code"),
        ]

        mock_agent = AsyncMock()
        mock_agent.aget_state.return_value = MagicMock(values={"messages": messages})

        mock_model = AsyncMock()
        mock_model.ainvoke.return_value = AIMessage(content="## Auth Summary\nFixed auth bug")

        result = await compact_conversation(
            agent=mock_agent,
            model=mock_model,
            thread_id="test-thread",
            focus_instructions="Focus on authentication changes",
        )

        assert result is not None
        assert result.success is True
        assert "Auth Summary" in result.summary

    @pytest.mark.asyncio
    async def test_compact_state_error(self) -> None:
        """Test handling of state access error."""
        mock_agent = AsyncMock()
        mock_agent.aget_state.side_effect = Exception("State access failed")

        mock_model = AsyncMock()

        result = await compact_conversation(
            agent=mock_agent,
            model=mock_model,
            thread_id="test-thread",
        )

        assert result is not None
        assert result.success is False
        assert "State access failed" in result.error

    @pytest.mark.asyncio
    async def test_compact_summarization_error(self) -> None:
        """Test handling of summarization error."""
        messages = [
            HumanMessage(content="Hello"),
            AIMessage(content="Hi!"),
        ]

        mock_agent = AsyncMock()
        mock_agent.aget_state.return_value = MagicMock(values={"messages": messages})

        mock_model = AsyncMock()
        mock_model.ainvoke.side_effect = Exception("Model error")

        result = await compact_conversation(
            agent=mock_agent,
            model=mock_model,
            thread_id="test-thread",
        )

        assert result is not None
        assert result.success is False
        assert "Model error" in result.error

    @pytest.mark.asyncio
    async def test_compact_update_state_error(self) -> None:
        """Test handling of state update error."""
        messages = [
            HumanMessage(content="Hello"),
            AIMessage(content="Hi!"),
        ]

        mock_agent = AsyncMock()
        mock_agent.aget_state.return_value = MagicMock(values={"messages": messages})
        mock_agent.aupdate_state.side_effect = Exception("Update failed")

        mock_model = AsyncMock()
        mock_model.ainvoke.return_value = AIMessage(content="## Summary")

        result = await compact_conversation(
            agent=mock_agent,
            model=mock_model,
            thread_id="test-thread",
        )

        assert result is not None
        assert result.success is False
        assert "Update failed" in result.error

    @pytest.mark.asyncio
    async def test_compact_tokens_estimated(self) -> None:
        """Test that tokens are estimated correctly."""
        # Create a message with known content length
        # ~4 chars per token, so "Hello" (5 chars) + "Hi!" (3 chars) = 8 chars = ~2 tokens
        messages = [
            HumanMessage(content="Hello"),
            AIMessage(content="Hi!"),
        ]

        mock_agent = AsyncMock()
        mock_agent.aget_state.return_value = MagicMock(values={"messages": messages})

        mock_model = AsyncMock()
        mock_model.ainvoke.return_value = AIMessage(content="Summary")

        result = await compact_conversation(
            agent=mock_agent,
            model=mock_model,
            thread_id="test-thread",
        )

        assert result is not None
        assert result.success is True
        # Original tokens should be estimated from message content
        assert result.original_tokens > 0
        # New tokens should be estimated from summary
        assert result.new_tokens > 0
        # Tokens saved should be non-negative (enforced by max(0, ...))
        assert result.tokens_saved >= 0

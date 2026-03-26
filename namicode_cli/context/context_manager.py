"""Context window management and analysis for namicode-cli.

This module provides utilities for tracking and analyzing context window usage,
including model-specific context window sizes and detailed token breakdowns.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from langchain_core.messages import BaseMessage

# Model context window sizes (input tokens)
# These are approximate and may vary by version
MODEL_CONTEXT_WINDOWS: dict[str, int] = {
    # OpenAI models
    "gpt-4": 128_000,
    "gpt-4-turbo": 128_000,
    "gpt-4-turbo-preview": 128_000,
    "gpt-4o": 128_000,
    "gpt-4o-mini": 128_000,
    "gpt-5-mini": 128_000,
    "gpt-3.5-turbo": 16_000,
    "gpt-3.5-turbo-16k": 16_000,
    # Anthropic models
    "claude-sonnet-4-5-20250929": 200_000,
    "claude-opus-4-5-20251101": 200_000,
    "claude-3-5-sonnet-20241022": 200_000,
    "claude-3-5-haiku-20241022": 200_000,
    "claude-3-opus-20240229": 200_000,
    "claude-3-sonnet-20240229": 200_000,
    "claude-3-haiku-20240307": 200_000,
    # Google Gemini models
    "gemini-3-pro-preview": 1_000_000,
    "gemini-2.0-flash-exp": 1_000_000,
    "gemini-1.5-pro": 2_000_000,
    "gemini-1.5-flash": 1_000_000,
    "gemini-1.0-pro": 32_000,
    # Ollama models (cloud and local variants)
    "qwen3-coder": 200_000,
    "qwen3-coder:480b-cloud": 200_000,
    "qwen3-next:80b-cloud": 200_000,
    "qwen3-vl:235b-instruct-cloud": 200_000,
    "qwen3-vl:235b-cloud": 200_000,
    "llama3": 128_000,
    "codellama": 16_000,
    "mistral": 32_000,
    "mistral-large-3:675b-cloud": 128_000,
    "mixtral": 32_000,
    # DeepSeek models
    "deepseek-v3.1:671b-cloud": 128_000,
    # Devstral models
    "devstral-2:123b-cloud": 128_000,
    # Cogito models
    "cogito-2.1:671b-cloud": 128_000,
    # Kimi models
    "kimi-k2-thinking:cloud": 128_000,
    "kimi-k2:1t-cloud": 128_000,
    # GLM models
    "glm-4.7:cloud": 128_000,
    "glm-4.6:cloud": 128_000,
    # MiniMax models
    "minimax-m2.1:cloud": 128_000,
    "minimax-m2:cloud": 128_000,
    # Nemotron models
    "nemotron-3-nano:30b-cloud": 128_000,
    # RNJ models
    "rnj-1:8b-cloud": 128_000,
    # GPT-OSS models
    "gpt-oss:20b-cloud": 128_000,
    "gpt-oss:120b-cloud": 128_000,
    # Default fallback
    "default": 128_000,
}

# Context usage thresholds for warnings
CONTEXT_WARNING_THRESHOLD = 0.75  # Yellow warning at 75%
CONTEXT_CRITICAL_THRESHOLD = 0.90  # Red warning at 90%


@dataclass
class ContextBreakdown:
    """Detailed breakdown of context window usage.

    Attributes:
        system_prompt_tokens: Tokens used by the system prompt
        user_memory_tokens: Tokens used by user agent.md
        project_memory_tokens: Tokens used by project agent.md
        tool_definitions_tokens: Tokens used by tool definitions
        user_message_tokens: Tokens from user messages
        assistant_message_tokens: Tokens from assistant messages
        tool_result_tokens: Tokens from tool call results
        total_tokens: Total tokens currently used
        context_window_size: Maximum context window for the model
        user_message_count: Number of user messages
        assistant_message_count: Number of assistant messages
        tool_call_count: Number of tool calls made
    """

    # Static/baseline content
    system_prompt_tokens: int = 0
    user_memory_tokens: int = 0
    project_memory_tokens: int = 0
    tool_definitions_tokens: int = 0

    # Conversation content
    user_message_tokens: int = 0
    assistant_message_tokens: int = 0
    tool_result_tokens: int = 0

    # Totals
    total_tokens: int = 0
    context_window_size: int = 128_000

    # Message counts
    user_message_count: int = 0
    assistant_message_count: int = 0
    tool_call_count: int = 0

    @property
    def baseline_tokens(self) -> int:
        """Calculate tokens used by static/baseline content.

        This includes system prompt, memory files, and tool definitions.
        """
        return (
            self.system_prompt_tokens
            + self.user_memory_tokens
            + self.project_memory_tokens
            + self.tool_definitions_tokens
        )

    @property
    def conversation_tokens(self) -> int:
        """Calculate tokens used by conversation content.

        This includes user messages, assistant messages, and tool results.
        """
        return self.user_message_tokens + self.assistant_message_tokens + self.tool_result_tokens

    @property
    def remaining_tokens(self) -> int:
        """Calculate tokens still available in context window."""
        return max(0, self.context_window_size - self.total_tokens)

    @property
    def usage_percentage(self) -> float:
        """Calculate percentage of context window used."""
        if self.context_window_size == 0:
            return 0.0
        return (self.total_tokens / self.context_window_size) * 100

    @property
    def is_warning(self) -> bool:
        """Check if context usage has reached warning threshold (75%)."""
        return self.usage_percentage >= CONTEXT_WARNING_THRESHOLD * 100

    @property
    def is_critical(self) -> bool:
        """Check if context usage has reached critical threshold (90%)."""
        return self.usage_percentage >= CONTEXT_CRITICAL_THRESHOLD * 100


@dataclass
class CompactionResult:
    """Result of conversation compaction operation.

    Attributes:
        success: Whether compaction completed successfully
        original_tokens: Estimated tokens before compaction
        new_tokens: Estimated tokens after compaction
        tokens_saved: Tokens freed by compaction
        messages_before: Number of messages before compaction
        messages_after: Number of messages after compaction
        summary: The generated summary text
        error: Error message if compaction failed
    """

    success: bool
    original_tokens: int
    new_tokens: int
    tokens_saved: int
    messages_before: int
    messages_after: int
    summary: str
    error: str | None = None


def get_context_window_size(model_name: str) -> int:
    """Get the context window size for a given model.

    Args:
        model_name: The name of the model (e.g., "gpt-4", "claude-3-opus")

    Returns:
        The context window size in tokens. Falls back to default (128K)
        if the model is not recognized.
    """
    # Direct match
    if model_name in MODEL_CONTEXT_WINDOWS:
        return MODEL_CONTEXT_WINDOWS[model_name]

    # Try lowercase match
    model_lower = model_name.lower()
    for key, size in MODEL_CONTEXT_WINDOWS.items():
        if key.lower() == model_lower:
            return size

    # Partial match - check if any known model name is contained
    for key, size in MODEL_CONTEXT_WINDOWS.items():
        if key in model_name or key in model_lower:
            return size
        # Also check if model_name contains the key
        if model_name in key or model_lower in key.lower():
            return size

    # Check for model family prefixes
    if "gpt-4" in model_lower:
        return MODEL_CONTEXT_WINDOWS["gpt-4"]
    if "gpt-3.5" in model_lower:
        return MODEL_CONTEXT_WINDOWS["gpt-3.5-turbo"]
    if "claude" in model_lower:
        return 200_000  # Most Claude models have 200K
    if "gemini" in model_lower:
        return 1_000_000  # Conservative for Gemini
    if "qwen" in model_lower or "ollama" in model_lower:
        return 200_000  # Ollama default

    return MODEL_CONTEXT_WINDOWS["default"]


def format_token_count(tokens: int) -> str:
    """Format a token count for display.

    Args:
        tokens: The token count to format

    Returns:
        Formatted string with thousands separators (e.g., "128,000")
    """
    return f"{tokens:,}"


def _estimate_tokens(text: str) -> int:
    """Estimate token count from text using char/4 heuristic."""
    return len(text) // 4


def _message_text(msg: BaseMessage) -> str:
    """Extract text content from a message."""
    content = msg.content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                parts.append(block.get("text", ""))
            elif isinstance(block, str):
                parts.append(block)
        return " ".join(parts)
    return str(content)


def build_context_breakdown(
    messages: list[BaseMessage],
    model_name: str,
) -> ContextBreakdown:
    """Build a ContextBreakdown from the current conversation state.

    Uses character-based token estimation (len // 4). This is approximate
    but sufficient for threshold-based warnings.

    Args:
        messages: Current conversation messages from agent state.
        model_name: Model name for looking up context window size.

    Returns:
        Populated ContextBreakdown with usage stats.
    """
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

    context_window = get_context_window_size(model_name)

    system_tokens = 0
    user_tokens = 0
    assistant_tokens = 0
    tool_tokens = 0
    user_count = 0
    assistant_count = 0
    tool_count = 0

    for msg in messages:
        text = _message_text(msg)
        tokens = _estimate_tokens(text)

        if isinstance(msg, SystemMessage):
            system_tokens += tokens
        elif isinstance(msg, HumanMessage):
            user_tokens += tokens
            user_count += 1
        elif isinstance(msg, AIMessage):
            assistant_tokens += tokens
            assistant_count += 1
            # Count tool calls
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                tool_count += len(msg.tool_calls)
        elif isinstance(msg, ToolMessage):
            tool_tokens += tokens

    total = system_tokens + user_tokens + assistant_tokens + tool_tokens

    return ContextBreakdown(
        system_prompt_tokens=system_tokens,
        user_message_tokens=user_tokens,
        assistant_message_tokens=assistant_tokens,
        tool_result_tokens=tool_tokens,
        total_tokens=total,
        context_window_size=context_window,
        user_message_count=user_count,
        assistant_message_count=assistant_count,
        tool_call_count=tool_count,
    )

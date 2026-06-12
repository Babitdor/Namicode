"""Context-window analysis: token breakdown, window sizing, compaction advice.

Private to the ``context`` package. Provides the deterministic, model-aware
analysis that backs ``ContextManager``: per-message token estimation, the
hardcoded model→window table (with Ollama dynamic detection as the first
source), and the compaction recommendation heuristics.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from langchain_core.messages import BaseMessage

logger = logging.getLogger(__name__)

# Model context window sizes (input tokens). Approximate; may vary by version.
# Updated with actual values from Ollama (2026-04-05).
MODEL_CONTEXT_WINDOWS: dict[str, int] = {
    # OpenAI models
    "gpt-4": 128_000,
    "gpt-4-turbo": 128_000,
    "gpt-4-turbo-preview": 128_000,
    "gpt-4o": 128_000,
    "gpt-4o-mini": 128_000,
    "gpt-5": 128_000,
    "gpt-5-mini": 128_000,
    "gpt-3.5-turbo": 16_000,
    "gpt-3.5-turbo-16k": 16_000,
    # Anthropic models — Claude 4.x
    "claude-opus-4-8": 200_000,
    "claude-sonnet-4-8": 200_000,
    "claude-opus-4-7": 200_000,
    "claude-sonnet-4-7": 200_000,
    "claude-opus-4-6": 200_000,
    "claude-sonnet-4-6": 200_000,
    "claude-haiku-4-5-20251001": 200_000,
    "claude-haiku-4-5": 200_000,
    # Anthropic models — Claude 4.5
    "claude-sonnet-4-5-20250929": 200_000,
    "claude-opus-4-5-20251101": 200_000,
    "claude-sonnet-4-5": 200_000,
    "claude-opus-4-5": 200_000,
    # Anthropic models — Claude 3.x
    "claude-3-5-sonnet-20241022": 200_000,
    "claude-3-5-haiku-20241022": 200_000,
    "claude-3-opus-20240229": 200_000,
    "claude-3-sonnet-20240229": 200_000,
    "claude-3-haiku-20240307": 200_000,
    # Google Gemini models
    "gemini-3-pro-preview": 1_048_576,  # 1M context
    "gemini-3-flash-preview": 1_048_576,  # 1M context
    "gemini-2.0-flash-exp": 1_000_000,
    "gemini-1.5-pro": 2_000_000,
    "gemini-1.5-flash": 1_000_000,
    "gemini-1.0-pro": 32_000,
    # Ollama cloud models (actual values from Ollama)
    "glm-5": 202_752,
    "glm-4.7": 202_752,
    "glm-4.6": 202_752,
    "qwen3.5": 262_144,  # 256K
    "qwen3-coder": 262_144,
    "qwen3-coder:480b-cloud": 262_144,
    "qwen3-next:80b-cloud": 262_144,
    "qwen3-vl:235b-instruct-cloud": 262_144,
    "qwen3-vl:235b-cloud": 262_144,
    "gemma4": 262_144,
    "minimax-m2.7": 204_800,
    "minimax-m2.5": 204_800,
    "minimax-m2.1": 204_800,
    "minimax-m2": 204_800,
    "cogito-2.1:671b-cloud": 163_840,
    "deepseek-v3.1:671b-cloud": 163_840,
    "devstral-2:123b-cloud": 262_144,
    "mistral-large-3:675b-cloud": 262_144,
    "ministral-3:14b-cloud": 262_144,
    "kimi-k2.5": 262_144,
    "kimi-k2-thinking": 262_144,
    "kimi-k2:1t-cloud": 262_144,
    "nemotron-3-nano:30b-cloud": 1_048_576,  # 1M context
    # Ollama local models (actual values from Ollama)
    "llama3.1": 131_072,  # 128K
    "llama3.2": 131_072,  # 128K
    "llama3": 131_072,
    "mistral": 32_768,  # 32K
    "mixtral": 32_768,
    "codellama": 16_000,
    "glm-ocr": 131_072,
    "qwen3": 40_960,
    "qwen3:8b": 40_960,
    "qwen3:1.7b": 40_960,
    # SysML models
    "SysML-V2-llama3.1": 131_072,
    "SysML-V2-llama3.2": 131_072,
    "Qwen3-4B-SysMLv2": 40_960,
    "Qwen3-8B-SysMLv2": 40_960,
    "Qwen3-SysMLv2": 40_960,
    # GPT-OSS models
    "gpt-oss:20b-cloud": 131_072,
    "gpt-oss:120b-cloud": 131_072,
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
        """Tokens used by static/baseline content (system prompt, memory, tools)."""
        return (
            self.system_prompt_tokens
            + self.user_memory_tokens
            + self.project_memory_tokens
            + self.tool_definitions_tokens
        )

    @property
    def conversation_tokens(self) -> int:
        """Tokens used by conversation content (user/assistant/tool messages)."""
        return (
            self.user_message_tokens
            + self.assistant_message_tokens
            + self.tool_result_tokens
        )

    @property
    def remaining_tokens(self) -> int:
        """Tokens still available in context window."""
        return max(0, self.context_window_size - self.total_tokens)

    @property
    def usage_percentage(self) -> float:
        """Percentage of context window used."""
        if self.context_window_size == 0:
            return 0.0
        return (self.total_tokens / self.context_window_size) * 100

    @property
    def is_warning(self) -> bool:
        """Whether context usage has reached the warning threshold (75%)."""
        return self.usage_percentage >= CONTEXT_WARNING_THRESHOLD * 100

    @property
    def is_critical(self) -> bool:
        """Whether context usage has reached the critical threshold (90%)."""
        return self.usage_percentage >= CONTEXT_CRITICAL_THRESHOLD * 100


@dataclass
class CompactionResult:
    """Result of a conversation compaction operation.

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


def _lookup_hardcoded_window(model_name: str) -> int:
    """Resolve a model's architecture context window from the static table.

    Tries exact, case-insensitive, substring, then model-family matches, and
    falls back to the 128K default. This is the model's *trained* window; for
    Ollama-served models it is bounded by ``num_ctx`` in
    :func:`get_context_window_size`.
    """
    # Direct match in hardcoded configs
    if model_name in MODEL_CONTEXT_WINDOWS:
        return MODEL_CONTEXT_WINDOWS[model_name]

    # Try lowercase match
    model_lower = model_name.lower()
    for key, size in MODEL_CONTEXT_WINDOWS.items():
        if key.lower() == model_lower:
            return size

    # Partial match — check if any known model name is contained
    for key, size in MODEL_CONTEXT_WINDOWS.items():
        if key in model_name or key in model_lower:
            return size
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


def get_context_window_size(model_name: str, use_dyNovac: bool = True) -> int:
    """Get the *effective* context window size for a given model.

    For cloud API models (Claude/GPT/Gemini/o-series) this is the model's
    published window. For Ollama-served models the effective window is
    ``min(architecture_window, num_ctx)``: Nova loads Ollama models with a fixed
    ``num_ctx`` (see :func:`~novacode_cli.context._dynamic.get_ollama_num_ctx`),
    which is the real truncation limit. Reporting the raw architecture window
    (e.g. 262K from ``ollama show``) overstated capacity when ``num_ctx`` was
    smaller, and understated usage% — silently risking truncation. Conversely,
    when ``num_ctx`` exceeds the model's trained window, the trained window is
    the quality ceiling, so the smaller of the two is the honest number.

    Args:
        model_name: The name of the model (e.g., "gpt-4", "claude-3-opus", "glm-5:cloud").
        use_dyNovac: Whether to use dynamic detection from Ollama (default: True).

    Returns:
        The effective context window size in tokens (falls back to 128K default).
    """
    from novacode_cli.context._dynamic import is_ollama_cloud_model

    cloud_api_prefixes = ("claude-", "gpt-", "gemini-", "o1", "o3", "o4")
    is_cloud_api_model = any(
        model_name.lower().startswith(p) for p in cloud_api_prefixes
    )
    # Ollama cloud models (`:cloud`) run on Ollama's servers — not loaded into
    # local VRAM, so `ollama ps` won't list them and the local `num_ctx` cap
    # doesn't apply. Their window is the model maximum from `ollama show`.
    is_ollama_cloud = is_ollama_cloud_model(model_name)
    # "Local model" == a model whose context is allocated in *our* VRAM.
    is_local_ollama = not is_cloud_api_model and not is_ollama_cloud

    if use_dyNovac and is_local_ollama:
        # Best source for a local model: the context Ollama ACTUALLY allocated
        # for the loaded model (`ollama ps`). It may be clamped below the
        # requested num_ctx to fit VRAM, so it's authoritative when present.
        try:
            from novacode_cli.context._dynamic import get_ollama_running_context

            running = get_ollama_running_context(model_name)
            if running:
                logger.debug(
                    f"Allocated context for {model_name}: {running:,} (ollama ps)"
                )
                return running
        except Exception as e:  # noqa: BLE001
            logger.debug(f"ollama ps probe failed for {model_name}: {e}")

    # Architecture / max window: dynamic `ollama show` probe (works for both
    # local AND cloud Ollama models), else the static table.
    arch_window: int | None = None
    if use_dyNovac and not is_cloud_api_model:
        try:
            from novacode_cli.context._dynamic import get_ollama_context_length

            detected = get_ollama_context_length(model_name)
            if detected:
                arch_window = detected
                logger.debug(
                    f"Dynamic context for {model_name}: {detected:,} tokens (max)"
                )
        except Exception as e:  # noqa: BLE001
            logger.debug(
                f"Dynamic context detection failed for {model_name}: {e}, "
                f"falling back to hardcoded"
            )
    if arch_window is None:
        arch_window = _lookup_hardcoded_window(model_name)

    # Cloud (API or Ollama-cloud): the window is the model maximum, NOT capped
    # by the local num_ctx (no local VRAM allocation involved).
    if not is_local_ollama:
        return arch_window

    # Local Ollama model not currently loaded: predict the effective window as
    # min(architecture max, configured num_ctx) — the smaller is what truncates.
    from novacode_cli.context._dynamic import get_ollama_num_ctx

    effective = min(arch_window, get_ollama_num_ctx())
    if effective != arch_window:
        logger.debug(
            f"Capping {model_name} window {arch_window:,} → {effective:,} "
            f"(num_ctx)"
        )
    return effective


def format_token_count(tokens: int) -> str:
    """Format a token count for display with thousands separators."""
    return f"{tokens:,}"


def _estimate_tokens(text: str) -> int:
    """Estimate token count from text using a char/4 heuristic."""
    return len(text) // 4


def _message_text(msg: BaseMessage) -> str:
    """Extract text content from a message.

    Handles both plain-string content and the provider block formats:
    ``{"type": "text", "text": ...}`` plus tool-result blocks that carry their
    payload under ``content`` (Anthropic ``tool_result``) so large tool outputs
    aren't counted as zero.
    """
    content = msg.content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict):
                # Common: {"type": "text", "text": "..."}. Fall back to a
                # nested "content" payload (tool_result blocks) so the tokens
                # in tool output are not silently dropped.
                txt = block.get("text")
                if txt:
                    parts.append(str(txt))
                else:
                    inner = block.get("content")
                    if isinstance(inner, str):
                        parts.append(inner)
                    elif isinstance(inner, list):
                        for ib in inner:
                            if isinstance(ib, dict):
                                parts.append(str(ib.get("text", "")))
                            elif isinstance(ib, str):
                                parts.append(ib)
            elif isinstance(block, str):
                parts.append(block)
        return " ".join(parts)
    return str(content)


def _tool_call_text(msg: BaseMessage) -> str:
    """Serialize an AIMessage's tool calls (name + arguments) for token counting.

    Tool-call arguments (e.g. a ``write_file`` body or a large ``edit`` payload)
    re-enter the context on every subsequent turn but live in ``msg.tool_calls``,
    not in ``msg.content`` — so they must be counted explicitly or context usage
    is badly under-reported.
    """
    import json

    tool_calls = getattr(msg, "tool_calls", None) or []
    parts: list[str] = []
    for tc in tool_calls:
        if isinstance(tc, dict):
            name = tc.get("name", "")
            args = tc.get("args", "")
        else:
            name = getattr(tc, "name", "")
            args = getattr(tc, "args", "")
        if name:
            parts.append(str(name))
        if isinstance(args, (dict, list)):
            try:
                parts.append(json.dumps(args, ensure_ascii=False))
            except (TypeError, ValueError):
                parts.append(str(args))
        elif args:
            parts.append(str(args))
    return " ".join(parts)


def build_context_breakdown(
    messages: list[BaseMessage],
    model_name: str,
    use_dyNovac: bool = True,
) -> ContextBreakdown:
    """Build a ContextBreakdown from the current conversation state.

    Uses character-based token estimation (len // 4). This is approximate but
    sufficient for threshold-based warnings.

    Args:
        messages: Current conversation messages from agent state.
        model_name: Model name for looking up context window size.
        use_dyNovac: Whether to use dynamic detection from Ollama (default: True).

    Returns:
        Populated ContextBreakdown with usage stats.
    """
    from langchain_core.messages import (
        AIMessage,
        HumanMessage,
        SystemMessage,
        ToolMessage,
    )

    context_window = get_context_window_size(model_name, use_dyNovac=use_dyNovac)

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
            if getattr(msg, "tool_calls", None):
                tool_count += len(msg.tool_calls)
                # Tool-call arguments are part of the assistant turn and often
                # dominate context (file contents, diffs) — count them.
                assistant_tokens += _estimate_tokens(_tool_call_text(msg))
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


@dataclass
class CompactionRecommendation:
    """Recommendation for whether compaction should be performed.

    Attributes:
        should_compact: Whether compaction is recommended
        reason: Human-readable explanation for the recommendation
        usage_percentage: Current context usage percentage
        tokens_used: Total tokens currently used
        tokens_available: Tokens remaining before hitting limit
        messages_count: Number of messages in conversation
        estimated_tokens_saved: Estimated tokens that would be saved by compaction
    """

    should_compact: bool
    reason: str
    usage_percentage: float
    tokens_used: int
    tokens_available: int
    messages_count: int
    estimated_tokens_saved: int = 0


def get_compaction_recommendation(
    messages: list[BaseMessage],
    model_name: str,
    baseline_tokens: int = 0,
    use_dyNovac: bool = True,
) -> CompactionRecommendation:
    """Analyze a conversation and recommend whether compaction should run.

    Evaluates context-window usage percentage, message count, estimated token
    savings, and conversation-length heuristics.

    Args:
        messages: Current conversation messages from agent state.
        model_name: Model name for context window lookup.
        baseline_tokens: Baseline tokens (system prompt, tools, memory) already used.
        use_dyNovac: Whether to use dynamic detection from Ollama (default: True).

    Returns:
        CompactionRecommendation with analysis and recommendation.
    """
    breakdown = build_context_breakdown(messages, model_name, use_dyNovac=use_dyNovac)

    total_with_baseline = breakdown.total_tokens + baseline_tokens
    effective_usage_pct = (total_with_baseline / breakdown.context_window_size) * 100
    tokens_available = breakdown.context_window_size - total_with_baseline

    total_messages = len(messages)

    reasons = []

    # Critical threshold: >90% usage - always recommend
    if effective_usage_pct >= CONTEXT_CRITICAL_THRESHOLD * 100:
        reasons.append(f"Critical context usage ({effective_usage_pct:.1f}%)")
    # Warning threshold: >75% usage with significant message count
    elif effective_usage_pct >= CONTEXT_WARNING_THRESHOLD * 100:
        if total_messages >= 20:
            reasons.append(
                f"High context usage ({effective_usage_pct:.1f}%) "
                f"with {total_messages} messages"
            )
    # Moderate usage but lots of messages - recommend for efficiency
    elif effective_usage_pct >= 50 and total_messages >= 50:
        reasons.append(
            f"Many messages ({total_messages}) with moderate usage "
            f"({effective_usage_pct:.1f}%)"
        )
    # Long conversation without compaction - recommend for cleanliness
    elif total_messages >= 100:
        reasons.append(f"Very long conversation ({total_messages} messages)")

    # Estimate tokens that would be saved (keep last ~6 exchanges + a summary).
    if total_messages > 10:
        messages_to_summarize = max(0, total_messages - 12)
        avg_tokens_per_message = breakdown.conversation_tokens / max(1, total_messages)
        estimated_summary_tokens = 500
        estimated_tokens_saved = int(
            (messages_to_summarize * avg_tokens_per_message) - estimated_summary_tokens
        )
        estimated_tokens_saved = max(0, estimated_tokens_saved)
    else:
        estimated_tokens_saved = 0

    should_compact = len(reasons) > 0

    if not reasons:
        if effective_usage_pct < 25:
            reason = (
                f"Low context usage ({effective_usage_pct:.1f}%) - no compaction needed"
            )
        elif total_messages < 10:
            reason = (
                f"Short conversation ({total_messages} messages) - no compaction needed"
            )
        else:
            reason = (
                f"Context usage acceptable ({effective_usage_pct:.1f}%) - "
                f"compaction optional"
            )
    else:
        reason = "; ".join(reasons)

    return CompactionRecommendation(
        should_compact=should_compact,
        reason=reason,
        usage_percentage=effective_usage_pct,
        tokens_used=total_with_baseline,
        tokens_available=tokens_available,
        messages_count=total_messages,
        estimated_tokens_saved=estimated_tokens_saved,
    )

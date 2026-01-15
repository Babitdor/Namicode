"""Tests for context_manager module."""

import pytest

from namicode_cli.context.context_manager import (
    CONTEXT_CRITICAL_THRESHOLD,
    CONTEXT_WARNING_THRESHOLD,
    MODEL_CONTEXT_WINDOWS,
    CompactionResult,
    ContextBreakdown,
    get_context_window_size,
)


class TestModelContextWindows:
    """Test MODEL_CONTEXT_WINDOWS constant."""

    def test_contains_common_models(self) -> None:
        """Test that common models are included."""
        assert "gpt-4" in MODEL_CONTEXT_WINDOWS
        assert "gpt-4o" in MODEL_CONTEXT_WINDOWS
        assert "default" in MODEL_CONTEXT_WINDOWS

    def test_default_exists(self) -> None:
        """Test that default fallback exists."""
        assert "default" in MODEL_CONTEXT_WINDOWS
        assert MODEL_CONTEXT_WINDOWS["default"] == 128_000


class TestGetContextWindowSize:
    """Test get_context_window_size function."""

    def test_known_model(self) -> None:
        """Test getting context window for a known model."""
        result = get_context_window_size("gpt-4")
        assert result == MODEL_CONTEXT_WINDOWS["gpt-4"]

    def test_unknown_model_returns_default(self) -> None:
        """Test that unknown models return default size."""
        result = get_context_window_size("unknown-model-xyz")
        assert result == MODEL_CONTEXT_WINDOWS["default"]

    def test_partial_match_gpt4(self) -> None:
        """Test partial matching for gpt-4 variants."""
        result = get_context_window_size("gpt-4-turbo-preview")
        assert result == MODEL_CONTEXT_WINDOWS["gpt-4"]

    def test_partial_match_gpt4o(self) -> None:
        """Test partial matching for gpt-4o variants."""
        result = get_context_window_size("gpt-4o-mini")
        assert result == MODEL_CONTEXT_WINDOWS["gpt-4o"]

    def test_partial_match_claude(self) -> None:
        """Test partial matching for claude variants."""
        result = get_context_window_size("claude-3-opus-20240229")
        assert result == 200_000

    def test_partial_match_gemini(self) -> None:
        """Test partial matching for gemini variants."""
        # gemini-1.5-flash is in the dict directly with 1_000_000
        result = get_context_window_size("gemini-1.5-flash")
        assert result == MODEL_CONTEXT_WINDOWS["gemini-1.5-flash"]
        assert result == 1_000_000

    def test_case_insensitive(self) -> None:
        """Test that matching is case insensitive."""
        result = get_context_window_size("GPT-4")
        assert result == MODEL_CONTEXT_WINDOWS["gpt-4"]


class TestContextBreakdown:
    """Test ContextBreakdown dataclass."""

    def test_default_values(self) -> None:
        """Test default values are set correctly."""
        breakdown = ContextBreakdown()
        assert breakdown.system_prompt_tokens == 0
        assert breakdown.user_memory_tokens == 0
        assert breakdown.project_memory_tokens == 0
        assert breakdown.tool_definitions_tokens == 0
        assert breakdown.user_message_tokens == 0
        assert breakdown.assistant_message_tokens == 0
        assert breakdown.tool_result_tokens == 0
        assert breakdown.total_tokens == 0
        assert breakdown.context_window_size == 128_000
        assert breakdown.user_message_count == 0
        assert breakdown.assistant_message_count == 0
        assert breakdown.tool_call_count == 0

    def test_baseline_tokens(self) -> None:
        """Test baseline_tokens property."""
        breakdown = ContextBreakdown(
            system_prompt_tokens=1000,
            user_memory_tokens=300,
            project_memory_tokens=200,
            tool_definitions_tokens=500,
        )
        # baseline = system + user_memory + project_memory + tool_definitions
        assert breakdown.baseline_tokens == 2000

    def test_conversation_tokens(self) -> None:
        """Test conversation_tokens property."""
        breakdown = ContextBreakdown(
            user_message_tokens=1000,
            assistant_message_tokens=2000,
            tool_result_tokens=500,
        )
        assert breakdown.conversation_tokens == 3500

    def test_remaining_tokens(self) -> None:
        """Test remaining_tokens property."""
        breakdown = ContextBreakdown(
            total_tokens=50_000,
            context_window_size=128_000,
        )
        assert breakdown.remaining_tokens == 78_000

    def test_remaining_tokens_never_negative(self) -> None:
        """Test remaining_tokens doesn't go negative."""
        breakdown = ContextBreakdown(
            total_tokens=150_000,
            context_window_size=128_000,
        )
        assert breakdown.remaining_tokens == 0

    def test_usage_percentage(self) -> None:
        """Test usage_percentage property."""
        breakdown = ContextBreakdown(
            total_tokens=64_000,
            context_window_size=128_000,
        )
        assert breakdown.usage_percentage == 50.0

    def test_usage_percentage_zero_context(self) -> None:
        """Test usage_percentage with zero context window."""
        breakdown = ContextBreakdown(
            total_tokens=1000,
            context_window_size=0,
        )
        assert breakdown.usage_percentage == 0.0

    def test_is_warning_below_threshold(self) -> None:
        """Test is_warning when below threshold."""
        # 74% usage - below 75% threshold
        breakdown = ContextBreakdown(
            total_tokens=74_000,
            context_window_size=100_000,
        )
        assert not breakdown.is_warning

    def test_is_warning_at_threshold(self) -> None:
        """Test is_warning at threshold."""
        # 75% usage - at threshold
        breakdown = ContextBreakdown(
            total_tokens=75_000,
            context_window_size=100_000,
        )
        assert breakdown.is_warning

    def test_is_warning_above_threshold(self) -> None:
        """Test is_warning above threshold but below critical."""
        # 80% usage - above warning but below critical
        breakdown = ContextBreakdown(
            total_tokens=80_000,
            context_window_size=100_000,
        )
        assert breakdown.is_warning

    def test_is_critical_below_threshold(self) -> None:
        """Test is_critical below threshold."""
        # 89% usage - below 90% threshold
        breakdown = ContextBreakdown(
            total_tokens=89_000,
            context_window_size=100_000,
        )
        assert not breakdown.is_critical

    def test_is_critical_at_threshold(self) -> None:
        """Test is_critical at threshold."""
        # 90% usage - at threshold
        breakdown = ContextBreakdown(
            total_tokens=90_000,
            context_window_size=100_000,
        )
        assert breakdown.is_critical

    def test_is_critical_above_threshold(self) -> None:
        """Test is_critical above threshold."""
        # 95% usage
        breakdown = ContextBreakdown(
            total_tokens=95_000,
            context_window_size=100_000,
        )
        assert breakdown.is_critical


class TestCompactionResult:
    """Test CompactionResult dataclass."""

    def test_default_values(self) -> None:
        """Test required fields are set correctly."""
        result = CompactionResult(
            success=True,
            original_tokens=10000,
            new_tokens=1000,
            tokens_saved=9000,
            messages_before=20,
            messages_after=1,
            summary="Test summary",
        )
        assert result.success is True
        assert result.original_tokens == 10000
        assert result.new_tokens == 1000
        assert result.tokens_saved == 9000
        assert result.messages_before == 20
        assert result.messages_after == 1
        assert result.summary == "Test summary"
        assert result.error is None

    def test_error_field(self) -> None:
        """Test error field."""
        result = CompactionResult(
            success=False,
            original_tokens=0,
            new_tokens=0,
            tokens_saved=0,
            messages_before=0,
            messages_after=0,
            summary="",
            error="Something went wrong",
        )
        assert result.success is False
        assert result.error == "Something went wrong"


class TestThresholds:
    """Test threshold constants."""

    def test_warning_threshold_value(self) -> None:
        """Test warning threshold is 75%."""
        assert CONTEXT_WARNING_THRESHOLD == 0.75

    def test_critical_threshold_value(self) -> None:
        """Test critical threshold is 90%."""
        assert CONTEXT_CRITICAL_THRESHOLD == 0.90

    def test_warning_less_than_critical(self) -> None:
        """Test warning threshold is less than critical."""
        assert CONTEXT_WARNING_THRESHOLD < CONTEXT_CRITICAL_THRESHOLD

"""Tests for tool limits and circuit breaker functionality."""

import pytest
from novacode_cli.utils.tool_limits import (
    ToolCallLimit,
    ToolCallTracker,
    ToolCallCircuitBreaker,
    get_circuit_breaker,
    reset_circuit_breaker,
)


def test_tool_call_limit_defaults():
    """Test default configuration values."""
    config = ToolCallLimit()
    
    assert config.max_calls_per_turn == 50
    assert config.max_repeated_calls == 3
    assert config.max_context_tokens == 100000
    assert config.warning_threshold == 20
    assert config.reset_after_seconds == 60


def test_tool_call_limit_custom():
    """Test custom configuration values."""
    config = ToolCallLimit(
        max_calls_per_turn=100,
        max_repeated_calls=5,
        max_context_tokens=200000,
    )
    
    assert config.max_calls_per_turn == 100
    assert config.max_repeated_calls == 5
    assert config.max_context_tokens == 200000


def test_tool_call_tracker_basic():
    """Test basic tool call tracking."""
    tracker = ToolCallTracker()
    
    # Add some calls
    tracker.add_call("read_file", {"path": "test.py"})
    tracker.add_call("write_file", {"path": "test.py", "content": "hello"})
    tracker.add_call("read_file", {"path": "test.py"})
    
    assert len(tracker.calls) == 3
    assert tracker.total_tokens == 0
    assert "read_file" in tracker.call_counts
    assert "write_file" in tracker.call_counts
    assert tracker.call_counts["read_file"] == 2
    assert tracker.call_counts["write_file"] == 1


def test_tool_call_tracker_identical_calls():
    """Test detection of identical calls."""
    tracker = ToolCallTracker()
    
    # Add identical calls
    for i in range(4):
        tracker.add_call("read_file", {"path": "same.py"})
    
    # Check for identical calls
    identical = tracker.get_identical_call_counts()
    assert "read_file" in identical
    # The signature should be the same for all 4 calls
    assert len(identical["read_file"]) == 1
    # Get the count for the signature
    for signature, count in identical["read_file"].items():
        assert count == 4


def test_tool_call_tracker_different_args():
    """Test that different args create different signatures."""
    tracker = ToolCallTracker()
    
    # Add calls with different args
    tracker.add_call("read_file", {"path": "test1.py"})
    tracker.add_call("read_file", {"path": "test2.py"})
    tracker.add_call("read_file", {"path": "test1.py"})  # Same as first
    
    identical = tracker.get_identical_call_counts()
    
    # Should have 2 different signatures
    assert len(identical["read_file"]) == 2
    
    # Find the count for test1.py (appears twice)
    found_test1 = False
    for signature, count in identical["read_file"].items():
        if "test1.py" in signature:
            assert count == 2
            found_test1 = True
    
    assert found_test1


def test_tool_call_tracker_token_tracking():
    """Test token consumption tracking."""
    tracker = ToolCallTracker()
    
    tracker.add_call("read_file", {"path": "test.py"}, tokens_used=100)
    tracker.add_call("write_file", {"path": "test.py"}, tokens_used=200)
    
    assert tracker.total_tokens == 300


def test_loop_detection_max_calls():
    """Test detection of exceeding max calls."""
    tracker = ToolCallTracker()
    config = ToolCallLimit(max_calls_per_turn=5)
    
    # Add 5 calls
    for i in range(5):
        tracker.add_call("test_tool", {"arg": i})
    
    # Should not detect loop yet
    is_loop, reason = tracker.is_loop_detected(config)
    assert not is_loop
    
    # Add one more call
    tracker.add_call("test_tool", {"arg": 100})
    
    # Should detect loop now
    is_loop, reason = tracker.is_loop_detected(config)
    assert is_loop
    assert "Exceeded maximum" in reason
    assert "6" in reason
    assert "5" in reason


def test_loop_detection_identical_calls():
    """Test detection of identical calls."""
    tracker = ToolCallTracker()
    config = ToolCallLimit(max_repeated_calls=3)
    
    # Add 3 identical calls (should be allowed)
    for i in range(3):
        tracker.add_call("test_tool", {"arg": "same"})
    
    is_loop, reason = tracker.is_loop_detected(config)
    assert not is_loop
    
    # Add 4th identical call
    tracker.add_call("test_tool", {"arg": "same"})
    
    # Should detect loop
    is_loop, reason = tracker.is_loop_detected(config)
    assert is_loop
    assert "identical arguments" in reason
    assert "4 times" in reason


def test_loop_detection_token_limit():
    """Test detection of token limit exceeded."""
    tracker = ToolCallTracker()
    config = ToolCallLimit(max_context_tokens=1000)
    
    # Add calls with token consumption
    tracker.add_call("test_tool", {"arg": 1}, tokens_used=600)
    tracker.add_call("test_tool", {"arg": 2}, tokens_used=500)
    
    # Should detect token limit exceeded
    is_loop, reason = tracker.is_loop_detected(config)
    assert is_loop
    assert "exceed limit" in reason
    assert "1100" in reason
    assert "1000" in reason


def test_warning_threshold():
    """Test warning threshold detection."""
    tracker = ToolCallTracker()
    config = ToolCallLimit(warning_threshold=5)
    
    # Add 4 calls (below threshold)
    for i in range(4):
        tracker.add_call("test_tool", {"arg": i})
    
    should_warn, reason = tracker.should_warn(config)
    assert not should_warn
    
    # Add 5th call (at threshold)
    tracker.add_call("test_tool", {"arg": 5})
    
    should_warn, reason = tracker.should_warn(config)
    assert should_warn
    assert "5 calls" in reason


def test_circuit_breaker_basic():
    """Test basic circuit breaker functionality."""
    config = ToolCallLimit(max_calls_per_turn=3)
    cb = ToolCallCircuitBreaker(config)
    
    # First 3 calls should be allowed
    for i in range(3):
        should_allow, reason = cb.should_allow_call("test_tool", {"arg": i})
        assert should_allow
        assert reason == ""
    
    # 4th call should be blocked
    should_allow, reason = cb.should_allow_call("test_tool", {"arg": 100})
    assert not should_allow
    assert "Exceeded maximum" in reason
    
    # Circuit should be open now
    assert cb._is_open


def test_circuit_breaker_reset():
    """Test circuit breaker reset."""
    config = ToolCallLimit(max_calls_per_turn=2)
    cb = ToolCallCircuitBreaker(config)
    
    # Make calls to open circuit
    cb.should_allow_call("test", {})
    cb.should_allow_call("test", {})
    cb.should_allow_call("test", {})  # This opens circuit
    
    assert cb._is_open
    
    # Reset
    cb.reset()
    
    assert not cb._is_open
    assert len(cb.tracker.calls) == 0


def test_circuit_breaker_cooldown():
    """Test circuit breaker auto-reset after cooldown."""
    import time
    
    config = ToolCallLimit(max_calls_per_turn=2, reset_after_seconds=1)
    cb = ToolCallCircuitBreaker(config)
    
    # Open circuit
    cb.should_allow_call("test", {})
    cb.should_allow_call("test", {})
    cb.should_allow_call("test", {})  # Opens circuit
    
    assert cb._is_open
    
    # Wait for cooldown
    time.sleep(1.5)
    
    # Should auto-reset
    should_allow, reason = cb.should_allow_call("test", {})
    assert should_allow  # Circuit should be closed after cooldown


def test_circuit_breaker_identical_calls():
    """Test circuit breaker blocks identical calls."""
    config = ToolCallLimit(max_repeated_calls=2)
    cb = ToolCallCircuitBreaker(config)
    
    # Make 2 identical calls (allowed)
    cb.should_allow_call("test", {"arg": "same"})
    cb.should_allow_call("test", {"arg": "same"})
    
    # 3rd identical call should be blocked
    should_allow, reason = cb.should_allow_call("test", {"arg": "same"})
    assert not should_allow
    assert "identical arguments" in reason


def test_global_circuit_breaker():
    """Test global circuit breaker singleton."""
    # Reset to start fresh
    reset_circuit_breaker()
    
    # Get global instance
    cb1 = get_circuit_breaker()
    cb2 = get_circuit_breaker()
    
    # Should be same instance
    assert cb1 is cb2
    
    # Make a call
    cb1.should_allow_call("test", {})
    
    # Should be tracked in both
    assert len(cb2.tracker.calls) == 1
    
    # Reset
    reset_circuit_breaker()
    
    # Get new instance
    cb3 = get_circuit_breaker()
    
    # Should be different instance
    assert cb3 is not cb1
    assert len(cb3.tracker.calls) == 0


def test_circuit_breaker_token_tracking():
    """Test circuit breaker tracks token consumption."""
    config = ToolCallLimit(max_context_tokens=1000)
    cb = ToolCallCircuitBreaker(config)
    
    # Add calls with tokens
    cb.should_allow_call("test", {})
    cb.tracker.total_tokens = 600
    
    cb.should_allow_call("test", {})
    cb.tracker.total_tokens = 1100  # Exceeds limit
    
    # Next call should be blocked
    should_allow, reason = cb.should_allow_call("test", {})
    assert not should_allow
    assert "exceed limit" in reason


def test_circuit_breaker_different_tools():
    """Test circuit breaker tracks different tools separately."""
    config = ToolCallLimit(max_calls_per_turn=5)
    cb = ToolCallCircuitBreaker(config)
    
    # Make calls to different tools
    for i in range(3):
        cb.should_allow_call("tool_a", {"arg": i})
    
    for i in range(3):
        cb.should_allow_call("tool_b", {"arg": i})
    
    # Total is 6 calls, should be blocked
    should_allow, reason = cb.should_allow_call("tool_c", {})
    assert not should_allow
    assert "Exceeded maximum" in reason


def test_circuit_breaker_warning():
    """Test circuit breaker warning threshold."""
    config = ToolCallLimit(warning_threshold=3)
    cb = ToolCallCircuitBreaker(config)
    
    # Make calls below threshold
    cb.should_allow_call("test", {})
    cb.should_allow_call("test", {})
    
    should_warn, reason = cb.tracker.should_warn(config)
    assert not should_warn
    
    # Make call at threshold
    cb.should_allow_call("test", {})
    
    should_warn, reason = cb.tracker.should_warn(config)
    assert should_warn
    assert "3 calls" in reason


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
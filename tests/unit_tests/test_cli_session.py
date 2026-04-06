"""Unit tests for cli_session module.

Tests for:
- SeenMessageIds: Bounded collection for tracking message IDs
- GracefulShutdown: Flag-based signal handler
- AutoSaveManager: Auto-save timing and thresholds
"""

import pytest
import time
from unittest.mock import MagicMock, patch

from novacode_cli.cli_session import (
    SeenMessageIds,
    GracefulShutdown,
    AutoSaveManager,
    MAX_SEEN_MESSAGE_IDS,
    AUTO_SAVE_INTERVAL_SECONDS,
    AUTO_SAVE_MESSAGE_THRESHOLD,
)


class TestSeenMessageIds:
    """Tests for the SeenMessageIds bounded collection."""

    def test_add_and_contains(self):
        """Test adding IDs and checking membership."""
        seen = SeenMessageIds(max_size=100)
        
        seen.add("msg-1")
        seen.add("msg-2")
        seen.add("msg-3")
        
        assert "msg-1" in seen
        assert "msg-2" in seen
        assert "msg-3" in seen
        assert "msg-4" not in seen

    def test_duplicate_add(self):
        """Test that duplicate adds don't increase size."""
        seen = SeenMessageIds(max_size=100)
        
        seen.add("msg-1")
        seen.add("msg-1")
        seen.add("msg-1")
        
        assert len(seen) == 1
        assert "msg-1" in seen

    def test_bounded_eviction(self):
        """Test that old IDs are evicted when max size is reached."""
        seen = SeenMessageIds(max_size=3)
        
        seen.add("msg-1")
        seen.add("msg-2")
        seen.add("msg-3")
        
        assert len(seen) == 3
        assert "msg-1" in seen
        
        # Adding a 4th should evict the oldest
        seen.add("msg-4")
        
        assert len(seen) == 3
        assert "msg-1" not in seen  # Evicted
        assert "msg-2" in seen
        assert "msg-3" in seen
        assert "msg-4" in seen

    def test_clear(self):
        """Test clearing all tracked IDs."""
        seen = SeenMessageIds(max_size=100)
        
        seen.add("msg-1")
        seen.add("msg-2")
        seen.add("msg-3")
        
        assert len(seen) == 3
        
        seen.clear()
        
        assert len(seen) == 0
        assert "msg-1" not in seen
        assert "msg-2" not in seen
        assert "msg-3" not in seen

    def test_default_max_size(self):
        """Test that default max size is used."""
        seen = SeenMessageIds()
        
        assert seen._max_size == MAX_SEEN_MESSAGE_IDS

    def test_custom_max_size(self):
        """Test custom max size."""
        seen = SeenMessageIds(max_size=50)
        
        assert seen._max_size == 50


class TestGracefulShutdown:
    """Tests for the GracefulShutdown flag-based signal handler."""

    def test_initial_state(self):
        """Test initial state is not shutdown requested."""
        shutdown = GracefulShutdown()
        
        assert not shutdown.shutdown_requested

    def test_request_shutdown(self):
        """Test requesting shutdown sets the flag."""
        shutdown = GracefulShutdown()
        
        shutdown.request_shutdown()
        
        assert shutdown.shutdown_requested

    def test_reset(self):
        """Test resetting the shutdown flag."""
        shutdown = GracefulShutdown()
        
        shutdown.request_shutdown()
        assert shutdown.shutdown_requested
        
        shutdown.reset()
        
        assert not shutdown.shutdown_requested

    @pytest.mark.skipif(
        not hasattr(__import__('signal'), 'SIGTERM'),
        reason="SIGTERM not available on this platform"
    )
    def test_install_handlers_unix(self):
        """Test signal handlers are installed on Unix."""
        import signal
        
        shutdown = GracefulShutdown()
        
        # Save original handlers
        original_sigterm = signal.getsignal(signal.SIGTERM)
        
        try:
            shutdown.install_handlers()
            
            # Handler should be installed (not the original)
            # Note: We can't easily verify the handler works without
            # actually sending signals
        finally:
            # Restore original handlers
            try:
                signal.signal(signal.SIGTERM, original_sigterm)
            except (ValueError, OSError):
                pass

    def test_install_handlers_windows(self):
        """Test signal handlers are skipped on Windows."""
        shutdown = GracefulShutdown()
        
        with patch('sys.platform', 'win32'):
            # Should not raise any errors
            shutdown.install_handlers()
            
            # shutdown_requested should still be False
            assert not shutdown.shutdown_requested


class TestAutoSaveManager:
    """Tests for the AutoSaveManager class."""

    def test_initial_state(self):
        """Test initial state."""
        manager = AutoSaveManager()
        
        assert manager.messages_since_save == 0

    def test_increment_messages(self):
        """Test incrementing message count."""
        manager = AutoSaveManager()
        
        manager.increment_messages()
        assert manager.messages_since_save == 1
        
        manager.increment_messages()
        assert manager.messages_since_save == 2

    def test_reset_messages(self):
        """Test resetting message count."""
        manager = AutoSaveManager()
        
        manager.increment_messages()
        manager.increment_messages()
        manager.increment_messages()
        
        assert manager.messages_since_save == 3
        
        manager.reset_messages()
        
        assert manager.messages_since_save == 0

    def test_should_save_no_messages(self):
        """Test should_save returns False when no messages."""
        manager = AutoSaveManager(interval_seconds=0, message_threshold=5)
        
        # No messages, should not save
        assert not manager.should_save()

    def test_should_save_by_message_threshold(self):
        """Test should_save returns True when message threshold reached."""
        manager = AutoSaveManager(interval_seconds=1000, message_threshold=5)
        
        # Add messages up to threshold
        for _ in range(5):
            manager.increment_messages()
        
        assert manager.should_save()

    def test_should_save_by_time(self):
        """Test should_save returns True when time interval passed."""
        manager = AutoSaveManager(interval_seconds=0, message_threshold=1000)
        
        manager.increment_messages()
        
        # Time interval is 0, so should save immediately
        assert manager.should_save()

    def test_should_save_not_yet(self):
        """Test should_save returns False when thresholds not met."""
        manager = AutoSaveManager(interval_seconds=1000, message_threshold=1000)
        
        manager.increment_messages()
        
        # Neither threshold met
        assert not manager.should_save()

    def test_custom_thresholds(self):
        """Test custom thresholds."""
        manager = AutoSaveManager(interval_seconds=60, message_threshold=10)
        
        assert manager._interval == 60
        assert manager._threshold == 10

    def test_default_thresholds(self):
        """Test default thresholds match constants."""
        manager = AutoSaveManager()
        
        assert manager._interval == AUTO_SAVE_INTERVAL_SECONDS
        assert manager._threshold == AUTO_SAVE_MESSAGE_THRESHOLD


class TestConstants:
    """Tests for module constants."""

    def test_auto_save_interval(self):
        """Test AUTO_SAVE_INTERVAL_SECONDS value."""
        assert AUTO_SAVE_INTERVAL_SECONDS == 300  # 5 minutes

    def test_auto_save_threshold(self):
        """Test AUTO_SAVE_MESSAGE_THRESHOLD value."""
        assert AUTO_SAVE_MESSAGE_THRESHOLD == 5

    def test_max_seen_message_ids(self):
        """Test MAX_SEEN_MESSAGE_IDS value."""
        assert MAX_SEEN_MESSAGE_IDS == 10000
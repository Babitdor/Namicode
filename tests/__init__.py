"""Tests for Nova Code CLI."""
import sys
from unittest.mock import MagicMock

# Mock keyring to prevent tests from blocking/timing out on Windows keyring backend scans
mock_keyring = MagicMock()
mock_keyring.get_keyring.return_value = MagicMock()
mock_errors = MagicMock()
mock_errors.PasswordDeleteError = Exception
mock_keyring.errors = mock_errors

sys.modules['keyring'] = mock_keyring
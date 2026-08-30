"""Tests for Nova Code CLI."""
import sys
from unittest.mock import MagicMock

# Mock keyring to prevent tests from blocking/timing out on Windows keyring backend scans
mock_keyring = MagicMock()
mock_keyring.get_keyring.return_value = MagicMock()
# An empty keychain returns None. Without this the stub hands back a truthy
# MagicMock for EVERY secret, so any test building Settings believes all
# providers are configured and the env-var fallback is never exercised.
mock_keyring.get_password.return_value = None
mock_errors = MagicMock()
mock_errors.PasswordDeleteError = Exception
mock_keyring.errors = mock_errors

sys.modules['keyring'] = mock_keyring
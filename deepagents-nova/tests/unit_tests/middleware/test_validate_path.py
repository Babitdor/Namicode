"""Unit tests for _validate_path() function."""

import pytest

from nova_deepagents.middleware.filesystem import _validate_path


class TestValidatePath:
    """Test cases for path validation and normalization."""

    def test_relative_path_normalization(self):
        """Test that relative paths get normalized with leading slash."""
        assert _validate_path("foo/bar") == "/foo/bar"
        assert _validate_path("relative/path.txt") == "/relative/path.txt"

    def test_absolute_path_normalization(self):
        """Test that absolute virtual paths are preserved."""
        assert _validate_path("/workspace/file.txt") == "/workspace/file.txt"
        assert _validate_path("/output/report.csv") == "/output/report.csv"

    def test_path_normalization_removes_redundant_separators(self):
        """Test that redundant path separators are normalized."""
        assert _validate_path("/./foo//bar") == "/foo/bar"
        assert _validate_path("foo/./bar") == "/foo/bar"

    def test_path_traversal_rejected_virtual_mode(self):
        """Test that path traversal attempts are rejected in virtual mode."""
        with pytest.raises(ValueError, match="Path traversal not allowed"):
            _validate_path("../etc/passwd", virtual_mode=True)

        with pytest.raises(ValueError, match="Path traversal not allowed"):
            _validate_path("foo/../../etc/passwd", virtual_mode=True)

    def test_path_traversal_allowed_nonvirtual_mode(self):
        """Test that path traversal is allowed in non-virtual mode (for backwards compat)."""
        # In non-virtual mode, we don't validate path traversal
        # This allows the backend to handle it
        result = _validate_path("../etc/passwd", virtual_mode=False)
        assert result is not None  # Should not raise

    def test_home_directory_expansion_rejected_virtual_mode(self):
        """Test that home directory expansion is rejected in virtual mode."""
        with pytest.raises(ValueError, match="Path traversal not allowed"):
            _validate_path("~/secret.txt", virtual_mode=True)

    def test_home_directory_expansion_allowed_nonvirtual_mode(self):
        """Test that home directory expansion is allowed in non-virtual mode."""
        result = _validate_path("~/secret.txt", virtual_mode=False)
        assert result is not None  # Should not raise

    def test_windows_absolute_path_rejected_in_virtual_mode(self):
        """Test that Windows absolute paths are rejected in virtual mode."""
        with pytest.raises(ValueError, match="Windows absolute paths are not supported"):
            _validate_path("C:\\Users\\Documents\\file.txt", virtual_mode=True)

        with pytest.raises(ValueError, match="Windows absolute paths are not supported"):
            _validate_path("F:\\git\\project\\file.txt", virtual_mode=True)

        with pytest.raises(ValueError, match="Windows absolute paths are not supported"):
            _validate_path("C:/Users/Documents/file.txt", virtual_mode=True)

        with pytest.raises(ValueError, match="Windows absolute paths are not supported"):
            _validate_path("D:/data/output.csv", virtual_mode=True)

    def test_windows_absolute_path_accepted_in_nonvirtual_mode(self):
        """Test that Windows absolute paths are accepted in non-virtual mode."""
        # With backslashes
        result = _validate_path("C:\\Users\\Documents\\file.txt", virtual_mode=False)
        assert result == "C:/Users/Documents/file.txt"

        result = _validate_path("F:\\git\\project\\file.txt", virtual_mode=False)
        assert result == "F:/git/project/file.txt"

        # With forward slashes
        result = _validate_path("C:/Users/Documents/file.txt", virtual_mode=False)
        assert result == "C:/Users/Documents/file.txt"

        result = _validate_path("D:/data/output.csv", virtual_mode=False)
        assert result == "D:/data/output.csv"

    def test_allowed_prefixes_enforcement(self):
        """Test that allowed_prefixes parameter is enforced."""
        # Should pass when prefix matches
        result = _validate_path("/workspace/file.txt", allowed_prefixes=["/workspace/"])
        assert result == "/workspace/file.txt"

        # Should fail when prefix doesn't match
        with pytest.raises(ValueError, match="Path must start with one of"):
            _validate_path("/etc/file.txt", allowed_prefixes=["/workspace/"])

    def test_backslash_normalization(self):
        """Test that backslashes in relative paths are normalized to forward slashes."""
        # Relative paths with backslashes should be normalized
        assert _validate_path("foo\\bar\\baz") == "/foo/bar/baz"

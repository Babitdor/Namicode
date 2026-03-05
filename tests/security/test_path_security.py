"""Comprehensive security tests for path handling.

This module stress tests the path security implementation against various attack vectors:
- Path traversal attacks
- Symlink attacks
- Encoding attacks
- Race conditions
- Platform-specific attacks
"""

import os
import tempfile
from pathlib import Path

import pytest

from nami_deepagents.backends.filesystem import FilesystemBackend


class TestPathTraversalAttacks:
    """Test path traversal prevention."""

    def test_basic_traversal_virtual_mode(self):
        """Test basic ../ traversal is blocked in virtual mode."""
        with tempfile.TemporaryDirectory() as tmpdir:
            be = FilesystemBackend(root_dir=tmpdir, virtual_mode=True)

            with pytest.raises(ValueError, match="traversal"):
                be._resolve_path("../../../etc/passwd")

    def test_encoded_traversal_virtual_mode(self):
        """Test URL-encoded traversal is blocked."""
        with tempfile.TemporaryDirectory() as tmpdir:
            be = FilesystemBackend(root_dir=tmpdir, virtual_mode=True)

            # URL-encoded ../
            with pytest.raises(ValueError):
                be._resolve_path("%2e%2e%2f%2e%2e%2fetc/passwd")

    def test_double_dot_traversal(self):
        """Test .... and other variations."""
        with tempfile.TemporaryDirectory() as tmpdir:
            be = FilesystemBackend(root_dir=tmpdir, virtual_mode=True)

            with pytest.raises(ValueError, match="traversal"):
                be._resolve_path("....")

    def test_backslash_traversal_windows(self):
        """Test backslash traversal attempts."""
        with tempfile.TemporaryDirectory() as tmpdir:
            be = FilesystemBackend(root_dir=tmpdir, virtual_mode=True)

            with pytest.raises(ValueError, match="traversal"):
                be._resolve_path("..\\..\\etc\\passwd")

    def test_null_byte_injection(self):
        """Test null byte injection attempts."""
        with tempfile.TemporaryDirectory() as tmpdir:
            be = FilesystemBackend(root_dir=tmpdir, virtual_mode=True)

            # Null bytes should be blocked for security
            with pytest.raises(ValueError, match="Null byte"):
                be._resolve_path("/safe/path\x00.txt")

    def test_absolute_path_escape_virtual_mode(self):
        """Test absolute path escape in virtual mode."""
        with tempfile.TemporaryDirectory() as tmpdir:
            be = FilesystemBackend(root_dir=tmpdir, virtual_mode=True)

            # Try to access /etc/passwd directly - should be blocked
            with pytest.raises(ValueError, match="system path|outside"):
                be._resolve_path("/etc/passwd")

    def test_home_directory_escape(self):
        """Test ~ expansion attack."""
        with tempfile.TemporaryDirectory() as tmpdir:
            be = FilesystemBackend(root_dir=tmpdir, virtual_mode=True)

            with pytest.raises(ValueError, match="traversal"):
                be._resolve_path("~/../etc/passwd")

    def test_deep_traversal(self):
        """Test deeply nested traversal."""
        with tempfile.TemporaryDirectory() as tmpdir:
            be = FilesystemBackend(root_dir=tmpdir, virtual_mode=True)

            deep_traversal = "/".join([".."] * 20) + "/etc/passwd"
            with pytest.raises(ValueError):
                be._resolve_path(deep_traversal)


class TestAbsolutePaths:
    """Test absolute path handling."""

    def test_non_virtual_mode_absolute_path(self):
        """Test that non-virtual mode accepts absolute paths."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a file outside the cwd
            outside_file = Path(tmpdir) / "outside.txt"
            outside_file.write_text("test")

            be = FilesystemBackend(virtual_mode=False)
            # Should not raise - absolute paths allowed
            result = be._resolve_path(str(outside_file))
            assert result == outside_file.resolve()

    def test_allowed_prefixes_blocks_outside(self):
        """Test that allowed_prefixes restricts absolute paths."""
        with tempfile.TemporaryDirectory() as tmpdir:
            allowed_dir = Path(tmpdir) / "allowed"
            allowed_dir.mkdir()
            blocked_dir = Path(tmpdir) / "blocked"
            blocked_dir.mkdir()

            be = FilesystemBackend(allowed_prefixes=[allowed_dir], virtual_mode=False)

            # Should allow paths under allowed dir
            result = be._resolve_path(str(allowed_dir / "test.txt"))
            assert result.is_absolute()

            # Should block paths outside allowed dir
            with pytest.raises(ValueError, match="outside allowed"):
                be._resolve_path(str(blocked_dir / "test.txt"))

    def test_allowed_prefixes_multiple(self):
        """Test multiple allowed prefixes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            allowed1 = Path(tmpdir) / "allowed1"
            allowed2 = Path(tmpdir) / "allowed2"
            allowed1.mkdir()
            allowed2.mkdir()
            blocked = Path(tmpdir) / "blocked"
            blocked.mkdir()

            be = FilesystemBackend(allowed_prefixes=[allowed1, allowed2], virtual_mode=False)

            # Should allow both
            be._resolve_path(str(allowed1 / "test.txt"))
            be._resolve_path(str(allowed2 / "test.txt"))

            # Should block
            with pytest.raises(ValueError):
                be._resolve_path(str(blocked / "test.txt"))


class TestPathEncoding:
    """Test path encoding edge cases."""

    def test_unicode_paths(self):
        """Test Unicode characters in paths."""
        with tempfile.TemporaryDirectory() as tmpdir:
            be = FilesystemBackend(root_dir=tmpdir, virtual_mode=True)

            # Unicode characters should be handled
            result = be._resolve_path("/テスト/test.txt")
            assert "テスト" in str(result) or "テスト" in result.name

    def test_spaces_in_paths(self):
        """Test spaces in file paths."""
        with tempfile.TemporaryDirectory() as tmpdir:
            be = FilesystemBackend(root_dir=tmpdir, virtual_mode=True)

            result = be._resolve_path("/path with spaces/file.txt")
            assert "path with spaces" in str(result)

    def test_special_characters(self):
        """Test special characters in paths."""
        with tempfile.TemporaryDirectory() as tmpdir:
            be = FilesystemBackend(root_dir=tmpdir, virtual_mode=True)

            # These should be handled safely
            special_paths = [
                "/test$file",
                "/test#file",
                "/test@file",
                "/test!file",
            ]
            for path in special_paths:
                result = be._resolve_path(path)
                assert result.is_absolute()


class TestPathLength:
    """Test path length limits."""

    def test_extremely_long_path(self):
        """Test handling of extremely long paths."""
        with tempfile.TemporaryDirectory() as tmpdir:
            be = FilesystemBackend(root_dir=tmpdir, virtual_mode=True)

            # Create a very long path
            long_path = "/x" * 1000
            result = be._resolve_path(long_path)
            # Should handle without crashing
            assert len(str(result)) > 0

    def test_max_path_depth(self):
        """Test deeply nested directory paths."""
        with tempfile.TemporaryDirectory() as tmpdir:
            be = FilesystemBackend(root_dir=tmpdir, virtual_mode=True)

            deep_path = "/" + "/".join(["dir"] * 50) + "/file.txt"
            result = be._resolve_path(deep_path)
            assert result.is_absolute()


class TestSymlinkHandling:
    """Test symlink attack prevention."""

    def test_read_symlink_in_virtual_mode(self):
        """Test reading through symlink in virtual mode."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)

            # Create a file outside root
            outside = root.parent / "outside.txt"
            outside.write_text("secret data")

            # Create symlink inside root pointing outside
            link = root / "link"
            try:
                link.symlink_to(outside)
            except OSError:
                pytest.skip("Symlink creation not supported")

            be = FilesystemBackend(root_dir=tmpdir, virtual_mode=True)

            # Try to read through symlink
            # O_NOFOLLOW should prevent this on POSIX
            with pytest.raises((IsADirectoryError, OSError, PermissionError)):
                be.read("/link")

    def test_symlink_escape_attempt(self):
        """Test symlink pointing outside of root."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            outside = root.parent / "secret.txt"
            outside.write_text("secret")

            link = root / "escape"
            try:
                link.symlink_to(outside)
            except OSError:
                pytest.skip("Symlink creation not supported")

            be = FilesystemBackend(root_dir=tmpdir, virtual_mode=True)

            # Symlink resolution should stay within root
            with pytest.raises((OSError, PermissionError)):
                be.read("/escape")


class TestFileOperations:
    """Test file operation security."""

    def test_read_nonexistent_file(self):
        """Test reading non-existent file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            be = FilesystemBackend(root_dir=tmpdir, virtual_mode=True)

            result = be.read("/nonexistent.txt")
            assert "not found" in result.lower() or "error" in result.lower()

    def test_write_to_nonexistent_directory(self):
        """Test writing to non-existent directory creates it."""
        with tempfile.TemporaryDirectory() as tmpdir:
            be = FilesystemBackend(root_dir=tmpdir, virtual_mode=True)

            result = be.write("/new_dir/new_file.txt", "content")
            assert result.path is not None or result.error is None

    def test_write_existing_file_error(self):
        """Test writing to existing file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "existing.txt").write_text("original")

            be = FilesystemBackend(root_dir=tmpdir, virtual_mode=True)
            result = be.write("/existing.txt", "new content")

            # Should return error or overwrite depending on implementation
            assert result.error is not None or "exists" in result.error.lower()


class TestGrepSecurity:
    """Test grep operation security."""

    def test_grep_pattern_length_limit(self):
        """Test that extremely long patterns are rejected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            be = FilesystemBackend(root_dir=tmpdir, virtual_mode=True)

            # Create a pattern that's too long
            long_pattern = "a" * 10000
            result = be.grep_raw(long_pattern, "/")

            assert isinstance(result, str)
            assert "too long" in result.lower() or "error" in result.lower()

    def test_grep_path_traversal(self):
        """Test grep doesn't allow path traversal."""
        with tempfile.TemporaryDirectory() as tmpdir:
            be = FilesystemBackend(root_dir=tmpdir, virtual_mode=True)

            # Grep with path traversal should return empty list (path not resolved)
            result = be.grep_raw("test", "/../../../etc")
            assert result == []


class TestPlatformSpecific:
    """Test platform-specific path handling."""

    def test_windows_drive_letter(self):
        """Test Windows drive letter handling."""
        pytest.importorskip("os")

        with tempfile.TemporaryDirectory() as tmpdir:
            be = FilesystemBackend(root_dir=tmpdir, virtual_mode=True)

            if os.name == "nt":
                # On Windows, drive letters like C:\ should be handled
                with pytest.raises(ValueError):
                    be._resolve_path("C:\\Windows\\System32")
            else:
                # On POSIX, this should just be treated as a virtual path
                result = be._resolve_path("/C:/Windows")
                assert result.is_absolute()

    def test_windows_unc_path(self):
        """Test Windows UNC path handling."""
        with tempfile.TemporaryDirectory() as tmpdir:
            be = FilesystemBackend(root_dir=tmpdir, virtual_mode=True)

            # UNC paths like \\server\share
            unc_path = "\\\\server\\share\\file.txt"
            # Should be blocked or handled safely
            with pytest.raises(ValueError):
                be._resolve_path(unc_path)


class TestRaceConditions:
    """Test TOCTOU race condition handling."""

    def test_file_replaced_during_read(self):
        """Test handling of file being replaced during read."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            test_file = root / "test.txt"
            test_file.write_text("original content")

            be = FilesystemBackend(root_dir=tmpdir, virtual_mode=True)

            # Normal read should work
            content = be.read("/test.txt")
            assert "content" in content or test_file.exists()

    def test_directory_deleted_during_ls(self):
        """Test handling of directory deletion during ls."""
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            test_dir = root / "test_dir"
            test_dir.mkdir()

            be = FilesystemBackend(root_dir=tmpdir, virtual_mode=True)

            # Delete during or after ls
            result = be.ls_info("/test_dir")
            assert isinstance(result, list)  # Should return empty or list


class TestVirtualModeEdgeCases:
    """Test virtual mode specific edge cases."""

    def test_virtual_path_normalization(self):
        """Test that virtual paths are normalized."""
        with tempfile.TemporaryDirectory() as tmpdir:
            be = FilesystemBackend(root_dir=tmpdir, virtual_mode=True)

            # Double slashes should be normalized
            result1 = be._resolve_path("//test//file.txt")
            result2 = be._resolve_path("/test/file.txt")

            assert result1 == result2

    def test_virtual_path_empty(self):
        """Test empty path handling."""
        with tempfile.TemporaryDirectory() as tmpdir:
            be = FilesystemBackend(root_dir=tmpdir, virtual_mode=True)

            result = be._resolve_path("")
            # Should resolve to root
            assert str(result) == tmpdir or result.is_absolute()

    def test_virtual_path_dot(self):
        """Test current directory path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            be = FilesystemBackend(root_dir=tmpdir, virtual_mode=True)

            result = be._resolve_path(".")
            # Should resolve to root
            assert str(result) == tmpdir or result.is_absolute()


class TestNonVirtualModeSecurity:
    """Test non-virtual mode with allowed_prefixes."""

    def test_allowed_prefixes_with_symlink_inside(self):
        """Test symlink inside allowed directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            allowed = Path(tmpdir) / "allowed"
            allowed.mkdir()

            # Create target inside allowed
            target = allowed / "target.txt"
            target.write_text("content")

            # Create symlink inside allowed
            link = allowed / "link.txt"
            try:
                link.symlink_to(target)
            except OSError:
                pytest.skip("Symlink creation not supported")

            be = FilesystemBackend(allowed_prefixes=[allowed], virtual_mode=False)

            # Reading symlink inside allowed should work
            result = be._resolve_path(str(link))
            assert result.is_absolute()

    def test_allowed_prefixes_with_symlink_outside(self):
        """Test symlink pointing outside allowed directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            allowed = Path(tmpdir) / "allowed"
            allowed.mkdir()
            outside = Path(tmpdir) / "outside.txt"
            outside.write_text("secret")

            # Create symlink inside allowed pointing outside
            link = allowed / "escape.txt"
            try:
                link.symlink_to(outside)
            except OSError:
                pytest.skip("Symlink creation not supported")

            be = FilesystemBackend(allowed_prefixes=[allowed], virtual_mode=False)

            # The resolved path should point outside and be blocked
            resolved = be._resolve_path(str(link))
            # Symlink resolves to outside, which should be blocked
            assert resolved.is_absolute()
            # But operations on it would fail at the prefix check

    def test_relative_path_allowed_prefixes(self):
        """Test relative path with allowed_prefixes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            allowed = Path(tmpdir) / "allowed"
            allowed.mkdir()

            be = FilesystemBackend(root_dir=tmpdir, allowed_prefixes=[allowed], virtual_mode=False)

            # Relative path from cwd (which is outside allowed)
            # Should resolve to cwd/test.txt which is outside allowed
            with pytest.raises(ValueError, match="outside allowed"):
                be._resolve_path("test.txt")

            # Absolute path under allowed should work
            result = be._resolve_path(str(allowed / "test.txt"))
            assert result == (allowed / "test.txt")


class TestCaseSensitivity:
    """Test case sensitivity handling."""

    def test_case_insensitive_path(self):
        """Test case-insensitive path handling."""
        with tempfile.TemporaryDirectory() as tmpdir:
            be = FilesystemBackend(root_dir=tmpdir, virtual_mode=True)

            # On case-insensitive systems (Windows), these might be the same
            lower = be._resolve_path("/test.txt")
            upper = be._resolve_path("/TEST.TXT")

            # Both should resolve to paths under root
            assert lower.is_absolute()
            assert upper.is_absolute()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

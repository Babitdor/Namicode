"""Tests for novacode_cli.errors.taxonomy — error categorization and recovery."""

import pytest

from novacode_cli.errors.taxonomy import ErrorCategory, RecoverableError


class TestErrorCategory:
    """Tests for the ErrorCategory enum."""

    def test_has_user_error(self):
        assert ErrorCategory.USER_ERROR.value == "user_error"

    def test_has_file_not_found(self):
        assert ErrorCategory.FILE_NOT_FOUND.value == "file_not_found"

    def test_has_network_error(self):
        assert ErrorCategory.NETWORK_ERROR.value == "network_error"

    def test_has_timeout_error(self):
        assert ErrorCategory.TIMEOUT_ERROR.value == "timeout_error"

    def test_all_values_are_strings(self):
        for member in ErrorCategory:
            assert isinstance(member.value, str)


class TestRecoverableError:
    """Tests for the RecoverableError dataclass."""

    def test_can_create_directly(self):
        err = RecoverableError(
            category=ErrorCategory.FILE_NOT_FOUND,
            original_error=FileNotFoundError("missing.txt"),
            context={"path": "/tmp/missing.txt"},
            recovery_suggestion="Check if the file exists and the path is correct.",
            user_message="File not found: missing.txt",
        )
        assert err.category == ErrorCategory.FILE_NOT_FOUND
        assert isinstance(err.original_error, FileNotFoundError)
        assert err.context["path"] == "/tmp/missing.txt"
        assert err.retry_allowed is True

    def test_retry_allowed_defaults_to_true(self):
        err = RecoverableError(
            category=ErrorCategory.SYNTAX_ERROR,
            original_error=SyntaxError("bad syntax"),
            context={},
            recovery_suggestion="Fix the syntax error.",
            user_message="Syntax error",
        )
        assert err.retry_allowed is True

    def test_can_set_retry_allowed_to_false(self):
        err = RecoverableError(
            category=ErrorCategory.SYSTEM_ERROR,
            original_error=RuntimeError("critical"),
            context={},
            recovery_suggestion="Restart the application.",
            user_message="Critical error",
            retry_allowed=False,
        )
        assert err.retry_allowed is False

    def test_from_exception_creates_recoverable_error(self):
        """from_exception() should create a RecoverableError from an exception."""
        try:
            raise ValueError("invalid input")
        except ValueError as exc:
            err = RecoverableError.from_exception(
                exc,
                category=ErrorCategory.USER_ERROR,
                context={"input": "bad_data"},
                recovery_suggestion="Check your input and try again.",
            )
            _exc = exc  # capture before except block exit

        assert err.category == ErrorCategory.USER_ERROR
        assert isinstance(_exc, ValueError)
        assert err.original_error is _exc
        assert err.context == {"input": "bad_data"}
        assert err.recovery_suggestion == "Check your input and try again."
        assert err.user_message == "invalid input"
        assert err.retry_allowed is True

    def test_from_exception_with_custom_user_message(self):
        try:
            raise PermissionError("access denied")
        except PermissionError as exc:
            err = RecoverableError.from_exception(
                exc,
                category=ErrorCategory.PERMISSION_DENIED,
                context={},
                recovery_suggestion="Grant permissions.",
                user_message="You do not have access to this resource.",
            )
            _exc = exc

        assert err.user_message == "You do not have access to this resource."
        assert err.original_error is _exc

    def test_from_exception_uses_str_on_exception_as_default_message(self):
        try:
            raise RuntimeError("something broke")
        except RuntimeError as exc:
            err = RecoverableError.from_exception(
                exc,
                category=ErrorCategory.SYSTEM_ERROR,
                context={},
                recovery_suggestion="Restart.",
            )

        assert err.user_message == "something broke"

    def test_from_exception_with_retry_false(self):
        try:
            raise ConnectionError("db down")
        except ConnectionError as exc:
            err = RecoverableError.from_exception(
                exc,
                category=ErrorCategory.NETWORK_ERROR,
                context={},
                recovery_suggestion="Check network.",
                retry_allowed=False,
            )

        assert err.retry_allowed is False

    def test_from_exception_nested_context(self):
        try:
            raise ValueError("bad")
        except ValueError as exc:
            err = RecoverableError.from_exception(
                exc,
                category=ErrorCategory.TYPE_ERROR,
                context={"key": "age", "expected": "int"},
                recovery_suggestion="Fix the type.",
            )

        assert err.context["key"] == "age"
        assert err.context["expected"] == "int"
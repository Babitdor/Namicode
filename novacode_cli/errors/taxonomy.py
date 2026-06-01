"""Error taxonomy and classification for deepagents CLI."""

from dataclasses import dataclass
from enum import Enum


class ErrorCategory(Enum):
    """Classification of errors for recovery strategies."""

    USER_ERROR = "user_error"  # User input issues
    FILE_NOT_FOUND = "file_not_found"  # Missing files
    PERMISSION_DENIED = "permission_denied"  # Permission issues
    COMMAND_NOT_FOUND = "command_not_found"  # Missing commands/packages
    SYNTAX_ERROR = "syntax_error"  # Code syntax issues
    NETWORK_ERROR = "network_error"  # API/network failures
    CONTEXT_OVERFLOW = "context_overflow"  # Context limit issues
    TOOL_ERROR = "tool_error"  # Tool execution failures
    SYSTEM_ERROR = "system_error"  # Internal errors
    IMPORT_ERROR = "import_error"  # Missing imports, module not found
    TYPE_ERROR = "type_error"  # Type mismatches, wrong argument types
    TEST_FAILURE = "test_failure"  # Test assertions failed
    DEPENDENCY_ERROR = "dependency_error"  # Missing packages, version conflicts
    CONFIGURATION_ERROR = "configuration_error"  # Config issues, missing env vars
    TIMEOUT_ERROR = "timeout_error"  # Operation exceeded time limit


@dataclass
class RecoverableError:
    """An error that can be automatically recovered.

    Attributes:
        category: The error category for recovery strategy selection
        original_error: The original exception that was raised
        context: Additional context about the error (file paths, etc.)
        recovery_suggestion: Human-readable suggestion for fixing the error
        user_message: User-friendly error message
        retry_allowed: Whether automatic retry is allowed
    """

    category: ErrorCategory
    original_error: Exception
    context: dict
    recovery_suggestion: str
    user_message: str
    retry_allowed: bool = True

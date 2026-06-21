"""Error handling and recovery system for deepagents CLI."""

from novacode_cli.errors.handlers import ErrorHandler, RecoveryResult
from novacode_cli.errors.provider_errors import (
    friendly_model_error,
    is_retryable_model_error,
)
from novacode_cli.errors.taxonomy import ErrorCategory, RecoverableError

__all__ = [
    "ErrorCategory",
    "ErrorHandler",
    "RecoverableError",
    "RecoveryResult",
    "friendly_model_error",
    "is_retryable_model_error",
]

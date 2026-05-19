"""Error handling and recovery system for deepagents CLI."""

from novacode_cli.errors.handlers import ErrorHandler, RecoveryResult
from novacode_cli.errors.taxonomy import ErrorCategory, RecoverableError

__all__ = ["ErrorCategory", "ErrorHandler", "RecoverableError", "RecoveryResult"]

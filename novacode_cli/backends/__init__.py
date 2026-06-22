"""Nova's custom backend wrappers extending deepagents backends.

Provides performance and feature enhancements to deepagents backends while
maintaining full backward compatibility.
"""

from novacode_cli.backends.filesystem import (
    OptimizedFilesystemBackend,
    OptimizedLocalShellBackend,
)

__all__ = ["OptimizedFilesystemBackend", "OptimizedLocalShellBackend"]

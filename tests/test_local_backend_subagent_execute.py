"""Regression tests for local-mode subagent command execution.

Declarative subagents built by deepagents always get a FilesystemMiddleware, and
that middleware always registers an `execute` tool. In local mode Nova used to use
a plain FilesystemBackend as the CompositeBackend default, so the subagent's
`execute` tool failed with:

    Default backend doesn't support command execution (SandboxBackendProtocol).

The fix uses deepagents' LocalShellBackend as the local-mode default. It is a
FilesystemBackend subclass that also implements SandboxBackendProtocol, so
project file operations keep their existing virtual-root semantics and
subagent `execute` calls now work. The ShellMiddleware in turn must *not* treat
LocalShellBackend as a sandbox, otherwise it would bypass Nova's local shell
blocklist / OS confinement.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from deepagents.backends import CompositeBackend
from deepagents.backends.local_shell import LocalShellBackend

from novacode_cli.shell.middleware import ShellMiddleware

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def local_backend(tmp_path: Path) -> CompositeBackend:
    """Build the same local-mode CompositeBackend that create_agent_with_config uses."""
    workspace_root = tmp_path / "project"
    workspace_root.mkdir()

    default = LocalShellBackend(
        root_dir=str(workspace_root),
        virtual_mode=True,
        env={},
    )

    return CompositeBackend(
        default=default,
        routes={},
    )


def test_local_default_backend_supports_execution(local_backend: CompositeBackend) -> None:
    """Subagents see a default backend that satisfies SandboxBackendProtocol."""
    from deepagents.backends.protocol import SandboxBackendProtocol

    assert isinstance(local_backend.default, SandboxBackendProtocol)
    result = local_backend.execute("echo hello-subagent")
    assert result.exit_code == 0
    assert "hello-subagent" in result.output


def test_local_file_ops_still_use_filesystem_backend(local_backend: CompositeBackend) -> None:
    """`/`-rooted project paths are routed to the plain FilesystemBackend."""
    local_backend.write("/subagent-file.txt", "subagent content")
    read_result = local_backend.read("/subagent-file.txt")
    assert read_result.error is None
    assert read_result.file_data["content"] == "subagent content"


def test_shell_middleware_ignores_local_shell_backend(local_backend: CompositeBackend) -> None:
    """LocalShellBackend must not be treated as a remote sandbox by ShellMiddleware."""
    middleware = ShellMiddleware(
        workspace_root=".",
        backend=local_backend,
    )
    assert not middleware._supports_sandbox_execution()

"""LangSmith Sandbox backend implementation.

Wraps a LangSmith Sandbox instance to conform to the deepagents
SandboxBackendProtocol. File operations are inherited from BaseSandbox
(via shell commands through execute()). Only execute(), download_files(),
and upload_files() need backend-specific implementations.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from deepagents.backends.protocol import (
    ExecuteResponse,
    FileDownloadResponse,
    FileUploadResponse,
)
from deepagents.backends.sandbox import BaseSandbox

if TYPE_CHECKING:
    from langsmith.sandbox import Sandbox


class LangSmithBackend(BaseSandbox):
    """Backend wrapping a LangSmith Sandbox instance.

    This implementation inherits all file operation methods from BaseSandbox
    and only implements execute() using the LangSmith Sandbox API.

    File operations (read, write, edit, ls, glob, grep) are performed by
    BaseSandbox default implementations, which execute shell commands via
    the execute() method.

    Attributes:
        _sandbox: The LangSmith Sandbox instance.
        _timeout: Default timeout for command execution (30 minutes).
    """

    def __init__(self, sandbox: Sandbox) -> None:
        """Initialize the LangSmithBackend with a LangSmith Sandbox.

        Args:
            sandbox: LangSmith Sandbox instance obtained from SandboxClient.
        """
        self._sandbox = sandbox
        self._timeout: int = 30 * 60  # 30 minutes

    @property
    def id(self) -> str:
        """Unique identifier for the sandbox backend.

        Uses the sandbox name since it remains constant across the sandbox
        lifecycle and is the primary key for the LangSmith Sandbox API.
        Falls back to the UUID id if name is not available.
        """
        return self._sandbox.name or self._sandbox.id or "langsmith-unknown"

    def execute(
        self,
        command: str,
        *,
        timeout: int | None = None,
        env: dict[str, str] | None = None,
        cwd: str | None = None,
    ) -> ExecuteResponse:
        """Execute a command in the sandbox and return ExecuteResponse.

        Args:
            command: Full shell command string to execute.
            timeout: Maximum execution time in seconds. Defaults to 30 minutes.
            env: Optional environment variables to set for this command.
            cwd: Optional working directory for this command.

        Returns:
            ExecuteResponse with combined output, exit code, and truncation flag.
        """
        result = self._sandbox.run(  # noqa: S604 — LangSmith SDK arg, not subprocess shell
            command,
            timeout=timeout or self._timeout,
            shell="/bin/bash",
            env=env,
            cwd=cwd,
        )

        # Combine stdout and stderr (same pattern as RunloopBackend)
        output = result.stdout or ""
        if result.stderr:
            output += "\n" + result.stderr if output else result.stderr

        return ExecuteResponse(
            output=output,
            exit_code=result.exit_code,
            truncated=False,  # LangSmith doesn't provide truncation info
        )

    def download_files(self, paths: list[str]) -> list[FileDownloadResponse]:
        """Download multiple files from the LangSmith sandbox.

        Downloads files individually using the Sandbox.read() API.
        Supports partial success — individual downloads may fail without
        affecting others.

        Args:
            paths: List of file paths to download.

        Returns:
            List of FileDownloadResponse objects, one per input path.
            Response order matches input order.
        """
        responses: list[FileDownloadResponse] = []
        for path in paths:
            try:
                content = self._sandbox.read(path)
                responses.append(FileDownloadResponse(path=path, content=content, error=None))
            except Exception as e:  # noqa: BLE001
                responses.append(
                    FileDownloadResponse(
                        path=path,
                        content=b"",
                        error=str(e),
                    )
                )
        return responses

    def upload_files(self, files: list[tuple[str, bytes]]) -> list[FileUploadResponse]:
        """Upload multiple files to the LangSmith sandbox.

        Uploads files individually using the Sandbox.write() API.
        Supports partial success — individual uploads may fail without
        affecting others.

        Args:
            files: List of (path, content) tuples to upload.

        Returns:
            List of FileUploadResponse objects, one per input file.
            Response order matches input order.
        """
        responses: list[FileUploadResponse] = []
        for path, content in files:
            try:
                self._sandbox.write(path, content)
                responses.append(FileUploadResponse(path=path, error=None))
            except Exception as e:  # noqa: BLE001
                responses.append(
                    FileUploadResponse(
                        path=path,
                        error=str(e),
                    )
                )
        return responses

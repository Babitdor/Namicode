"""E2B sandbox executor for secure code execution.

This module provides integration with E2B Code Interpreter for running
Python, Node.js, and Bash code in isolated cloud sandboxes.
"""

import time
from dataclasses import dataclass

from e2b_code_interpreter import Sandbox

# Language runtime command mapping
LANGUAGE_RUNTIMES = {
    "python": "python3",
    "nodejs": "node",
    "javascript": "node",
    "bash": "bash",
    "shell": "bash",
}

# Maximum output size to prevent context overflow
MAX_OUTPUT_SIZE = 50000


@dataclass
class ExecuteResult:
    """Result of code execution in E2B sandbox.

    Attributes:
        stdout: Standard output from execution
        stderr: Standard error from execution
        exit_code: Process exit code (None if timeout/error)
        error: Error message if execution failed
        execution_time: Time taken to execute in seconds
        truncated: Whether output was truncated due to size
    """

    stdout: str
    stderr: str
    exit_code: int | None
    error: str | None
    execution_time: float
    truncated: bool


class E2BExecutor:
    """Executor for running code in E2B cloud sandboxes.

    Manages sandbox lifecycle, code execution, and result capture.
    """

    def __init__(self, api_key: str) -> None:
        """Initialize E2B executor.

        Args:
            api_key: E2B API key for authentication
        """
        self.api_key = api_key
        # Future: Add session pooling here
        # self.sandboxes = {}

    def execute(
        self,
        code: str,
        language: str = "python",
        files: list[tuple[str, str]] | None = None,
        timeout: int = 60,
    ) -> ExecuteResult:
        """Execute code in E2B sandbox.

        Args:
            code: Code to execute
            language: Runtime language (python, nodejs, bash)
            files: Optional list of (path, content) tuples to upload
            timeout: Execution timeout in seconds (max 300)

        Returns:
            ExecuteResult with output, errors, and execution metadata
        """
        start_time = time.time()
        sandbox = None

        try:
            # Create sandbox
            sandbox = Sandbox.create(api_key=self.api_key)

            # Upload files if provided
            if files:
                self._upload_files(sandbox, files)

            # Get runtime command
            runtime = LANGUAGE_RUNTIMES.get(language.lower(), "bash")

            # Execute code based on language
            if language.lower() in ["python", "nodejs", "javascript"]:
                # For Python/Node, use code interpreter execute
                execution = sandbox.run_code(code, language=language.lower())

                stdout = ""
                stderr = ""

                # Collect results
                if execution.results:
                    for result in execution.results:
                        if hasattr(result, "text") and result.text:
                            stdout += result.text
                        elif hasattr(result, "data") and result.data:
                            stdout += str(result.data)

                if execution.logs:
                    stdout_logs = execution.logs.stdout if execution.logs.stdout else []
                    stderr_logs = execution.logs.stderr if execution.logs.stderr else []

                    if stdout_logs:
                        stdout += "\n".join(stdout_logs)
                    if stderr_logs:
                        stderr += "\n".join(stderr_logs)

                # Check for errors
                error_msg = None
                if execution.error:
                    error_msg = str(execution.error)
                    stderr += f"\n{error_msg}" if stderr else error_msg

                exit_code = 0 if not execution.error else 1

            else:
                # For bash/shell, write code to file and execute
                sandbox.files.write("/tmp/script.sh", code)
                result = sandbox.commands.run(f"{runtime} /tmp/script.sh", timeout=timeout)

                stdout = result.stdout if result.stdout else ""
                stderr = result.stderr if result.stderr else ""
                exit_code = result.exit_code if result.exit_code is not None else 0
                error_msg = stderr if exit_code != 0 else None

            # Check output size and truncate if needed
            truncated = False
            total_output = len(stdout) + len(stderr)
            if total_output > MAX_OUTPUT_SIZE:
                truncated = True
                # Truncate stdout first, then stderr if needed
                if len(stdout) > MAX_OUTPUT_SIZE:
                    stdout = stdout[:MAX_OUTPUT_SIZE]
                    stderr = ""
                else:
                    remaining = MAX_OUTPUT_SIZE - len(stdout)
                    stderr = stderr[:remaining]

            execution_time = time.time() - start_time

            return ExecuteResult(
                stdout=stdout,
                stderr=stderr,
                exit_code=exit_code,
                error=error_msg,
                execution_time=execution_time,
                truncated=truncated,
            )

        except TimeoutError as e:
            execution_time = time.time() - start_time
            return ExecuteResult(
                stdout="",
                stderr="",
                exit_code=None,
                error=f"Execution timeout after {timeout} seconds: {e}",
                execution_time=execution_time,
                truncated=False,
            )
        except Exception as e:  # noqa: BLE001
            execution_time = time.time() - start_time
            return ExecuteResult(
                stdout="",
                stderr="",
                exit_code=None,
                error=f"Sandbox execution failed: {e}",
                execution_time=execution_time,
                truncated=False,
            )
        finally:
            # Clean up sandbox
            if sandbox:
                try:
                    sandbox.kill()
                except Exception:  # noqa: BLE001, S110
                    pass  # Best effort cleanup

    def _upload_files(self, sandbox: Sandbox, files: list[tuple[str, str]]) -> None:
        """Upload files to sandbox before execution.

        Args:
            sandbox: Active E2B sandbox instance
            files: List of (path, content) tuples to upload
        """
        for file_path, content in files:
            try:
                sandbox.files.write(file_path, content)
            except Exception as e:  # noqa: BLE001
                # Log error but continue with other files
                print(f"Warning: Failed to upload {file_path}: {e}")  # noqa: T201


def format_e2b_result(result: ExecuteResult) -> str:
    """Format E2B execution result for LLM consumption.

    Args:
        result: ExecuteResult from E2BExecutor

    Returns:
        Formatted string with execution details
    """
    output_parts = []

    if result.error:
        output_parts.append(f"Error: {result.error}")

    if result.stdout:
        output_parts.append(f"Output:\n{result.stdout}")

    if result.stderr and not result.error:
        # Only show stderr separately if there's no error
        # (error already includes stderr)
        output_parts.append(f"Errors:\n{result.stderr}")

    if result.exit_code is not None:
        output_parts.append(f"Exit code: {result.exit_code}")
    else:
        output_parts.append("Exit code: N/A (timeout or error)")

    output_parts.append(f"Execution time: {result.execution_time:.2f}s")

    if result.truncated:
        output_parts.append(f"\n[Output truncated - exceeded {MAX_OUTPUT_SIZE:,} character limit]")

    return "\n\n".join(output_parts)

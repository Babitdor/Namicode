"""Code execution tools.

This module provides tools for executing code in isolated environments.
"""

from __future__ import annotations

import json
import os

from langchain.tools import tool


@tool
def execute_in_e2b(
    code: str,
    language: str = "python",
    files: str | None = None,
    timeout: int = 60,
) -> str:
    r"""Execute code in isolated E2B cloud sandbox.

    Use this tool to run Python, Node.js, or Bash code in a secure, isolated
    cloud environment. Perfect for:
    - Testing code snippets before committing
    - Running untrusted or experimental code safely
    - Executing skill reference scripts
    - Installing and testing packages (pip, npm)
    - Running code that requires network access

    The sandbox is fully isolated from the local system with automatic cleanup.
    Package managers (pip, npm) work automatically within the sandbox.

    Args:
        code: The code to execute (as a string)
        language: Runtime to use - "python", "nodejs", "javascript", or "bash" (default: "python")
        files: Optional JSON string of files to upload before execution.
               Format: '{"filename1": "content1", "filename2": "content2"}'
               Files will be available in the sandbox filesystem.
        timeout: Maximum execution time in seconds (default: 60, max: 300)

    Returns:
        Formatted string with execution results including:
        - Standard output from the code
        - Standard error (if any)
        - Exit code
        - Execution time
        - Error messages (if execution failed)

    Examples:
        # Run Python code
        execute_in_e2b(code="print('Hello from E2B')", language="python")

        # Install and use a package
        execute_in_e2b(
            code=(
                "import subprocess\\n"
                "subprocess.run(['pip', 'install', 'requests'])\\n"
                "import requests\\n"
                "print(requests.__version__)"
            ),
            language="python"
        )

        # Run with uploaded files
        execute_in_e2b(
            code="with open('data.txt') as f: print(f.read())",
            language="python",
            files='{"data.txt": "Hello World"}'
        )

        # Run Node.js
        execute_in_e2b(code="console.log(process.version)", language="nodejs")

    Note: Requires E2B_API_KEY to be configured. Set it with:
          Nova secrets set e2b_api_key
          Or set environment variable: export E2B_API_KEY=your-key-here
    """
    # Lazy import to avoid dependency issues if e2b not installed
    try:
        from novacode_cli.integrations.e2b_executor import (
            E2BExecutor,
            format_e2b_result,
        )
    except ImportError as e:
        return (
            f"Error: E2B Code Interpreter SDK not installed: {e}\n\n"
            "Install it with: uv add e2b-code-interpreter"
        )

    # Check for API key in SecretManager or environment
    from novacode_cli.onboarding import SecretManager

    secret_manager = SecretManager()
    api_key = secret_manager.get_secret("e2b_api_key") or os.environ.get("E2B_API_KEY")

    if not api_key:
        return (
            "Error: E2B_API_KEY not configured.\n\n"
            "To set up E2B sandbox execution:\n"
            "1. Sign up at https://e2b.dev and create an API key\n"
            "2. Configure it with: Nova secrets set e2b_api_key\n"
            "   Or set environment variable: export E2B_API_KEY=your-key-here\n\n"
            "E2B provides isolated cloud sandboxes for secure code execution."
        )

    # Validate timeout
    if timeout > 300:
        timeout = 300
        timeout_warning = "\nWarning: Timeout capped at 300 seconds (5 minutes)\n"
    else:
        timeout_warning = ""

    # Parse files if provided
    file_list = None
    if files:
        try:
            files_dict = json.loads(files)
            file_list = [(path, content) for path, content in files_dict.items()]
        except json.JSONDecodeError as e:
            return (
                f"Error: Invalid JSON in files parameter: {e}\n\n"
                'Expected format: {{"filename": "content", ...}}'
            )

    # Execute code in sandbox
    try:
        executor = E2BExecutor(api_key=api_key)
        result = executor.execute(
            code=code,
            language=language,
            files=file_list,
            timeout=timeout,
        )

        # Format result for LLM
        formatted = format_e2b_result(result)

        # Add timeout warning if applicable
        if timeout_warning:
            formatted = timeout_warning + "\n" + formatted

        return formatted

    except Exception as e:  # noqa: BLE001
        return (
            f"Error: Failed to execute code in E2B sandbox: {e}\n\n"
            "This may be due to:\n"
            "- Invalid API key\n"
            "- Network connectivity issues\n"
            "- E2B service unavailable\n\n"
            f"Error details: {e!s}"
        )

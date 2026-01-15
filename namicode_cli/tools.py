"""Custom tools for the CLI agent.

This module provides additional tools beyond the filesystem and shell tools,
enabling the agent to interact with external services and the web:

Key Tools:
- http_request(): Make HTTP requests to APIs and web services
- fetch_url(): Fetch web pages and convert HTML to markdown
- web_search(): Search the web using Tavily API
- execute_in_e2b(): Execute code in isolated E2B cloud sandboxes

These tools are registered with the agent and allow it to:
- Fetch data from REST APIs
- Scrape web content and convert to readable markdown
- Search for current information online
- Handle various HTTP methods (GET, POST, PUT, DELETE, etc.)
- Run Python, Node.js, and Bash code securely in isolated environments

Dependencies:
- requests: HTTP client library
- markdownify: HTML to markdown conversion
- tavily: Web search API client
- e2b-code-interpreter: E2B sandbox execution

The Tavily client is initialized if TAVILY_API_KEY is available in settings.
"""

import difflib
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Literal

import requests
from markdownify import markdownify
from tavily import TavilyClient

from namicode_cli.config.config import settings

# Initialize Tavily client if API key is available
tavily_client = (
    TavilyClient(api_key=settings.tavily_api_key) if settings.has_tavily else None
)


def http_request(
    url: str,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    data: str | dict | None = None,
    params: dict[str, str] | None = None,
    timeout: int = 30,
) -> dict[str, Any]:
    """Make HTTP requests to APIs and web services.

    Args:
        url: Target URL
        method: HTTP method (GET, POST, PUT, DELETE, etc.)
        headers: HTTP headers to include
        data: Request body data (string or dict)
        params: URL query parameters
        timeout: Request timeout in seconds

    Returns:
        Dictionary with response data including status, headers, and content
    """
    try:
        kwargs = {"url": url, "method": method.upper(), "timeout": timeout}

        if headers:
            kwargs["headers"] = headers
        if params:
            kwargs["params"] = params
        if data:
            if isinstance(data, dict):
                kwargs["json"] = data
            else:
                kwargs["data"] = data

        response = requests.request(**kwargs)

        try:
            content = response.json()
        except:
            content = response.text

        return {
            "success": response.status_code < 400,
            "status_code": response.status_code,
            "headers": dict(response.headers),
            "content": content,
            "url": response.url,
        }

    except requests.exceptions.Timeout:
        return {
            "success": False,
            "status_code": 0,
            "headers": {},
            "content": f"Request timed out after {timeout} seconds",
            "url": url,
        }
    except requests.exceptions.RequestException as e:
        return {
            "success": False,
            "status_code": 0,
            "headers": {},
            "content": f"Request error: {e!s}",
            "url": url,
        }
    except Exception as e:
        return {
            "success": False,
            "status_code": 0,
            "headers": {},
            "content": f"Error making request: {e!s}",
            "url": url,
        }


def web_search(
    query: str,
    max_results: int = 5,
    topic: Literal["general", "news", "finance"] = "general",
    include_raw_content: bool = False,
):
    """Search the web using Tavily for current information and documentation.

    This tool searches the web and returns relevant results. After receiving results,
    you MUST synthesize the information into a natural, helpful response for the user.

    Args:
        query: The search query (be specific and detailed)
        max_results: Number of results to return (default: 5)
        topic: Search topic type - "general" for most queries, "news" for current events
        include_raw_content: Include full page content (warning: uses more tokens)

    Returns:
        Dictionary containing:
        - results: List of search results, each with:
            - title: Page title
            - url: Page URL
            - content: Relevant excerpt from the page
            - score: Relevance score (0-1)
        - query: The original search query

    IMPORTANT: After using this tool:
    1. Read through the 'content' field of each result
    2. Extract relevant information that answers the user's question
    3. Synthesize this into a clear, natural language response
    4. Cite sources by mentioning the page titles or URLs
    5. NEVER show the raw JSON to the user - always provide a formatted response
    """
    if tavily_client is None:
        return {
            "error": "Tavily API key not configured. Please set TAVILY_API_KEY environment variable.",
            "query": query,
        }

    try:
        return tavily_client.search(
            query,
            max_results=max_results,
            include_raw_content=include_raw_content,
            topic=topic,
        )
    except Exception as e:
        return {"error": f"Web search error: {e!s}", "query": query}


def fetch_url(url: str, timeout: int = 30) -> dict[str, Any]:
    """Fetch content from a URL and convert HTML to markdown format.

    This tool fetches web page content and converts it to clean markdown text,
    making it easy to read and process HTML content. After receiving the markdown,
    you MUST synthesize the information into a natural, helpful response for the user.

    Args:
        url: The URL to fetch (must be a valid HTTP/HTTPS URL)
        timeout: Request timeout in seconds (default: 30)

    Returns:
        Dictionary containing:
        - success: Whether the request succeeded
        - url: The final URL after redirects
        - markdown_content: The page content converted to markdown
        - status_code: HTTP status code
        - content_length: Length of the markdown content in characters

    IMPORTANT: After using this tool:
    1. Read through the markdown content
    2. Extract relevant information that answers the user's question
    3. Synthesize this into a clear, natural language response
    4. NEVER show the raw markdown to the user unless specifically requested
    """
    try:
        response = requests.get(
            url,
            timeout=timeout,
            headers={"User-Agent": "Mozilla/5.0 (compatible; DeepAgents/1.0)"},
        )
        response.raise_for_status()

        # Convert HTML content to markdown
        markdown_content = markdownify(response.text)

        return {
            "url": str(response.url),
            "markdown_content": markdown_content,
            "status_code": response.status_code,
            "content_length": len(markdown_content),
        }
    except Exception as e:
        return {"error": f"Fetch URL error: {e!s}", "url": url}


def execute_in_e2b(
    code: str,
    language: str = "python",
    files: str | None = None,
    timeout: int = 60,
) -> str:
    """Execute code in isolated E2B cloud sandbox.

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
            code="import subprocess\\nsubprocess.run(['pip', 'install', 'requests'])\\nimport requests\\nprint(requests.__version__)",
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
          nami secrets set e2b_api_key
          Or set environment variable: export E2B_API_KEY=your-key-here
    """
    # Lazy import to avoid dependency issues if e2b not installed
    try:
        from namicode_cli.integrations.e2b_executor import (
            E2BExecutor,
            format_e2b_result,
        )
    except ImportError as e:
        return (
            f"Error: E2B Code Interpreter SDK not installed: {e}\n\n"
            "Install it with: pip install e2b-code-interpreter"
        )

    # Check for API key in SecretManager or environment
    from namicode_cli.onboarding import SecretManager

    secret_manager = SecretManager()
    api_key = secret_manager.get_secret("e2b_api_key") or os.environ.get("E2B_API_KEY")

    if not api_key:
        return (
            "Error: E2B_API_KEY not configured.\n\n"
            "To set up E2B sandbox execution:\n"
            "1. Sign up at https://e2b.dev and create an API key\n"
            "2. Configure it with: nami secrets set e2b_api_key\n"
            "   Or set environment variable: export E2B_API_KEY=your-key-here\n\n"
            "E2B provides isolated cloud sandboxes for secure code execution."
        )

    # Validate timeout
    if timeout > 300:  # noqa: PLR2004
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
            return f'Error: Invalid JSON in files parameter: {e}\n\nExpected format: {{"filename": "content", ...}}'

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

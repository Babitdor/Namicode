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
from datetime import datetime
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


def duckduckgo_search(
    query: str,
    max_results: int = 5,
    region: str = "wt-wt",
    safesearch: Literal["on", "moderate", "off"] = "moderate",
    time_range: Literal["d", "w", "m", "y", ""] = "",
) -> dict[str, Any]:
    """Search the web using DuckDuckGo (no API key required).

    A free alternative to Tavily for web search. Returns relevant search results
    that you should synthesize into a natural response for the user.

    Args:
        query: The search query (be specific and detailed)
        max_results: Number of results to return (default: 5, max: 20)
        region: Region for search results (default: "wt-wt" for worldwide)
                Examples: "us-en", "uk-en", "de-de", "fr-fr", "jp-jp"
        safesearch: Safe search level - "on", "moderate", or "off"
        time_range: Time filter - "d" (day), "w" (week), "m" (month), "y" (year), "" (any)

    Returns:
        Dictionary containing:
        - success: Whether search succeeded
        - results: List of search results, each with:
            - title: Page title
            - url: Page URL
            - body: Relevant excerpt/snippet from the page
        - query: The original search query
        - total_results: Number of results returned

    IMPORTANT: After using this tool:
    1. Read through the 'body' field of each result
    2. Extract relevant information that answers the user's question
    3. Synthesize this into a clear, natural language response
    4. Cite sources by mentioning the page titles or URLs
    5. NEVER show the raw JSON to the user - always provide a formatted response

    Example:
        duckduckgo_search("Python asyncio tutorial")
        duckduckgo_search("latest news AI", time_range="w")
    """
    try:
        from ddgs import DDGS
    except ImportError:
        try:
            from duckduckgo_search import DDGS  # Fallback to old package name
        except ImportError:
            return {
                "success": False,
                "error": "ddgs not installed. Install with: pip install ddgs",
                "query": query,
            }

    # Limit max_results to reasonable bounds
    max_results = min(max(1, max_results), 20)

    try:
        with DDGS() as ddgs:
            results = list(
                ddgs.text(
                    query,
                    region=region,
                    safesearch=safesearch,
                    timelimit=time_range if time_range else None,
                    max_results=max_results,
                )
            )

        # Format results to match expected structure
        formatted_results = [
            {
                "title": r.get("title", ""),
                "url": r.get("href", r.get("link", "")),
                "body": r.get("body", r.get("snippet", "")),
            }
            for r in results
        ]

        return {
            "success": True,
            "results": formatted_results,
            "query": query,
            "total_results": len(formatted_results),
        }

    except Exception as e:
        return {
            "success": False,
            "error": f"DuckDuckGo search error: {e!s}",
            "query": query,
        }


# Documentation site mappings for docs_search
_DOCS_SITES: dict[str, list[str]] = {
    # Python ecosystem
    "python": ["docs.python.org", "docs.python-guide.org"],
    "django": ["docs.djangoproject.com"],
    "flask": ["flask.palletsprojects.com"],
    "fastapi": ["fastapi.tiangolo.com"],
    "numpy": ["numpy.org/doc"],
    "pandas": ["pandas.pydata.org/docs"],
    "pytorch": ["pytorch.org/docs"],
    "tensorflow": ["tensorflow.org/api_docs"],
    "requests": ["requests.readthedocs.io"],
    "sqlalchemy": ["docs.sqlalchemy.org"],
    "pydantic": ["docs.pydantic.dev"],
    # JavaScript/TypeScript ecosystem
    "javascript": ["developer.mozilla.org/en-US/docs/Web/JavaScript"],
    "typescript": ["typescriptlang.org/docs"],
    "nodejs": ["nodejs.org/docs", "nodejs.org/api"],
    "node": ["nodejs.org/docs", "nodejs.org/api"],
    "react": ["react.dev", "reactjs.org/docs"],
    "vue": ["vuejs.org/guide", "vuejs.org/api"],
    "angular": ["angular.io/docs"],
    "nextjs": ["nextjs.org/docs"],
    "express": ["expressjs.com"],
    "deno": ["deno.land/manual", "docs.deno.com"],
    # Web/CSS
    "css": ["developer.mozilla.org/en-US/docs/Web/CSS"],
    "html": ["developer.mozilla.org/en-US/docs/Web/HTML"],
    "mdn": ["developer.mozilla.org"],
    "web": ["developer.mozilla.org/en-US/docs/Web"],
    # Other languages
    "rust": ["doc.rust-lang.org", "docs.rs"],
    "go": ["go.dev/doc", "pkg.go.dev"],
    "golang": ["go.dev/doc", "pkg.go.dev"],
    "java": ["docs.oracle.com/en/java"],
    "kotlin": ["kotlinlang.org/docs"],
    "swift": ["developer.apple.com/documentation/swift"],
    "ruby": ["ruby-doc.org", "docs.ruby-lang.org"],
    "php": ["php.net/docs.php", "php.net/manual"],
    "csharp": ["docs.microsoft.com/en-us/dotnet/csharp"],
    "dotnet": ["docs.microsoft.com/en-us/dotnet"],
    # Databases
    "postgresql": ["postgresql.org/docs"],
    "postgres": ["postgresql.org/docs"],
    "mysql": ["dev.mysql.com/doc"],
    "mongodb": ["docs.mongodb.com"],
    "redis": ["redis.io/docs"],
    "sqlite": ["sqlite.org/docs.html"],
    # DevOps/Cloud
    "docker": ["docs.docker.com"],
    "kubernetes": ["kubernetes.io/docs"],
    "k8s": ["kubernetes.io/docs"],
    "aws": ["docs.aws.amazon.com"],
    "azure": ["docs.microsoft.com/en-us/azure"],
    "gcp": ["cloud.google.com/docs"],
    # Tools
    "git": ["git-scm.com/doc"],
    "github": ["docs.github.com"],
    "vscode": ["code.visualstudio.com/docs"],
    "linux": ["man7.org/linux/man-pages", "linux.die.net/man"],
    # AI/ML
    "langchain": ["python.langchain.com/docs", "js.langchain.com/docs"],
    "openai": ["platform.openai.com/docs"],
    "anthropic": ["docs.anthropic.com"],
    "huggingface": ["huggingface.co/docs"],
}

# General documentation aggregators (used when no specific topic)
_GENERAL_DOCS_SITES = [
    "devdocs.io",
    "developer.mozilla.org",
    "docs.python.org",
    "nodejs.org/docs",
    "readthedocs.io",
]


def docs_search(
    query: str,
    topic: str = "",
    max_results: int = 5,
) -> dict[str, Any]:
    """Search official documentation sites only.

    A focused search tool that queries only official documentation and reference
    sites, filtering out blog posts, tutorials, and Stack Overflow answers.
    Ideal for finding authoritative API references and official guides.

    Args:
        query: The search query (e.g., "asyncio gather", "useState hook")
        topic: Optional topic/language to focus search (e.g., "python", "react", "rust")
               If not specified, searches general documentation sites.
               Available topics: python, javascript, typescript, react, vue, nodejs,
               rust, go, java, docker, kubernetes, aws, postgresql, and many more.
        max_results: Number of results to return (default: 5, max: 10)

    Returns:
        Dictionary containing:
        - success: Whether search succeeded
        - results: List of documentation results with title, url, body
        - query: The search query used (including site restrictions)
        - topic: The topic searched (if specified)
        - sites_searched: List of documentation sites that were searched

    Example:
        docs_search("async await", topic="python")
        docs_search("useEffect cleanup", topic="react")
        docs_search("SELECT JOIN", topic="postgresql")
        docs_search("container networking", topic="docker")
    """
    try:
        from ddgs import DDGS
    except ImportError:
        try:
            from duckduckgo_search import DDGS
        except ImportError:
            return {
                "success": False,
                "error": "ddgs not installed. Install with: pip install ddgs",
                "query": query,
            }

    max_results = min(max(1, max_results), 10)

    # Determine which sites to search
    topic_lower = topic.lower().strip() if topic else ""
    if topic_lower and topic_lower in _DOCS_SITES:
        sites = _DOCS_SITES[topic_lower]
    elif topic_lower:
        # Try partial match
        for key, value in _DOCS_SITES.items():
            if topic_lower in key or key in topic_lower:
                sites = value
                topic_lower = key
                break
        else:
            # Unknown topic - search general docs with topic as keyword
            sites = _GENERAL_DOCS_SITES
            query = f"{topic} {query}"
    else:
        sites = _GENERAL_DOCS_SITES

    # Build site-restricted query
    site_query = " OR ".join(f"site:{site}" for site in sites)
    full_query = f"{query} ({site_query})"

    try:
        with DDGS() as ddgs:
            results = list(
                ddgs.text(
                    full_query,
                    max_results=max_results,
                )
            )

        formatted_results = [
            {
                "title": r.get("title", ""),
                "url": r.get("href", r.get("link", "")),
                "body": r.get("body", r.get("snippet", "")),
            }
            for r in results
        ]

        return {
            "success": True,
            "results": formatted_results,
            "query": query,
            "topic": topic_lower if topic_lower else "general",
            "sites_searched": sites,
            "total_results": len(formatted_results),
        }

    except Exception as e:
        return {
            "success": False,
            "error": f"Documentation search error: {e!s}",
            "query": query,
        }


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


def package_info(
    name: str,
    registry: Literal["pypi", "npm"] = "pypi",
) -> dict[str, Any]:
    """Get package metadata from PyPI or npm registry.

    Useful for researching packages before adding them as dependencies,
    checking latest versions, or understanding package details.

    Args:
        name: Package name to look up
        registry: Package registry - "pypi" for Python packages, "npm" for Node.js

    Returns:
        Dictionary containing:
        - name: Package name
        - version: Latest version
        - description: Package description
        - author: Package author/maintainer
        - license: Package license
        - homepage: Project homepage URL
        - repository: Source code repository URL
        - dependencies: List of dependencies (npm) or requires (pypi)
        - keywords: Package keywords/tags

    Example:
        package_info("requests", registry="pypi")
        package_info("express", registry="npm")
    """
    try:
        if registry == "pypi":
            url = f"https://pypi.org/pypi/{name}/json"
            response = requests.get(url, timeout=10)

            if response.status_code == 404:
                return {"error": f"Package '{name}' not found on PyPI", "name": name}

            response.raise_for_status()
            data = response.json()
            info = data.get("info", {})

            return {
                "success": True,
                "registry": "pypi",
                "name": info.get("name"),
                "version": info.get("version"),
                "description": info.get("summary"),
                "author": info.get("author") or info.get("maintainer"),
                "author_email": info.get("author_email") or info.get("maintainer_email"),
                "license": info.get("license"),
                "homepage": info.get("home_page") or info.get("project_url"),
                "repository": next(
                    (
                        url
                        for key, url in (info.get("project_urls") or {}).items()
                        if "source" in key.lower() or "repo" in key.lower() or "github" in key.lower()
                    ),
                    None,
                ),
                "requires_python": info.get("requires_python"),
                "dependencies": info.get("requires_dist") or [],
                "keywords": info.get("keywords", "").split(",") if info.get("keywords") else [],
                "classifiers": info.get("classifiers", [])[:10],  # Limit classifiers
            }

        elif registry == "npm":
            url = f"https://registry.npmjs.org/{name}"
            response = requests.get(url, timeout=10)

            if response.status_code == 404:
                return {"error": f"Package '{name}' not found on npm", "name": name}

            response.raise_for_status()
            data = response.json()
            latest_version = data.get("dist-tags", {}).get("latest", "")
            latest_data = data.get("versions", {}).get(latest_version, {})

            # Extract repository URL
            repo = latest_data.get("repository", {})
            repo_url = repo.get("url", "") if isinstance(repo, dict) else repo
            if repo_url:
                repo_url = repo_url.replace("git+", "").replace("git://", "https://").rstrip(".git")

            return {
                "success": True,
                "registry": "npm",
                "name": data.get("name"),
                "version": latest_version,
                "description": data.get("description"),
                "author": (
                    latest_data.get("author", {}).get("name")
                    if isinstance(latest_data.get("author"), dict)
                    else latest_data.get("author")
                ),
                "license": latest_data.get("license"),
                "homepage": latest_data.get("homepage"),
                "repository": repo_url,
                "dependencies": list(latest_data.get("dependencies", {}).keys()),
                "dev_dependencies": list(latest_data.get("devDependencies", {}).keys())[:10],
                "keywords": data.get("keywords", []),
                "engines": latest_data.get("engines"),
            }

        else:
            return {"error": f"Unknown registry: {registry}. Use 'pypi' or 'npm'"}

    except requests.exceptions.Timeout:
        return {"error": f"Request timed out while fetching {registry} package info", "name": name}
    except requests.exceptions.RequestException as e:
        return {"error": f"Network error: {e!s}", "name": name}
    except Exception as e:
        return {"error": f"Failed to get package info: {e!s}", "name": name}


def convert_format(
    content: str,
    from_format: Literal["json", "yaml", "toml"],
    to_format: Literal["json", "yaml", "toml"],
    indent: int = 2,
) -> dict[str, Any]:
    """Convert between JSON, YAML, and TOML data formats.

    Useful for converting configuration files, API responses, or data
    between different serialization formats.

    Args:
        content: The content string to convert
        from_format: Source format - "json", "yaml", or "toml"
        to_format: Target format - "json", "yaml", or "toml"
        indent: Indentation level for output (default: 2)

    Returns:
        Dictionary containing:
        - success: Whether conversion succeeded
        - result: The converted content string
        - from_format: Source format used
        - to_format: Target format used

    Example:
        # Convert JSON to YAML
        convert_format('{"name": "test", "value": 123}', "json", "yaml")

        # Convert YAML to TOML
        convert_format("name: test\\nvalue: 123", "yaml", "toml")
    """
    # Parse input based on source format
    try:
        if from_format == "json":
            data = json.loads(content)

        elif from_format == "yaml":
            try:
                import yaml
            except ImportError:
                return {
                    "success": False,
                    "error": "PyYAML not installed. Install with: pip install pyyaml",
                }
            data = yaml.safe_load(content)

        elif from_format == "toml":
            try:
                import tomllib
            except ImportError:
                try:
                    import tomli as tomllib  # Fallback for Python < 3.11
                except ImportError:
                    return {
                        "success": False,
                        "error": "TOML parser not available. Requires Python 3.11+ or: pip install tomli",
                    }
            data = tomllib.loads(content)

        else:
            return {"success": False, "error": f"Unknown source format: {from_format}"}

    except json.JSONDecodeError as e:
        return {"success": False, "error": f"Invalid JSON: {e!s}"}
    except Exception as e:
        return {"success": False, "error": f"Failed to parse {from_format}: {e!s}"}

    # Convert to target format
    try:
        if to_format == "json":
            result = json.dumps(data, indent=indent, ensure_ascii=False)

        elif to_format == "yaml":
            try:
                import yaml
            except ImportError:
                return {
                    "success": False,
                    "error": "PyYAML not installed. Install with: pip install pyyaml",
                }
            result = yaml.dump(
                data,
                default_flow_style=False,
                allow_unicode=True,
                indent=indent,
                sort_keys=False,
            )

        elif to_format == "toml":
            try:
                import tomli_w
            except ImportError:
                return {
                    "success": False,
                    "error": "TOML writer not installed. Install with: pip install tomli-w",
                }
            result = tomli_w.dumps(data)

        else:
            return {"success": False, "error": f"Unknown target format: {to_format}"}

        return {
            "success": True,
            "result": result,
            "from_format": from_format,
            "to_format": to_format,
        }

    except Exception as e:
        return {"success": False, "error": f"Failed to convert to {to_format}: {e!s}"}


def format_code(
    code: str,
    language: Literal["python", "javascript", "typescript", "json", "yaml"],
    line_length: int = 88,
) -> dict[str, Any]:
    """Format code using language-appropriate formatters.

    Formats code to follow standard style conventions:
    - Python: Uses Black formatter
    - JavaScript/TypeScript: Uses basic formatting (or Prettier if available)
    - JSON: Uses standard library json formatting
    - YAML: Uses PyYAML formatting

    Args:
        code: The code string to format
        language: Programming language - "python", "javascript", "typescript", "json", "yaml"
        line_length: Maximum line length (default: 88, Black's default)

    Returns:
        Dictionary containing:
        - success: Whether formatting succeeded
        - result: The formatted code string
        - language: Language that was formatted
        - formatter: Name of formatter used
        - changed: Whether the code was modified

    Example:
        format_code("def foo( x,y ):return x+y", "python")
        format_code('{"a":1,"b":2}', "json")
    """
    original = code

    try:
        if language == "python":
            try:
                import black
            except ImportError:
                return {
                    "success": False,
                    "error": "Black not installed. Install with: pip install black",
                }
            try:
                mode = black.Mode(line_length=line_length)
                result = black.format_str(code, mode=mode)
                return {
                    "success": True,
                    "result": result,
                    "language": language,
                    "formatter": "black",
                    "changed": result != original,
                }
            except black.InvalidInput as e:
                return {"success": False, "error": f"Invalid Python syntax: {e!s}"}

        elif language == "json":
            try:
                data = json.loads(code)
                result = json.dumps(data, indent=2, ensure_ascii=False)
                return {
                    "success": True,
                    "result": result,
                    "language": language,
                    "formatter": "json.dumps",
                    "changed": result != original,
                }
            except json.JSONDecodeError as e:
                return {"success": False, "error": f"Invalid JSON: {e!s}"}

        elif language == "yaml":
            try:
                import yaml
            except ImportError:
                return {
                    "success": False,
                    "error": "PyYAML not installed. Install with: pip install pyyaml",
                }
            try:
                data = yaml.safe_load(code)
                result = yaml.dump(
                    data,
                    default_flow_style=False,
                    allow_unicode=True,
                    indent=2,
                    sort_keys=False,
                )
                return {
                    "success": True,
                    "result": result,
                    "language": language,
                    "formatter": "pyyaml",
                    "changed": result != original,
                }
            except yaml.YAMLError as e:
                return {"success": False, "error": f"Invalid YAML: {e!s}"}

        elif language in ("javascript", "typescript"):
            # Try to use Prettier via subprocess if available
            try:
                parser = "typescript" if language == "typescript" else "babel"
                result = subprocess.run(
                    ["npx", "prettier", "--parser", parser, "--print-width", str(line_length)],
                    input=code,
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=False,
                )
                if result.returncode == 0:
                    return {
                        "success": True,
                        "result": result.stdout,
                        "language": language,
                        "formatter": "prettier",
                        "changed": result.stdout != original,
                    }
                else:
                    # Prettier failed or not available, provide basic formatting
                    return {
                        "success": False,
                        "error": f"Prettier formatting failed: {result.stderr or 'Unknown error'}",
                        "hint": "Install Prettier globally: npm install -g prettier",
                    }
            except FileNotFoundError:
                return {
                    "success": False,
                    "error": "Prettier not available (npx not found)",
                    "hint": "Install Node.js and Prettier: npm install -g prettier",
                }
            except subprocess.TimeoutExpired:
                return {"success": False, "error": "Prettier timed out after 30 seconds"}

        else:
            return {"success": False, "error": f"Unsupported language: {language}"}

    except Exception as e:
        return {"success": False, "error": f"Formatting failed: {e!s}"}


# =============================================================================
# Image Generation (Replicate API)
# =============================================================================

# Available models on Replicate
REPLICATE_MODELS = {
    "flux-schnell": "black-forest-labs/flux-schnell",  # Fast, good quality
    "flux-dev": "black-forest-labs/flux-dev",  # Higher quality, slower
    "sdxl": "stability-ai/sdxl:39ed52f2a78e934b3ba6e2a89f5b1c712de7dfea535525255b1aa35c5565e08b",
    "sdxl-turbo": "stability-ai/sdxl-turbo",  # Fast SDXL
}


def generate_image(
    prompt: str,
    output_path: str | None = None,
    model: str = "flux-schnell",
    aspect_ratio: str = "1:1",
    output_format: str = "png",
    num_outputs: int = 1,
    seed: int | None = None,
) -> dict[str, Any]:
    """Generate an image using Replicate API (open source models like FLUX and SDXL).

    IMPORTANT: This tool generates images from text descriptions using open source
    models like FLUX and SDXL. Free tier includes 50 generations per month.

    Args:
        prompt: Text description of the image to generate. Be specific and detailed.
        output_path: Path to save the image. If not provided, saves to current directory
                     with timestamp (e.g., "generated_20240115_143022.png")
        model: Model to use:
            - "flux-schnell" (default) - Fast FLUX model, ~1.2 seconds
            - "flux-dev" - Higher quality FLUX, slower
            - "sdxl" - Stable Diffusion XL
            - "sdxl-turbo" - Fast SDXL variant
        aspect_ratio: Output dimensions - "1:1", "16:9", "9:16", "4:3", "3:4", "21:9"
        output_format: Image format - "png", "jpg", "webp"
        num_outputs: Number of images to generate (1-4)
        seed: Random seed for reproducibility (optional)

    Returns:
        Dictionary with:
        - success: bool - Whether generation succeeded
        - file_path: str | list[str] - Path(s) to saved image(s)
        - model: str - Model used
        - error: str - Error message (if failed)
    """
    try:
        import replicate
    except ImportError:
        return {
            "success": False,
            "error": "replicate package not installed. Run: pip install replicate",
        }

    # Get API key
    from namicode_cli.onboarding import SecretManager

    secret_manager = SecretManager()
    api_key = secret_manager.get_secret("replicate_api_key") or os.environ.get(
        "REPLICATE_API_TOKEN"
    )

    if not api_key:
        return {
            "success": False,
            "error": "REPLICATE_API_TOKEN not configured. Get your free API key at https://replicate.com/account/api-tokens",
        }

    # Validate model
    if model not in REPLICATE_MODELS:
        return {
            "success": False,
            "error": f"Invalid model '{model}'. Valid options: {list(REPLICATE_MODELS.keys())}",
        }

    # Set API token
    os.environ["REPLICATE_API_TOKEN"] = api_key

    # Build input parameters
    model_id = REPLICATE_MODELS[model]

    input_params = {
        "prompt": prompt,
        "num_outputs": min(max(num_outputs, 1), 4),
        "output_format": output_format,
    }

    # Add aspect ratio (FLUX models support this)
    if model.startswith("flux"):
        input_params["aspect_ratio"] = aspect_ratio

    if seed is not None:
        input_params["seed"] = seed

    try:
        # Run the model
        output = replicate.run(model_id, input=input_params)

        # Handle output (can be list of URLs or FileOutput objects)
        if not output:
            return {
                "success": False,
                "error": "No output received from model",
            }

        # Convert to list if single output
        outputs = (
            list(output)
            if hasattr(output, "__iter__") and not isinstance(output, str)
            else [output]
        )

        saved_paths = []
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        for i, img_output in enumerate(outputs):
            # Determine output path
            if output_path and len(outputs) == 1:
                save_path = output_path
            elif output_path:
                base, ext = os.path.splitext(output_path)
                save_path = f"{base}_{i + 1}{ext}"
            else:
                suffix = f"_{i + 1}" if len(outputs) > 1 else ""
                save_path = f"generated_{timestamp}{suffix}.{output_format}"

            # Save the image
            output_file = Path(save_path)
            output_file.parent.mkdir(parents=True, exist_ok=True)

            # Handle different output types
            if hasattr(img_output, "read"):
                # FileOutput object
                output_file.write_bytes(img_output.read())
            elif isinstance(img_output, str) and img_output.startswith("http"):
                # URL - download it
                response = requests.get(img_output, timeout=60)
                response.raise_for_status()
                output_file.write_bytes(response.content)
            else:
                # Assume bytes
                output_file.write_bytes(img_output)

            saved_paths.append(str(output_file.absolute()))

        return {
            "success": True,
            "file_path": saved_paths[0] if len(saved_paths) == 1 else saved_paths,
            "model": model,
            "prompt": prompt[:100] + "..." if len(prompt) > 100 else prompt,
        }

    except Exception as e:
        error_msg = str(e)
        if "authentication" in error_msg.lower() or "unauthorized" in error_msg.lower():
            return {
                "success": False,
                "error": "Invalid API token. Check your REPLICATE_API_TOKEN.",
            }
        return {
            "success": False,
            "error": f"Error generating image: {error_msg}",
        }

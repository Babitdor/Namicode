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

import json
import os
import subprocess
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


# =============================================================================
# Code Quality Tools (Linting, Formatting, Type Checking)
# =============================================================================


def _detect_project_type(path: str | Path) -> dict[str, Any]:
    """Detect project type and available tools.

    Args:
        path: File or directory path

    Returns:
        Dict with project_type, linter, formatter, type_checker info
    """
    path = Path(path)
    if path.is_file():
        working_dir = path.parent
        file_ext = path.suffix.lower()
    else:
        working_dir = path
        file_ext = None

    result: dict[str, Any] = {
        "project_type": "unknown",
        "linter": None,
        "formatter": None,
        "type_checker": None,
        "working_dir": str(working_dir),
    }

    # Check for Python project
    python_indicators = [
        working_dir / "pyproject.toml",
        working_dir / "setup.py",
        working_dir / "requirements.txt",
        working_dir / "ruff.toml",
        working_dir / ".ruff.toml",
    ]

    for indicator in python_indicators:
        if indicator.exists():
            result["project_type"] = "python"
            # Check for ruff
            try:
                subprocess.run(
                    ["ruff", "--version"],
                    capture_output=True,
                    timeout=5,
                    check=True,
                )
                result["linter"] = "ruff"
                result["formatter"] = "ruff"
            except (FileNotFoundError, subprocess.CalledProcessError):
                pass

            # Check for mypy
            try:
                subprocess.run(
                    ["mypy", "--version"],
                    capture_output=True,
                    timeout=5,
                    check=True,
                )
                result["type_checker"] = "mypy"
            except (FileNotFoundError, subprocess.CalledProcessError):
                # Try pyright
                try:
                    subprocess.run(
                        ["pyright", "--version"],
                        capture_output=True,
                        timeout=5,
                        check=True,
                    )
                    result["type_checker"] = "pyright"
                except (FileNotFoundError, subprocess.CalledProcessError):
                    pass
            break

    # Check for Node.js project
    package_json = working_dir / "package.json"
    if package_json.exists() and result["project_type"] == "unknown":
        result["project_type"] = "javascript"
        try:
            pkg_content = json.loads(package_json.read_text())
            dev_deps = pkg_content.get("devDependencies", {})
            deps = pkg_content.get("dependencies", {})
            all_deps = {**deps, **dev_deps}

            # Check for ESLint
            if "eslint" in all_deps:
                result["linter"] = "eslint"

            # Check for Prettier
            if "prettier" in all_deps:
                result["formatter"] = "prettier"

            # Check for TypeScript
            if "typescript" in all_deps:
                result["project_type"] = "typescript"
                result["type_checker"] = "tsc"
        except (json.JSONDecodeError, OSError):
            pass

    # Detect by file extension if still unknown
    if file_ext and result["project_type"] == "unknown":
        if file_ext in (".py", ".pyi"):
            result["project_type"] = "python"
        elif file_ext in (".js", ".jsx", ".mjs"):
            result["project_type"] = "javascript"
        elif file_ext in (".ts", ".tsx"):
            result["project_type"] = "typescript"
        elif file_ext == ".go":
            result["project_type"] = "go"
            result["linter"] = "golangci-lint"
            result["formatter"] = "gofmt"
        elif file_ext == ".rs":
            result["project_type"] = "rust"
            result["linter"] = "clippy"
            result["formatter"] = "rustfmt"

    return result


def lint_code(
    path: str = ".",
    fix: bool = False,
    show_fixes: bool = True,
) -> dict[str, Any]:
    """Lint code to find errors, style issues, and potential bugs.

    IMPORTANT: Use this tool AFTER writing or editing code to catch issues early.
    It detects undefined variables, unused imports, syntax errors, and style violations.

    Args:
        path: File or directory to lint (default: current directory)
        fix: Auto-fix issues where possible (default: False, only report)
        show_fixes: Show what fixes are available (default: True)

    Returns:
        Dictionary with:
        - success: bool - True if no errors found
        - linter: str - Tool used (ruff, eslint, etc.)
        - errors: list - List of errors found
        - warnings: list - List of warnings found
        - fixed: int - Number of issues auto-fixed (if fix=True)
        - summary: str - Human-readable summary

    Detects:
        - Undefined variables and names
        - Unused imports and variables
        - Syntax errors
        - Type annotation issues
        - Security vulnerabilities (SQL injection, etc.)
        - Style violations
    """
    path = Path(path).resolve()
    if not path.exists():
        return {
            "success": False,
            "error": f"Path not found: {path}",
        }

    project = _detect_project_type(path)

    if project["linter"] == "ruff":
        return _lint_with_ruff(path, fix, show_fixes)
    elif project["linter"] == "eslint":
        return _lint_with_eslint(path, fix)
    elif project["project_type"] == "python":
        # Try ruff anyway, it might be installed globally
        try:
            subprocess.run(["ruff", "--version"], capture_output=True, check=True, timeout=5)
            return _lint_with_ruff(path, fix, show_fixes)
        except (FileNotFoundError, subprocess.CalledProcessError):
            return {
                "success": False,
                "error": "No linter available. Install ruff: pip install ruff",
            }
    elif project["project_type"] in ("javascript", "typescript"):
        return _lint_with_eslint(path, fix)
    else:
        return {
            "success": False,
            "error": f"No linter configured for {project['project_type']} projects",
            "hint": "For Python: pip install ruff. For JS/TS: npm install eslint",
        }


def _lint_with_ruff(path: Path, fix: bool, show_fixes: bool) -> dict[str, Any]:
    """Run ruff linter on Python code."""
    cmd = ["ruff", "check", str(path), "--output-format", "json"]

    if fix:
        cmd.append("--fix")
    if show_fixes:
        cmd.append("--show-fixes")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )

        errors: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []

        if result.stdout.strip():
            try:
                issues = json.loads(result.stdout)
                for issue in issues:
                    entry = {
                        "file": issue.get("filename", ""),
                        "line": issue.get("location", {}).get("row", 0),
                        "column": issue.get("location", {}).get("column", 0),
                        "code": issue.get("code", ""),
                        "message": issue.get("message", ""),
                        "fix": issue.get("fix", {}).get("message") if issue.get("fix") else None,
                    }
                    # Treat E (error) and F (fatal/undefined) as errors
                    if entry["code"].startswith(("E", "F")):
                        errors.append(entry)
                    else:
                        warnings.append(entry)
            except json.JSONDecodeError:
                # Fallback to text output
                errors.append({"message": result.stdout})

        # Check for syntax errors in stderr
        if result.stderr and "SyntaxError" in result.stderr:
            errors.append({
                "file": str(path),
                "code": "E999",
                "message": result.stderr.strip(),
            })

        total_issues = len(errors) + len(warnings)
        summary_parts = []
        if errors:
            summary_parts.append(f"{len(errors)} error(s)")
        if warnings:
            summary_parts.append(f"{len(warnings)} warning(s)")

        return {
            "success": len(errors) == 0,
            "linter": "ruff",
            "errors": errors,
            "warnings": warnings,
            "total_issues": total_issues,
            "summary": ", ".join(summary_parts) if summary_parts else "No issues found",
            "exit_code": result.returncode,
        }

    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Linting timed out after 120 seconds"}
    except FileNotFoundError:
        return {"success": False, "error": "ruff not found. Install with: pip install ruff"}
    except Exception as e:
        return {"success": False, "error": f"Linting failed: {e!s}"}


def _lint_with_eslint(path: Path, fix: bool) -> dict[str, Any]:
    """Run ESLint on JavaScript/TypeScript code."""
    cmd = ["npx", "eslint", str(path), "--format", "json"]

    if fix:
        cmd.append("--fix")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )

        errors: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []

        if result.stdout.strip():
            try:
                files = json.loads(result.stdout)
                for file_result in files:
                    for msg in file_result.get("messages", []):
                        entry = {
                            "file": file_result.get("filePath", ""),
                            "line": msg.get("line", 0),
                            "column": msg.get("column", 0),
                            "code": msg.get("ruleId", ""),
                            "message": msg.get("message", ""),
                        }
                        if msg.get("severity", 0) == 2:  # noqa: PLR2004
                            errors.append(entry)
                        else:
                            warnings.append(entry)
            except json.JSONDecodeError:
                errors.append({"message": result.stdout})

        return {
            "success": len(errors) == 0,
            "linter": "eslint",
            "errors": errors,
            "warnings": warnings,
            "total_issues": len(errors) + len(warnings),
            "summary": f"{len(errors)} error(s), {len(warnings)} warning(s)"
            if errors or warnings
            else "No issues found",
        }

    except subprocess.TimeoutExpired:
        return {"success": False, "error": "ESLint timed out after 120 seconds"}
    except FileNotFoundError:
        return {"success": False, "error": "ESLint not found. Install with: npm install eslint"}
    except Exception as e:
        return {"success": False, "error": f"Linting failed: {e!s}"}


def format_code_file(
    path: str,
    check_only: bool = False,
) -> dict[str, Any]:
    """Format a code file using the project's configured formatter.

    IMPORTANT: Use this tool to ensure consistent code style. Respects project
    configuration (pyproject.toml, .prettierrc, etc.).

    Args:
        path: File or directory to format
        check_only: If True, only check if formatting needed (don't modify files)

    Returns:
        Dictionary with:
        - success: bool - True if formatted successfully (or no changes needed)
        - formatter: str - Tool used (ruff, prettier, gofmt, etc.)
        - files_changed: list - Files that were/would be changed
        - already_formatted: bool - True if no changes needed

    Supported formatters:
        - Python: ruff format (or black fallback)
        - JavaScript/TypeScript: prettier
        - Go: gofmt
        - Rust: rustfmt
    """
    path = Path(path).resolve()
    if not path.exists():
        return {
            "success": False,
            "error": f"Path not found: {path}",
        }

    project = _detect_project_type(path)

    if project["formatter"] == "ruff":
        return _format_with_ruff(path, check_only)
    elif project["formatter"] == "prettier":
        return _format_with_prettier(path, check_only)
    elif project["formatter"] == "gofmt":
        return _format_with_gofmt(path, check_only)
    elif project["formatter"] == "rustfmt":
        return _format_with_rustfmt(path, check_only)
    elif project["project_type"] == "python":
        # Try ruff format anyway
        try:
            subprocess.run(["ruff", "--version"], capture_output=True, check=True, timeout=5)
            return _format_with_ruff(path, check_only)
        except (FileNotFoundError, subprocess.CalledProcessError):
            return {
                "success": False,
                "error": "No formatter available. Install ruff: pip install ruff",
            }
    elif project["project_type"] in ("javascript", "typescript"):
        return _format_with_prettier(path, check_only)
    else:
        return {
            "success": False,
            "error": f"No formatter configured for {project['project_type']} projects",
        }


def _format_with_ruff(path: Path, check_only: bool) -> dict[str, Any]:
    """Format Python code with ruff."""
    cmd = ["ruff", "format", str(path)]

    if check_only:
        cmd.append("--check")
        cmd.append("--diff")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )

        # Parse output for changed files
        files_changed: list[str] = []
        if check_only and result.stdout:
            # ruff format --check --diff shows file paths
            for line in result.stdout.split("\n"):
                if line.startswith("---") or line.startswith("+++"):
                    # Extract filename from diff header
                    parts = line.split()
                    if len(parts) >= 2:
                        fname = parts[1].lstrip("a/").lstrip("b/")
                        if fname not in files_changed:
                            files_changed.append(fname)

        already_formatted = result.returncode == 0 and not files_changed

        return {
            "success": True,
            "formatter": "ruff",
            "files_changed": files_changed,
            "already_formatted": already_formatted,
            "diff": result.stdout if check_only and result.stdout else None,
            "message": "Already formatted" if already_formatted else (
                f"{len(files_changed)} file(s) would be changed" if check_only
                else "Formatted successfully"
            ),
        }

    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Formatting timed out after 120 seconds"}
    except FileNotFoundError:
        return {"success": False, "error": "ruff not found. Install with: pip install ruff"}
    except Exception as e:
        return {"success": False, "error": f"Formatting failed: {e!s}"}


def _format_with_prettier(path: Path, check_only: bool) -> dict[str, Any]:
    """Format JS/TS code with Prettier."""
    cmd = ["npx", "prettier", str(path)]

    if check_only:
        cmd.append("--check")
    else:
        cmd.append("--write")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )

        # Parse output for changed files
        files_changed: list[str] = []
        for line in result.stdout.split("\n"):
            if line.strip() and Path(line.strip()).exists():
                files_changed.append(line.strip())

        already_formatted = result.returncode == 0 and "All matched files" not in result.stdout

        return {
            "success": result.returncode == 0 or check_only,
            "formatter": "prettier",
            "files_changed": files_changed,
            "already_formatted": already_formatted,
            "message": result.stdout or result.stderr,
        }

    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Formatting timed out after 120 seconds"}
    except FileNotFoundError:
        return {"success": False, "error": "Prettier not found. Install with: npm install prettier"}
    except Exception as e:
        return {"success": False, "error": f"Formatting failed: {e!s}"}


def _format_with_gofmt(path: Path, check_only: bool) -> dict[str, Any]:
    """Format Go code with gofmt."""
    cmd = ["gofmt"]
    if not check_only:
        cmd.append("-w")
    cmd.append(str(path))

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )

        return {
            "success": result.returncode == 0,
            "formatter": "gofmt",
            "output": result.stdout or result.stderr,
            "already_formatted": not result.stdout,
        }

    except FileNotFoundError:
        return {"success": False, "error": "gofmt not found. Install Go."}
    except Exception as e:
        return {"success": False, "error": f"Formatting failed: {e!s}"}


def _format_with_rustfmt(path: Path, check_only: bool) -> dict[str, Any]:
    """Format Rust code with rustfmt."""
    cmd = ["rustfmt"]
    if check_only:
        cmd.append("--check")
    cmd.append(str(path))

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )

        return {
            "success": result.returncode == 0,
            "formatter": "rustfmt",
            "output": result.stdout or result.stderr,
            "already_formatted": result.returncode == 0,
        }

    except FileNotFoundError:
        return {"success": False, "error": "rustfmt not found. Install with: rustup component add rustfmt"}
    except Exception as e:
        return {"success": False, "error": f"Formatting failed: {e!s}"}


def check_types(
    path: str = ".",
    strict: bool = False,
) -> dict[str, Any]:
    """Run type checking to detect undefined names, type errors, and missing imports.

    IMPORTANT: Use this tool to catch undefined variables, incorrect function calls,
    and type mismatches that linting alone cannot detect.

    Args:
        path: File or directory to check (default: current directory)
        strict: Enable strict type checking mode (more thorough but noisier)

    Returns:
        Dictionary with:
        - success: bool - True if no type errors found
        - checker: str - Tool used (mypy, pyright, tsc)
        - errors: list - List of type errors found
        - summary: str - Human-readable summary

    Detects:
        - Undefined names and variables
        - Missing imports
        - Type mismatches (wrong argument types, return types)
        - Missing function arguments
        - Invalid attribute access
        - Incompatible types in assignments
    """
    path = Path(path).resolve()
    if not path.exists():
        return {
            "success": False,
            "error": f"Path not found: {path}",
        }

    project = _detect_project_type(path)

    if project["type_checker"] == "mypy":
        return _check_types_mypy(path, strict)
    elif project["type_checker"] == "pyright":
        return _check_types_pyright(path, strict)
    elif project["type_checker"] == "tsc":
        return _check_types_tsc(path)
    elif project["project_type"] == "python":
        # Try mypy, then pyright
        try:
            subprocess.run(["mypy", "--version"], capture_output=True, check=True, timeout=5)
            return _check_types_mypy(path, strict)
        except (FileNotFoundError, subprocess.CalledProcessError):
            try:
                subprocess.run(["pyright", "--version"], capture_output=True, check=True, timeout=5)
                return _check_types_pyright(path, strict)
            except (FileNotFoundError, subprocess.CalledProcessError):
                return {
                    "success": False,
                    "error": "No type checker available. Install mypy: pip install mypy",
                }
    elif project["project_type"] == "typescript":
        return _check_types_tsc(path)
    else:
        return {
            "success": False,
            "error": f"No type checker configured for {project['project_type']} projects",
        }


def _check_types_mypy(path: Path, strict: bool) -> dict[str, Any]:
    """Run mypy type checker."""
    cmd = ["mypy", str(path), "--no-color-output", "--show-column-numbers"]

    if strict:
        cmd.append("--strict")

    # Add common useful flags
    cmd.extend([
        "--show-error-codes",
        "--no-error-summary",  # We'll generate our own summary
    ])

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )

        errors: list[dict[str, Any]] = []

        # Parse mypy output: file:line:col: error: message [code]
        for line in result.stdout.split("\n"):
            if ": error:" in line or ": note:" in line:
                parts = line.split(":", 3)
                if len(parts) >= 4:
                    error_part = parts[3].strip()
                    code_match = None
                    message = error_part

                    # Extract error code if present [code]
                    import re
                    code_match = re.search(r"\[([a-z-]+)\]$", error_part)
                    if code_match:
                        code = code_match.group(1)
                        message = error_part[: code_match.start()].strip()
                    else:
                        code = "error" if ": error:" in line else "note"

                    errors.append({
                        "file": parts[0],
                        "line": int(parts[1]) if parts[1].isdigit() else 0,
                        "column": int(parts[2]) if parts[2].isdigit() else 0,
                        "code": code,
                        "message": message.replace("error: ", "").replace("note: ", ""),
                    })

        return {
            "success": len(errors) == 0,
            "checker": "mypy",
            "errors": errors,
            "total_errors": len(errors),
            "summary": f"{len(errors)} type error(s) found" if errors else "No type errors found",
            "raw_output": result.stdout if errors else None,
        }

    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Type checking timed out after 5 minutes"}
    except FileNotFoundError:
        return {"success": False, "error": "mypy not found. Install with: pip install mypy"}
    except Exception as e:
        return {"success": False, "error": f"Type checking failed: {e!s}"}


def _check_types_pyright(path: Path, strict: bool) -> dict[str, Any]:
    """Run pyright type checker."""
    cmd = ["pyright", str(path), "--outputjson"]

    if strict:
        cmd.append("--strict")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )

        errors: list[dict[str, Any]] = []

        if result.stdout.strip():
            try:
                data = json.loads(result.stdout)
                for diag in data.get("generalDiagnostics", []):
                    errors.append({
                        "file": diag.get("file", ""),
                        "line": diag.get("range", {}).get("start", {}).get("line", 0),
                        "column": diag.get("range", {}).get("start", {}).get("character", 0),
                        "code": diag.get("rule", "error"),
                        "message": diag.get("message", ""),
                        "severity": diag.get("severity", "error"),
                    })
            except json.JSONDecodeError:
                errors.append({"message": result.stdout})

        return {
            "success": len(errors) == 0,
            "checker": "pyright",
            "errors": errors,
            "total_errors": len(errors),
            "summary": f"{len(errors)} type error(s) found" if errors else "No type errors found",
        }

    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Type checking timed out after 5 minutes"}
    except FileNotFoundError:
        return {"success": False, "error": "pyright not found. Install with: pip install pyright"}
    except Exception as e:
        return {"success": False, "error": f"Type checking failed: {e!s}"}


def _check_types_tsc(path: Path) -> dict[str, Any]:
    """Run TypeScript compiler for type checking."""
    cmd = ["npx", "tsc", "--noEmit", "--pretty", "false"]

    # If path is a specific file, check just that file
    if path.is_file():
        cmd.append(str(path))

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
            cwd=str(path.parent if path.is_file() else path),
            check=False,
        )

        errors: list[dict[str, Any]] = []

        # Parse tsc output: file(line,col): error TSxxxx: message
        import re
        for line in result.stdout.split("\n"):
            match = re.match(r"(.+)\((\d+),(\d+)\):\s+(error|warning)\s+(TS\d+):\s+(.+)", line)
            if match:
                errors.append({
                    "file": match.group(1),
                    "line": int(match.group(2)),
                    "column": int(match.group(3)),
                    "severity": match.group(4),
                    "code": match.group(5),
                    "message": match.group(6),
                })

        return {
            "success": len(errors) == 0,
            "checker": "tsc",
            "errors": errors,
            "total_errors": len(errors),
            "summary": f"{len(errors)} type error(s) found" if errors else "No type errors found",
        }

    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Type checking timed out after 5 minutes"}
    except FileNotFoundError:
        return {"success": False, "error": "TypeScript not found. Install with: npm install typescript"}
    except Exception as e:
        return {"success": False, "error": f"Type checking failed: {e!s}"}

"""Custom tools for the CLI agent.

This module provides additional tools beyond the filesystem and shell tools,
enabling the agent to interact with external services and the web:

Key Tools:
- http_request(): Make HTTP requests to APIs and web services
- fetch_url(): Fetch web pages and convert HTML to markdown
- web_search(): Search the web using Tavily API (requires TAVILY_API_KEY)
- duckduckgo_search(): Search the web (no API key required)
- docs_search(): Search official documentation sites only
- execute_in_e2b(): Execute code in isolated E2B cloud sandboxes

LSP Tools (Code Intelligence):
- lsp_goto_definition(): Navigate to symbol definitions
- lsp_find_references(): Find all references to a symbol
- lsp_hover(): Get documentation and type info for symbols
- lsp_completions(): Get auto-complete suggestions
- lsp_document_symbols(): List all symbols in a file
- lsp_workspace_symbols(): Search symbols across workspace
- lsp_diagnostics(): Get syntax errors and linting issues
- lsp_rename(): Rename a symbol across files
- lsp_signature_help(): Get function/method signatures
- lsp_type_definition(): Navigate to type definitions
- lsp_implementation(): Find implementations of interfaces

These tools are registered with the agent and allow it to:
- Fetch data from REST APIs
- Scrape web content and convert to readable markdown
- Search for current information online
- Handle various HTTP methods (GET, POST, PUT, DELETE, etc.)
- Run Python, Node.js, and Bash code securely in isolated environments
- Navigate and understand codebases with LSP-like features

Dependencies:
- requests: HTTP client library
- markdownify: HTML to markdown conversion
- tavily: Tavily search client (optional)
- ddgs: DuckDuckGo search client (no API key needed)
- e2b-code-interpreter: E2B sandbox execution
- jedi: Python static analysis for LSP tools

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

from novacode_cli.config.config import settings

# Initialize Tavily client if API key is available
tavily_client = TavilyClient(api_key=settings.tavily_api_key) if settings.has_tavily else None


# Session for http_request (separate from fetch_url to avoid conflicts)
_http_request_session: requests.Session | None = None


def _get_http_session() -> requests.Session:
    """Get or create a reusable requests session for http_request with connection pooling."""
    global _http_request_session
    if _http_request_session is None:
        _http_request_session = requests.Session()
        # Configure retry strategy for transient failures
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry

        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        _http_request_session.mount("http://", adapter)
        _http_request_session.mount("https://", adapter)
    return _http_request_session


def http_request(
    url: str,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    data: str | dict | None = None,
    params: dict[str, str] | None = None,
    timeout: int = 30,
    max_retries: int = 3,
    follow_redirects: bool = True,
    verify_ssl: bool = True,
    auth: tuple[str, str] | None = None,
    cookies: dict[str, str] | None = None,
    max_content_size: int = 10 * 1024 * 1024,  # 10MB default
    user_agent: str = "browser",
    stream: bool = False,
) -> dict[str, Any]:
    """Make HTTP requests to APIs and web services with enhanced reliability.

    Enhanced version with retry logic, connection pooling, and better error handling.

    Args:
        url: Target URL
        method: HTTP method (GET, POST, PUT, DELETE, PATCH, etc.)
        headers: HTTP headers to include
        data: Request body data (string or dict). Dict is sent as JSON.
        params: URL query parameters
        timeout: Request timeout in seconds (default: 30)
        max_retries: Maximum number of retry attempts (default: 3)
        follow_redirects: Whether to follow HTTP redirects (default: True)
        verify_ssl: Whether to verify SSL certificates (default: True)
        auth: Tuple of (username, password) for basic authentication
        cookies: Dictionary of cookies to send
        max_content_size: Maximum response content size in bytes (default: 10MB)
        user_agent: User agent type - "browser" for real browser UA, "bot" for bot UA,
                   or provide custom string (default: "browser")
        stream: Whether to stream the response (useful for large files)

    Returns:
        Dictionary with response data including:
        - success: Whether the request succeeded (status < 400)
        - status_code: HTTP status code
        - headers: Response headers
        - content: Response body (parsed JSON if possible, otherwise text)
        - url: Final URL after redirects
        - attempts: Number of attempts made
        - elapsed_time: Request duration in seconds

    Example:
        # Simple GET request
        http_request("https://api.example.com/data")

        # POST with JSON body
        http_request(
            "https://api.example.com/users",
            method="POST",
            data={"name": "John", "email": "john@example.com"}
        )

        # With authentication
        http_request(
            "https://api.example.com/protected",
            auth=("username", "password")
        )
    """
    import random
    import time

    start_time = time.time()

    # Build headers
    request_headers = {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
    }

    # Set User-Agent
    if user_agent == "browser":
        request_headers["User-Agent"] = random.choice(_BROWSER_USER_AGENTS)
    elif user_agent == "bot":
        request_headers["User-Agent"] = "Mozilla/5.0 (compatible; DeepAgents/1.0)"
    else:
        request_headers["User-Agent"] = user_agent

    # Merge custom headers
    if headers:
        request_headers.update(headers)

    # Get session with connection pooling
    session = _get_http_session()

    last_error: Exception | None = None
    attempts = 0

    for attempt in range(max_retries):
        attempts = attempt + 1

        try:
            kwargs: dict[str, Any] = {
                "url": url,
                "method": method.upper(),
                "headers": request_headers,
                "timeout": (timeout // 2, timeout),  # (connect timeout, read timeout)
                "allow_redirects": follow_redirects,
                "verify": verify_ssl,
                "stream": stream or (max_content_size > 0),  # Stream if size limit set
            }

            if params:
                kwargs["params"] = params

            if data:
                if isinstance(data, dict):
                    kwargs["json"] = data
                    # Set Content-Type if not already set
                    if "Content-Type" not in request_headers:
                        request_headers["Content-Type"] = "application/json"
                else:
                    kwargs["data"] = data

            if auth:
                kwargs["auth"] = auth

            if cookies:
                kwargs["cookies"] = cookies

            response = session.request(**kwargs)

            # Check for HTTP errors (4xx, 5xx)
            if response.status_code >= 400:
                status_code = response.status_code
                # Retry on server errors (5xx) and rate limiting (429)
                if (status_code >= 500 or status_code == 429) and attempt < max_retries - 1:
                    last_error = requests.exceptions.HTTPError(f"HTTP {status_code}")
                    time.sleep(2 ** (attempt + 1))  # Exponential backoff
                    continue

                # Try to get error details from response
                try:
                    error_content = response.json()
                    error_msg = error_content.get("message", error_content.get("error", str(error_content)))
                except Exception:
                    error_msg = response.text[:500] if response.text else response.reason

                elapsed = time.time() - start_time
                return {
                    "success": False,
                    "status_code": status_code,
                    "headers": dict(response.headers),
                    "content": error_msg,
                    "url": str(response.url),
                    "attempts": attempts,
                    "elapsed_time": round(elapsed, 3),
                }

            # Handle streaming or size-limited responses
            if stream or max_content_size > 0:
                content_length = response.headers.get("Content-Length")
                if content_length and int(content_length) > max_content_size:
                    elapsed = time.time() - start_time
                    return {
                        "success": False,
                        "status_code": response.status_code,
                        "headers": dict(response.headers),
                        "content": f"Response too large: {int(content_length) / 1024 / 1024:.2f}MB exceeds {max_content_size / 1024 / 1024:.2f}MB limit",
                        "url": str(response.url),
                        "attempts": attempts,
                        "elapsed_time": round(elapsed, 3),
                    }

                # Download with size check
                chunks = []
                total_size = 0
                for chunk in response.iter_content(chunk_size=8192):
                    total_size += len(chunk)
                    if total_size > max_content_size:
                        elapsed = time.time() - start_time
                        return {
                            "success": False,
                            "status_code": response.status_code,
                            "headers": dict(response.headers),
                            "content": f"Response exceeded {max_content_size / 1024 / 1024:.2f}MB limit during download",
                            "url": str(response.url),
                            "attempts": attempts,
                            "elapsed_time": round(elapsed, 3),
                        }
                    chunks.append(chunk)

                raw_content = b"".join(chunks)
                # Try to decode as text
                try:
                    text_content = raw_content.decode("utf-8")
                except UnicodeDecodeError:
                    # Return base64 for binary content
                    import base64

                    text_content = base64.b64encode(raw_content).decode("ascii")

                # Try to parse as JSON
                try:
                    content = response.json()
                except Exception:
                    content = text_content
            else:
                # Non-streaming response
                try:
                    content = response.json()
                except Exception:
                    content = response.text

            elapsed = time.time() - start_time
            return {
                "success": True,
                "status_code": response.status_code,
                "headers": dict(response.headers),
                "content": content,
                "url": str(response.url),
                "attempts": attempts,
                "elapsed_time": round(elapsed, 3),
                "content_type": response.headers.get("Content-Type", ""),
            }

        except requests.exceptions.Timeout as e:
            last_error = e
            if attempt < max_retries - 1:
                time.sleep(2 ** (attempt + 1))
                continue

        except requests.exceptions.SSLError as e:
            elapsed = time.time() - start_time
            return {
                "success": False,
                "status_code": 0,
                "headers": {},
                "content": f"SSL certificate verification failed: {e!s}. Try setting verify_ssl=False if you trust this server.",
                "url": url,
                "attempts": attempts,
                "elapsed_time": round(elapsed, 3),
            }

        except requests.exceptions.ConnectionError as e:
            last_error = e
            if attempt < max_retries - 1:
                time.sleep(2 ** (attempt + 1))
                continue

        except requests.exceptions.RequestException as e:
            last_error = e
            if attempt < max_retries - 1:
                time.sleep(2 ** (attempt + 1))
                continue

        except Exception as e:
            last_error = e
            if attempt < max_retries - 1:
                time.sleep(2 ** (attempt + 1))
                continue

    # All retries exhausted
    elapsed = time.time() - start_time
    return {
        "success": False,
        "status_code": 0,
        "headers": {},
        "content": f"Request failed after {attempts} attempts: {last_error!s}",
        "url": url,
        "attempts": attempts,
        "elapsed_time": round(elapsed, 3),
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
                "error": "ddgs not installed. Install with: uv add ddgs",
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


def image_search(
    query: str,
    download_path: str | None = None,
    max_results: int = 5,
    size: str | None = None,
    image_type: str | None = None,
    layout: str | None = None,
    license: str | None = None,
) -> dict[str, Any]:
    """Search for images by description and optionally download them.

    Useful for finding stock photos, icons, and illustrations for web projects.

    Args:
        query: Description of the image to search for (e.g. "modern office workspace")
        download_path: If provided, download the first result to this file path.
            Supports .jpg, .png, .webp extensions.
        max_results: Number of search results to return (1-20, default 5)
        size: Filter by size - "Small", "Medium", "Large", or "Wallpaper"
        image_type: Filter by type - "photo", "clipart", "gif", "transparent", "line"
        layout: Filter by layout - "Square", "Tall", "Wide"
        license: Filter by license - "any", "Public", "Share", "Modify", "ModifyCommercially"

    Returns:
        Dictionary with:
        - success: Whether search succeeded
        - results: List of image results with title, image_url, thumbnail_url, source, width, height
        - downloaded_to: File path if download_path was provided and download succeeded

    Example:
        image_search("modern office workspace photo")
        image_search("transparent gear icon", image_type="transparent", download_path="./icons/gear.png")
    """
    try:
        from ddgs import DDGS
    except ImportError:
        try:
            from duckduckgo_search import DDGS
        except ImportError:
            return {
                "success": False,
                "error": "ddgs not installed. Install with: uv add ddgs",
                "query": query,
            }

    max_results = max(1, min(20, max_results))

    try:
        kwargs: dict[str, Any] = {}
        if size:
            kwargs["size"] = size
        if image_type:
            kwargs["type_image"] = image_type
        if layout:
            kwargs["layout"] = layout
        if license and license != "any":
            kwargs["license_image"] = license

        with DDGS() as ddgs:
            raw = list(ddgs.images(query, max_results=max_results, **kwargs))

        results = [
            {
                "title": r.get("title", ""),
                "image_url": r.get("image", ""),
                "thumbnail_url": r.get("thumbnail", ""),
                "source": r.get("source", ""),
                "width": r.get("width", 0),
                "height": r.get("height", 0),
            }
            for r in raw
        ]

        output: dict[str, Any] = {
            "success": True,
            "results": results,
            "query": query,
            "total_results": len(results),
        }

        if download_path and results:
            import requests

            img_url = results[0]["image_url"]
            resp = requests.get(
                img_url,
                timeout=30,
                headers={"User-Agent": "Mozilla/5.0 (compatible; DeepAgents/1.0)"},
            )
            resp.raise_for_status()
            Path(download_path).parent.mkdir(parents=True, exist_ok=True)
            Path(download_path).write_bytes(resp.content)
            output["downloaded_to"] = str(Path(download_path).resolve())
            output["downloaded_url"] = img_url
            output["file_size_bytes"] = len(resp.content)

        return output

    except Exception as e:
        return {
            "success": False,
            "error": f"Image search error: {e!s}",
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
                "error": "ddgs not installed. Install with: uv add ddgs",
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


# Session-level connection pool for better performance
_fetch_url_session: requests.Session | None = None


def _get_fetch_session() -> requests.Session:
    """Get or create a reusable requests session with connection pooling."""
    global _fetch_url_session
    if _fetch_url_session is None:
        _fetch_url_session = requests.Session()
        # Configure retry strategy for transient failures
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry

        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "HEAD"],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        _fetch_url_session.mount("http://", adapter)
        _fetch_url_session.mount("https://", adapter)
    return _fetch_url_session


# Common browser user agents for rotation
_BROWSER_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
]


def summarize_web_content(
    content: str,
    max_length: int = 8000,
    focus_query: str | None = None,
) -> dict[str, Any]:
    """Summarize large web content for efficient token usage.

    When fetched content exceeds token limits, use this tool to extract
    the most relevant information while preserving key details.

    Args:
        content: The markdown content to summarize
        max_length: Maximum length of summarized content (default: 8000 chars)
        focus_query: Optional query to focus summarization on relevant sections

    Returns:
        Dictionary containing:
        - success: Whether summarization succeeded
        - summarized_content: The summarized content
        - original_length: Length of original content
        - summarized_length: Length of summarized content
        - compression_ratio: How much the content was compressed

    Example:
        result = fetch_url("https://example.com/long-article")
        if result["success"] and len(result["markdown_content"]) > 10000:
            summary = summarize_web_content(
                result["markdown_content"],
                focus_query="API authentication"
            )
    """
    if not content:
        return {
            "success": False,
            "error": "No content to summarize",
            "original_length": 0,
            "summarized_length": 0,
        }

    original_length = len(content)

    # If content is already small enough, return as-is
    if original_length <= max_length:
        return {
            "success": True,
            "summarized_content": content,
            "original_length": original_length,
            "summarized_length": original_length,
            "compression_ratio": 1.0,
        }

    # Extract key sections
    lines = content.split("\n")
    sections: list[dict[str, str]] = []
    current_section: dict[str, str] = {"title": "Intro", "content": ""}
    code_blocks: list[str] = []

    for line in lines:
        # Track code blocks separately
        if line.strip().startswith("```"):
            if current_section["content"].strip():
                sections.append(current_section.copy())
                current_section = {"title": "", "content": ""}
            # Extract code block
            code_content = []
            continue

        # Track headers as section boundaries
        if line.startswith("#"):
            if current_section["content"].strip():
                sections.append(current_section.copy())
            current_section = {"title": line.strip("# ").strip(), "content": ""}
            continue

        current_section["content"] += line + "\n"

    # Add final section
    if current_section["content"].strip():
        sections.append(current_section)

    # Score sections by relevance
    def score_section(section: dict[str, str]) -> float:
        score = 0.0
        text = section["title"] + " " + section["content"]

        # Boost for headers/keywords
        if section["title"]:
            score += 10.0

        # Boost for focus query matches
        if focus_query:
            query_terms = focus_query.lower().split()
            for term in query_terms:
                score += text.lower().count(term) * 2.0

        # Boost for important patterns
        important_patterns = [
            "api",
            "example",
            "usage",
            "install",
            "config",
            "important",
            "note",
            "warning",
            "parameter",
            "return",
            "argument",
        ]
        for pattern in important_patterns:
            score += text.lower().count(pattern) * 0.5

        return score

    # Sort sections by score
    scored_sections = [(score_section(s), s) for s in sections]
    scored_sections.sort(key=lambda x: x[0], reverse=True)

    # Build summarized content
    summarized_parts: list[str] = []
    current_length = 0

    # Always include first section (intro)
    if sections:
        intro = sections[0]
        summarized_parts.append(f"## {intro['title']}\n{intro['content']}")
        current_length += len(intro["content"])

    # Add highest-scored sections until we hit max_length
    for score, section in scored_sections[1:]:
        section_text = f"## {section['title']}\n{section['content']}"
        if current_length + len(section_text) < max_length:
            summarized_parts.append(section_text)
            current_length += len(section_text)
        else:
            # Truncate section if needed
            remaining = max_length - current_length - 100
            if remaining > 200:
                truncated = section["content"][:remaining] + "\n...[truncated]"
                summarized_parts.append(f"## {section['title']}\n{truncated}")
            break

    summarized_content = "\n\n".join(summarized_parts)
    summarized_length = len(summarized_content)

    return {
        "success": True,
        "summarized_content": summarized_content,
        "original_length": original_length,
        "summarized_length": summarized_length,
        "compression_ratio": round(summarized_length / original_length, 2),
        "sections_analyzed": len(sections),
        "sections_included": len(summarized_parts),
    }


def _convert_github_to_raw_url(url: str) -> tuple[str, bool]:
    """Convert GitHub page URLs to raw content URLs for better fetching.

    Handles:
    - Blob URLs: https://github.com/owner/repo/blob/branch/path -> raw.githubusercontent.com
    - Tree URLs: https://github.com/owner/repo/tree/branch/path -> raw.githubusercontent.com
    - Raw URLs: Already raw, return as-is

    Args:
        url: The GitHub URL to convert

    Returns:
        Tuple of (converted_url, was_converted)
    """
    import re

    # Pattern: https://github.com/owner/repo/blob/branch/path
    blob_match = re.match(
        r"https://github\.com/([^/]+)/([^/]+)/blob/([^/]+)/(.+)",
        url
    )
    if blob_match:
        owner, repo, branch, path = blob_match.groups()
        raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{path}"
        return raw_url, True

    # Pattern: https://github.com/owner/repo/tree/branch/path (for directory listings)
    tree_match = re.match(
        r"https://github\.com/([^/]+)/([^/]+)/tree/([^/]+)/(.+)",
        url
    )
    if tree_match:
        owner, repo, branch, path = tree_match.groups()
        # For tree URLs, we can't get raw content, but we can try the API
        # Return the API URL for directory contents
        api_url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}?ref={branch}"
        return api_url, True

    # Pattern: https://github.com/owner/repo (repo root)
    repo_match = re.match(
        r"https://github\.com/([^/]+)/([^/]+)/?$",
        url
    )
    if repo_match:
        owner, repo = repo_match.groups()
        # Return API URL for repo info
        api_url = f"https://api.github.com/repos/{owner}/{repo}"
        return api_url, True

    # Already a raw URL or not a GitHub URL
    return url, False


def fetch_url(
    url: str,
    timeout: int = 30,
    max_retries: int = 3,
    headers: dict[str, str] | None = None,
    follow_redirects: bool = True,
    max_content_size: int = 10 * 1024 * 1024,  # 10MB default
    verify_ssl: bool = True,
    user_agent: str = "browser",
    summarize: bool = False,
    summarize_max_length: int = 8000,
    focus_query: str | None = None,
) -> dict[str, Any]:
    """Fetch content from a URL and convert HTML to markdown format.

    Enhanced version with retry logic, connection pooling, and better error handling.

    This tool fetches web page content and converts it to clean markdown text,
    making it easy to read and process HTML content. After receiving the markdown,
    you MUST synthesize the information into a natural, helpful response for the user.

    GitHub URL Support:
    - Automatically converts GitHub blob URLs to raw content URLs
    - Example: https://github.com/owner/repo/blob/main/file.py
      -> https://raw.githubusercontent.com/owner/repo/main/file.py
    - Handles tree URLs via GitHub API for directory listings
    - Handles repo root URLs via GitHub API for repository info

    Args:
        url: The URL to fetch (must be a valid HTTP/HTTPS URL)
            - Supports GitHub URLs (blob, tree, repo root)
            - Supports raw.githubusercontent.com URLs directly
        timeout: Request timeout in seconds (default: 30)
        max_retries: Maximum number of retry attempts (default: 3)
        headers: Additional HTTP headers to include
        follow_redirects: Whether to follow HTTP redirects (default: True)
        max_content_size: Maximum content size in bytes (default: 10MB)
        verify_ssl: Whether to verify SSL certificates (default: True)
        user_agent: User agent type - "browser" for real browser UA, "bot" for bot UA,
                   or provide custom string (default: "browser")
        summarize: Whether to summarize large content (default: False)
        summarize_max_length: Max length for summarized content (default: 8000 chars)
        focus_query: Optional query to focus summarization on relevant sections

    Returns:
        Dictionary containing:
        - success: Whether the request succeeded
        - url: The final URL after redirects
        - original_url: The original URL (before GitHub conversion)
        - github_url_converted: Whether the URL was converted from GitHub format
        - markdown_content: The page content converted to markdown
        - status_code: HTTP status code
        - content_length: Length of the markdown content in characters
        - attempts: Number of attempts made (useful for debugging retries)
        - final_url: The final URL after any redirects
        - summarized: Whether content was summarized (if summarize=True)

    IMPORTANT: After using this tool:
    1. Read through the markdown content
    2. Extract relevant information that answers the user's question
    3. Synthesize this into a clear, natural language response
    4. NEVER show the raw markdown to the user unless specifically requested
    """
    import random
    import time

    # Convert GitHub URLs to raw content URLs for better fetching
    original_url = url
    url, was_github_url = _convert_github_to_raw_url(url)
    is_github_api_url = url.startswith("https://api.github.com")

    # Build headers
    request_headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    }

    # For GitHub API URLs, use JSON Accept header
    if is_github_api_url:
        request_headers["Accept"] = "application/vnd.github.v3+json"

    # Set User-Agent
    if user_agent == "browser":
        request_headers["User-Agent"] = random.choice(_BROWSER_USER_AGENTS)
    elif user_agent == "bot":
        request_headers["User-Agent"] = "Mozilla/5.0 (compatible; DeepAgents/1.0)"
    else:
        request_headers["User-Agent"] = user_agent

    # Merge custom headers
    if headers:
        request_headers.update(headers)

    # Get session with connection pooling
    session = _get_fetch_session()

    last_error: Exception | None = None
    attempts = 0

    for attempt in range(max_retries):
        attempts = attempt + 1

        try:
            # Use separate timeouts for connect and read
            response = session.get(
                url,
                headers=request_headers,
                timeout=(timeout // 2, timeout),  # (connect timeout, read timeout)
                allow_redirects=follow_redirects,
                stream=True,  # Stream to check content size before downloading all
                verify=verify_ssl,
            )

            # Check for HTTP errors (4xx, 5xx)
            if response.status_code >= 400:
                status_code = response.status_code
                # Retry on server errors (5xx)
                if status_code >= 500 and attempt < max_retries - 1:
                    last_error = requests.exceptions.HTTPError(f"HTTP {status_code}")
                    time.sleep(2 ** (attempt + 1))
                    continue
                # Client errors (4xx) don't benefit from retry
                return {
                    "success": False,
                    "error": f"HTTP error {status_code}: {response.reason}",
                    "url": url,
                    "status_code": status_code,
                    "attempts": attempts,
                }

            # Check content size before downloading
            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) > max_content_size:
                return {
                    "success": False,
                    "error": f"Content too large: {int(content_length) / 1024 / 1024:.2f}MB exceeds {max_content_size / 1024 / 1024:.2f}MB limit",
                    "url": url,
                    "status_code": response.status_code,
                    "attempts": attempts,
                }

            # Check content type
            content_type = response.headers.get("Content-Type", "")
            if content_type and not any(
                ct in content_type.lower()
                for ct in ["text/html", "text/plain", "application/xhtml", "text/xml"]
            ):
                # For non-HTML content, return raw text with warning
                if "application/json" in content_type.lower():
                    # JSON content - return as-is
                    content = response.text
                    return {
                        "success": True,
                        "url": str(response.url),
                        "markdown_content": f"```json\n{content}\n```",
                        "status_code": response.status_code,
                        "content_length": len(content),
                        "content_type": content_type,
                        "attempts": attempts,
                    }
                # Other binary content
                return {
                    "success": False,
                    "error": f"Unsupported content type: {content_type}. This tool is designed for HTML/text content.",
                    "url": url,
                    "status_code": response.status_code,
                    "content_type": content_type,
                    "attempts": attempts,
                }

            # Download content with size check
            chunks = []
            total_size = 0
            for chunk in response.iter_content(chunk_size=8192, decode_unicode=True):
                total_size += len(chunk)
                if total_size > max_content_size:
                    return {
                        "success": False,
                        "error": f"Content exceeded {max_content_size / 1024 / 1024:.2f}MB limit during download",
                        "url": url,
                        "status_code": response.status_code,
                        "attempts": attempts,
                    }
                chunks.append(chunk)

            content = "".join(chunks)

            # Handle encoding
            if response.encoding and response.encoding.lower() not in ["utf-8", "utf8"]:
                try:
                    content = content.encode(response.encoding).decode("utf-8", errors="replace")
                except (UnicodeDecodeError, UnicodeEncodeError):
                    pass  # Keep original content

            # Convert HTML content to markdown
            markdown_content = markdownify(content)

            # For GitHub API responses, format as JSON code block
            if is_github_api_url:
                try:
                    import json
                    parsed = json.loads(content)
                    markdown_content = f"```json\n{json.dumps(parsed, indent=2)}\n```"
                except (json.JSONDecodeError, ImportError):
                    pass  # Keep original content

            # Apply summarization if requested and content is large
            if summarize and len(markdown_content) > summarize_max_length:
                summary_result = summarize_web_content(
                    markdown_content,
                    max_length=summarize_max_length,
                    focus_query=focus_query,
                )
                if summary_result["success"]:
                    return {
                        "success": True,
                        "url": str(response.url),
                        "final_url": str(response.url),
                        "original_url": original_url,
                        "github_url_converted": was_github_url,
                        "markdown_content": summary_result["summarized_content"],
                        "status_code": response.status_code,
                        "content_length": summary_result["summarized_length"],
                        "original_content_length": summary_result["original_length"],
                        "compression_ratio": summary_result["compression_ratio"],
                        "content_type": response.headers.get("Content-Type", ""),
                        "attempts": attempts,
                        "summarized": True,
                        "sections_analyzed": summary_result["sections_analyzed"],
                        "sections_included": summary_result["sections_included"],
                    }

            return {
                "success": True,
                "url": str(response.url),
                "final_url": str(response.url),
                "original_url": original_url,
                "github_url_converted": was_github_url,
                "markdown_content": markdown_content,
                "status_code": response.status_code,
                "content_length": len(markdown_content),
                "content_type": response.headers.get("Content-Type", ""),
                "attempts": attempts,
                "summarized": False,
            }

        except requests.exceptions.Timeout as e:
            last_error = e
            if attempt < max_retries - 1:
                time.sleep(2 ** (attempt + 1))  # Exponential backoff: 2s, 4s, 8s
                continue

        except requests.exceptions.SSLError as e:
            # SSL errors are usually not transient - don't retry
            return {
                "success": False,
                "error": f"SSL certificate verification failed: {e!s}. Try setting verify_ssl=False if you trust this site.",
                "url": url,
                "attempts": attempts,
            }

        except requests.exceptions.ConnectionError as e:
            last_error = e
            if attempt < max_retries - 1:
                time.sleep(2 ** (attempt + 1))
                continue

        except requests.exceptions.HTTPError as e:
            # HTTP errors (4xx, 5xx) - retry on server errors
            if hasattr(e, "response") and e.response is not None:
                status_code = e.response.status_code
                if status_code >= 500 and attempt < max_retries - 1:
                    last_error = e
                    time.sleep(2 ** (attempt + 1))
                    continue
                # Client errors (4xx) don't benefit from retry
                return {
                    "success": False,
                    "error": f"HTTP error {status_code}: {e!s}",
                    "url": url,
                    "status_code": status_code,
                    "attempts": attempts,
                }
            last_error = e

        except Exception as e:
            last_error = e
            if attempt < max_retries - 1:
                time.sleep(2 ** (attempt + 1))
                continue

    # All retries exhausted
    return {
        "success": False,
        "error": f"Failed after {attempts} attempts: {last_error!s}",
        "url": url,
        "attempts": attempts,
    }


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
                        if "source" in key.lower()
                        or "repo" in key.lower()
                        or "github" in key.lower()
                    ),
                    None,
                ),
                "requires_python": info.get("requires_python"),
                "dependencies": info.get("requires_dist") or [],
                "keywords": info.get("keywords", "").split(",") if info.get("keywords") else [],
                "classifiers": info.get("classifiers", [])[:10],  # Limit classifiers
            }

        if registry == "npm":
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
                    "error": "PyYAML not installed. Install with: uv add pyyaml",
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
                        "error": "TOML parser not available. Requires Python 3.11+ or: uv add tomli",
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
                    "error": "PyYAML not installed. Install with: uv add pyyaml",
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
                    "error": "TOML writer not installed. Install with: uv add tomli-w",
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


# =============================================================================
# NVIDIA GenAI API (Stable Diffusion 3 Medium)
# =============================================================================

# NVIDIA GenAI API endpoint for Stable Diffusion 3 Medium
NVIDIA_API_ENDPOINT = "https://ai.api.nvidia.com/v1/genai/stabilityai/stable-diffusion-3-medium"

# Available aspect ratios for NVIDIA API
NVIDIA_ASPECT_RATIOS = {
    "1:1": "1:1",
    "16:9": "16:9",
    "9:16": "9:16",
    "4:3": "4:3",
    "3:4": "3:4",
    "21:9": "21:9",
}


def generate_image_nvidia(
    prompt: str,
    output_path: str | None = None,
    cfg_scale: float = 3.5,
    aspect_ratio: str = "1:1",
    seed: int = 0,
    steps: int = 30,
    negative_prompt: str = "",
) -> dict[str, Any]:
    """Generate an image using NVIDIA GenAI API (Stable Diffusion 3 Medium).

    This tool generates high-quality images from text descriptions using
    NVIDIA's Stable Diffusion 3 Medium model through the NVIDIA GenAI API.

    Args:
        prompt: Text description of the image to generate. Be specific and detailed.
        output_path: Path to save the image. If not provided, saves to current directory
                     with timestamp (e.g., "generated_20240115_143022.png")
        cfg_scale: Classifier-Free Guidance scale (1.0-10.0). Higher values follow prompt more strictly.
        aspect_ratio: Output dimensions - "1:1", "16:9", "9:16", "4:3", "3:4", "21:9"
        seed: Random seed for reproducibility (0 for random)
        steps: Number of inference steps (10-100). More steps = higher quality but slower
        negative_prompt: Description of elements to avoid in the image

    Returns:
        Dictionary with:
        - success: bool - Whether generation succeeded
        - file_path: str | None - Path to saved image (if successful)
        - seed: int - Seed used for generation
        - error: str - Error message (if failed)

    Example:
        >>> generate_image_nvidia("A futuristic city with neon lights", output_path="city.png")
        {'success': True, 'file_path': 'B:/path/to/city.png', 'seed': 12345}
    """
    # Get API key
    from novacode_cli.onboarding import SecretManager

    secret_manager = SecretManager()
    api_key = secret_manager.get_secret("nvidia_api_key") or os.environ.get("NVIDIA_API_KEY")

    if not api_key:
        return {
            "success": False,
            "error": (
                "NVIDIA_API_KEY not configured.\n\n"
                "To set up NVIDIA GenAI API:\n"
                "1. Sign up at https://developer.nvidia.com/api-access\n"
                "2. Get your API key from the AI Foundation section\n"
                "3. Configure it with: Nova secrets set nvidia_api_key\n"
                "   Or set environment variable: export NVIDIA_API_KEY=your-key-here\n\n"
                "NVIDIA GenAI API provides access to Stable Diffusion 3 and other models."
            ),
        }

    # Validate aspect ratio
    if aspect_ratio not in NVIDIA_ASPECT_RATIOS:
        return {
            "success": False,
            "error": f"Invalid aspect_ratio '{aspect_ratio}'. Valid options: {list(NVIDIA_ASPECT_RATIOS.keys())}",
        }

    # Validate parameters
    if not (1.0 <= cfg_scale <= 10.0):
        return {
            "success": False,
            "error": f"cfg_scale must be between 1.0 and 10.0, got {cfg_scale}",
        }
    if not (10 <= steps <= 100):
        return {
            "success": False,
            "error": f"steps must be between 10 and 100, got {steps}",
        }

    # Build request headers
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    # Build request body
    payload = {
        "prompt": prompt,
        "cfg_scale": cfg_scale,
        "aspect_ratio": aspect_ratio,
        "seed": seed if seed > 0 else None,  # None for random seed
        "steps": steps,
        "negative_prompt": negative_prompt,
    }

    # Remove None values from payload
    payload = {k: v for k, v in payload.items() if v is not None}

    try:
        # Make API request
        response = requests.post(
            NVIDIA_API_ENDPOINT,
            headers=headers,
            json=payload,
            timeout=120,  # 2 minutes for image generation
        )

        # Check for HTTP errors
        response.raise_for_status()

        # Parse response
        result = response.json()

        # Handle different response formats
        # NVIDIA API can return: {"artifacts": [{"base64": "..."}]} or {"image": "base64..."}
        image_data = None
        
        # Format 1: {"artifacts": [{"base64": "..."}]}
        if "artifacts" in result and len(result["artifacts"]) > 0:
            artifact = result["artifacts"][0]
            if "base64" in artifact:
                import base64
                image_data = base64.b64decode(artifact["base64"])
                actual_seed = artifact.get("seed", seed) if "seed" in artifact else seed
        
        # Format 2: {"image": "base64..."}
        elif "image" in result:
            import base64
            image_data = base64.b64decode(result["image"])
            actual_seed = result.get("seed", seed)
        
        if image_data:
            # Determine output path
            if output_path is None:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                output_path = f"generated_{timestamp}.png"

            # Save image
            output_file = Path(output_path)
            output_file.parent.mkdir(parents=True, exist_ok=True)
            output_file.write_bytes(image_data)

            return {
                "success": True,
                "file_path": str(output_file.absolute()),
                "seed": actual_seed,
                "prompt": prompt[:100] + "..." if len(prompt) > 100 else prompt,
            }

        return {
            "success": False,
            "error": f"No image data in API response. Response keys: {list(result.keys())}",
        }

    except requests.exceptions.HTTPError as e:
        error_msg = str(e)
        status_code = e.response.status_code if hasattr(e, "response") else "unknown"

        if status_code == 401:
            return {
                "success": False,
                "error": "Invalid NVIDIA API key. Please check your NVIDIA_API_KEY.",
            }
        elif status_code == 429:
            return {
                "success": False,
                "error": "Rate limit exceeded. Please try again later.",
            }
        elif status_code == 500:
            return {
                "success": False,
                "error": "NVIDIA API server error. Please try again.",
            }

        return {
            "success": False,
            "error": f"HTTP {status_code} error: {error_msg}",
        }

    except requests.exceptions.Timeout:
        return {
            "success": False,
            "error": "Request timed out. The server took too long to respond.",
        }
    except requests.exceptions.ConnectionError:
        return {
            "success": False,
            "error": "Connection error. Please check your internet connection.",
        }
    except json.JSONDecodeError as e:
        return {
            "success": False,
            "error": f"Invalid JSON response from API: {e}",
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Error generating image: {e!s}",
        }


def generate_image(
    prompt: str,
    output_path: str | None = None,
    model: str = "flux-schnell",
    aspect_ratio: str = "1:1",
    output_format: str = "png",
    num_outputs: int = 1,
    seed: int | None = None,
    backend: str = "replicate",
    cfg_scale: float | None = None,
    steps: int | None = None,
    negative_prompt: str | None = None,
) -> dict[str, Any]:
    """Generate an image using Replicate or NVIDIA GenAI API.

    IMPORTANT: This tool generates images from text descriptions using open source
    models (Replicate) or NVIDIA's Stable Diffusion 3 Medium.

    Args:
        prompt: Text description of the image to generate. Be specific and detailed.
        output_path: Path to save the image. If not provided, saves to current directory
                     with timestamp (e.g., "generated_20240115_143022.png")
        model: Model to use:
            - Replicate: "flux-schnell" (default for Replicate), "flux-dev", "sdxl", "sdxl-turbo"
            - NVIDIA: "stable-diffusion-3-medium" (default for NVIDIA)
        aspect_ratio: Output dimensions - "1:1", "16:9", "9:16", "4:3", "3:4", "21:9"
        output_format: Image format - "png", "jpg", "webp" (Replicate only)
        num_outputs: Number of images to generate (1-4) (Replicate only)
        seed: Random seed for reproducibility (optional)
        backend: API backend - "replicate" or "nvidia"
        cfg_scale: Classifier-Free Guidance scale (1.0-10.0) (NVIDIA only, default: 3.5)
        steps: Number of inference steps (10-100) (NVIDIA only, default: 30)
        negative_prompt: Description of elements to avoid in the image (NVIDIA only)

    Returns:
        Dictionary with:
        - success: bool - Whether generation succeeded
        - file_path: str | list[str] - Path(s) to saved image(s)
        - model: str - Model used
        - error: str - Error message (if failed)

    Note:
        - For NVIDIA backend: Set NVIDIA_API_KEY environment variable or run
          "Nova secrets set nvidia_api_key"
    """
    # Dispatch to appropriate backend
    if backend == "nvidia":
        return generate_image_nvidia(
            prompt=prompt,
            output_path=output_path,
            cfg_scale=cfg_scale if cfg_scale is not None else 3.5,
            aspect_ratio=aspect_ratio,
            seed=seed if seed is not None else 0,
            steps=steps if steps is not None else 30,
            negative_prompt=negative_prompt if negative_prompt is not None else "",
        )
    elif backend != "replicate":
        return {
            "success": False,
            "error": f"Invalid backend '{backend}'. Valid options: 'replicate', 'nvidia'",
        }

    try:
        import replicate
    except ImportError:
        return {
            "success": False,
            "error": "replicate package not installed. Run: uv add replicate",
        }

    # Get API key
    from novacode_cli.onboarding import SecretManager

    secret_manager = SecretManager()
    api_key = secret_manager.get_secret("replicate_api_key") or os.environ.get(
        "REPLICATE_API_TOKEN"
    )

    if not api_key:
        return {
            "success": False,
            "error": "REPLICATE_API_TOKEN not configured. Get your free API key at https://replicate.com/account/api-tokens",
        }

    # Validate model (only for Replicate backend)
    if backend == "replicate" and model not in REPLICATE_MODELS:
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
                output_file.write_bytes(img_output.read()) # type: ignore
            elif isinstance(img_output, str) and img_output.startswith("http"):
                # URL - download it
                response = requests.get(img_output, timeout=60)
                response.raise_for_status()
                output_file.write_bytes(response.content)
            else:
                # Assume bytes
                output_file.write_bytes(img_output) # type: ignore

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
    if project["linter"] == "eslint":
        return _lint_with_eslint(path, fix)
    if project["project_type"] == "python":
        # Try ruff anyway, it might be installed globally
        try:
            subprocess.run(["ruff", "--version"], capture_output=True, check=True, timeout=5)
            return _lint_with_ruff(path, fix, show_fixes)
        except (FileNotFoundError, subprocess.CalledProcessError):
            return {
                "success": False,
                "error": "No linter available. Install ruff: uv add ruff",
            }
    elif project["project_type"] in ("javascript", "typescript"):
        return _lint_with_eslint(path, fix)
    else:
        return {
            "success": False,
            "error": f"No linter configured for {project['project_type']} projects",
            "hint": "For Python: uv add ruff. For JS/TS: npm install eslint",
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
            encoding="utf-8",
            errors="replace",
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
            errors.append(
                {
                    "file": str(path),
                    "code": "E999",
                    "message": result.stderr.strip(),
                }
            )

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
        return {"success": False, "error": "ruff not found. Install with: uv add ruff"}
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
            encoding="utf-8",
            errors="replace",
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
    if project["formatter"] == "prettier":
        return _format_with_prettier(path, check_only)
    if project["formatter"] == "gofmt":
        return _format_with_gofmt(path, check_only)
    if project["formatter"] == "rustfmt":
        return _format_with_rustfmt(path, check_only)
    if project["project_type"] == "python":
        # Try ruff format anyway
        try:
            subprocess.run(["ruff", "--version"], capture_output=True, check=True, timeout=5)
            return _format_with_ruff(path, check_only)
        except (FileNotFoundError, subprocess.CalledProcessError):
            return {
                "success": False,
                "error": "No formatter available. Install ruff: uv add ruff",
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
            encoding="utf-8",
            errors="replace",
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
            "message": "Already formatted"
            if already_formatted
            else (
                f"{len(files_changed)} file(s) would be changed"
                if check_only
                else "Formatted successfully"
            ),
        }

    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Formatting timed out after 120 seconds"}
    except FileNotFoundError:
        return {"success": False, "error": "ruff not found. Install with: uv add ruff"}
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
            encoding="utf-8",
            errors="replace",
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
            encoding="utf-8",
            errors="replace",
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
            encoding="utf-8",
            errors="replace",
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
        return {
            "success": False,
            "error": "rustfmt not found. Install with: rustup component add rustfmt",
        }
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
    if project["type_checker"] == "pyright":
        return _check_types_pyright(path, strict)
    if project["type_checker"] == "tsc":
        return _check_types_tsc(path)
    if project["project_type"] == "python":
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
                    "error": "No type checker available. Install mypy: uv add mypy",
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
    cmd.extend(
        [
            "--show-error-codes",
            "--no-error-summary",  # We'll generate our own summary
        ]
    )

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
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

                    errors.append(
                        {
                            "file": parts[0],
                            "line": int(parts[1]) if parts[1].isdigit() else 0,
                            "column": int(parts[2]) if parts[2].isdigit() else 0,
                            "code": code,
                            "message": message.replace("error: ", "").replace("note: ", ""),
                        }
                    )

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
        return {"success": False, "error": "mypy not found. Install with: uv add mypy"}
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
            encoding="utf-8",
            errors="replace",
            timeout=300,
            check=False,
        )

        errors: list[dict[str, Any]] = []

        if result.stdout.strip():
            try:
                data = json.loads(result.stdout)
                for diag in data.get("generalDiagnostics", []):
                    errors.append(
                        {
                            "file": diag.get("file", ""),
                            "line": diag.get("range", {}).get("start", {}).get("line", 0),
                            "column": diag.get("range", {}).get("start", {}).get("character", 0),
                            "code": diag.get("rule", "error"),
                            "message": diag.get("message", ""),
                            "severity": diag.get("severity", "error"),
                        }
                    )
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
        return {"success": False, "error": "pyright not found. Install with: uv add pyright"}
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
            encoding="utf-8",
            errors="replace",
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
                errors.append(
                    {
                        "file": match.group(1),
                        "line": int(match.group(2)),
                        "column": int(match.group(3)),
                        "severity": match.group(4),
                        "code": match.group(5),
                        "message": match.group(6),
                    }
                )

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
        return {
            "success": False,
            "error": "TypeScript not found. Install with: npm install typescript",
        }
    except Exception as e:
        return {"success": False, "error": f"Type checking failed: {e!s}"}

def think(reflection: str) -> str:
    """Tool for strategic reflection on code exploration and task progress.

    Use this tool to pause and analyze your findings, assess what you've learned,
    and make deliberate decisions about next steps in code analysis and exploration.

    This creates a checkpoint for quality decision-making before continuing.

    When to use:
    - After exploring codebase sections: What key patterns did I discover?
    - Before deciding next exploration targets: Do I understand the architecture enough?
    - When assessing code understanding: What crucial details am I still missing?
    - When planning refactoring/fixes: Is my analysis complete and correct?
    - Before recommending changes: Have I considered all implications?
    - When context is complex: Am I on the right track?

    Reflection should address:
    1. Key findings - What concrete code patterns, dependencies, or issues did I discover?
    2. Current understanding - What have I learned about the architecture/functionality?
    3. Knowledge gaps - What critical information is still missing?
    4. Quality assessment - Do I have sufficient evidence to proceed with recommendations?
    5. Strategic decision - Should I explore further or am I ready to make recommendations?

    Args:
        reflection: Your detailed reflection on code findings, understanding gaps,
                   analysis quality, and decision about next steps

    Returns:
        Confirmation that reflection was recorded for decision-making
    """
    return f"Reflection recorded: {reflection}"


def browser_automate(
    task: str,
    model: str = "qwen3.5:cloud",
    use_vision: bool = True,
) -> dict[str, Any]:
    """Run browser automation with AI to perform web tasks.

    This tool uses AI-powered browser automation to navigate websites, interact
    with elements, and extract information. It's useful for tasks that require
    web browsing, form filling, data extraction, or multi-step web interactions.

    The browser automation runs asynchronously and returns results that can be
    processed by the agent for further analysis or action.

    Args:
        task: Natural language description of the browser task to perform
              (e.g., "Go to github.com and find trending Python repos")
        model: Ollama model to use for browser automation (default: llama3.1:8b)
        use_vision: Whether to enable vision capabilities for the browser (default: True)

    Returns:
        Dictionary containing:
        - success: Whether the browser automation succeeded
        - result: The result of the browser automation task
        - task: The task description that was executed
        - model: The model used for automation
        - vision_enabled: Whether vision was enabled
        - error: Error message if automation failed

    Example:
        # Search for information on a website
        browser_automate("Go to wikipedia.org and search for 'Python programming language'")

        # Fill out a form
        browser_automate("Go to example.com/contact and fill out the contact form with test data")

        # Extract data from a webpage
        browser_automate("Go to news.ycombinator.com and get the top 5 stories")

    Note: Requires browser-use library to be installed. Install with:
          pip install browser-use
    """
    import asyncio

    try:
        # Import browser-use components
        from browser_use import Agent, ChatOllama
    except ImportError as e:
        return {
            "success": False,
            "error": f"browser-use library not installed: {e}\n\nInstall with: pip install browser-use",
            "task": task,
        }

    async def run_browser_task():
        """Execute the browser automation task asynchronously."""
        try:
            # Create the browser-use ChatOllama model
            llm = ChatOllama(model=model)

            # Create the browser-use agent
            agent = Agent(
                task=task,
                llm=llm,
                use_vision=use_vision,
            )

            # Run the agent
            result = await agent.run()

            # Extract result string
            if hasattr(result, "final_result"):
                final = result.final_result()
                if final:
                    return final
            if hasattr(result, "content"):
                return str(result.content) # type: ignore
            return str(result)

        except Exception as e:
            return f"Browser automation error: {e!s}"

    # Run the async task
    try:
        # Check if we're already in an async context
        try:
            loop = asyncio.get_running_loop()
            # We're in an async context, create a task
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(asyncio.run, run_browser_task())
                result = future.result(timeout=300)  # 5 minute timeout
        except RuntimeError:
            # No running loop, we can use asyncio.run directly
            result = asyncio.run(run_browser_task())

        return {
            "success": True,
            "result": result,
            "task": task,
            "model": model,
            "vision_enabled": use_vision,
        }

    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to run browser automation: {e!s}",
            "task": task,
            "model": model,
            "vision_enabled": use_vision,
        }


# =============================================================================
# Memory Management Tools
# =============================================================================


def write_memory(
    content: str,
    memory_type: Literal["user", "project"] = "user",
    path: str | None = None,
    append: bool = False,
) -> dict[str, Any]:
    """Write content to agent memory file for persistence across sessions.

    Memory allows the agent to remember information across conversations.
    Use this tool when the user explicitly asks to remember something or when
    you identify information that should be persisted for future sessions.

    Args:
        content: Memory content to write (Markdown format recommended)
        memory_type: "user" for user preferences (applies to all projects),
                    "project" for project-specific context
        path: Optional custom path (defaults to standard locations)
        append: If True, append to existing memory; if False, replace (default: False)

    Returns:
        Dictionary with:
        - success: bool - Whether write succeeded
        - path: str - Path to memory file
        - message: str - Success/error message
        - memory_type: str - Type of memory written

    Memory Locations:
        - User memory: ~/.nova/{agent-id}/agent.md
        - Project memory: {project-root}/.nova/NOVA.md

    Example:
        >>> write_memory("# Preferences\\n\\n- Use concise responses", memory_type="user")
        {'success': True, 'path': '/home/user/.nova/nova-agent/agent.md', 'message': '...'}

        >>> write_memory("# Project Notes\\n\\n- Use Python 3.11+", memory_type="project")
        {'success': True, 'path': '/project/Nova.md', 'message': '...'}
    """
    from pathlib import Path

    from novacode_cli.config.config import MAIN_AGENT_ID, settings

    # Determine memory path
    if path:
        memory_path = Path(path)
    elif memory_type == "user":
        # User memory: ~/.nova/{agent-id}/agent.md
        agent_dir = settings.get_agent_dir(MAIN_AGENT_ID)
        memory_path = agent_dir / "agent.md"
    else:
        # Project memory: {project-root}/.nova/NOVA.md
        if not settings.project_root:
            return {
                "success": False,
                "error": "Not in a project directory. Use memory_type='user' for user memory.",
                "memory_type": memory_type,
            }
        memory_path = settings.project_root / ".nova" / "NOVA.md"

    # Create parent directory if needed
    memory_path.parent.mkdir(parents=True, exist_ok=True)

    # Read existing content if appending
    existing_content = ""
    if append and memory_path.exists():
        try:
            existing_content = memory_path.read_text(encoding="utf-8")
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to read existing memory: {e!s}",
                "path": str(memory_path),
                "memory_type": memory_type,
            }

    # Write or append content
    try:
        if append and existing_content:
            # Append with separator
            full_content = f"{existing_content}\n\n---\n\n{content}"
        else:
            full_content = content

        memory_path.write_text(full_content, encoding="utf-8")

        return {
            "success": True,
            "path": str(memory_path),
            "message": f"Memory written to {memory_path}",
            "memory_type": memory_type,
            "appended": append,
            "content_length": len(full_content),
        }

    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to write memory: {e!s}",
            "path": str(memory_path),
            "memory_type": memory_type,
        }


def read_memory(
    memory_type: Literal["user", "project"] = "user",
    path: str | None = None,
) -> dict[str, Any]:
    """Read agent memory file to see what the agent remembers.

    Use this tool to check what information is stored in memory before
    updating it or when the user asks "what do you remember?"

    Args:
        memory_type: "user" for user preferences, "project" for project context
        path: Optional custom path (defaults to standard locations)

    Returns:
        Dictionary with:
        - success: bool - Whether read succeeded
        - content: str - Memory file content
        - path: str - Path to memory file
        - exists: bool - Whether memory file exists
        - memory_type: str - Type of memory read

    Example:
        >>> read_memory(memory_type="user")
        {'success': True, 'content': '# Preferences\\n\\n...', 'path': '...'}
    """
    from pathlib import Path

    from novacode_cli.config.config import MAIN_AGENT_ID, settings

    # Determine memory path
    if path:
        memory_path = Path(path)
    elif memory_type == "user":
        agent_dir = settings.get_agent_dir(MAIN_AGENT_ID)
        memory_path = agent_dir / "agent.md"
    else:
        if not settings.project_root:
            return {
                "success": False,
                "error": "Not in a project directory. Use memory_type='user' for user memory.",
                "memory_type": memory_type,
            }
        memory_path = settings.project_root / ".nova" / "NOVA.md"

    # Check if memory exists
    if not memory_path.exists():
        return {
            "success": True,
            "content": "",
            "path": str(memory_path),
            "exists": False,
            "message": f"No memory file found at {memory_path}",
            "memory_type": memory_type,
        }

    # Read memory
    try:
        content = memory_path.read_text(encoding="utf-8")
        return {
            "success": True,
            "content": content,
            "path": str(memory_path),
            "exists": True,
            "content_length": len(content),
            "memory_type": memory_type,
        }

    except Exception as e:
        return {
            "success": False,
            "error": f"Failed to read memory: {e!s}",
            "path": str(memory_path),
            "memory_type": memory_type,
        }


def create_memory_structure(
    structure_type: Literal["simple", "advanced"] = "simple",
    topics: list[str] | None = None,
) -> dict[str, Any]:
    """Create memory directory structure for organizing agent memory.

    Use this tool to set up an organized memory structure. The agent can then
    use the advanced structure to organize memories by topic.

    Args:
        structure_type: "simple" for single agent.md file (default),
                       "advanced" for memories/ directory with topic files
        topics: List of topic names for advanced structure (e.g., ["preferences", "coding-style", "workflows"])
               If None, creates default topics: ["preferences", "coding-style", "project-context"]

    Returns:
        Dictionary with:
        - success: bool - Whether creation succeeded
        - structure_type: str - Type of structure created
        - path: str - Path to memory directory/file
        - topics_created: list - List of topic files created (advanced only)
        - message: str - Success/error message

    Structure Types:
        - Simple: ~/.nova/{agent-id}/agent.md (single file)
        - Advanced: ~/.nova/{agent-id}/memories/ (directory with topic files)
            - INDEX.md (memory index)
            - preferences.md
            - coding-style.md
            - project-context.md
            - ... (custom topics)

    Example:
        >>> create_memory_structure("simple")
        {'success': True, 'path': '/home/user/.nova/nova-agent/agent.md', ...}

        >>> create_memory_structure("advanced", topics=["preferences", "workflows"])
        {'success': True, 'topics_created': ['preferences.md', 'workflows.md'], ...}
    """
    from pathlib import Path

    from novacode_cli.config.config import MAIN_AGENT_ID, settings

    # Get agent directory
    agent_dir = settings.get_agent_dir(MAIN_AGENT_ID)

    if structure_type == "simple":
        # Simple structure: single agent.md file
        memory_path = agent_dir / "agent.md"

        # Create parent directory if needed
        memory_path.parent.mkdir(parents=True, exist_ok=True)

        # Create file with template if it doesn't exist
        if not memory_path.exists():
            template = """# Agent Memory

This file stores your preferences and context that persist across sessions.

## Communication Style
- [Your preferred communication style]

## Coding Preferences
- [Your coding preferences]

## Project Context
- [Project-specific notes]

## Workflows
- [Common workflows you use]
"""
            memory_path.write_text(template, encoding="utf-8")

        return {
            "success": True,
            "structure_type": "simple",
            "path": str(memory_path),
            "message": f"Simple memory structure created at {memory_path}",
            "created_files": ["agent.md"],
        }

    else:
        # Advanced structure: memories/ directory with topic files
        memories_dir = agent_dir / "memories"

        # Create memories directory
        memories_dir.mkdir(parents=True, exist_ok=True)

        # Default topics if none provided
        if topics is None:
            topics = ["preferences", "coding-style", "project-context"]

        # Create INDEX.md
        index_path = memories_dir / "INDEX.md"
        if not index_path.exists():
            index_content = f"""# Memory Index

This directory contains organized memory files by topic.

## Topics

"""
            for topic in topics:
                index_content += f"- [{topic}]({topic}.md) - [Description]\n"

            index_content += """
## Usage

- Each file contains memories for a specific topic
- Use `/dream` to consolidate and organize memories
- Update this INDEX.md when adding new topics
"""
            index_path.write_text(index_content, encoding="utf-8")

        # Create topic files
        created_files = ["INDEX.md"]
        for topic in topics:
            # Sanitize topic name
            safe_topic = topic.replace(" ", "-").replace("_", "-").lower()
            topic_path = memories_dir / f"{safe_topic}.md"

            if not topic_path.exists():
                # Create topic file with template
                topic_content = f"""# {topic.replace('-', ' ').title()}

This file contains memories related to {topic}.

## Notes

- [Add your notes here]

## Preferences

- [Add your preferences here]

## Examples

- [Add examples here]
"""
                topic_path.write_text(topic_content, encoding="utf-8")
                created_files.append(f"{safe_topic}.md")

        return {
            "success": True,
            "structure_type": "advanced",
            "path": str(memories_dir),
            "topics_created": created_files,
            "message": f"Advanced memory structure created at {memories_dir} with {len(created_files)} files",
            "index_file": str(index_path),
        }


# =============================================================================
# LSP Tools (Language Server Protocol - Code Intelligence)
# =============================================================================

# Import LSP tools from the dedicated module
# These tools provide code intelligence features similar to IDE LSP functionality
from novacode_cli.lsp_tools import (  # noqa: F401
    lsp_completions,
    lsp_diagnostics,
    lsp_document_symbols,
    lsp_find_references,
    lsp_goto_definition,
    lsp_hover,
    lsp_implementation,
    lsp_rename,
    lsp_signature_help,
    lsp_type_definition,
    lsp_workspace_symbols,
)

# Import command tool for CLI slash commands
# This allows the agent to invoke CLI commands programmatically
from novacode_cli.command_tool import (  # noqa: F401
    list_commands,
    run_command,
)

"""Web search tools.

This module provides tools for searching the web using various search engines.
"""

from __future__ import annotations

from typing import Any, Literal

from langchain.tools import tool

from novacode_cli.config.config import settings

# Initialize Tavily client if API key is available
try:
    from tavily import TavilyClient

    tavily_client = TavilyClient(api_key=settings.tavily_api_key) if settings.has_tavily else None
except ImportError:
    tavily_client = None


@tool
def web_search(
    query: str,
    max_results: int = 5,
    topic: Literal["general", "news", "finance"] = "general",
    include_raw_content: bool = False,
) -> dict[str, Any]:
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
            "error": (
                "Tavily API key not configured. Please set TAVILY_API_KEY environment variable."
            ),
            "query": query,
        }

    try:
        return tavily_client.search(
            query,
            max_results=max_results,
            include_raw_content=include_raw_content,
            topic=topic,
        )
    except Exception as e:  # noqa: BLE001
        return {"error": f"Web search error: {e!s}", "query": query}


@tool
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

    except Exception as e:  # noqa: BLE001
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


@tool
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

    except Exception as e:  # noqa: BLE001
        return {
            "success": False,
            "error": f"Documentation search error: {e!s}",
            "query": query,
        }

"""URL fetching tools.

This module provides tools for fetching web content and converting to markdown.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any

import requests
from langchain.tools import tool
from markdownify import markdownify

from novacode_cli.tools._shared import (
    _BROWSER_USER_AGENTS,
    _get_fetch_session,
    _secure_random,
)


def _summarize_web_content(
    content: str,
    max_length: int = 8000,
    focus_query: str | None = None,
) -> dict[str, Any]:
    """Compress large web content to fit token limits, optionally focused on a query."""
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

    for line in lines:
        # Track code blocks separately
        if line.strip().startswith("```"):
            if current_section["content"].strip():
                sections.append(current_section.copy())
                current_section = {"title": "", "content": ""}
            # Extract code block
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
    for _score, section in scored_sections[1:]:
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
    # Pattern: https://github.com/owner/repo/blob/branch/path
    blob_match = re.match(r"https://github\.com/([^/]+)/([^/]+)/blob/([^/]+)/(.+)", url)
    if blob_match:
        owner, repo, branch, path = blob_match.groups()
        raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{path}"
        return raw_url, True

    # Pattern: https://github.com/owner/repo/tree/branch/path (for directory listings)
    tree_match = re.match(r"https://github\.com/([^/]+)/([^/]+)/tree/([^/]+)/(.+)", url)
    if tree_match:
        owner, repo, branch, path = tree_match.groups()
        # For tree URLs, we can't get raw content, but we can try the API
        # Return the API URL for directory contents
        api_url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}?ref={branch}"
        return api_url, True

    # Pattern: https://github.com/owner/repo (repo root)
    repo_match = re.match(r"https://github\.com/([^/]+)/([^/]+)/?$", url)
    if repo_match:
        owner, repo = repo_match.groups()
        # Return API URL for repo info
        api_url = f"https://api.github.com/repos/{owner}/{repo}"
        return api_url, True

    # Already a raw URL or not a GitHub URL
    return url, False


@tool
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
        request_headers["User-Agent"] = _secure_random.choice(_BROWSER_USER_AGENTS)
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
                    "error": (
                        f"Content too large: "
                        f"{int(content_length) / 1024 / 1024:.2f}MB "
                        f"exceeds {max_content_size / 1024 / 1024:.2f}MB limit"
                    ),
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
                    "error": (
                        f"Unsupported content type: {content_type}. "
                        "This tool is designed for HTML/text content."
                    ),
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
                        "error": (
                            f"Content exceeded "
                            f"{max_content_size / 1024 / 1024:.2f}MB limit during download"
                        ),
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
                    parsed = json.loads(content)
                    markdown_content = f"```json\n{json.dumps(parsed, indent=2)}\n```"
                except (json.JSONDecodeError, ImportError):  # type: ignore
                    pass  # Keep original content

            # Apply summarization if requested and content is large
            if summarize and len(markdown_content) > summarize_max_length:
                summary_result = _summarize_web_content(
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
                "error": (
                    f"SSL certificate verification failed: {e!s}. "
                    f"Try setting verify_ssl=False if you trust this site."
                ),
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

        except Exception as e:  # noqa: BLE001
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

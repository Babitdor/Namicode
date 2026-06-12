"""Shared utilities and constants for tools modules.

This module provides common imports, constants, and session management
shared across all tool modules.
"""

from __future__ import annotations

from secrets import SystemRandom

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Secure random generator for user agent rotation
_secure_random = SystemRandom()

# Common browser user agents for rotation
_BROWSER_USER_AGENTS = [
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    ("Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0"),
    (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/17.2 Safari/605.1.15"
    ),
]

# Shared session-level connection pool for all HTTP requests
_http_session: requests.Session | None = None


def _get_http_session() -> requests.Session:
    """Get or create a reusable requests session with connection pooling."""
    global _http_session
    if _http_session is None:
        _http_session = requests.Session()
        # Configure retry strategy for transient failures
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=[
                "GET",
                "POST",
                "PUT",
                "DELETE",
                "PATCH",
                "HEAD",
                "OPTIONS",
            ],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        _http_session.mount("http://", adapter)
        _http_session.mount("https://", adapter)
    return _http_session


def _get_fetch_session() -> requests.Session:
    """Alias for _get_http_session — unified connection pool."""
    return _get_http_session()

"""Tests for tools module."""

import pytest

requests = pytest.importorskip("requests")
responses = pytest.importorskip("responses")

from novacode_cli.tools import fetch_url


@responses.activate
def test_fetch_url_success() -> None:
    """Test successful URL fetch and HTML to markdown conversion."""
    responses.add(
        responses.GET,
        "http://example.com",
        body="<html><body><h1>Test</h1><p>Content</p></body></html>",
        status=200,
        content_type="text/html",
    )

    result = fetch_url("http://example.com")

    assert result["success"] is True
    assert result["status_code"] == 200
    assert "Test" in result["markdown_content"]
    assert result["url"].startswith("http://example.com")
    assert result["content_length"] > 0
    assert "attempts" in result


@responses.activate
def test_fetch_url_http_error() -> None:
    """Test handling of HTTP errors."""
    responses.add(
        responses.GET,
        "http://example.com/notfound",
        status=404,
    )

    result = fetch_url("http://example.com/notfound")

    assert result["success"] is False
    assert "error" in result
    assert "404" in result["error"]
    assert result["url"] == "http://example.com/notfound"


@responses.activate
def test_fetch_url_timeout() -> None:
    """Test handling of request timeout."""
    responses.add(
        responses.GET,
        "http://example.com/slow",
        body=requests.exceptions.Timeout(),
    )

    result = fetch_url("http://example.com/slow", timeout=1, max_retries=1)

    assert result["success"] is False
    assert "error" in result
    assert result["url"] == "http://example.com/slow"
    assert "attempts" in result


@responses.activate
def test_fetch_url_connection_error() -> None:
    """Test handling of connection errors."""
    responses.add(
        responses.GET,
        "http://example.com/error",
        body=requests.exceptions.ConnectionError(),
    )

    result = fetch_url("http://example.com/error", max_retries=1)

    assert result["success"] is False
    assert "error" in result
    assert result["url"] == "http://example.com/error"
    assert "attempts" in result


@responses.activate
def test_fetch_url_with_custom_headers() -> None:
    """Test fetch with custom headers."""
    responses.add(
        responses.GET,
        "http://example.com/api",
        body="<html><body>API Content</body></html>",
        status=200,
        content_type="text/html",
    )

    result = fetch_url(
        "http://example.com/api",
        headers={"X-Custom-Header": "test-value"},
    )

    assert result["success"] is True
    assert "API Content" in result["markdown_content"]


@responses.activate
def test_fetch_url_json_content() -> None:
    """Test handling of JSON content."""
    responses.add(
        responses.GET,
        "http://example.com/api/json",
        body='{"key": "value"}',
        status=200,
        content_type="application/json",
    )

    result = fetch_url("http://example.com/api/json")

    assert result["success"] is True
    assert "json" in result["markdown_content"].lower()
    assert result["content_type"] == "application/json"


@responses.activate
def test_fetch_url_large_content() -> None:
    """Test handling of content size limits."""
    # Create a response that exceeds size limit
    large_body = "x" * (2 * 1024 * 1024)  # 2MB
    responses.add(
        responses.GET,
        "http://example.com/large",
        body=large_body,
        status=200,
        content_type="text/html",
    )

    # Set max_content_size to 1MB
    result = fetch_url("http://example.com/large", max_content_size=1024 * 1024)

    assert result["success"] is False
    assert "error" in result
    assert "large" in result["error"].lower() or "exceeded" in result["error"].lower()


@responses.activate
def test_fetch_url_retry_on_server_error() -> None:
    """Test retry behavior on server errors."""
    # First call returns 500, second call succeeds
    responses.add(
        responses.GET,
        "http://example.com/flaky",
        status=500,
    )
    responses.add(
        responses.GET,
        "http://example.com/flaky",
        body="<html><body>Success</body></html>",
        status=200,
        content_type="text/html",
    )

    # Note: The session-level retry adapter may handle retries differently
    # than our manual retry loop. The key test is that we eventually succeed.
    result = fetch_url("http://example.com/flaky", max_retries=3)

    assert result["success"] is True
    assert "Success" in result["markdown_content"]
    # Attempts should be at least 1 (may be more due to retries)
    assert result["attempts"] >= 1

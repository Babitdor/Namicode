"""Unit tests for http_request tool."""

from unittest.mock import MagicMock, patch

import pytest
import requests

from namicode_cli.tools import http_request


class TestHttpRequestBasic:
    """Test basic http_request functionality."""

    def test_successful_get_request(self):
        """Test successful GET request."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.json.return_value = {"data": "value"}
        mock_response.url = "https://api.example.com/data"

        with patch("namicode_cli.tools._get_http_session") as mock_session:
            mock_sess = MagicMock()
            mock_sess.request.return_value = mock_response
            mock_session.return_value = mock_sess
            result = http_request("https://api.example.com/data")

        assert result["success"] is True
        assert result["status_code"] == 200
        assert result["content"] == {"data": "value"}
        assert result["url"] == "https://api.example.com/data"

    def test_successful_post_request_with_json(self):
        """Test successful POST request with JSON data."""
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.json.return_value = {"id": 123, "created": True}
        mock_response.url = "https://api.example.com/create"

        with patch("namicode_cli.tools._get_http_session") as mock_session:
            mock_sess = MagicMock()
            mock_sess.request.return_value = mock_response
            mock_session.return_value = mock_sess
            result = http_request(
                "https://api.example.com/create",
                method="POST",
                data={"name": "test"},
            )

        assert result["success"] is True
        assert result["status_code"] == 201
        assert result["content"]["id"] == 123

    def test_successful_post_request_with_string_data(self):
        """Test POST request with string data."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {}
        mock_response.json.return_value = {"received": True}
        mock_response.url = "https://api.example.com/raw"

        with patch("namicode_cli.tools._get_http_session") as mock_session:
            mock_sess = MagicMock()
            mock_sess.request.return_value = mock_response
            mock_session.return_value = mock_sess
            result = http_request(
                "https://api.example.com/raw",
                method="POST",
                data="raw string data",
            )

        assert result["success"] is True

    def test_request_with_headers(self):
        """Test request with custom headers."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {}
        mock_response.json.return_value = {}
        mock_response.url = "https://api.example.com"

        with patch("namicode_cli.tools._get_http_session") as mock_session:
            mock_sess = MagicMock()
            mock_sess.request.return_value = mock_response
            mock_session.return_value = mock_sess
            http_request(
                "https://api.example.com",
                headers={"Authorization": "Bearer token123"},
            )

            # Verify headers were passed
            call_kwargs = mock_sess.request.call_args[1]
            assert "Authorization" in call_kwargs["headers"]
            assert call_kwargs["headers"]["Authorization"] == "Bearer token123"

    def test_request_with_params(self):
        """Test request with query parameters."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {}
        mock_response.json.return_value = {}
        mock_response.url = "https://api.example.com?q=test"

        with patch("namicode_cli.tools._get_http_session") as mock_session:
            mock_sess = MagicMock()
            mock_sess.request.return_value = mock_response
            mock_session.return_value = mock_sess
            http_request(
                "https://api.example.com",
                params={"q": "test", "limit": "10"},
            )

            call_kwargs = mock_sess.request.call_args[1]
            assert call_kwargs["params"] == {"q": "test", "limit": "10"}


class TestHttpRequestResponseHandling:
    """Test http_request response handling."""

    def test_non_json_response(self):
        """Test handling of non-JSON response (falls back to text)."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "text/html"}
        mock_response.json.side_effect = ValueError("No JSON")
        mock_response.text = "<html>Hello World</html>"
        mock_response.url = "https://example.com"
        # Mock iter_content for streaming
        mock_response.iter_content.return_value = [b"<html>Hello World</html>"]

        with patch("namicode_cli.tools._get_http_session") as mock_session:
            mock_sess = MagicMock()
            mock_sess.request.return_value = mock_response
            mock_session.return_value = mock_sess
            result = http_request("https://example.com")

        assert result["success"] is True
        assert result["content"] == "<html>Hello World</html>"

    def test_error_status_code(self):
        """Test handling of error HTTP status codes (4xx, 5xx)."""
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.headers = {}
        mock_response.json.return_value = {"error": "Not found"}
        mock_response.text = '{"error": "Not found"}'
        mock_response.reason = "Not Found"
        mock_response.url = "https://api.example.com/missing"

        with patch("namicode_cli.tools._get_http_session") as mock_session:
            mock_sess = MagicMock()
            mock_sess.request.return_value = mock_response
            mock_session.return_value = mock_sess
            result = http_request("https://api.example.com/missing")

        assert result["success"] is False  # 404 >= 400
        assert result["status_code"] == 404

    def test_server_error_status_code(self):
        """Test handling of server error status codes."""
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.headers = {}
        mock_response.json.return_value = {"error": "Internal server error"}
        mock_response.text = '{"error": "Internal server error"}'
        mock_response.reason = "Internal Server Error"
        mock_response.url = "https://api.example.com/broken"

        with patch("namicode_cli.tools._get_http_session") as mock_session:
            mock_sess = MagicMock()
            mock_sess.request.return_value = mock_response
            mock_session.return_value = mock_sess
            result = http_request("https://api.example.com/broken", max_retries=1)

        assert result["success"] is False
        assert result["status_code"] == 500


class TestHttpRequestErrorHandling:
    """Test http_request error handling."""

    def test_timeout_error(self):
        """Test handling of request timeout."""
        with patch("namicode_cli.tools._get_http_session") as mock_session:
            mock_sess = MagicMock()
            mock_sess.request.side_effect = requests.exceptions.Timeout("Connection timed out")
            mock_session.return_value = mock_sess
            result = http_request("https://api.example.com", timeout=5, max_retries=1)

        assert result["success"] is False
        assert result["status_code"] == 0
        assert "attempts" in result

    def test_connection_error(self):
        """Test handling of connection error."""
        with patch("namicode_cli.tools._get_http_session") as mock_session:
            mock_sess = MagicMock()
            mock_sess.request.side_effect = requests.exceptions.ConnectionError("Connection refused")
            mock_session.return_value = mock_sess
            result = http_request("https://invalid.example.com", max_retries=1)

        assert result["success"] is False
        assert result["status_code"] == 0
        assert "attempts" in result

    def test_generic_request_exception(self):
        """Test handling of generic request exception."""
        with patch("namicode_cli.tools._get_http_session") as mock_session:
            mock_sess = MagicMock()
            mock_sess.request.side_effect = requests.exceptions.RequestException("Unknown error")
            mock_session.return_value = mock_sess
            result = http_request("https://api.example.com", max_retries=1)

        assert result["success"] is False
        assert "attempts" in result

    def test_unexpected_exception(self):
        """Test handling of unexpected exception."""
        with patch("namicode_cli.tools._get_http_session") as mock_session:
            mock_sess = MagicMock()
            mock_sess.request.side_effect = RuntimeError("Something unexpected")
            mock_session.return_value = mock_sess
            result = http_request("https://api.example.com", max_retries=1)

        assert result["success"] is False
        assert "attempts" in result


class TestHttpRequestMethods:
    """Test different HTTP methods."""

    @pytest.mark.parametrize("method", ["GET", "POST", "PUT", "DELETE", "PATCH"])
    def test_http_methods(self, method):
        """Test that different HTTP methods are passed correctly."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {}
        mock_response.json.return_value = {}
        mock_response.url = "https://api.example.com"

        with patch("namicode_cli.tools._get_http_session") as mock_session:
            mock_sess = MagicMock()
            mock_sess.request.return_value = mock_response
            mock_session.return_value = mock_sess
            http_request("https://api.example.com", method=method)

            call_kwargs = mock_sess.request.call_args[1]
            assert call_kwargs["method"] == method.upper()

    def test_method_case_insensitive(self):
        """Test that method is converted to uppercase."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {}
        mock_response.json.return_value = {}
        mock_response.url = "https://api.example.com"

        with patch("namicode_cli.tools._get_http_session") as mock_session:
            mock_sess = MagicMock()
            mock_sess.request.return_value = mock_response
            mock_session.return_value = mock_sess
            http_request("https://api.example.com", method="post")

            call_kwargs = mock_sess.request.call_args[1]
            assert call_kwargs["method"] == "POST"


class TestHttpRequestTimeout:
    """Test timeout parameter."""

    def test_custom_timeout(self):
        """Test custom timeout is passed correctly."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {}
        mock_response.json.return_value = {}
        mock_response.url = "https://api.example.com"

        with patch("namicode_cli.tools._get_http_session") as mock_session:
            mock_sess = MagicMock()
            mock_sess.request.return_value = mock_response
            mock_session.return_value = mock_sess
            http_request("https://api.example.com", timeout=60)

            call_kwargs = mock_sess.request.call_args[1]
            # Timeout is now a tuple (connect_timeout, read_timeout)
            assert call_kwargs["timeout"] == (30, 60)  # (timeout//2, timeout)

    def test_default_timeout(self):
        """Test default timeout is 30 seconds."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.headers = {}
        mock_response.json.return_value = {}
        mock_response.url = "https://api.example.com"

        with patch("namicode_cli.tools._get_http_session") as mock_session:
            mock_sess = MagicMock()
            mock_sess.request.return_value = mock_response
            mock_session.return_value = mock_sess
            http_request("https://api.example.com")

            call_kwargs = mock_sess.request.call_args[1]
            assert call_kwargs["timeout"] == (15, 30)  # (timeout//2, timeout)

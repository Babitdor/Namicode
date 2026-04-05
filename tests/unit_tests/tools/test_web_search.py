"""Unit tests for web_search tool."""

from unittest.mock import MagicMock, patch


class TestWebSearchNoApiKey:
    """Test web_search when Tavily API key is not configured."""

    def test_no_api_key_returns_error(self):
        """Test that web_search returns error when API key is not set."""
        # We need to patch the module-level tavily_client
        with patch("NovaCode_cli.tools.tavily_client", None):
            from novacode_cli.tools import web_search

            result = web_search("test query")

        assert "error" in result
        assert "API key not configured" in result["error"]
        assert result["query"] == "test query"


class TestWebSearchWithApiKey:
    """Test web_search when Tavily API key is configured."""

    def test_successful_search(self):
        """Test successful web search."""
        mock_tavily = MagicMock()
        mock_tavily.search.return_value = {
            "results": [
                {
                    "title": "Result 1",
                    "url": "https://example.com/1",
                    "content": "Relevant content 1",
                    "score": 0.95,
                },
                {
                    "title": "Result 2",
                    "url": "https://example.com/2",
                    "content": "Relevant content 2",
                    "score": 0.85,
                },
            ],
            "query": "test query",
        }

        with patch("NovaCode_cli.tools.tavily_client", mock_tavily):
            from novacode_cli.tools import web_search

            result = web_search("test query")

        assert "results" in result
        assert len(result["results"]) == 2
        assert result["results"][0]["title"] == "Result 1"
        mock_tavily.search.assert_called_once_with(
            "test query",
            max_results=5,
            include_raw_content=False,
            topic="general",
        )

    def test_search_with_max_results(self):
        """Test search with custom max_results."""
        mock_tavily = MagicMock()
        mock_tavily.search.return_value = {"results": [], "query": "test"}

        with patch("NovaCode_cli.tools.tavily_client", mock_tavily):
            from novacode_cli.tools import web_search

            web_search("test query", max_results=10)

        mock_tavily.search.assert_called_once_with(
            "test query",
            max_results=10,
            include_raw_content=False,
            topic="general",
        )

    def test_search_with_news_topic(self):
        """Test search with news topic type."""
        mock_tavily = MagicMock()
        mock_tavily.search.return_value = {"results": [], "query": "test"}

        with patch("NovaCode_cli.tools.tavily_client", mock_tavily):
            from novacode_cli.tools import web_search

            web_search("latest news", topic="news")

        mock_tavily.search.assert_called_once_with(
            "latest news",
            max_results=5,
            include_raw_content=False,
            topic="news",
        )

    def test_search_with_finance_topic(self):
        """Test search with finance topic type."""
        mock_tavily = MagicMock()
        mock_tavily.search.return_value = {"results": [], "query": "test"}

        with patch("NovaCode_cli.tools.tavily_client", mock_tavily):
            from novacode_cli.tools import web_search

            web_search("stock prices", topic="finance")

        mock_tavily.search.assert_called_once_with(
            "stock prices",
            max_results=5,
            include_raw_content=False,
            topic="finance",
        )

    def test_search_with_raw_content(self):
        """Test search with include_raw_content enabled."""
        mock_tavily = MagicMock()
        mock_tavily.search.return_value = {"results": [], "query": "test"}

        with patch("NovaCode_cli.tools.tavily_client", mock_tavily):
            from novacode_cli.tools import web_search

            web_search("test query", include_raw_content=True)

        mock_tavily.search.assert_called_once_with(
            "test query",
            max_results=5,
            include_raw_content=True,
            topic="general",
        )


class TestWebSearchErrorHandling:
    """Test web_search error handling."""

    def test_tavily_api_error(self):
        """Test handling of Tavily API errors."""
        mock_tavily = MagicMock()
        mock_tavily.search.side_effect = Exception("API rate limit exceeded")

        with patch("NovaCode_cli.tools.tavily_client", mock_tavily):
            from novacode_cli.tools import web_search

            result = web_search("test query")

        assert "error" in result
        assert "Web search error" in result["error"]
        assert "API rate limit exceeded" in result["error"]
        assert result["query"] == "test query"

    def test_network_error(self):
        """Test handling of network errors."""
        mock_tavily = MagicMock()
        mock_tavily.search.side_effect = ConnectionError("Network unreachable")

        with patch("NovaCode_cli.tools.tavily_client", mock_tavily):
            from novacode_cli.tools import web_search

            result = web_search("test query")

        assert "error" in result
        assert "Web search error" in result["error"]
        assert result["query"] == "test query"


class TestWebSearchParameters:
    """Test web_search parameter handling."""

    def test_all_parameters_combined(self):
        """Test search with all parameters specified."""
        mock_tavily = MagicMock()
        mock_tavily.search.return_value = {"results": [], "query": "test"}

        with patch("NovaCode_cli.tools.tavily_client", mock_tavily):
            from novacode_cli.tools import web_search

            web_search(
                "financial news today",
                max_results=3,
                topic="news",
                include_raw_content=True,
            )

        mock_tavily.search.assert_called_once_with(
            "financial news today",
            max_results=3,
            include_raw_content=True,
            topic="news",
        )

    def test_default_parameters(self):
        """Test that default parameters are correct."""
        mock_tavily = MagicMock()
        mock_tavily.search.return_value = {"results": [], "query": "test"}

        with patch("NovaCode_cli.tools.tavily_client", mock_tavily):
            from novacode_cli.tools import web_search

            web_search("simple query")

        # Verify defaults: max_results=5, topic="general", include_raw_content=False
        mock_tavily.search.assert_called_once_with(
            "simple query",
            max_results=5,
            include_raw_content=False,
            topic="general",
        )

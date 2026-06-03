"""Tools package for novacode_cli.

This package provides various tools for the CLI agent, organized into submodules:
- http_tools: HTTP request tools
- web_tools: Web search tools (Tavily, DuckDuckGo, docs search)
- fetch_tools: URL fetching and content conversion
- package_tools: Package information from registries
- format_tools: Format conversion (JSON, YAML, TOML)
- memory_tools: Memory management tools
- time_tools: Time and date tools
- reflection_tools: Reflection tools for strategic thinking
- graph_tools: Project knowledge-graph query tool
- code_search_tools: Semantic code search (Semble-powered, optional)
"""

# URL fetching tools
from novacode_cli.tools.fetch_tools import fetch_url

# Format conversion tools
from novacode_cli.tools.format_tools import convert_format

# HTTP tools
from novacode_cli.tools.http_tools import http_request

# Memory tools
from novacode_cli.tools.memory_tools import (
    create_memory_structure,
    read_memory,
    write_memory,
)

# Package information tools
from novacode_cli.tools.package_tools import package_info

# Project graph query tool
from novacode_cli.tools.graph_tools import query_project_graph

# Code search tools (Semble-powered, optional — gracefully degrades)
try:
    from novacode_cli.tools.code_search_tools import (
        code_search,
        find_related_code,
        _is_semble_available as _semble_avail,
    )
except ImportError:
    code_search = None  # type: ignore[assignment]
    find_related_code = None  # type: ignore[assignment]
    _semble_avail = lambda: False  # type: ignore[assignment]

# Reflection tools
from novacode_cli.tools.reflection_tools import think

# Time tools
from novacode_cli.tools.time_tools import get_current_time

# Web search tools
from novacode_cli.tools.web_tools import (
    docs_search,
    duckduckgo_search,
    web_search,
)

__all__ = [
    # Format conversion tools
    "convert_format",
    "create_memory_structure",
    "docs_search",
    "duckduckgo_search",
    # URL fetching tools
    "fetch_url",
    # Time tools
    "get_current_time",
    # HTTP tools
    "http_request",
    # Package information tools
    "package_info",
    # Project graph query tool
    "query_project_graph",
    "read_memory",
    # Reflection tools
    "think",
    # Web search tools
    "web_search",
    # Memory tools
    "write_memory",
    # Code search tools (Semble-powered, optional)
    "code_search",
    "find_related_code",
]

"""Tools package for novacode_cli.

This package provides various tools for the CLI agent, organized into submodules:
- web_tools: Web search tools (Tavily, DuckDuckGo, docs search)
- fetch_tools: URL fetching and content conversion (merged from http_tools)
- package_tools: Package information from registries
- memory_tools: Memory management tools
- reflection_tools: Reflection tools for strategic thinking
- graph_tools: Project knowledge-graph query tool
- code_search_tools: Semantic code search (Semble-powered, optional)
"""

# URL fetching tools (covers all HTTP methods — http_request merged into fetch_url)
from novacode_cli.tools.fetch_tools import fetch_url

# Memory tools (markdown files injected into the prompt)
from novacode_cli.tools.memory_tools import (
    read_memory,
    write_memory,
)

# Structured, durable, cross-session memory (key/value via the LangGraph store)
from novacode_cli.tools.store_memory_tools import (
    forget,
    list_memories,
    recall,
    remember,
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

# Web search tools
from novacode_cli.tools.web_tools import (
    docs_search,
    duckduckgo_search,
    web_search,
)

__all__ = [
    "docs_search",
    "duckduckgo_search",
    # URL fetching tools
    "fetch_url",
    # Package information tools
    "package_info",
    # Project graph query tool
    "query_project_graph",
    "read_memory",
    # Structured durable memory (LangGraph store)
    "remember",
    "recall",
    "list_memories",
    "forget",
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

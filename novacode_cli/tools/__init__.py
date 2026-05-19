"""Tools package for novacode_cli.

This package provides various tools for the CLI agent, organized into submodules:
- http_tools: HTTP request tools
- web_tools: Web search tools (Tavily, DuckDuckGo, docs search)
- fetch_tools: URL fetching and content conversion
- code_exec: Code execution in E2B sandboxes
- package_tools: Package information from registries
- format_tools: Format conversion (JSON, YAML, TOML)
- lint_tools: Code linting tools
- format_code_tools: Code formatting tools
- typecheck_tools: Type checking tools
- browser_tools: Browser automation and console capture
- memory_tools: Memory management tools
- time_tools: Time and date tools
- reflection_tools: Reflection tools for strategic thinking
- git_tools: Git version control tools
- lsp_tools: Language Server Protocol tools
- code_search_tools: Semantic code search (Semble-powered, optional)
"""

# HTTP tools
# Browser tools
from novacode_cli.tools.browser_tools import (
    browser_automate,
    capture_browser_console,
)

# Code execution tools
from novacode_cli.tools.code_exec import execute_in_e2b

# URL fetching tools
from novacode_cli.tools.fetch_tools import fetch_url

# Code formatting tools
from novacode_cli.tools.format_code_tools import format_code_file

# Format conversion tools
from novacode_cli.tools.format_tools import convert_format

# Git tools
from novacode_cli.tools.git_tools import (
    git_blame,
    git_diff,
    git_log,
    git_status,
)
from novacode_cli.tools.http_tools import http_request

# Code linting tools
from novacode_cli.tools.lint_tools import lint_code

# LSP tools
from novacode_cli.tools.lsp_tools import (
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

# Type checking tools
from novacode_cli.tools.typecheck_tools import check_types

# Web search tools
from novacode_cli.tools.web_tools import (
    docs_search,
    duckduckgo_search,
    web_search,
)

__all__ = [
    "browser_automate",
    # Browser tools
    "capture_browser_console",
    # Type checking tools
    "check_types",
    # Format conversion tools
    "convert_format",
    "create_memory_structure",
    "docs_search",
    "duckduckgo_search",
    # Code execution tools
    "execute_in_e2b",
    # URL fetching tools
    "fetch_url",
    # Code formatting tools
    "format_code_file",
    # Time tools
    "get_current_time",
    "git_blame",
    "git_diff",
    "git_log",
    # Git tools
    "git_status",
    # HTTP tools
    "http_request",
    # Code linting tools
    "lint_code",
    "lsp_completions",
    "lsp_diagnostics",
    "lsp_document_symbols",
    "lsp_find_references",
    # LSP tools
    "lsp_goto_definition",
    "lsp_hover",
    "lsp_implementation",
    "lsp_rename",
    "lsp_signature_help",
    "lsp_type_definition",
    "lsp_workspace_symbols",
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

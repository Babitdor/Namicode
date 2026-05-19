"""Format conversion tools.

This module provides tools for converting between JSON, YAML, and TOML formats.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from langchain.tools import tool


@tool
def convert_format(
    content: str,
    from_format: Literal["json", "yaml", "toml"],
    to_format: Literal["json", "yaml", "toml"],
    indent: int = 2,
) -> dict[str, Any]:
    r"""Convert between JSON, YAML, and TOML data formats.

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
                        "error": (
                            "TOML parser not available. Requires Python 3.11+ or: uv add tomli"
                        ),
                    }
            data = tomllib.loads(content)

        else:
            return {"success": False, "error": f"Unknown source format: {from_format}"}

    except json.JSONDecodeError as e:
        return {"success": False, "error": f"Invalid JSON: {e!s}"}
    except Exception as e:  # noqa: BLE001
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

    except Exception as e:  # noqa: BLE001
        return {"success": False, "error": f"Failed to convert to {to_format}: {e!s}"}

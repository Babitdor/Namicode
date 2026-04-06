"""Language Server Protocol (LSP) tools for code intelligence.

This module provides LSP-like functionality for code analysis without requiring
a full LSP server. It uses Jedi for Python and can be extended for other languages.

Key Tools:
- lsp_goto_definition(): Navigate to symbol definitions
- lsp_find_references(): Find all references to a symbol
- lsp_hover(): Get documentation and type info for symbols
- lsp_completions(): Get auto-complete suggestions
- lsp_document_symbols(): List all symbols in a file
- lsp_workspace_symbols(): Search symbols across the workspace
- lsp_diagnostics(): Get syntax errors and type errors
- lsp_rename(): Rename a symbol across files

These tools enable the agent to:
- Understand code structure and relationships
- Navigate codebases efficiently
- Get inline documentation
- Find usages of functions, classes, and variables
- Detect errors before running code

Dependencies:
- jedi: Python static analysis (already installed)
- pyright/pylance: Optional for TypeScript/JavaScript support
"""

import ast
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Literal


def _get_jedi_script(file_path: str, content: str | None = None):
    """Get a Jedi Script object for the given file.

    Args:
        file_path: Path to the Python file
        content: Optional file content (reads from disk if not provided)

    Returns:
        Jedi Script object or None if jedi not available
    """
    try:
        import jedi

        if content is None:
            try:
                content = Path(file_path).read_text(encoding="utf-8")
            except Exception:
                content = ""

        # Get the project root for better analysis
        project_path = Path(file_path).parent
        while project_path.parent != project_path:
            if (project_path / "pyproject.toml").exists() or (project_path / "setup.py").exists():
                break
            project_path = project_path.parent

        return jedi.Script(code=content, path=file_path, project=jedi.Project(str(project_path)))
    except ImportError:
        return None


def _get_line_content(file_path: str, line: int) -> str:
    """Get the content of a specific line in a file.

    Args:
        file_path: Path to the file
        line: Line number (1-indexed)

    Returns:
        The line content or empty string if not found
    """
    try:
        lines = Path(file_path).read_text(encoding="utf-8").splitlines()
        if 0 < line <= len(lines):
            return lines[line - 1]
    except Exception:
        pass
    return ""


def _format_location(file_path: str, line: int, column: int) -> str:
    """Format a location for display.

    Args:
        file_path: Path to the file
        line: Line number (1-indexed)
        column: Column number (0-indexed)

    Returns:
        Formatted location string
    """
    return f"{file_path}:{line}:{column}"


def _symbol_kind_to_string(kind: int) -> str:
    """Convert LSP symbol kind to string.

    Args:
        kind: LSP SymbolKind integer

    Returns:
        Human-readable symbol kind
    """
    kinds = {
        1: "file",
        2: "module",
        3: "namespace",
        4: "package",
        5: "class",
        6: "method",
        7: "property",
        8: "field",
        9: "constructor",
        10: "enum",
        11: "interface",
        12: "function",
        13: "variable",
        14: "constant",
        15: "string",
        16: "number",
        17: "boolean",
        18: "array",
        19: "object",
        20: "key",
        21: "null",
        22: "enum_member",
        23: "struct",
        24: "event",
        25: "operator",
        26: "type_parameter",
    }
    return kinds.get(kind, "unknown")


def lsp_goto_definition(
    file_path: str,
    line: int,
    column: int,
) -> dict[str, Any]:
    """Navigate to the definition of a symbol.

    Finds where a symbol (function, class, variable) is defined. Works across
    files and follows imports.

    Args:
        file_path: Path to the file containing the symbol
        line: Line number (1-indexed) where the symbol appears
        column: Column number (0-indexed) where the symbol starts

    Returns:
        Dictionary containing:
        - success: Whether the operation succeeded
        - definitions: List of definition locations, each with:
            - file_path: Path to the definition file
            - line: Line number (1-indexed)
            - column: Column number (0-indexed)
            - text: The line content at the definition
            - description: Brief description of the definition
        - symbol: The symbol that was analyzed
        - error: Error message if operation failed

    Example:
        # Find definition of a function call
        lsp_goto_definition("src/main.py", 42, 15)

        # Find definition of an imported class
        lsp_goto_definition("src/utils.py", 10, 8)
    """
    try:
        import jedi
    except ImportError:
        return {
            "success": False,
            "error": "jedi not installed. Install with: pip install jedi",
            "definitions": [],
        }

    try:
        # Read file content
        content = Path(file_path).read_text(encoding="utf-8")

        # Create Jedi script
        script = _get_jedi_script(file_path, content)
        if script is None:
            return {"success": False, "error": "Failed to create Jedi script", "definitions": []}

        # Get definitions
        definitions = script.goto(line, column, follow_imports=True)

        results = []
        for defn in definitions:
            if defn.module_path:
                defn_line = defn.line or 1
                defn_col = defn.column or 0
                line_content = _get_line_content(str(defn.module_path), defn_line)

                results.append({
                    "file_path": str(defn.module_path),
                    "line": defn_line,
                    "column": defn_col,
                    "text": line_content.strip(),
                    "description": defn.description or "",
                    "name": defn.name,
                    "type": defn.type,
                })

        if not results:
            return {
                "success": True,
                "definitions": [],
                "message": "No definition found. The symbol may be built-in or defined externally.",
            }

        return {
            "success": True,
            "definitions": results,
            "symbol": definitions[0].name if definitions else None,
            "count": len(results),
        }

    except Exception as e:
        return {
            "success": False,
            "error": f"Error finding definition: {e!s}",
            "definitions": [],
        }


def lsp_find_references(
    file_path: str,
    line: int,
    column: int,
    include_declaration: bool = True,
) -> dict[str, Any]:
    """Find all references to a symbol across the workspace.

    Searches for all usages of a symbol (function, class, variable) across
    all Python files in the project.

    Args:
        file_path: Path to the file containing the symbol
        line: Line number (1-indexed) where the symbol appears
        column: Column number (0-indexed) where the symbol starts
        include_declaration: Whether to include the symbol's declaration

    Returns:
        Dictionary containing:
        - success: Whether the operation succeeded
        - references: List of reference locations, each with:
            - file_path: Path to the file
            - line: Line number (1-indexed)
            - column: Column number (0-indexed)
            - text: The line content
            - is_declaration: Whether this is the declaration
        - symbol: The symbol that was analyzed
        - count: Total number of references found
        - error: Error message if operation failed

    Example:
        # Find all usages of a function
        lsp_find_references("src/utils.py", 15, 4)

        # Find all usages excluding the definition
        lsp_find_references("src/main.py", 42, 10, include_declaration=False)
    """
    try:
        import jedi
    except ImportError:
        return {
            "success": False,
            "error": "jedi not installed. Install with: pip install jedi",
            "references": [],
        }

    try:
        # Read file content
        content = Path(file_path).read_text(encoding="utf-8")

        # Create Jedi script
        script = _get_jedi_script(file_path, content)
        if script is None:
            return {"success": False, "error": "Failed to create Jedi script", "references": []}

        # Get references
        references = script.get_references(line, column)

        results = []
        for ref in references:
            if ref.module_path:
                ref_line = ref.line or 1
                ref_col = ref.column or 0
                line_content = _get_line_content(str(ref.module_path), ref_line)

                is_decl = ref.is_definition() if hasattr(ref, "is_definition") else False

                if not include_declaration and is_decl:
                    continue

                results.append({
                    "file_path": str(ref.module_path),
                    "line": ref_line,
                    "column": ref_col,
                    "text": line_content.strip(),
                    "is_declaration": is_decl,
                    "name": ref.name,
                })

        return {
            "success": True,
            "references": results,
            "symbol": references[0].name if references else None,
            "count": len(results),
        }

    except Exception as e:
        return {
            "success": False,
            "error": f"Error finding references: {e!s}",
            "references": [],
        }


def lsp_hover(
    file_path: str,
    line: int,
    column: int,
) -> dict[str, Any]:
    """Get documentation and type information for a symbol.

    Retrieves hover information including docstrings, type hints, and
    inferred types for any symbol in the code.

    Args:
        file_path: Path to the file containing the symbol
        line: Line number (1-indexed) where the symbol appears
        column: Column number (0-indexed) where the symbol starts

    Returns:
        Dictionary containing:
        - success: Whether the operation succeeded
        - hover: Dictionary with:
            - name: Symbol name
            - type: Inferred type or type hint
            - docstring: Documentation string (if available)
            - signature: Function/method signature (if applicable)
            - module: Module where defined
            - line: Line number where defined
        - text: The line content where the symbol appears
        - error: Error message if operation failed

    Example:
        # Get documentation for a function
        lsp_hover("src/utils.py", 15, 4)

        # Get type info for a variable
        lsp_hover("src/main.py", 42, 10)
    """
    try:
        import jedi
    except ImportError:
        return {
            "success": False,
            "error": "jedi not installed. Install with: pip install jedi",
            "hover": {},
        }

    try:
        # Read file content
        content = Path(file_path).read_text(encoding="utf-8")

        # Create Jedi script
        script = _get_jedi_script(file_path, content)
        if script is None:
            return {"success": False, "error": "Failed to create Jedi script", "hover": {}}

        # Get hover info
        hovers = script.help(line, column)

        if not hovers:
            # Try inference as fallback
            infers = script.infer(line, column)
            if infers:
                hovers = infers

        if not hovers:
            line_content = _get_line_content(file_path, line)
            return {
                "success": True,
                "hover": None,
                "message": "No hover information available for this position",
                "text": line_content.strip(),
            }

        # Get the first (most relevant) hover
        hover = hovers[0]

        hover_info = {
            "name": hover.name,
            "type": hover.type,
            "module_path": str(hover.module_path) if hover.module_path else None,
            "module_name": hover.module_name,
            "line": hover.line,
            "column": hover.column,
            "description": hover.description,
            "docstring": None,
            "signature": None,
        }

        # Get docstring if available
        if hasattr(hover, "docstring") and hover.docstring:
            hover_info["docstring"] = hover.docstring()

        # Get signature for callables
        if hasattr(hover, "get_signatures"):
            try:
                sigs = hover.get_signatures()
                if sigs:
                    hover_info["signature"] = sigs[0].to_string()
            except Exception:
                pass

        line_content = _get_line_content(file_path, line)

        return {
            "success": True,
            "hover": hover_info,
            "text": line_content.strip(),
            "position": {"line": line, "column": column},
        }

    except Exception as e:
        return {
            "success": False,
            "error": f"Error getting hover info: {e!s}",
            "hover": {},
        }


def lsp_completions(
    file_path: str,
    line: int,
    column: int,
    prefix: str = "",
    fuzzy: bool = True,
) -> dict[str, Any]:
    """Get auto-complete suggestions at a position.

    Returns completion suggestions for code at the given position, including
    function signatures, variable names, and import suggestions.

    Args:
        file_path: Path to the file
        line: Line number (1-indexed) where completions are requested
        column: Column number (0-indexed) where completions are requested
        prefix: Optional prefix to filter completions
        fuzzy: Whether to use fuzzy matching for completions

    Returns:
        Dictionary containing:
        - success: Whether the operation succeeded
        - completions: List of completion items, each with:
            - name: The completion text
            - type: Type of completion (function, class, variable, etc.)
            - signature: Function signature (if applicable)
            - docstring: Brief documentation (if available)
            - module: Module where defined
        - prefix: The prefix used for filtering
        - count: Number of completions returned
        - error: Error message if operation failed

    Example:
        # Get completions after typing "os."
        lsp_completions("src/main.py", 10, 5, prefix="os.")

        # Get completions for a variable name
        lsp_completions("src/utils.py", 25, 12)
    """
    try:
        import jedi
    except ImportError:
        return {
            "success": False,
            "error": "jedi not installed. Install with: pip install jedi",
            "completions": [],
        }

    try:
        # Read file content
        content = Path(file_path).read_text(encoding="utf-8")

        # Create Jedi script
        script = _get_jedi_script(file_path, content)
        if script is None:
            return {"success": False, "error": "Failed to create Jedi script", "completions": []}

        # Get completions
        completions = script.complete(line, column, fuzzy=fuzzy)

        results = []
        for comp in completions:
            # Filter by prefix if provided
            if prefix and not comp.name.lower().startswith(prefix.lower()):
                if fuzzy and prefix.lower() not in comp.name.lower():
                    continue

            comp_info = {
                "name": comp.name,
                "type": comp.type,
                "module_path": str(comp.module_path) if comp.module_path else None,
                "module_name": comp.module_name,
            }

            # Get signature for callables
            if hasattr(comp, "get_signatures"):
                try:
                    sigs = comp.get_signatures()
                    if sigs:
                        comp_info["signature"] = sigs[0].to_string()
                except Exception:
                    pass

            # Get docstring
            if hasattr(comp, "docstring"):
                try:
                    doc = comp.docstring()
                    if doc:
                        # Get first line of docstring for brief description
                        comp_info["docstring"] = doc.split("\n")[0][:200]
                except Exception:
                    pass

            results.append(comp_info)

        # Sort by relevance
        def sort_key(c):
            # Prioritize exact matches, then by type, then alphabetically
            name = c["name"]
            type_priority = {"class": 0, "function": 1, "instance": 2, "module": 3, "statement": 4}
            return (0 if name.lower().startswith(prefix.lower()) else 1, type_priority.get(c["type"], 5), name)

        results.sort(key=sort_key)

        # Limit results
        max_results = 50
        if len(results) > max_results:
            results = results[:max_results]

        return {
            "success": True,
            "completions": results,
            "prefix": prefix,
            "count": len(results),
        }

    except Exception as e:
        return {
            "success": False,
            "error": f"Error getting completions: {e!s}",
            "completions": [],
        }


def lsp_document_symbols(
    file_path: str,
) -> dict[str, Any]:
    """List all symbols (classes, functions, variables) in a file.

    Parses the file and returns a hierarchical list of all symbols with
    their locations and types.

    Args:
        file_path: Path to the file to analyze

    Returns:
        Dictionary containing:
        - success: Whether the operation succeeded
        - symbols: List of symbols, each with:
            - name: Symbol name
            - kind: Symbol kind (class, function, variable, etc.)
            - line: Line number (1-indexed)
            - column: Column number (0-indexed)
            - end_line: End line number
            - docstring: Brief documentation (if available)
            - children: Nested symbols (for classes)
        - file_path: The analyzed file path
        - count: Number of top-level symbols
        - error: Error message if operation failed

    Example:
        # Get all symbols in a file
        lsp_document_symbols("src/utils.py")

        # Get symbols for a class-heavy file
        lsp_document_symbols("src/models/user.py")
    """
    try:
        import jedi
    except ImportError:
        return {
            "success": False,
            "error": "jedi not installed. Install with: pip install jedi",
            "symbols": [],
        }

    try:
        # Read file content
        content = Path(file_path).read_text(encoding="utf-8")

        # Create Jedi script
        script = _get_jedi_script(file_path, content)
        if script is None:
            return {"success": False, "error": "Failed to create Jedi script", "symbols": []}

        # Get names in the file
        names = script.get_names(all_scopes=True, definitions=True)

        # Build symbol tree
        def build_symbol_tree(names_list, parent_line=None):
            symbols = []
            for name in names_list:
                if name.module_path and str(name.module_path) == file_path:
                    symbol = {
                        "name": name.name,
                        "kind": name.type,
                        "line": name.line or 1,
                        "column": name.column or 0,
                        "docstring": None,
                        "children": [],
                    }

                    # Get docstring
                    if hasattr(name, "docstring"):
                        try:
                            doc = name.docstring()
                            if doc:
                                symbol["docstring"] = doc.split("\n")[0][:200]
                        except Exception:
                            pass

                    symbols.append(symbol)

            return symbols

        results = build_symbol_tree(names)

        # Also use AST for more accurate symbol extraction
        try:
            tree = ast.parse(content)
            ast_symbols = []

            for node in ast.iter_child_nodes(tree):
                if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                    ast_symbols.append({
                        "name": node.name,
                        "kind": "function",
                        "line": node.lineno,
                        "column": node.col_offset,
                        "docstring": ast.get_docstring(node),
                        "children": [],
                    })
                elif isinstance(node, ast.ClassDef):
                    class_symbol = {
                        "name": node.name,
                        "kind": "class",
                        "line": node.lineno,
                        "column": node.col_offset,
                        "docstring": ast.get_docstring(node),
                        "children": [],
                    }
                    # Get class methods
                    for child in node.body:
                        if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                            class_symbol["children"].append({
                                "name": child.name,
                                "kind": "method",
                                "line": child.lineno,
                                "column": child.col_offset,
                                "docstring": ast.get_docstring(child),
                            })
                    ast_symbols.append(class_symbol)
                elif isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            ast_symbols.append({
                                "name": target.id,
                                "kind": "variable",
                                "line": node.lineno,
                                "column": node.col_offset,
                                "docstring": None,
                                "children": [],
                            })

            # Merge Jedi and AST results (prefer AST for structure)
            if ast_symbols:
                results = ast_symbols

        except SyntaxError:
            # Fall back to Jedi results if AST parsing fails
            pass

        return {
            "success": True,
            "symbols": results,
            "file_path": file_path,
            "count": len(results),
        }

    except Exception as e:
        return {
            "success": False,
            "error": f"Error getting document symbols: {e!s}",
            "symbols": [],
        }


def lsp_workspace_symbols(
    query: str,
    workspace_path: str,
    symbol_kind: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    """Search for symbols across the entire workspace.

    Searches for classes, functions, and variables matching a query across
    all Python files in the workspace.

    Args:
        query: Search query (symbol name or pattern)
        workspace_path: Root directory of the workspace
        symbol_kind: Optional filter by symbol kind (class, function, variable)
        limit: Maximum number of results (default: 50)

    Returns:
        Dictionary containing:
        - success: Whether the operation succeeded
        - symbols: List of matching symbols, each with:
            - name: Symbol name
            - kind: Symbol kind
            - file_path: Path to the file
            - line: Line number (1-indexed)
            - column: Column number (0-indexed)
            - docstring: Brief documentation (if available)
        - query: The search query
        - count: Number of results returned
        - error: Error message if operation failed

    Example:
        # Search for a class by name
        lsp_workspace_symbols("UserManager", "/workspace")

        # Search for all functions matching a pattern
        lsp_workspace_symbols("get_*", "/workspace", symbol_kind="function")
    """
    try:
        import jedi
    except ImportError:
        return {
            "success": False,
            "error": "jedi not installed. Install with: pip install jedi",
            "symbols": [],
        }

    try:
        workspace = Path(workspace_path)
        if not workspace.exists():
            return {"success": False, "error": f"Workspace not found: {workspace_path}", "symbols": []}

        results = []
        query_lower = query.lower()

        # Find all Python files
        python_files = list(workspace.rglob("*.py"))

        # Limit files to search for performance
        max_files = 500
        if len(python_files) > max_files:
            # Prioritize files in common source directories
            priority_dirs = ["src", "lib", "app", "novacode_cli", "deepagents"]
            prioritized = []
            for pd in priority_dirs:
                prioritized.extend([f for f in python_files if pd in str(f)])
            python_files = prioritized[:max_files] if prioritized else python_files[:max_files]

        for py_file in python_files:
            try:
                content = py_file.read_text(encoding="utf-8")

                # Quick text search first
                if query_lower not in content.lower():
                    continue

                # Parse with AST for accurate symbol locations
                try:
                    tree = ast.parse(content)
                    for node in ast.walk(tree):
                        symbol_name = None
                        kind = None

                        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                            symbol_name = node.name
                            kind = "function"
                        elif isinstance(node, ast.ClassDef):
                            symbol_name = node.name
                            kind = "class"
                        elif isinstance(node, ast.Assign):
                            for target in node.targets:
                                if isinstance(target, ast.Name):
                                    symbol_name = target.id
                                    kind = "variable"

                        if symbol_name and query_lower in symbol_name.lower():
                            # Filter by kind if specified
                            if symbol_kind and kind != symbol_kind:
                                continue

                            results.append({
                                "name": symbol_name,
                                "kind": kind,
                                "file_path": str(py_file.relative_to(workspace)),
                                "line": node.lineno,
                                "column": node.col_offset,
                                "docstring": ast.get_docstring(node) if hasattr(node, "body") else None,
                            })

                            if len(results) >= limit:
                                break

                except SyntaxError:
                    continue

            except Exception:
                continue

            if len(results) >= limit:
                break

        # Sort by relevance (exact match first, then by file path)
        def sort_key(r):
            name_lower = r["name"].lower()
            return (0 if name_lower == query_lower else 1, r["file_path"])

        results.sort(key=sort_key)

        return {
            "success": True,
            "symbols": results,
            "query": query,
            "workspace": str(workspace),
            "count": len(results),
        }

    except Exception as e:
        return {
            "success": False,
            "error": f"Error searching workspace symbols: {e!s}",
            "symbols": [],
        }


def lsp_diagnostics(
    file_path: str,
    include_warnings: bool = True,
    include_style: bool = False,
) -> dict[str, Any]:
    """Get syntax errors, type errors, and linting issues for a file.

    Analyzes a Python file for errors, warnings, and style issues using
    AST parsing and optional linting tools.

    Args:
        file_path: Path to the file to analyze
        include_warnings: Whether to include warnings (default: True)
        include_style: Whether to include style issues (default: False)

    Returns:
        Dictionary containing:
        - success: Whether the operation succeeded
        - diagnostics: List of issues, each with:
            - message: The diagnostic message
            - severity: "error", "warning", or "info"
            - line: Line number (1-indexed)
            - column: Column number (0-indexed)
            - end_line: End line number (if applicable)
            - end_column: End column number
            - code: Error code (if available)
            - source: Source of the diagnostic (syntax, type, lint)
        - file_path: The analyzed file path
        - error_count: Number of errors
        - warning_count: Number of warnings
        - error: Error message if operation failed

    Example:
        # Get all errors and warnings
        lsp_diagnostics("src/main.py")

        # Get only errors
        lsp_diagnostics("src/utils.py", include_warnings=False)
    """
    try:
        # Read file content
        content = Path(file_path).read_text(encoding="utf-8")
        diagnostics = []
        error_count = 0
        warning_count = 0

        # Parse with AST for syntax errors
        try:
            tree = ast.parse(content)
        except SyntaxError as e:
            diagnostics.append({
                "message": str(e),
                "severity": "error",
                "line": e.lineno or 1,
                "column": e.offset or 0,
                "end_line": e.lineno or 1,
                "end_column": (e.offset or 0) + 1,
                "code": "E001",
                "source": "syntax",
            })
            error_count += 1
            return {
                "success": True,
                "diagnostics": diagnostics,
                "file_path": file_path,
                "error_count": error_count,
                "warning_count": warning_count,
                "has_syntax_error": True,
            }

        # Check for undefined variables using Jedi
        try:
            import jedi

            script = _get_jedi_script(file_path, content)
            if script:
                # Get syntax errors from Jedi
                for error in script.get_syntax_errors():
                    diagnostics.append({
                        "message": error.message,
                        "severity": "error",
                        "line": error.line,
                        "column": error.column,
                        "end_line": error.until_line,
                        "end_column": error.until_column,
                        "code": "E002",
                        "source": "syntax",
                    })
                    error_count += 1
        except ImportError:
            pass

        # Try to use ruff for linting if available
        try:
            result = subprocess.run(
                [sys.executable, "-m", "ruff", "check", "--output-format=json", file_path],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.stdout:
                issues = json.loads(result.stdout)
                for issue in issues:
                    severity = "error" if issue.get("severity") == "error" else "warning"
                    if severity == "error" or include_warnings:
                        diagnostics.append({
                            "message": issue.get("message", ""),
                            "severity": severity,
                            "line": issue.get("location", {}).get("row", 1),
                            "column": issue.get("location", {}).get("column", 0),
                            "end_line": issue.get("end_location", {}).get("row"),
                            "end_column": issue.get("end_location", {}).get("column"),
                            "code": issue.get("code", ""),
                            "source": "ruff",
                        })
                        if severity == "error":
                            error_count += 1
                        else:
                            warning_count += 1
        except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError):
            pass

        # Try pyflakes for additional checks
        try:
            from pyflakes import api as pyflakes_api
            from pyflakes import checker

            class DiagnosticCollector:
                def __init__(self):
                    self.issues = []

                def flake(self, message):
                    self.issues.append(message)

            collector = DiagnosticCollector()
            pyflakes_api.check(content, file_path, collector)

            for issue in collector.issues:
                diagnostics.append({
                    "message": str(issue),
                    "severity": "warning",
                    "line": getattr(issue, "lineno", 1) or 1,
                    "column": getattr(issue, "col_offset", 0) or 0,
                    "code": "W001",
                    "source": "pyflakes",
                })
                warning_count += 1
        except ImportError:
            pass

        # Sort by line number
        diagnostics.sort(key=lambda d: (d.get("line", 0), d.get("column", 0)))

        return {
            "success": True,
            "diagnostics": diagnostics,
            "file_path": file_path,
            "error_count": error_count,
            "warning_count": warning_count,
            "has_syntax_error": False,
        }

    except Exception as e:
        return {
            "success": False,
            "error": f"Error getting diagnostics: {e!s}",
            "diagnostics": [],
        }


def lsp_rename(
    file_path: str,
    line: int,
    column: int,
    new_name: str,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Rename a symbol across all files in the workspace.

    Renames a symbol (function, class, variable) and updates all references
    across the project. Use dry_run=True to preview changes without applying.

    Args:
        file_path: Path to the file containing the symbol
        line: Line number (1-indexed) where the symbol appears
        column: Column number (0-indexed) where the symbol starts
        new_name: The new name for the symbol
        dry_run: If True, only preview changes without applying (default: True)

    Returns:
        Dictionary containing:
        - success: Whether the operation succeeded
        - changes: List of files that would be/are modified, each with:
            - file_path: Path to the file
            - edits: List of edits, each with:
                - line: Line number
                - old_text: Text to replace
                - new_text: Replacement text
        - symbol: The symbol being renamed
        - new_name: The new name
        - applied: Whether changes were applied
        - error: Error message if operation failed

    Example:
        # Preview renaming a function
        lsp_rename("src/utils.py", 15, 4, "new_function_name", dry_run=True)

        # Apply renaming
        lsp_rename("src/main.py", 42, 10, "new_var_name", dry_run=False)
    """
    try:
        import jedi
    except ImportError:
        return {
            "success": False,
            "error": "jedi not installed. Install with: pip install jedi",
            "changes": [],
        }

    try:
        # Read file content
        content = Path(file_path).read_text(encoding="utf-8")

        # Create Jedi script
        script = _get_jedi_script(file_path, content)
        if script is None:
            return {"success": False, "error": "Failed to create Jedi script", "changes": []}

        # Get references
        references = script.get_references(line, column)

        if not references:
            return {
                "success": False,
                "error": "No references found for symbol at this position",
                "changes": [],
            }

        # Group references by file
        file_changes: dict[str, list[dict]] = {}
        symbol_name = references[0].name

        for ref in references:
            if ref.module_path:
                ref_file = str(ref.module_path)
                ref_line = ref.line or 1
                ref_col = ref.column or 0

                if ref_file not in file_changes:
                    file_changes[ref_file] = []

                file_changes[ref_file].append({
                    "line": ref_line,
                    "column": ref_col,
                    "old_name": symbol_name,
                    "new_name": new_name,
                })

        # Build changes list
        changes = []
        for ref_file, edits in file_changes.items():
            try:
                file_content = Path(ref_file).read_text(encoding="utf-8")
                lines = file_content.splitlines()

                # Sort edits by line (descending) to avoid offset issues
                sorted_edits = sorted(edits, key=lambda e: (e["line"], e["column"]), reverse=True)

                text_edits = []
                for edit in sorted_edits:
                    line_idx = edit["line"] - 1
                    if 0 <= line_idx < len(lines):
                        line_content = lines[line_idx]
                        col = edit["column"]

                        # Find the symbol in the line
                        old_name = edit["old_name"]
                        if line_content[col:col + len(old_name)] == old_name:
                            new_line = line_content[:col] + new_name + line_content[col + len(old_name):]
                            lines[line_idx] = new_line
                            text_edits.append({
                                "line": edit["line"],
                                "column": edit["column"],
                                "old_text": old_name,
                                "new_text": new_name,
                            })

                changes.append({
                    "file_path": ref_file,
                    "edits": text_edits,
                })

            except Exception:
                continue

        # Apply changes if not dry run
        applied = False
        if not dry_run:
            for change in changes:
                try:
                    file_content = Path(change["file_path"]).read_text(encoding="utf-8")
                    lines = file_content.splitlines()

                    for edit in sorted(change["edits"], key=lambda e: e["line"], reverse=True):
                        line_idx = edit["line"] - 1
                        if 0 <= line_idx < len(lines):
                            line_content = lines[line_idx]
                            col = edit["column"]
                            old_name = edit["old_text"]
                            lines[line_idx] = line_content[:col] + edit["new_text"] + line_content[col + len(old_name):]

                    Path(change["file_path"]).write_text("\n".join(lines) + "\n", encoding="utf-8")
                except Exception:
                    continue
            applied = True

        return {
            "success": True,
            "changes": changes,
            "symbol": symbol_name,
            "new_name": new_name,
            "applied": applied,
            "files_affected": len(changes),
            "total_edits": sum(len(c["edits"]) for c in changes),
        }

    except Exception as e:
        return {
            "success": False,
            "error": f"Error renaming symbol: {e!s}",
            "changes": [],
        }


def lsp_signature_help(
    file_path: str,
    line: int,
    column: int,
) -> dict[str, Any]:
    """Get function/method signature help at a position.

    Returns signature information for function calls, including parameter
    names, types, and documentation.

    Args:
        file_path: Path to the file
        line: Line number (1-indexed) where the function call is
        column: Column number (0-indexed) where the opening parenthesis is

    Returns:
        Dictionary containing:
        - success: Whether the operation succeeded
        - signatures: List of signatures, each with:
            - label: Full signature string
            - parameters: List of parameters, each with:
                - name: Parameter name
                - type: Parameter type (if available)
                - default: Default value (if available)
                - docstring: Parameter documentation
            - docstring: Function docstring
            - return_type: Return type annotation
        - active_parameter: Index of the active parameter
        - error: Error message if operation failed

    Example:
        # Get signature help for a function call
        lsp_signature_help("src/main.py", 42, 15)
    """
    try:
        import jedi
    except ImportError:
        return {
            "success": False,
            "error": "jedi not installed. Install with: pip install jedi",
            "signatures": [],
        }

    try:
        # Read file content
        content = Path(file_path).read_text(encoding="utf-8")

        # Create Jedi script
        script = _get_jedi_script(file_path, content)
        if script is None:
            return {"success": False, "error": "Failed to create Jedi script", "signatures": []}

        # Get signatures
        signatures = script.get_signatures(line, column)

        if not signatures:
            return {
                "success": True,
                "signatures": [],
                "message": "No signature information available at this position",
            }

        results = []
        for sig in signatures:
            sig_info = {
                "label": sig.to_string() if hasattr(sig, "to_string") else sig.name,
                "name": sig.name,
                "parameters": [],
                "docstring": None,
                "return_type": None,
            }

            # Get parameters
            if hasattr(sig, "params"):
                for param in sig.params:
                    param_info = {
                        "name": param.name if hasattr(param, "name") else str(param),
                        "type": None,
                        "default": None,
                        "docstring": None,
                    }
                    if hasattr(param, "type") and param.type:
                        param_info["type"] = param.type
                    if hasattr(param, "default") and param.default:
                        param_info["default"] = param.default
                    sig_info["parameters"].append(param_info)

            # Get docstring
            if hasattr(sig, "docstring"):
                try:
                    sig_info["docstring"] = sig.docstring()
                except Exception:
                    pass

            results.append(sig_info)

        return {
            "success": True,
            "signatures": results,
            "active_signature": 0,
            "active_parameter": signatures[0].index if hasattr(signatures[0], "index") else 0,
        }

    except Exception as e:
        return {
            "success": False,
            "error": f"Error getting signature help: {e!s}",
            "signatures": [],
        }


def lsp_type_definition(
    file_path: str,
    line: int,
    column: int,
) -> dict[str, Any]:
    """Navigate to the type definition of a symbol.

    Finds where the type of a symbol is defined. Useful for understanding
    the type of variables and navigating to type definitions.

    Args:
        file_path: Path to the file containing the symbol
        line: Line number (1-indexed) where the symbol appears
        column: Column number (0-indexed) where the symbol starts

    Returns:
        Dictionary containing:
        - success: Whether the operation succeeded
        - definitions: List of type definition locations
        - symbol: The symbol that was analyzed
        - error: Error message if operation failed

    Example:
        # Find type definition of a variable
        lsp_type_definition("src/main.py", 42, 10)
    """
    try:
        import jedi
    except ImportError:
        return {
            "success": False,
            "error": "jedi not installed. Install with: pip install jedi",
            "definitions": [],
        }

    try:
        # Read file content
        content = Path(file_path).read_text(encoding="utf-8")

        # Create Jedi script
        script = _get_jedi_script(file_path, content)
        if script is None:
            return {"success": False, "error": "Failed to create Jedi script", "definitions": []}

        # Get inferred types
        infers = script.infer(line, column)

        results = []
        for inf in infers:
            if inf.module_path:
                inf_line = inf.line or 1
                inf_col = inf.column or 0
                line_content = _get_line_content(str(inf.module_path), inf_line)

                results.append({
                    "file_path": str(inf.module_path),
                    "line": inf_line,
                    "column": inf_col,
                    "text": line_content.strip(),
                    "name": inf.name,
                    "type": inf.type,
                    "description": inf.description or "",
                })

        if not results:
            return {
                "success": True,
                "definitions": [],
                "message": "No type definition found. The type may be built-in or inferred.",
            }

        return {
            "success": True,
            "definitions": results,
            "symbol": infers[0].name if infers else None,
            "count": len(results),
        }

    except Exception as e:
        return {
            "success": False,
            "error": f"Error finding type definition: {e!s}",
            "definitions": [],
        }


def lsp_implementation(
    file_path: str,
    line: int,
    column: int,
) -> dict[str, Any]:
    """Find implementations of an interface or abstract method.

    Finds all implementations of an interface, abstract class, or method.
    Useful for navigating polymorphic code.

    Args:
        file_path: Path to the file containing the interface/abstract
        line: Line number (1-indexed) where the symbol appears
        column: Column number (0-indexed) where the symbol starts

    Returns:
        Dictionary containing:
        - success: Whether the operation succeeded
        - implementations: List of implementation locations
        - symbol: The symbol that was analyzed
        - error: Error message if operation failed

    Example:
        # Find implementations of an interface
        lsp_implementation("src/interfaces.py", 10, 6)
    """
    # For Python, implementations are found via inheritance analysis
    # This is a simplified version that finds subclasses
    try:
        import jedi
    except ImportError:
        return {
            "success": False,
            "error": "jedi not installed. Install with: pip install jedi",
            "implementations": [],
        }

    try:
        # Read file content
        content = Path(file_path).read_text(encoding="utf-8")

        # Create Jedi script
        script = _get_jedi_script(file_path, content)
        if script is None:
            return {"success": False, "error": "Failed to create Jedi script", "implementations": []}

        # Get definition first
        definitions = script.goto(line, column, follow_imports=True)

        if not definitions:
            return {
                "success": True,
                "implementations": [],
                "message": "No definition found at this position",
            }

        # Get the class name
        defn = definitions[0]
        class_name = defn.name

        # Search for subclasses in the project
        # This is a simplified implementation
        project_path = Path(file_path)
        while project_path.parent != project_path:
            if (project_path / "pyproject.toml").exists() or (project_path / "setup.py").exists():
                break
            project_path = project_path.parent

        implementations = []

        # Search for class definitions that inherit from this class
        for py_file in project_path.rglob("*.py"):
            try:
                file_content = py_file.read_text(encoding="utf-8")
                if class_name in file_content:
                    # Parse to find inheritance
                    tree = ast.parse(file_content)
                    for node in ast.walk(tree):
                        if isinstance(node, ast.ClassDef):
                            for base in node.bases:
                                if isinstance(base, ast.Name) and base.id == class_name:
                                    implementations.append({
                                        "file_path": str(py_file.relative_to(project_path)),
                                        "line": node.lineno,
                                        "column": node.col_offset,
                                        "name": node.name,
                                        "text": _get_line_content(str(py_file), node.lineno).strip(),
                                    })
            except Exception:
                continue

        return {
            "success": True,
            "implementations": implementations,
            "symbol": class_name,
            "count": len(implementations),
        }

    except Exception as e:
        return {
            "success": False,
            "error": f"Error finding implementations: {e!s}",
            "implementations": [],
        }


# Export all LSP tools
__all__ = [
    "lsp_goto_definition",
    "lsp_find_references",
    "lsp_hover",
    "lsp_completions",
    "lsp_document_symbols",
    "lsp_workspace_symbols",
    "lsp_diagnostics",
    "lsp_rename",
    "lsp_signature_help",
    "lsp_type_definition",
    "lsp_implementation",
]
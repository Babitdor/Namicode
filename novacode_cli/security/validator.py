"""Security validation for tool arguments and user inputs.

This module provides security validation for:
- URL safety checks before fetching
- Unicode validation for user inputs
- Argument sanitization for tool calls
"""

from typing import Any
from rich.console import Console

from novacode_cli.security.unicode_security import (
    check_url_safety,
    detect_dangerous_unicode,
    strip_dangerous_unicode,
    UrlSafetyResult,
    UnicodeIssue,
)

console = Console()


def validate_url_for_fetch(url: str, *, show_warnings: bool = True) -> tuple[bool, str]:
    """Validate a URL before fetching to prevent security issues.

    Checks for:
    - Hidden Unicode characters (BiDi overrides, zero-width chars)
    - Punycode domain spoofing
    - Mixed script domain labels
    - Confusable character attacks

    Args:
        url: URL to validate
        show_warnings: Whether to display warnings to user

    Returns:
        Tuple of (is_safe, sanitized_url_or_error_message)
    """
    result = check_url_safety(url)

    if show_warnings and result.warnings:
        console.print("\n[yellow]⚠ URL Security Warnings:[/yellow]")
        for warning in result.warnings:
            console.print(f"  [dim]• {warning}[/dim]")

    if not result.safe:
        error_msg = f"URL failed security check: {'; '.join(result.warnings)}"
        if result.issues:
            error_msg += f" (Issues: {len(result.issues)} dangerous Unicode characters)"
        return False, error_msg

    # Strip dangerous Unicode from URL
    sanitized_url = strip_dangerous_unicode(url)

    return True, sanitized_url


def validate_tool_arguments(args: dict[str, Any]) -> dict[str, Any]:
    """Validate and sanitize tool arguments for security.

    Checks all string arguments for:
    - Dangerous Unicode characters
    - URL safety (for URL-like arguments)

    Args:
        args: Tool arguments to validate

    Returns:
        Sanitized arguments dictionary
    """
    sanitized = {}

    for key, value in args.items():
        if isinstance(value, str):
            # Check for dangerous Unicode
            issues = detect_dangerous_unicode(value)
            if issues:
                console.print(
                    f"\n[yellow]⚠ Sanitized {len(issues)} dangerous Unicode characters from {key}[/yellow]"
                )
                sanitized[key] = strip_dangerous_unicode(value)
            else:
                sanitized[key] = value

            # Additional check for URL-like arguments
            if key.lower() in {"url", "uri", "href", "link", "base_url", "endpoint"}:
                is_safe, result = validate_url_for_fetch(value, show_warnings=True)
                if not is_safe:
                    console.print(f"[red]✗ Unsafe URL in {key}: {result}[/red]")
                    # Still include the sanitized URL but mark as unsafe
                    sanitized[f"_{key}_unsafe"] = True
        elif isinstance(value, dict):
            # Recursively validate nested dicts
            sanitized[key] = validate_tool_arguments(value)
        elif isinstance(value, list):
            # Validate list items
            sanitized[key] = [
                validate_tool_arguments({"item": item})["item"]
                if isinstance(item, dict)
                else strip_dangerous_unicode(item)
                if isinstance(item, str)
                else item
                for item in value
            ]
        else:
            # Non-string, non-dict, non-list values pass through
            sanitized[key] = value

    return sanitized


def validate_user_input(text: str, *, show_warnings: bool = True) -> tuple[bool, str]:
    """Validate user input for security issues.

    Args:
        text: User input to validate
        show_warnings: Whether to display warnings

    Returns:
        Tuple of (is_safe, sanitized_text)
    """
    issues = detect_dangerous_unicode(text)

    if issues:
        if show_warnings:
            console.print(
                f"\n[yellow]⚠ Detected {len(issues)} dangerous Unicode characters:[/yellow]"
            )
            for issue in issues[:3]:  # Show first 3
                console.print(f"  [dim]• {issue.codepoint} {issue.name}[/dim]")
            if len(issues) > 3:
                console.print(f"  [dim]• ... and {len(issues) - 3} more[/dim]")

        sanitized = strip_dangerous_unicode(text)
        return False, sanitized

    return True, text


def display_security_warning(title: str, message: str, details: list[str] | None = None) -> None:
    """Display a formatted security warning to the user.

    Args:
        title: Warning title
        message: Warning message
        details: Optional list of detail strings
    """
    console.print(f"\n[yellow]⚠ {title}[/yellow]")
    console.print(f"  [dim]{message}[/dim]")

    if details:
        for detail in details[:5]:  # Show max 5 details
            console.print(f"  [dim]• {detail}[/dim]")
        if len(details) > 5:
            console.print(f"  [dim]• ... and {len(details) - 5} more[/dim]")


__all__ = [
    "validate_url_for_fetch",
    "validate_tool_arguments",
    "validate_user_input",
    "display_security_warning",
    "check_url_safety",
    "detect_dangerous_unicode",
    "strip_dangerous_unicode",
    "UrlSafetyResult",
    "UnicodeIssue",
]
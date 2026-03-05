"""Browser automation tools using Playwright.

This module provides browser automation capabilities for testing web applications,
taking screenshots, and interacting with web pages programmatically.

IMPORTANT: These tools require Playwright to be installed:
    pip install playwright
    playwright install

Key Tools:
- browser_navigate(): Navigate to URLs
- browser_click(): Click elements by selector
- browser_type(): Type text into inputs
- browser_screenshot(): Capture page screenshots
- browser_evaluate(): Execute JavaScript in browser context
- browser_wait(): Wait for elements or conditions
- browser_query(): Query DOM elements
- browser_scroll(): Scroll the page
- browser_snapshot(): Get page state for AI analysis
- browser_close(): Close the browser

All browser operations use a shared browser instance that persists across calls
within a session, enabling complex multi-step workflows.
"""

import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

# Global browser state
_browser_instance = None
_page_instance = None
_browser_context = None
_playwright = None


def _get_browser():
    """Get or create browser instance with error recovery.

    Returns:
        Tuple of (browser_instance, browser_context)

    Raises:
        ImportError: If playwright is not installed
        RuntimeError: If browser fails to start
    """
    global _browser_instance, _browser_context, _playwright

    # Check if previous instance is still valid
    if _browser_instance is not None:
        try:
            # Test if browser is still connected
            if _browser_instance.is_connected():
                return _browser_instance, _browser_context
        except Exception:
            # Browser is closed or crashed, reset
            _browser_instance = None
            _browser_context = None
            _page_instance = None
            _playwright = None

    # Create new browser instance
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise ImportError(
            "Playwright not installed. Install with:\n"
            "  pip install playwright\n"
            "  playwright install chromium"
        ) from None

    try:
        _playwright = sync_playwright().start()
        _browser_instance = _playwright.chromium.launch(headless=True)
        _browser_context = _browser_instance.new_context(
            viewport={"width": 1280, "height": 720},
            user_agent="Mozilla/5.0 (compatible; NamiCode/1.0)",
        )
    except Exception as e:
        # Clean up on failure
        if _playwright is not None:
            try:
                _playwright.stop()
            except Exception:
                pass
        _browser_instance = None
        _browser_context = None
        _playwright = None
        raise RuntimeError(f"Failed to start browser: {e}") from e

    return _browser_instance, _browser_context


def _get_page():
    """Get or create page instance with error recovery.

    Returns:
        Playwright Page object

    Raises:
        RuntimeError: If page cannot be created
    """
    global _page_instance

    # Check if previous page is still valid
    if _page_instance is not None:
        try:
            # Test if page is still open
            _ = _page_instance.url  # This will fail if page is closed
            return _page_instance
        except Exception:
            # Page is closed, reset
            _page_instance = None

    # Create new page
    try:
        _, context = _get_browser()
        _page_instance = context.new_page()
    except Exception as e:
        # Reset state and re-raise
        _page_instance = None
        raise RuntimeError(f"Failed to create browser page: {e}") from e

    return _page_instance


def browser_status() -> dict[str, Any]:
    """Get current browser status.

    Returns information about the browser state, useful for debugging
    and checking if browser is available.

    Returns:
        Dictionary containing:
        - browser_running: Whether browser instance exists
        - page_open: Whether a page is open
        - current_url: Current page URL (if any)
        - page_title: Current page title (if any)
    """
    global _browser_instance, _page_instance, _browser_context

    status = {
        "browser_running": False,
        "page_open": False,
        "current_url": None,
        "page_title": None,
    }

    try:
        if _browser_instance is not None and _browser_instance.is_connected():
            status["browser_running"] = True

            if _page_instance is not None:
                try:
                    status["current_url"] = _page_instance.url
                    status["page_title"] = _page_instance.title()
                    status["page_open"] = True
                except Exception:
                    status["page_open"] = False
    except Exception:
        pass

    return status


def browser_navigate(
    url: str,
    wait_until: Literal["load", "domcontentloaded", "networkidle"] = "load",
    timeout: int = 30000,
) -> dict[str, Any]:
    """Navigate to a URL in the browser.

    Opens a page or navigates the current page to the specified URL.
    Uses a persistent browser instance for efficiency.

    Args:
        url: The URL to navigate to (must include http:// or https://)
        wait_until: When to consider navigation complete:
            - "load": Wait for load event (default)
            - "domcontentloaded": Wait for DOMContentLoaded
            - "networkidle": Wait for no network activity
        timeout: Maximum time to wait in milliseconds (default: 30000)

    Returns:
        Dictionary containing:
        - success: Whether navigation succeeded
        - url: Final URL after redirects
        - title: Page title
        - status_code: HTTP status code (if available)

    Example:
        browser_navigate("https://example.com")
        browser_navigate("https://app.example.com", wait_until="networkidle")
    """
    try:
        page = _get_page()
        response = page.goto(url, wait_until=wait_until, timeout=timeout)

        return {
            "success": True,
            "url": page.url,
            "title": page.title(),
            "status_code": response.status if response else None,
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Navigation failed: {e!s}",
            "url": url,
        }


def browser_click(
    selector: str,
    button: Literal["left", "right", "middle"] = "left",
    click_count: int = 1,
    timeout: int = 30000,
) -> dict[str, Any]:
    """Click an element on the page.

    Finds an element by CSS selector and clicks it. Waits for the element
    to be visible and stable before clicking.

    Args:
        selector: CSS selector to find the element (e.g., "button#submit", ".login-btn")
        button: Mouse button to click - "left", "right", or "middle"
        click_count: Number of clicks (1 for single, 2 for double-click)
        timeout: Maximum wait time in milliseconds

    Returns:
        Dictionary containing:
        - success: Whether click succeeded
        - selector: The selector used
        - element_text: Text content of clicked element (if found)

    Example:
        browser_click("button[type='submit']")
        browser_click("#login-btn", click_count=2)  # Double-click
    """
    try:
        page = _get_page()

        # Wait for element and click
        element = page.wait_for_selector(selector, timeout=timeout)
        if element is None:
            return {
                "success": False,
                "error": f"Element not found: {selector}",
                "selector": selector,
            }

        element_text = element.text_content() or ""
        element.click(button=button, click_count=click_count)

        return {
            "success": True,
            "selector": selector,
            "element_text": element_text.strip(),
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Click failed: {e!s}",
            "selector": selector,
        }


def browser_type(
    selector: str,
    text: str,
    clear_first: bool = True,
    delay: int = 50,
    timeout: int = 30000,
) -> dict[str, Any]:
    """Type text into an input field.

    Finds an input/textarea by CSS selector and types text into it.
    Optionally clears existing content before typing.

    Args:
        selector: CSS selector for the input element
        text: Text to type
        clear_first: Clear existing content before typing (default: True)
        delay: Delay between keystrokes in milliseconds (default: 50)
        timeout: Maximum wait time for element

    Returns:
        Dictionary containing:
        - success: Whether typing succeeded
        - selector: The selector used
        - text_typed: Text that was typed

    Example:
        browser_type("#username", "john_doe")
        browser_type("#search-box", "hello world", clear_first=False)
    """
    try:
        page = _get_page()

        element = page.wait_for_selector(selector, timeout=timeout)
        if element is None:
            return {
                "success": False,
                "error": f"Element not found: {selector}",
                "selector": selector,
            }

        if clear_first:
            element.fill("")

        element.type(text, delay=delay)

        return {
            "success": True,
            "selector": selector,
            "text_typed": text,
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Type failed: {e!s}",
            "selector": selector,
        }


def browser_screenshot(
    path: str | None = None,
    full_page: bool = False,
    selector: str | None = None,
) -> dict[str, Any]:
    """Take a screenshot of the current page.

    Captures a screenshot of the visible page or a specific element.
    Saves to a file and returns the path.

    Args:
        path: Path to save screenshot. If None, saves to temp directory.
        full_page: Capture full scrollable page (default: False, viewport only)
        selector: Optional CSS selector to screenshot only that element

    Returns:
        Dictionary containing:
        - success: Whether screenshot succeeded
        - file_path: Path to saved screenshot
        - width: Screenshot width in pixels
        - height: Screenshot height in pixels

    Example:
        browser_screenshot()
        browser_screenshot("screenshots/home.png", full_page=True)
        browser_screenshot(selector=".results-table")
    """
    try:
        page = _get_page()

        # Generate default path if not provided
        if path is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            temp_dir = tempfile.gettempdir()
            path = os.path.join(temp_dir, f"namicode_screenshot_{timestamp}.png")

        # Ensure directory exists
        Path(path).parent.mkdir(parents=True, exist_ok=True)

        if selector:
            # Screenshot specific element
            element = page.query_selector(selector)
            if element is None:
                return {
                    "success": False,
                    "error": f"Element not found: {selector}",
                }
            element.screenshot(path=path)
            box = element.bounding_box() or {}
            width = int(box.get("width", 0))
            height = int(box.get("height", 0))
        else:
            # Screenshot page
            page.screenshot(path=path, full_page=full_page)
            viewport = page.viewport_size or {}
            width = viewport.get("width", 1280)
            height = viewport.get("height", 720)

        return {
            "success": True,
            "file_path": os.path.abspath(path),
            "width": width,
            "height": height,
            "full_page": full_page,
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Screenshot failed: {e!s}",
        }


def browser_evaluate(
    script: str,
    arg: Any | None = None,
) -> dict[str, Any]:
    """Execute JavaScript in the browser context.

    Runs arbitrary JavaScript code in the page context and returns the result.
    Can pass arguments to the script.

    Args:
        script: JavaScript code to execute (can be expression or statements)
        arg: Optional argument to pass to the script (accessible as 'arg')

    Returns:
        Dictionary containing:
        - success: Whether execution succeeded
        - result: Return value from JavaScript (JSON-serializable)
        - result_type: Type of the result

    Example:
        browser_evaluate("document.title")
        browser_evaluate("document.querySelectorAll('.item').length")
        browser_evaluate("arg.map(x => x * 2)", arg=[1, 2, 3])
    """
    try:
        page = _get_page()

        if arg is not None:
            result = page.evaluate(script, arg)
        else:
            result = page.evaluate(script)

        # Determine result type
        result_type = type(result).__name__

        return {
            "success": True,
            "result": result,
            "result_type": result_type,
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Evaluation failed: {e!s}",
        }


def browser_wait(
    selector: str | None = None,
    text: str | None = None,
    state: Literal["attached", "detached", "visible", "hidden"] = "visible",
    timeout: int = 30000,
) -> dict[str, Any]:
    """Wait for an element or condition on the page.

    Waits for a selector to appear, text to appear, or a specific state.
    Useful for dynamic pages with async content loading.

    Args:
        selector: CSS selector to wait for (optional)
        text: Text to wait for in the page (optional)
        state: Element state to wait for:
            - "attached": Element in DOM
            - "detached": Element removed from DOM
            - "visible": Element visible (default)
            - "hidden": Element hidden or removed
        timeout: Maximum wait time in milliseconds

    Returns:
        Dictionary containing:
        - success: Whether wait condition was met
        - waited_for: What was waited for (selector or text)

    Example:
        browser_wait(selector="#results")
        browser_wait(text="Loading complete")
        browser_wait(selector=".modal", state="hidden")
    """
    try:
        page = _get_page()

        if selector:
            page.wait_for_selector(selector, state=state, timeout=timeout)
            return {
                "success": True,
                "waited_for": f"selector: {selector}",
                "state": state,
            }
        if text:
            page.wait_for_selector(f"text={text}", timeout=timeout)
            return {
                "success": True,
                "waited_for": f"text: {text}",
            }
        return {
            "success": False,
            "error": "Must provide either selector or text",
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Wait failed: {e!s}",
        }


def browser_query(
    selector: str,
    attribute: str | None = None,
    all_matches: bool = False,
) -> dict[str, Any]:
    """Query DOM elements on the page.

    Finds elements by CSS selector and retrieves their content or attributes.
    Useful for scraping data or verifying page content.

    Args:
        selector: CSS selector to query
        attribute: Attribute to retrieve (e.g., "href", "src"). If None, returns text content.
        all_matches: Return all matching elements (default: False, first match only)

    Returns:
        Dictionary containing:
        - success: Whether query succeeded
        - count: Number of elements found
        - elements: List of element data (text or attribute values)

    Example:
        browser_query("h1")  # Get first h1 text
        browser_query("a", attribute="href", all_matches=True)  # All link URLs
        browser_query(".product-title", all_matches=True)  # All product titles
    """
    try:
        page = _get_page()

        if all_matches:
            elements = page.query_selector_all(selector)
            results = []
            for el in elements:
                if attribute:
                    val = el.get_attribute(attribute)
                else:
                    val = el.text_content()
                results.append(val)

            return {
                "success": True,
                "count": len(results),
                "elements": results,
                "selector": selector,
            }
        element = page.query_selector(selector)
        if element is None:
            return {
                "success": False,
                "error": f"Element not found: {selector}",
                "selector": selector,
                "count": 0,
                "elements": [],
            }

        if attribute:
            value = element.get_attribute(attribute)
        else:
            value = element.text_content()

        return {
            "success": True,
            "count": 1,
            "elements": [value],
            "selector": selector,
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Query failed: {e!s}",
            "selector": selector,
        }


def browser_scroll(
    direction: Literal["up", "down", "top", "bottom"] = "down",
    amount: int = 500,
) -> dict[str, Any]:
    """Scroll the page.

    Scrolls the page in the specified direction by given amount or to edges.

    Args:
        direction: Scroll direction:
            - "up": Scroll up by amount pixels
            - "down": Scroll down by amount pixels (default)
            - "top": Scroll to top of page
            - "bottom": Scroll to bottom of page
        amount: Pixels to scroll (for "up" and "down")

    Returns:
        Dictionary containing:
        - success: Whether scroll succeeded
        - scroll_position: Current scroll Y position

    Example:
        browser_scroll("down", 1000)  # Scroll down 1000px
        browser_scroll("bottom")  # Scroll to page bottom
        browser_scroll("top")  # Scroll to page top
    """
    try:
        page = _get_page()

        if direction == "top":
            page.evaluate("window.scrollTo(0, 0)")
        elif direction == "bottom":
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        elif direction == "up":
            page.evaluate(f"window.scrollBy(0, -{amount})")
        else:  # down
            page.evaluate(f"window.scrollBy(0, {amount})")

        scroll_y = page.evaluate("window.scrollY")

        return {
            "success": True,
            "direction": direction,
            "scroll_position": scroll_y,
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Scroll failed: {e!s}",
        }


def browser_fill_form(
    fields: dict[str, str],
    submit_selector: str | None = None,
    timeout: int = 30000,
) -> dict[str, Any]:
    """Fill multiple form fields at once.

    Convenience tool to fill a form with multiple fields and optionally submit.
    Uses CSS selectors for field identification.

    Args:
        fields: Dictionary mapping CSS selectors to values to fill
        submit_selector: Optional CSS selector for submit button to click after filling
        timeout: Maximum wait time per element

    Returns:
        Dictionary containing:
        - success: Whether form filling succeeded
        - filled_fields: Number of fields filled
        - errors: List of any errors (per field)

    Example:
        browser_fill_form({
            "#username": "john",
            "#password": "secret123",
            "#remember": "checked",
        }, submit_selector="button[type='submit']")
    """
    page = _get_page()
    filled = 0
    errors = []

    for selector, value in fields.items():
        try:
            element = page.wait_for_selector(selector, timeout=timeout)
            if element is None:
                errors.append(f"Element not found: {selector}")
                continue

            # Handle checkboxes and radio buttons
            if value.lower() in ("checked", "true", "yes", "1"):
                element.check()
            elif value.lower() in ("unchecked", "false", "no", "0"):
                element.uncheck()
            else:
                element.fill(value)

            filled += 1
        except Exception as e:
            errors.append(f"{selector}: {e!s}")

    # Submit form if requested
    if submit_selector and filled == len(fields):
        try:
            page.click(submit_selector, timeout=timeout)
        except Exception as e:
            errors.append(f"Submit failed: {e!s}")

    return {
        "success": len(errors) == 0,
        "filled_fields": filled,
        "total_fields": len(fields),
        "errors": errors if errors else None,
    }


def browser_get_content(
    selector: str | None = None,
    format: Literal["text", "html", "markdown"] = "text",
) -> dict[str, Any]:
    """Get page or element content.

    Retrieves the text, HTML, or markdown content of the page or a specific element.

    Args:
        selector: Optional CSS selector. If None, gets full page content.
        format: Output format:
            - "text": Plain text (default)
            - "html": Raw HTML
            - "markdown": Convert to markdown (requires markdownify)

    Returns:
        Dictionary containing:
        - success: Whether retrieval succeeded
        - content: The retrieved content
        - format: Format used
        - length: Content length in characters

    Example:
        browser_get_content()  # Full page text
        browser_get_content("#main", format="html")
        browser_get_content(format="markdown")
    """
    try:
        page = _get_page()

        if selector:
            element = page.query_selector(selector)
            if element is None:
                return {
                    "success": False,
                    "error": f"Element not found: {selector}",
                }

            if format == "html":
                content = element.inner_html()
            else:
                content = element.inner_text()
        elif format == "html":
            content = page.content()
        else:
            content = page.inner_text("body")

        # Convert to markdown if requested
        if format == "markdown":
            try:
                from markdownify import markdownify

                content = markdownify(content)
            except ImportError:
                return {
                    "success": False,
                    "error": "markdownify not installed. Install with: pip install markdownify",
                }

        return {
            "success": True,
            "content": content,
            "format": format,
            "length": len(content),
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Get content failed: {e!s}",
        }


def browser_select(
    selector: str,
    value: str | None = None,
    label: str | None = None,
    index: int | None = None,
) -> dict[str, Any]:
    """Select an option from a dropdown/select element.

    Selects an option from a <select> element by value, label, or index.

    Args:
        selector: CSS selector for the select element
        value: Option value attribute to select
        label: Visible option text to select
        index: Option index to select (0-based)

    Returns:
        Dictionary containing:
        - success: Whether selection succeeded
        - selected_value: Value of selected option
        - selected_label: Text of selected option

    Example:
        browser_select("#country", value="us")
        browser_select("#country", label="United States")
        browser_select("#country", index=0)
    """
    try:
        page = _get_page()

        element = page.query_selector(selector)
        if element is None:
            return {
                "success": False,
                "error": f"Select element not found: {selector}",
            }

        if value is not None:
            element.select_option(value=value)
        elif label is not None:
            element.select_option(label=label)
        elif index is not None:
            element.select_option(index=index)
        else:
            return {
                "success": False,
                "error": "Must provide value, label, or index",
            }

        # Get selected value
        selected_value = element.evaluate("el => el.value")
        selected_text = element.evaluate("el => el.options[el.selectedIndex]?.text")

        return {
            "success": True,
            "selector": selector,
            "selected_value": selected_value,
            "selected_label": selected_text,
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Select failed: {e!s}",
        }


def browser_get_url() -> dict[str, Any]:
    """Get current page URL and title.

    Returns:
        Dictionary containing:
        - success: Always True
        - url: Current page URL
        - title: Current page title
    """
    try:
        page = _get_page()
        return {
            "success": True,
            "url": page.url,
            "title": page.title(),
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Get URL failed: {e!s}",
        }


def browser_go_back(
    wait_until: Literal["load", "domcontentloaded", "networkidle"] = "load",
) -> dict[str, Any]:
    """Navigate back in browser history.

    Args:
        wait_until: When to consider navigation complete

    Returns:
        Dictionary with success status and current URL
    """
    try:
        page = _get_page()
        page.go_back(wait_until=wait_until)
        return {
            "success": True,
            "url": page.url,
            "title": page.title(),
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Go back failed: {e!s}",
        }


def browser_go_forward(
    wait_until: Literal["load", "domcontentloaded", "networkidle"] = "load",
) -> dict[str, Any]:
    """Navigate forward in browser history.

    Args:
        wait_until: When to consider navigation complete

    Returns:
        Dictionary with success status and current URL
    """
    try:
        page = _get_page()
        page.go_forward(wait_until=wait_until)
        return {
            "success": True,
            "url": page.url,
            "title": page.title(),
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Go forward failed: {e!s}",
        }


def browser_refresh(
    wait_until: Literal["load", "domcontentloaded", "networkidle"] = "load",
) -> dict[str, Any]:
    """Refresh the current page.

    Args:
        wait_until: When to consider refresh complete

    Returns:
        Dictionary with success status and current URL
    """
    try:
        page = _get_page()
        page.reload(wait_until=wait_until)
        return {
            "success": True,
            "url": page.url,
            "title": page.title(),
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Refresh failed: {e!s}",
        }


def browser_close() -> dict[str, Any]:
    """Close the browser instance.

    Closes the shared browser instance. A new browser will be created
    on the next browser operation.

    Returns:
        Dictionary with success status
    """
    global _browser_instance, _page_instance, _browser_context

    try:
        if _page_instance is not None:
            _page_instance.close()
            _page_instance = None

        if _browser_context is not None:
            _browser_context.close()
            _browser_context = None

        if _browser_instance is not None:
            _browser_instance.close()
            _browser_instance = None

        return {
            "success": True,
            "message": "Browser closed successfully",
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Close failed: {e!s}",
        }


def browser_run_code(code: str) -> dict[str, Any]:
    """Execute multi-step browser automation code.

    Execute a script that can perform multiple browser operations.
    Provides access to 'page', 'browser', and 'context' objects.

    WARNING: This tool exposes the Playwright API directly. Use with caution.

    Args:
        code: Python code to execute. Variables available:
            - page: The current Playwright Page object
            - context: Browser context
            - Result should be assigned to 'result' variable

    Returns:
        Dictionary containing:
        - success: Whether execution succeeded
        - result: Value of 'result' variable after execution
        - stdout: Captured print output

    Example:
        browser_run_code('''
            page.fill("#search", "playwright")
            page.click("button[type='submit']")
            page.wait_for_selector(".result")
            result = page.query_selector_all(".result")
        ''')
    """
    global _browser_instance, _page_instance, _browser_context

    try:
        # Ensure browser is started
        _, context = _get_browser()
        page = _get_page()

        # Create execution environment
        local_vars = {
            "page": page,
            "context": context,
            "browser": _browser_instance,
            "result": None,
        }

        # Capture stdout
        import io
        import sys

        old_stdout = sys.stdout
        sys.stdout = io.StringIO()

        try:
            exec(code, {"__builtins__": {}}, local_vars)
            stdout = sys.stdout.getvalue()
        finally:
            sys.stdout = old_stdout

        return {
            "success": True,
            "result": local_vars.get("result"),
            "stdout": stdout,
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Code execution failed: {e!s}",
        }


def browser_upload(
    selector: str,
    files: list[str],
) -> dict[str, Any]:
    """Upload files to a file input element.

    Args:
        selector: CSS selector for the file input element
        files: List of file paths to upload

    Returns:
        Dictionary containing:
        - success: Whether upload succeeded
        - files_uploaded: Number of files uploaded

    Example:
        browser_upload("input[type='file']", ["/path/to/file1.pdf", "/path/to/file2.png"])
    """
    try:
        page = _get_page()

        # Validate files exist
        valid_files = []
        for f in files:
            if os.path.exists(f):
                valid_files.append(f)
            else:
                return {
                    "success": False,
                    "error": f"File not found: {f}",
                }

        element = page.query_selector(selector)
        if element is None:
            return {
                "success": False,
                "error": f"Element not found: {selector}",
            }

        element.set_input_files(valid_files)

        return {
            "success": True,
            "files_uploaded": len(valid_files),
            "files": valid_files,
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Upload failed: {e!s}",
        }


def browser_snapshot() -> dict[str, Any]:
    """Get a comprehensive snapshot of the current page state.

    This is the primary tool for AI agents to understand page content.
    Returns page URL, title, visible text, and interactive elements.

    Returns:
        Dictionary containing:
        - success: Whether snapshot succeeded
        - url: Current page URL
        - title: Page title
        - text_content: Visible text from the page (truncated to 5000 chars)
        - interactive_elements: List of clickable/interactive elements
        - forms: List of form elements and their current values
        - metadata: Page meta tags

    Example:
        snapshot = browser_snapshot()
        print(snapshot["url"])
        print(snapshot["text_content"][:500])
    """
    try:
        page = _get_page()

        # Basic info
        url = page.url
        title = page.title()

        # Get visible text content (truncated)
        text_content = page.evaluate("""
            () => {
                // Get all text nodes that are visible
                const walker = document.createTreeWalker(
                    document.body,
                    NodeFilter.SHOW_TEXT,
                    null,
                    false
                );
                
                let text = '';
                let node;
                while (node = walker.nextNode()) {
                    const style = window.getComputedStyle(node.parentElement);
                    if (style.display !== 'none' && style.visibility !== 'hidden') {
                        text += node.textContent + ' ';
                    }
                }
                return text.trim().substring(0, 5000);
            }
        """)

        # Get interactive elements (clickable buttons, links, inputs)
        interactive_elements = page.evaluate("""
            () => {
                const elements = [];
                
                // Buttons
                document.querySelectorAll('button, input[type="button"], input[type="submit"]').forEach(el => {
                    if (el.offsetParent !== null) {
                        elements.push({
                            type: 'button',
                            text: el.textContent.trim().substring(0, 100),
                            selector: el.id ? `#${el.id}` : el.className ? `.${el.className.split(' ')[0]}` : el.tagName.toLowerCase()
                        });
                    }
                });
                
                // Links
                document.querySelectorAll('a').forEach(el => {
                    if (el.offsetParent !== null && el.href) {
                        elements.push({
                            type: 'link',
                            text: el.textContent.trim().substring(0, 100),
                            href: el.href
                        });
                    }
                });
                
                // Inputs
                document.querySelectorAll('input, textarea, select').forEach(el => {
                    if (el.offsetParent !== null) {
                        elements.push({
                            type: 'input',
                            input_type: el.type || el.tagName.toLowerCase(),
                            name: el.name || '',
                            placeholder: el.placeholder || '',
                            value: el.value ? '***' : ''
                        });
                    }
                });
                
                return elements;
            }
        """)

        # Get forms
        forms = page.evaluate("""
            () => {
                const forms = [];
                document.querySelectorAll('form').forEach(form => {
                    const inputs = [];
                    form.querySelectorAll('input, textarea, select').forEach(input => {
                        inputs.push({
                            name: input.name,
                            type: input.type || input.tagName.toLowerCase(),
                            value: input.value ? '***' : ''
                        });
                    });
                    forms.push({
                        action: form.action,
                        method: form.method,
                        inputs: inputs
                    });
                });
                return forms;
            }
        """)

        # Get metadata
        metadata = page.evaluate("""
            () => {
                const meta = {};
                document.querySelectorAll('meta[name], meta[property]').forEach(m => {
                    const key = m.getAttribute('name') || m.getAttribute('property');
                    if (key) meta[key] = m.content;
                });
                return meta;
            }
        """)

        return {
            "success": True,
            "url": url,
            "title": title,
            "text_content": text_content or "",
            "interactive_elements": interactive_elements[:50],  # Limit to 50 elements
            "forms": forms,
            "metadata": metadata,
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Snapshot failed: {e!s}",
        }


def browser_wait_for(
    selector: str | None = None,
    text: str | None = None,
    timeout: int = 30000,
) -> dict[str, Any]:
    """Wait for an element or text to appear on the page.

    Alias for browser_wait with simpler interface.

    Args:
        selector: CSS selector to wait for (optional)
        text: Text to wait for in the page (optional)
        timeout: Maximum wait time in milliseconds

    Returns:
        Dictionary containing:
        - success: Whether the condition was met
        - message: Description of what was waited for

    Example:
        browser_wait_for("#results")
        browser_wait_for(text="Loading complete")
    """
    return browser_wait(selector=selector, text=text, timeout=timeout)


# List of all browser tools for easy export
__all__ = [
    "browser_navigate",
    "browser_click",
    "browser_type",
    "browser_screenshot",
    "browser_evaluate",
    "browser_wait",
    "browser_wait_for",
    "browser_query",
    "browser_scroll",
    "browser_fill_form",
    "browser_get_content",
    "browser_select",
    "browser_get_url",
    "browser_go_back",
    "browser_go_forward",
    "browser_refresh",
    "browser_close",
    "browser_run_code",
    "browser_upload",
    "browser_pdf",
    "browser_status",
    "browser_snapshot",
]


def browser_pdf(
    path: str | None = None,
    format: Literal["A4", "Letter", "Legal", "Tabloid"] = "A4",
    landscape: bool = False,
) -> dict[str, Any]:
    """Save current page as PDF.

    Requires Chromium browser (default). Works best with web pages.

    Args:
        path: Path to save PDF. If None, saves to temp directory.
        format: Page format - "A4", "Letter", "Legal", or "Tabloid"
        landscape: Use landscape orientation (default: False)

    Returns:
        Dictionary containing:
        - success: Whether PDF generation succeeded
        - file_path: Path to saved PDF

    Example:
        browser_pdf("output.pdf")
        browser_pdf(format="Letter", landscape=True)
    """
    try:
        page = _get_page()

        if path is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            temp_dir = tempfile.gettempdir()
            path = os.path.join(temp_dir, f"namicode_page_{timestamp}.pdf")

        # Ensure directory exists
        Path(path).parent.mkdir(parents=True, exist_ok=True)

        page.pdf(
            path=path,
            format=format,
            landscape=landscape,
            print_background=True,
        )

        return {
            "success": True,
            "file_path": os.path.abspath(path),
            "format": format,
            "landscape": landscape,
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"PDF generation failed: {e!s}",
        }


# List of all browser tools for easy import
BROWSER_TOOLS = [
    browser_navigate,
    browser_click,
    browser_type,
    browser_screenshot,
    browser_evaluate,
    browser_wait,
    browser_wait_for,
    browser_query,
    browser_scroll,
    browser_fill_form,
    browser_get_content,
    browser_select,
    browser_get_url,
    browser_go_back,
    browser_go_forward,
    browser_refresh,
    browser_close,
    browser_run_code,
    browser_upload,
    browser_pdf,
    browser_status,
    browser_snapshot,
]

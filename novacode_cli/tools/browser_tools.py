"""Browser automation tools.

This module provides tools for browser automation and console capture.
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime
from typing import Any

from langchain.tools import tool


@tool
def capture_browser_console(
    url: str,
    duration: int = 30,
    capture_errors: bool = True,
    capture_warnings: bool = True,
    capture_logs: bool = True,
    headless: bool = True,
) -> dict[str, Any]:
    """Capture browser console errors, warnings, and logs from a running web application.

    This tool launches a browser, navigates to the specified URL, and captures all console
    messages for a specified duration. Useful for debugging web applications and monitoring
    JavaScript errors during development.

    Args:
        url: The URL to monitor (e.g., "http://localhost:3000", "https://example.com")
        duration: Duration in seconds to capture console messages (default: 30, max: 300)
        capture_errors: Whether to capture console.error messages (default: True)
        capture_warnings: Whether to capture console.warn messages (default: True)
        capture_logs: Whether to capture console.log messages (default: True)
        headless: Whether to run browser in headless mode (default: True)

    Returns:
        Dictionary containing:
        - success: Whether the capture succeeded
        - url: The URL that was monitored
        - duration: Actual capture duration in seconds
        - messages: List of captured console messages, each with:
            - type: "error", "warning", "log", or "info"
            - message: The console message content
            - timestamp: ISO format timestamp
            - location: File location if available (file:line:column)
        - summary: Summary statistics:
            - total_messages: Total number of messages captured
            - error_count: Number of error messages
            - warning_count: Number of warning messages
            - log_count: Number of log messages
        - error: Error message if capture failed

    Example:
        # Capture console errors from local development server
        capture_browser_console("http://localhost:3000", duration=60)

        # Capture all console messages from production site
        capture_browser_console("https://example.com", duration=30, capture_logs=True)

        # Quick error check (5 seconds)
        capture_browser_console("http://localhost:8080", duration=5, capture_logs=False)

    Note: Requires playwright to be installed. Install with:
          pip install playwright
          playwright install chromium
    """
    # Limit duration to reasonable bounds
    duration = min(max(1, duration), 300)  # Between 1 and 300 seconds

    try:
        from playwright.async_api import async_playwright
    except ImportError as e:
        return {
            "success": False,
            "error": (
                f"Playwright not installed: {e}\n\n"
                "Install with: pip install playwright\n"
                "Then run: playwright install chromium"
            ),
            "url": url,
            "duration": duration,
        }

    async def capture_console():
        """Async function to capture console messages."""
        messages = []
        start_time = time.time()

        try:
            async with async_playwright() as p:
                # Launch browser
                browser = await p.chromium.launch(headless=headless)
                context = await browser.new_context()
                page = await context.new_page()

                # Console message handler
                def handle_console(msg) -> None:
                    msg_type = msg.type
                    msg_text = msg.text
                    msg_location = msg.location

                    # Filter by type
                    if msg_type == "error" and not capture_errors:
                        return
                    if msg_type == "warning" and not capture_warnings:
                        return
                    if msg_type == "log" and not capture_logs:
                        return
                    if msg_type == "info" and not capture_logs:
                        return

                    # Format location
                    location_str = None
                    if msg_location:
                        location_str = (
                            f"{msg_location.get('file', 'unknown')}:"
                            f"{msg_location.get('line', 0)}:"
                            f"{msg_location.get('column', 0)}"
                        )

                    messages.append(
                        {
                            "type": msg_type,
                            "message": msg_text,
                            "timestamp": datetime.now(UTC).isoformat(),
                            "location": location_str,
                        }
                    )

                # Register console handler
                page.on("console", handle_console)

                # Navigate to URL
                try:
                    await page.goto(url, wait_until="networkidle", timeout=10000)
                except Exception as nav_error:  # noqa: BLE001
                    # Still capture console even if page doesn't fully load
                    messages.append(
                        {
                            "type": "warning",
                            "message": (f"Page navigation warning: {nav_error!s}"),
                            "timestamp": datetime.now(UTC).isoformat(),
                            "location": None,
                        }
                    )

                # Wait for specified duration, capturing console messages
                elapsed = 0
                while elapsed < duration:
                    await asyncio.sleep(1)
                    elapsed = time.time() - start_time

                await browser.close()

        except Exception as e:  # noqa: BLE001
            return {
                "success": False,
                "error": f"Browser capture failed: {e!s}",
                "url": url,
                "duration": time.time() - start_time,
                "messages": messages,
            }

        # Calculate summary
        error_count = sum(1 for m in messages if m["type"] == "error")
        warning_count = sum(1 for m in messages if m["type"] == "warning")
        log_count = sum(1 for m in messages if m["type"] in ("log", "info"))

        return {
            "success": True,
            "url": url,
            "duration": time.time() - start_time,
            "messages": messages,
            "summary": {
                "total_messages": len(messages),
                "error_count": error_count,
                "warning_count": warning_count,
                "log_count": log_count,
            },
        }

    # Run async capture
    try:
        # Check if we're already in an async context
        try:
            asyncio.get_running_loop()
            # We're in an async context, create a task
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(asyncio.run, capture_console())
                result = future.result(timeout=duration + 30)  # Extra buffer
        except RuntimeError:
            # No running loop, we can use asyncio.run directly
            result = asyncio.run(capture_console())

        return result

    except Exception as e:  # noqa: BLE001
        return {
            "success": False,
            "error": f"Failed to capture browser console: {e!s}",
            "url": url,
            "duration": duration,
            "messages": [],
        }


@tool
def browser_automate(
    task: str,
    model: str = "qwen3.5:cloud",
    use_vision: bool = True,
) -> dict[str, Any]:
    """Run browser automation with AI to perform web tasks.

    This tool uses AI-powered browser automation to navigate websites, interact
    with elements, and extract information. It's useful for tasks that require
    web browsing, form filling, data extraction, or multi-step web interactions.

    The browser automation runs asynchronously and returns results that can be
    processed by the agent for further analysis or action.

    Args:
        task: Natural language description of the browser task to perform
              (e.g., "Go to github.com and find trending Python repos")
        model: Ollama model to use for browser automation (default: llama3.1:8b)
        use_vision: Whether to enable vision capabilities for the browser (default: True)

    Returns:
        Dictionary containing:
        - success: Whether the browser automation succeeded
        - result: The result of the browser automation task
        - task: The task description that was executed
        - model: The model used for automation
        - vision_enabled: Whether vision was enabled
        - error: Error message if automation failed

    Example:
        # Search for information on a website
        browser_automate("Go to wikipedia.org and search for 'Python programming language'")

        # Fill out a form
        browser_automate("Go to example.com/contact and fill out the contact form with test data")

        # Extract data from a webpage
        browser_automate("Go to news.ycombinator.com and get the top 5 stories")

    Note: Requires browser-use library to be installed. Install with:
          pip install browser-use
    """
    import asyncio

    try:
        # Import browser-use components
        from browser_use import Agent, ChatOllama
    except ImportError as e:
        return {
            "success": False,
            "error": (
                f"browser-use library not installed: {e}\n\nInstall with: pip install browser-use"
            ),
            "task": task,
        }

    async def run_browser_task():
        """Execute the browser automation task asynchronously."""
        try:
            # Create the browser-use ChatOllama model
            llm = ChatOllama(model=model)

            # Create the browser-use agent
            agent = Agent(
                task=task,
                llm=llm,
                use_vision=use_vision,
            )

            # Run the agent
            result = await agent.run()

            # Extract result string
            if hasattr(result, "final_result"):
                final = result.final_result()
                if final:
                    return final
            if hasattr(result, "content"):
                return str(result.content)  # type: ignore
            return str(result)

        except Exception as e:  # noqa: BLE001
            return f"Browser automation error: {e!s}"

    # Run the async task
    try:
        # Check if we're already in an async context
        try:
            asyncio.get_running_loop()
            # We're in an async context, create a task
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(asyncio.run, run_browser_task())
                result = future.result(timeout=300)  # 5 minute timeout
        except RuntimeError:
            # No running loop, we can use asyncio.run directly
            result = asyncio.run(run_browser_task())

        return {
            "success": True,
            "result": result,
            "task": task,
            "model": model,
            "vision_enabled": use_vision,
        }

    except Exception as e:  # noqa: BLE001
        return {
            "success": False,
            "error": (f"Failed to run browser automation: {e!s}"),
            "task": task,
            "model": model,
            "vision_enabled": use_vision,
        }

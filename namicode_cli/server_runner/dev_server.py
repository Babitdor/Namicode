"""Dev server management with browser auto-open.

This module provides functionality to start, stop, and manage
development servers as background processes.
"""

from __future__ import annotations

import asyncio
import re
import socket
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from namicode_cli.process_manager import ProcessInfo, ProcessManager, ProcessStatus


# Common dev server commands and their default ports
DEV_SERVER_PATTERNS: dict[str, int] = {
    "npm run dev": 3000,
    "npm start": 3000,
    "yarn dev": 3000,
    "yarn start": 3000,
    "pnpm dev": 3000,
    "vite": 5173,
    "npx vite": 5173,
    "next dev": 3000,
    "npx next dev": 3000,
    "nuxt dev": 3000,
    "flask run": 5000,
    "uvicorn": 8000,
    "gunicorn": 8000,
    "python -m http.server": 8000,
    "python3 -m http.server": 8000,
    "php -S": 8000,
    "cargo run": 8080,
    "go run": 8080,
    "ruby -run -e httpd": 8080,
}

# Commands that should never be run as dev servers
BLOCKED_SERVER_PATTERNS: list[str] = [
    r"\bsudo\b",
    r"\brm\s",
    r"\bkill\b",
    r">\s*/dev/",
    r"\bformat\b",
    r"\bdel\s+\/",
    r"\brmdir\b",
]


@dataclass
class ServerInfo:
    """Information about a running dev server.

    Attributes:
        pid: Process ID
        name: Server name
        url: Server URL (e.g., http://localhost:3000)
        port: Port number
        status: Current health status
        command: Command used to start the server
    """

    pid: int
    name: str
    url: str
    port: int
    status: ProcessStatus
    command: str


def find_available_port(start_port: int = 3000, max_attempts: int = 100) -> int:
    """Find an available port starting from start_port.

    Args:
        start_port: Port to start searching from
        max_attempts: Maximum ports to try

    Returns:
        Available port number

    Raises:
        RuntimeError: If no available port found
    """
    for port in range(start_port, start_port + max_attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("localhost", port))
                return port
            except OSError:
                continue
    raise RuntimeError(
        f"No available ports in range {start_port}-{start_port + max_attempts}"
    )


def is_port_in_use(port: int) -> bool:
    """Check if a port is currently in use.

    Args:
        port: Port number to check

    Returns:
        True if port is in use, False otherwise
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("localhost", port))
            return False
        except OSError:
            return True


def extract_port_from_command(command: str, default: int = 3000) -> int:
    """Extract port number from a command string.

    Args:
        command: Command string to parse
        default: Default port if not found

    Returns:
        Extracted or default port number
    """
    # Common patterns: --port 3000, -p 8080, :8000, PORT=3000
    patterns = [
        r"--port[=\s]+(\d+)",
        r"-p[=\s]+(\d+)",
        r":(\d{4,5})\b(?!.*\.\w+)",  # Match :PORT but not in URLs like :3000/path
        r"PORT[=\s]+(\d+)",
        r"localhost:(\d+)",
        r"127\.0\.0\.1:(\d+)",
        r"0\.0\.0\.0:(\d+)",
    ]

    for pattern in patterns:
        match = re.search(pattern, command)
        if match:
            return int(match.group(1))

    # Check against known command patterns
    command_lower = command.lower()
    for cmd_pattern, port in DEV_SERVER_PATTERNS.items():
        if cmd_pattern in command_lower:
            return port

    return default


def validate_server_command(command: str) -> tuple[bool, str | None]:
    """Validate a server command for safety.

    Args:
        command: Command to validate

    Returns:
        Tuple of (is_valid, error_message)
    """
    # Check for blocked patterns
    for pattern in BLOCKED_SERVER_PATTERNS:
        if re.search(pattern, command, re.IGNORECASE):
            return False, f"Command contains blocked pattern for security: {pattern}"

    if not command.strip():
        return False, "Command cannot be empty"

    return True, None


async def wait_for_server(
    url: str,
    timeout: float = 60.0,
    poll_interval: float = 0.5,
) -> bool:
    """Wait for a server to become available.

    Args:
        url: URL to poll
        timeout: Maximum time to wait
        poll_interval: Time between polls

    Returns:
        True if server became available, False if timeout
    """
    import time

    start_time = time.time()

    while time.time() - start_time < timeout:
        try:
            # Try to connect to the server
            import urllib.request

            req = urllib.request.Request(url, method="HEAD")
            with urllib.request.urlopen(req, timeout=2) as response:
                if response.status < 500:
                    return True
        except Exception:
            pass

        await asyncio.sleep(poll_interval)

    return False


async def wait_for_port(
    port: int,
    timeout: float = 60.0,
    poll_interval: float = 0.5,
) -> bool:
    """Wait for a port to become available (in use by server).

    Args:
        port: Port to check
        timeout: Maximum time to wait
        poll_interval: Time between polls

    Returns:
        True if port is now in use (server started), False if timeout
    """
    import time

    start_time = time.time()

    while time.time() - start_time < timeout:
        if is_port_in_use(port):
            return True
        await asyncio.sleep(poll_interval)

    return False


def open_browser(url: str) -> bool:
    """Open URL in the default browser.

    Args:
        url: URL to open

    Returns:
        True if browser was opened successfully
    """
    try:
        webbrowser.open(url)
        return True
    except Exception:
        return False


async def start_dev_server(
    command: str,
    *,
    name: str = "dev-server",
    port: int | None = None,
    working_dir: str = ".",
    auto_open_browser: bool = True,
    env: dict[str, str] | None = None,
    output_callback: Callable[[str], None] | None = None,
    startup_timeout: float = 60.0,
) -> ServerInfo:
    """Start a development server as a managed process.

    Args:
        command: Command to start the server
        name: Name for the server process
        port: Port to use (auto-detected from command if not specified)
        working_dir: Working directory
        auto_open_browser: Whether to open browser when server is ready
        env: Additional environment variables
        output_callback: Callback for streaming output
        startup_timeout: Timeout waiting for server to be ready

    Returns:
        ServerInfo for the started server

    Raises:
        ValueError: If command is blocked
        RuntimeError: If server fails to start
    """
    # Validate command
    is_valid, error = validate_server_command(command)
    if not is_valid:
        raise ValueError(error)

    # Detect port if not specified
    if port is None:
        port = extract_port_from_command(command)

    # Check if port is already in use
    if is_port_in_use(port):
        # Try to find an available port
        try:
            port = find_available_port(port)
        except RuntimeError as e:
            raise RuntimeError(f"Port {port} is in use and no alternatives found: {e}")

    # Build URL
    url = f"http://localhost:{port}"
    health_check_url = url

    # Get process manager
    manager = ProcessManager.get_instance()

    # Start the process
    info = await manager.start_process(
        command,
        name=name,
        port=port,
        working_dir=working_dir,
        env=env,
        health_check_url=health_check_url,
        output_callback=output_callback,
    )

    # Wait for server to be ready (check port)
    server_ready = await wait_for_port(port, timeout=startup_timeout)

    if server_ready:
        info.status = ProcessStatus.HEALTHY

        # Auto-open browser if requested
        if auto_open_browser:
            open_browser(url)
    else:
        # Check if process is still alive
        if info.is_alive:
            info.status = ProcessStatus.UNHEALTHY
        else:
            info.status = ProcessStatus.FAILED
            raise RuntimeError(
                f"Server process exited with code {info.exit_code}. "
                f"Check output for errors."
            )

    return ServerInfo(
        pid=info.pid,
        name=info.name,
        url=url,
        port=port,
        status=info.status,
        command=command,
    )


async def stop_server(
    pid: int | None = None,
    name: str | None = None,
) -> bool:
    """Stop a running dev server.

    Args:
        pid: Process ID of server to stop
        name: Name of server to stop (alternative to pid)

    Returns:
        True if server was stopped
    """
    manager = ProcessManager.get_instance()

    if pid is not None:
        return await manager.stop_process(pid)
    elif name is not None:
        return await manager.stop_by_name(name)
    else:
        return False


def list_servers() -> list[ServerInfo]:
    """List all running dev servers.

    Returns:
        List of ServerInfo for running servers
    """
    manager = ProcessManager.get_instance()
    processes = manager.list_processes(alive_only=True)

    servers = []
    for info in processes:
        if info.port is not None:
            servers.append(
                ServerInfo(
                    pid=info.pid,
                    name=info.name,
                    url=f"http://localhost:{info.port}",
                    port=info.port,
                    status=info.status,
                    command=info.command,
                )
            )

    return servers


# Tool definitions for agent use

def start_dev_server_tool(
    command: str,
    name: str = "dev-server",
    port: int | None = None,
    working_dir: str = ".",
    auto_open_browser: bool = True,
) -> dict[str, Any]:
    """Start a development server with browser auto-open.

    Starts a dev server as a managed background process. The server will be
    automatically stopped when the CLI session ends.

    Args:
        command: Command to start the server.
                 Examples: "npm run dev", "python -m http.server 8000"
        name: Friendly name for the server (default: "dev-server")
        port: Port to use (auto-detected from command if not specified)
        working_dir: Directory to run the server in (default: current directory)
        auto_open_browser: Open browser when server is ready (default: True)

    Returns:
        Dictionary containing:
        - success: Whether server started successfully
        - pid: Process ID of the server
        - name: Server name
        - url: URL where server is accessible
        - port: Port number
        - message: Status message

    Notes:
        - Server output is streamed to the CLI in real-time
        - Server will be killed when the CLI session exits
        - Use /servers to list running servers
        - Use stop_server() or /kill to stop manually

    Examples:
        start_dev_server("npm run dev")
        start_dev_server("python -m http.server", port=8080)
        start_dev_server("uvicorn main:app --reload", name="api")
    """
    # This is a placeholder - actual implementation will be async
    return {
        "success": False,
        "error": "Tool must be called through agent framework",
        "command": command,
        "name": name,
        "port": port,
        "working_dir": working_dir,
        "auto_open_browser": auto_open_browser,
    }


def stop_server_tool(
    pid: int | None = None,
    name: str | None = None,
) -> dict[str, Any]:
    """Stop a running development server.

    Args:
        pid: Process ID of the server to stop
        name: Name of the server to stop (alternative to pid)

    Returns:
        Dictionary containing:
        - success: Whether server was stopped
        - message: Status message

    Examples:
        stop_server(pid=12345)
        stop_server(name="dev-server")
    """
    return {
        "success": False,
        "error": "Tool must be called through agent framework",
        "pid": pid,
        "name": name,
    }


def list_servers_tool() -> dict[str, Any]:
    """List all running development servers.

    Returns:
        Dictionary containing:
        - servers: List of server info dictionaries
        - count: Number of running servers
    """
    servers = list_servers()
    return {
        "success": True,
        "servers": [
            {
                "pid": s.pid,
                "name": s.name,
                "url": s.url,
                "port": s.port,
                "status": s.status.value,
                "command": s.command,
            }
            for s in servers
        ],
        "count": len(servers),
    }

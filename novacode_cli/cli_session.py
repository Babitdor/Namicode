"""CLI session management and helper functions.

This module contains extracted functions from main.py for better organization:
- Session display helpers (splash screen, model info, memory status)
- Session save/restore logic
- Signal handling for graceful shutdown
- Auto-save functionality
"""

import asyncio
import signal
import sys
import time
from collections import deque
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from novacode_cli.states.Session import SessionState

# Constants
AUTO_SAVE_INTERVAL_SECONDS = 300  # Save session every 5 minutes
AUTO_SAVE_MESSAGE_THRESHOLD = 5  # Also save after every N new messages
MAX_SEEN_MESSAGE_IDS = 10000  # Maximum number of message IDs to track


class SeenMessageIds:
    """Bounded collection for tracking seen message IDs.

    Uses a deque with a maximum size to prevent unbounded memory growth.
    Older IDs are automatically evicted when the limit is reached.
    """

    def __init__(self, max_size: int = MAX_SEEN_MESSAGE_IDS):
        self._max_size = max_size
        self._ids: deque[str] = deque(maxlen=max_size)
        self._set: set[str] = set()

    def add(self, message_id: str) -> None:
        """Add a message ID to the tracking set."""
        if message_id in self._set:
            return
        # If deque is full, remove oldest from set
        if len(self._ids) == self._max_size:
            oldest = self._ids.popleft()
            self._set.discard(oldest)
        self._ids.append(message_id)
        self._set.add(message_id)

    def __contains__(self, message_id: str) -> bool:
        return message_id in self._set

    def __len__(self) -> int:
        return len(self._ids)

    def clear(self) -> None:
        """Clear all tracked message IDs."""
        self._ids.clear()
        self._set.clear()


class GracefulShutdown:
    """Flag-based signal handler for graceful shutdown.

    Uses a flag instead of raising KeyboardInterrupt directly in the signal
    handler, which is safer and more reliable across platforms.
    """

    def __init__(self):
        self._shutdown_requested = False
        self._original_handlers: dict = {}

    @property
    def shutdown_requested(self) -> bool:
        return self._shutdown_requested

    def request_shutdown(self) -> None:
        """Request a graceful shutdown."""
        self._shutdown_requested = True

    def reset(self) -> None:
        """Reset the shutdown flag."""
        self._shutdown_requested = False

    def install_handlers(self) -> None:
        """Install signal handlers for SIGTERM and SIGHUP (Unix-only)."""
        if sys.platform == "win32":
            return

        def _handler(signum, frame):
            self._shutdown_requested = True

        try:
            self._original_handlers[signal.SIGTERM] = signal.signal(
                signal.SIGTERM, _handler
            )
            self._original_handlers[signal.SIGHUP] = signal.signal(
                signal.SIGHUP, _handler
            )
        except (ValueError, OSError):
            pass  # Signal handling may fail in some contexts

    def restore_handlers(self) -> None:
        """Restore original signal handlers."""
        if sys.platform == "win32":
            return

        for sig, handler in self._original_handlers.items():
            try:
                signal.signal(sig, handler)
            except (ValueError, OSError):
                pass


class AutoSaveManager:
    """Manages auto-save timing and thresholds."""

    def __init__(
        self,
        interval_seconds: int = AUTO_SAVE_INTERVAL_SECONDS,
        message_threshold: int = AUTO_SAVE_MESSAGE_THRESHOLD,
    ):
        self._interval = interval_seconds
        self._threshold = message_threshold
        self._last_save_time = time.time()
        self._messages_since_save = 0

    @property
    def messages_since_save(self) -> int:
        return self._messages_since_save

    def increment_messages(self) -> None:
        self._messages_since_save += 1

    def reset_messages(self) -> None:
        self._messages_since_save = 0
        self._last_save_time = time.time()

    def should_save(self) -> bool:
        """Check if auto-save should run based on time or message count."""
        if self._messages_since_save == 0:
            return False

        time_elapsed = time.time() - self._last_save_time
        return time_elapsed >= self._interval or self._messages_since_save >= self._threshold


def display_splash_screen(console, no_splash: bool = False) -> None:
    """Display the startup splash screen and model info.

    Args:
        console: Rich console instance
        no_splash: If True, skip displaying the splash screen
    """
    from novacode_cli.config.config import COLORS, get_responsive_ascii

    if no_splash:
        return

    ascii_art = get_responsive_ascii(console)
    console.print(ascii_art, style=f"bold {COLORS['primary']}")
    console.print()


def display_model_info(console) -> None:
    """Display the current model information in a bordered panel.

    Args:
        console: Rich console instance
    """
    from novacode_cli.config.config import COLORS
    from novacode_cli.utils.model_info import get_model_info, get_provider_icon, get_provider_color
    from rich.panel import Panel
    from rich.text import Text
    from rich import box

    try:
        provider, model_name, display_name = get_model_info()
        provider_icon = get_provider_icon(provider)
        provider_color = get_provider_color(provider)

        model_text = Text()
        model_text.append(f"{provider_icon} ", style="bold")
        model_text.append(f"{provider.capitalize()}", style=f"bold {provider_color}")
        model_text.append(" • ", style="dim")
        model_text.append(f"{display_name}", style="bold white")

        panel = Panel(
            model_text,
            border_style=provider_color,
            box=box.DOUBLE,
            padding=(0, 1),
            expand=False,
        )
        console.print(panel)
        console.print()
    except Exception:
        pass  # If there's any error getting model info, just skip it


def display_sandbox_info(
    console,
    sandbox_type: str | None,
    sandbox_id: str | None,
    setup_script_path: str | None = None,
) -> None:
    """Display sandbox information if running in sandbox mode.

    Args:
        console: Rich console instance
        sandbox_type: Type of sandbox (e.g., "modal", "runloop", "daytona")
        sandbox_id: ID of the sandbox
        setup_script_path: Path to setup script that was run
    """
    if not sandbox_type or not sandbox_id:
        return

    console.print(
        f"[yellow]⚡ {sandbox_type.capitalize()} sandbox: {sandbox_id}[/yellow]"
    )
    if setup_script_path:
        console.print(
            f"[green]✓ Setup script ({setup_script_path}) completed successfully[/green]"
        )
    console.print()


def display_tavily_warning(console) -> None:
    """Display warning if Tavily API key is not configured.

    Args:
        console: Rich console instance
    """
    from novacode_cli.config.config import COLORS, settings

    if settings.has_tavily:
        return

    console.print(
        "[yellow]⚠ Web search disabled:[/yellow] TAVILY_API_KEY not found.",
        style=COLORS["dim"],
    )
    console.print(
        "  To enable web search, set your Tavily API key:", style=COLORS["dim"]
    )
    console.print(
        "    export TAVILY_API_KEY=your_api_key_here", style=COLORS["dim"]
    )
    console.print(
        "  Or add it to your .env file. Get your key at: https://tavily.com",
        style=COLORS["dim"],
    )
    console.print()


def display_working_directory(console, sandbox_type: str | None = None) -> None:
    """Display the current working directory.

    Args:
        console: Rich console instance
        sandbox_type: Type of sandbox if running in sandbox mode
    """
    from novacode_cli.config.config import COLORS
    from novacode_cli.integrations.sandbox_factory import get_default_working_dir

    if sandbox_type:
        working_dir = get_default_working_dir(sandbox_type)
        console.print(f"  [dim]Local CLI directory: {Path.cwd()}[/dim]")
        console.print(f"  [dim]Code execution: Remote sandbox ({working_dir})[/dim]")
    else:
        console.print(f"  [dim]{Path.cwd()}[/dim]")


def display_memory_status(console, assistant_id: str | None) -> None:
    """Display memory status (agent.md / NOVA.md loaded).

    Args:
        console: Rich console instance
        assistant_id: Agent identifier for memory storage
    """
    from novacode_cli.config.config import settings

    if assistant_id:
        user_agent_md = settings.get_user_agent_md_path(assistant_id)
        has_user_memory = user_agent_md.exists()
    else:
        has_user_memory = False

    project_agent_mds = settings.get_project_agent_md_paths()
    has_project_memory = bool(project_agent_mds)

    if has_user_memory or has_project_memory:
        memory_parts = []
        if has_user_memory:
            memory_parts.append(f"(~/.nova/agents/{assistant_id}/agent.md)")
        if has_project_memory:
            names = ", ".join(p.name for p in project_agent_mds)
            memory_parts.append(f"Project: ({names})")
        console.print(f"  [dim]Memory: {', '.join(memory_parts)}[/dim]")
    else:
        console.print("  [dim]Memory: none (use /init to create project memory)[/dim]")


def display_tips(console) -> None:
    """Display keyboard shortcuts and tips.

    Args:
        console: Rich console instance
    """
    from novacode_cli.config.config import COLORS

    if sys.platform == "darwin":
        tips = (
            "Tips: ⏎ Enter to submit, ⌥ Option + ⏎ Enter for newline (or Esc+Enter), "
            "⌃E to open editor, ⌃T to toggle auto-approve, ⌃C to interrupt"
        )
    else:
        tips = (
            "Tips: Enter to submit, Alt+Enter (or Esc+Enter) for newline, "
            "Ctrl+E to open editor, Ctrl+T to toggle auto-approve, Ctrl+C to interrupt"
        )
    console.print(tips, style=f"dim {COLORS['dim']}")
    console.print()


def display_auto_approve_status(console, auto_approve: bool) -> None:
    """Display auto-approve status if enabled.

    Args:
        console: Rich console instance
        auto_approve: Whether auto-approve is enabled
    """
    if auto_approve:
        console.print(
            "  [yellow]⚡ Auto-approve: ON[/yellow] [dim](tools run without confirmation)[/dim]"
        )
        console.print()
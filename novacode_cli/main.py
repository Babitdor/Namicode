"""Main entry point and CLI loop for deepagents.

This module provides the primary CLI interface for nova-Code CLI, including:
- Command-line argument parsing and validation
- Interactive REPL loop for agent conversations
- Session management (save, restore, auto-save)
- Command handling for special CLI commands (/help, /tokens, etc.)
- Integration with sandbox backends and agent configuration
- Auto-save functionality for session persistence

The CLI loop handles:
1. Agent initialization with configuration and backends
2. User input collection via prompt_toolkit
3. Task execution through the deep agent
4. Tool approval and human-in-the-loop interaction
5. Output streaming and UI rendering
6. Session state management and persistence

Key Functions:
- parse_args(): Parse command-line arguments
- cli_main(): Main entry point for the CLI
- run_cli_session(): Execute the interactive CLI loop
- handle_command(): Handle special CLI commands (e.g., /help, /tokens)
"""

# Suppress transformer warnings before any imports that might trigger them
import os
import warnings

# Suppress "None of PyTorch, TensorFlow >= 2.0, or Flax have been found" warning
os.environ["TRANSFORMERS_VERBOSITY"] = "error"

# Silence HuggingFace Hub symlink warning on Windows (Semble/model2vec download)
if os.name == "nt":
    os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

# Suppress token sequence length warnings from transformers/tiktoken
warnings.filterwarnings(
    "ignore",
    message="Token indices sequence length is longer than",
)
warnings.filterwarnings(
    "ignore",
    message="None of PyTorch, TensorFlow",
)
warnings.filterwarnings(
    "ignore",
    message="Using fallback GPT-2 tokenizer for token counting",
)
# Suppress deepagents files_update deprecation warning (handled internally by deepagents)
from langchain_core._api.deprecation import LangChainDeprecationWarning

warnings.filterwarnings(
    "ignore",
    message=".*files_update.*",
    category=LangChainDeprecationWarning,
)

import argparse
import asyncio
import io
import logging
import signal
import sys
import time
from pathlib import Path

# Fix Windows console encoding to handle Unicode characters
# This must be done before any output is written.
# Skip under pytest: replacing sys.stdout/stderr here would detach pytest's
# output capture (its buffers get closed at session end -> "I/O operation on
# closed file"). The real CLI never runs under pytest, so this only guards tests.
if sys.platform == "win32" and "pytest" not in sys.modules:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# Configure logging to a file for troubleshooting
# Logs are saved to ~/.nova/logs/nova.log
log_dir = Path.home() / ".nova" / "logs"
log_dir.mkdir(parents=True, exist_ok=True)
log_file = log_dir / "nova.log"

# Configure file handler for warnings
file_handler = logging.FileHandler(log_file, mode="a", encoding="utf-8")
file_handler.setLevel(logging.WARNING)
file_handler.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))

# Configure root logger
root_logger = logging.getLogger()
root_logger.setLevel(logging.WARNING)
root_logger.addHandler(file_handler)

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.base import BaseStore
from novacode_cli.doctor import run_doctor

try:
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver as _AsyncSqliteSaver  # type: ignore

    _SQLITE_CHECKPOINTER_AVAILABLE = True
except ImportError:
    _SQLITE_CHECKPOINTER_AVAILABLE = False
from deepagents.backends.sandbox import BaseSandbox

# Apply safety patches for backends that don't handle all content block types
# (e.g., Ollama crashes on "file" type blocks from PDF reads)
from novacode_cli.utils.backend_patches import (
    apply_filesystem_host_path_patch,
    apply_ollama_content_block_patch,
    apply_write_file_dict_content_patch,
)

apply_ollama_content_block_patch()
# Let the agent pass real host paths inside the project to file tools without
# tripping deepagents' "Windows absolute paths are not supported" rejection.
apply_filesystem_host_path_patch()
# Tolerate a dict/list `content` to write_file (models pass JSON as an object) —
# serialize it to a string so the write succeeds (e.g. /init graph fragments).
apply_write_file_dict_content_patch()

from novacode_cli.agents.core_agent import (
    create_agent_with_config,
    list_agents,
    reset_agent,
)
from novacode_cli.cli_session import (
    AUTO_SAVE_INTERVAL_SECONDS,
    AUTO_SAVE_MESSAGE_THRESHOLD,
    AutoSaveManager,
    GracefulShutdown,
    SeenMessageIds,
    display_auto_approve_status,
    display_memory_status,
    display_model_info,
    display_sandbox_info,
    display_splash_screen,
    display_tavily_warning,
    display_tips,
    display_working_directory,
)
from novacode_cli.commands.commands import (
    execute_bash_command,
    execute_skills_command,
    handle_command,
)
from novacode_cli.config.config import (
    COLORS,
    HOME_DIR,
    NOVA_CODE_ASCII,
    boot_status,
    console,
    settings,
    get_responsive_ascii,
)
from novacode_cli.config.model_create import create_model
from novacode_cli.input import (
    ImageTracker,
    PasteTracker,
    create_prompt_session,
    resolve_paste_placeholders,
)
from novacode_cli.tracking.tracing import auto_configure as _auto_configure_tracing

# Initialize LangSmith tracing from environment variables (no-op when not configured)
_auto_configure_tracing()
from novacode_cli.integrations.sandbox_factory import (
    create_sandbox,
    get_default_working_dir,
)
from novacode_cli.mcp.commands import execute_mcp_command, setup_mcp_parser
from novacode_cli.migrate import check_migration_status, migrate_agents
from novacode_cli.path_approval import PathApprovalManager, check_path_approval
from novacode_cli.skills.skill_creation import setup_skills_parser
from novacode_cli.states.Session import SessionState
from novacode_cli.tools import (
    code_search,
    docs_search,
    duckduckgo_search,
    fetch_url,
    find_related_code,
    forget,
    github_trending,
    hacker_news,
    linkedin_jobs,
    list_memories,
    package_info,
    query_project_graph,
    read_memory,
    recall,
    reddit_posts,
    remember,
    skill_manage,
    speak,
    think,
    web_search,
    wiki_read,
    wiki_search,
    wiki_update_index,
    wiki_write,
    write_memory,
)
from novacode_cli.tools.plan_mode_tools import (
    ask_user_question,
    enter_plan_mode,
    exit_plan_mode,
)
from novacode_cli.ui.execution import execute_task

# Vixie desktop pet integration
from novacode_cli.vixie.server import start_vixie_server, stop_vixie_server

from novacode_cli.process_manager import ProcessManager
from novacode_cli.ui.ui_elements import TokenTracker, show_help
from novacode_cli.hooks import dispatch_hook_fire_and_forget, HookEvent


def check_cli_dependencies() -> None:
    """Check if CLI optional dependencies are installed."""
    missing = []

    try:
        import rich
    except ImportError:
        missing.append("rich")

    try:
        import requests
    except ImportError:
        missing.append("requests")

    try:
        import dotenv
    except ImportError:
        missing.append("python-dotenv")

    try:
        import tavily
    except ImportError:
        missing.append("tavily-python")

    try:
        import prompt_toolkit
    except ImportError:
        missing.append("prompt-toolkit")

    if missing:
        print("\n❌ Missing required CLI dependencies!")
        print("\nThe following packages are required to use the deepagents CLI:")
        for pkg in missing:
            print(f"  - {pkg}")
        print("\nPlease install them with:")
        print("  uv add 'deepagents[cli]'")
        sys.exit(1)


def format_version_banner(version: str) -> str:
    """Return a styled version banner for ``nova --version``."""
    return f"""
⣿⣿⣿⣿⣟⠊⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠙⢿⣿
⣿⣿⣿⡏⠁⠀⠀⠀⠀⠀⠀⢀⣰⣶⣶⡄⠀⠀⠀⠀⠀⠀⢀⠀⠀⠈⢻
⣿⣿⣿⠁⠄⠀⠀⠀⠀⠀⣤⣾⣿⣿⣿⣿⡂⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠽
⣿⣿⡏⣸⠀⠀⠀⠀⢀⣼⣿⣿⣿⣿⣿⣿⣿⡆⠀⠀⠈⠀⠀⠀⠀⠀⠀⠰
⣿⣿⡇⠁⠀⠀⠀⣤⣍⣙⣿⣿⣏⣠⠄⠲⠲⠦⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢻
⣿⣿⠁⠀⠀⠀⠀⠀⢤⠙⣿⣿⣿⣇⣀⡐⢂⣠⡄⠠⠀⠀⠀⠀⠀⠀⡀⢠⢸
⣿⣿⠀⠀⠐⠀⣶⣷⣷⣾⣿⣿⣿⣿⣿⣿⣿⣿⣿⠀⠀⠐⠈⠀⠀⠀⠉⠘⣼
⣿⣿⠀⠈⠀⠀⣿⣿⣿⡿⣿⠿⢿⣿⣿⣿⣿⣿⣿⣧⡀⠀⢄⠲⠀⠀⠀⣱
⣿⣿⡆⠀⠀⠀⠈⣿⣿⣷⣶⣼⣾⣿⣿⣿⣿⣿⣿⣿⣷⠂⠀⠀⠂⢀⢲
⣿⣿⣿⡆⠀⠀⠀⠙⣿⠋⠠⠄⢀⠉⣹⣿⣿⣿⣿⣿⣿⠀⠀⠀⠀⠀⣿
⣿⣿⣿⣿⣦⠀⠀⠀⠘⣿⣤⣤⣶⣿⣿⣿⣿⣿⠟⣛⡽⠀⠀⠀⠠⣸
⣿⣿⣿⣿⣿⣷⡀⠀⠀⠈⠻⣿⣿⣿⠿⠛⠋⠐⠚⠛⠃   ⣰⣿

███╗   ██╗ ██████╗  ██╗   ██╗  █████╗
████╗  ██║ ██╔═══██╗ ██║   ██║ ██╔══██╗
██╔██╗ ██║ ██║   ██║ ██║   ██║ ███████║
██║╚██╗██║ ██║   ██║ ╚██╗ ██╔╝ ██╔══██║
██║ ╚████║ ╚██████╔╝  ╚████╔╝  ██║  ██║
╚═╝  ╚═══╝  ╚═════╝    ╚═══╝   ╚═╝  ╚═╝ ~ v{version}
"""


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="DeepAgents - AI Coding Assistant",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        add_help=False,
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Init command - interactive configuration setup
    init_parser = subparsers.add_parser("init", help="Initialize project or global configuration")
    init_parser.add_argument(
        "--scope",
        choices=["project", "global"],
        help="Create project-specific or global configuration",
    )
    init_parser.add_argument(
        "--style",
        choices=["deepagents", "claude"],
        help="Use .nova/ or .claude/ directory structure",
    )
    init_parser.add_argument(
        "--reset",
        action="store_true",
        help="Re-run onboarding wizard to reset configuration",
    )

    # List command
    subparsers.add_parser("list", help="List all available agents")

    # Help command
    subparsers.add_parser("help", help="Show help information")

    # Reset command
    reset_parser = subparsers.add_parser("reset", help="Reset an agent")
    reset_parser.add_argument("--agent", required=True, help="Name of agent to reset")
    reset_parser.add_argument(
        "--target", dest="source_agent", help="Copy prompt from another agent"
    )

    # Skills command - setup delegated to skills module
    setup_skills_parser(subparsers)

    # MCP command - setup delegated to mcp module
    setup_mcp_parser(subparsers)

    # Config command - view/edit configuration
    config_parser = subparsers.add_parser("config", help="View or edit configuration (non-secret)")
    config_parser.add_argument(
        "config_command",
        nargs="?",
        choices=["show", "set", "get"],
        default="show",
        help="Config operation to perform",
    )
    config_parser.add_argument(
        "key",
        nargs="?",
        help="Configuration key to get/set",
    )
    config_parser.add_argument(
        "value",
        nargs="?",
        help="Value to set (for 'set' command)",
    )

    # Secrets command - manage API keys
    secrets_parser = subparsers.add_parser("secrets", help="Manage API keys securely")
    secrets_parser.add_argument(
        "secrets_command",
        choices=["set", "list", "delete"],
        help="Secrets operation to perform",
    )
    secrets_parser.add_argument(
        "key",
        nargs="?",
        help="API key name (e.g., 'openai_api_key')",
    )

    # Doctor command - validate setup
    subparsers.add_parser("doctor", help="Validate configuration and connections")

    # Paths command - manage approved paths
    paths_parser = subparsers.add_parser(
        "paths",
        help="Manage approved file system paths",
    )
    paths_subparsers = paths_parser.add_subparsers(dest="paths_command", help="Paths command")

    # paths list
    paths_subparsers.add_parser(
        "list",
        help="List all approved paths",
    )

    # paths revoke
    revoke_parser = paths_subparsers.add_parser(
        "revoke",
        help="Revoke approval for a path",
    )
    revoke_parser.add_argument(
        "path",
        help="Path to revoke (absolute path)",
    )

    # paths clear
    paths_subparsers.add_parser(
        "clear",
        help="Clear all approved paths",
    )

    # Migrate command - migrate from old to new directory structure
    migrate_parser = subparsers.add_parser(
        "migrate",
        help="Migrate from old directory structure to new Claude Code-compatible structure",
    )
    migrate_parser.add_argument(
        "--check",
        action="store_true",
        help="Check migration status without performing migration",
    )

    # Default interactive mode
    parser.add_argument(
        "--agent",
        default="nova-agent",
        help="Agent identifier for separate memory stores (default: nova-agent).",
    )
    parser.add_argument(
        "--auto-approve",
        action="store_true",
        help="Auto-approve tool usage without prompting (disables human-in-the-loop)",
    )
    parser.add_argument(
        "--sandbox",
        choices=["none", "os", "modal", "daytona", "runloop", "docker", "langsmith"],
        default=None,
        help="Sandbox for code execution. Default: 'os' on Linux/macOS (files on the "
        "host, shell confined to the workspace via an OS sandbox); host execution + "
        "approvals on Windows. 'docker' is an opt-in, Windows-only container. "
        "'langsmith' uses LangSmith Sandboxes (hardware-virtualized microVMs). Use "
        "--no-sandbox for unconfined local execution.",
    )
    parser.add_argument(
        "--no-sandbox",
        action="store_true",
        help="Run shell commands unconfined on the host (disables the OS/Docker sandbox)",
    )
    parser.add_argument(
        "--sandbox-id",
        help="Existing sandbox ID to reuse (skips creation and cleanup)",
    )
    parser.add_argument(
        "--sandbox-setup",
        help="Path to setup script to run in sandbox after creation",
    )
    parser.add_argument(
        "--sandbox-vcpus",
        type=int,
        default=None,
        help="Number of virtual CPUs for the sandbox (LangSmith only)",
    )
    parser.add_argument(
        "--sandbox-mem-bytes",
        type=int,
        default=None,
        help="Memory in bytes for the sandbox (LangSmith only). Example: 8589934592 for 8GB",
    )
    parser.add_argument(
        "--sandbox-fs-capacity-bytes",
        type=int,
        default=None,
        help="Filesystem capacity in bytes for the sandbox (LangSmith only)",
    )
    parser.add_argument(
        "--sandbox-snapshot",
        type=str,
        default=None,
        help="Snapshot name to boot the sandbox from (LangSmith only, mutually "
        "exclusive with --sandbox-snapshot-id)",
    )
    parser.add_argument(
        "--sandbox-snapshot-id",
        type=str,
        default=None,
        help="Snapshot ID to boot the sandbox from (LangSmith only, mutually "
        "exclusive with --sandbox-snapshot)",
    )
    parser.add_argument(
        "--ports",
        type=str,
        help="Port forwarding for Docker sandbox (format: 'PORT' or 'HOST_PORT:CONTAINER_PORT'). "
        "Multiple ports separated by comma. Example: '8080,3000:3000,5432:5432'",
    )
    parser.add_argument(
        "--no-splash",
        action="store_true",
        help="Disable the startup splash screen",
    )
    parser.add_argument(
        "--tui",
        action="store_true",
        dest="legacy_ui",
        help="Use the classic Rich-based REPL instead of the default TUI (deprecated, use --legacy-ui)",
    )
    parser.add_argument(
        "--legacy-ui",
        action="store_true",
        help="Use the classic Rich-based REPL instead of the default TUI",
    )
    parser.add_argument(
        "--continue",
        "-c",
        dest="continue_session",
        nargs="?",
        const=True,
        default=False,
        help="Continue last session (optionally specify session ID)",
    )
    parser.add_argument(
        "--resume",
        "-r",
        action="store_true",
        help="Interactively select and resume a session",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=format_version_banner(settings.version),
        help="Show the version number and exit",
    )
    parser.add_argument("-h", "--help", action="help", help="Show this help message and exit")

    return parser.parse_args()


def parse_ports(ports_str: str | None) -> dict[int, int] | None:
    """Parse port forwarding argument.

    Args:
        ports_str: Port string in format 'PORT' or 'HOST_PORT:CONTAINER_PORT'.
                   Multiple ports separated by comma.
                   Example: '8080,3000:3000,5432:5432'

    Returns:
        Dictionary mapping container ports to host ports, or None if no ports.
        Example: {8080: 8080, 3000: 3000, 5432: 5432}
    """
    if not ports_str:
        return None

    ports = {}
    for port_spec in ports_str.split(","):
        port_spec = port_spec.strip()
        if ":" in port_spec:
            # Format: HOST_PORT:CONTAINER_PORT
            host_port_str, container_port_str = port_spec.split(":", 1)
            host_port = int(host_port_str)
            container_port = int(container_port_str)
        else:
            # Format: PORT (same for both host and container)
            port = int(port_spec)
            host_port = port
            container_port = port
        ports[container_port] = host_port

    return ports if ports else None


def resolve_sandbox_type(
    sandbox_arg: str | None,
    no_sandbox: bool,  # noqa: FBT001
    platform: str | None = None,
) -> tuple[str, bool]:
    """Resolve the effective sandbox mode and whether the user chose it explicitly.

    The default depends on platform. Linux/macOS get Pattern A (``"os"`` — host
    files + an OS-confined shell). Windows has no lightweight OS sandbox primitive,
    so the default is plain host execution (``"none"``) gated by the
    dangerous-command blocklist + HITL approval — the same baseline Claude Code /
    Cursor use on Windows. Docker stays available there as an explicit opt-in
    (``--sandbox docker``); it is Windows-only and rejected elsewhere (Linux/macOS
    should use the ``"os"`` default or ``--no-sandbox``).

    Args:
        sandbox_arg: The ``--sandbox`` value, or None when unset.
        no_sandbox: Whether ``--no-sandbox`` was passed.
        platform: ``sys.platform`` override (for tests). Defaults to the host.

    Returns:
        ``(sandbox_type, explicit)`` — ``explicit`` is True when the user chose
        the mode (so a creation failure should not silently fall back).

    Raises:
        ValueError: On invalid combinations (caller maps these to a user error).
    """
    is_windows = (platform or sys.platform) == "win32"

    if no_sandbox:
        if sandbox_arg and sandbox_arg != "none":
            msg = "--no-sandbox conflicts with --sandbox."
            raise ValueError(msg)
        return "none", True

    if sandbox_arg is not None:
        if sandbox_arg == "docker" and not is_windows:
            msg = (
                "--sandbox docker is Windows-only. On Linux/macOS, Nova confines the "
                "shell with an OS sandbox by default (--sandbox os). Use --no-sandbox "
                "for unconfined local execution."
            )
            raise ValueError(msg)
        return sandbox_arg, True

    # Implicit default: host execution + approvals on Windows (no lightweight OS
    # sandbox primitive — Docker is opt-in via --sandbox docker); Pattern A
    # (OS-confined shell) on Linux/macOS.
    return ("none" if is_windows else "os"), False


async def simple_cli(
    agent,
    assistant_id: str | None,
    session_state,
    baseline_tokens: int = 0,
    backend=None,
    sandbox_type: str | None = None,
    setup_script_path: str | None = None,
    no_splash: bool = False,
    model_name: str | None = None,
    session_manager=None,
    store: BaseStore | None = None,
    checkpointer: InMemorySaver | None = None,
    restored_session_data: tuple | None = None,
) -> None:
    """Main CLI loop.

    Args:
        agent: The LangGraph agent
        assistant_id: Agent identifier for memory storage
        session_state: Session state with auto-approve settings
        baseline_tokens: Baseline token count for tracking
        backend: Backend for file operations (CompositeBackend)
        sandbox_type: Type of sandbox being used (e.g., "modal", "runloop", "daytona", "docker", "langsmith").
        model_name: Name of the model being used for context window calculation.
                     If None, running in local mode.
        setup_script_path: Path to setup script that was run (if any)
        no_splash: If True, skip displaying the startup splash screen
        session_manager: SessionManager for session persistence
        restored_session_data: Tuple of (session_data, warnings, nova_md_loaded) for continuation
    """
    console.clear()

    # Fire session.start hook
    dispatch_hook_fire_and_forget(
        HookEvent.SESSION_START,
        {
            "session_id": session_state.session_id,
            "thread_id": session_state.thread_id,
            "assistant_id": assistant_id,
            "model": model_name,
            "sandbox": sandbox_type,
            "continued": bool(restored_session_data),
        },
    )

    # Check path approval before proceeding
    if not await check_path_approval():
        console.print()
        console.print(
            "[red]Cannot start nova without path approval.[/red]",
            style=COLORS["dim"],
        )
        console.print("[dim]Path approval is required to ensure safe file system access.[/dim]")
        console.print()
        sys.exit(1)

    # Display splash screen and model info
    display_splash_screen(console, no_splash)
    if not no_splash:
        display_model_info(console)

    # Extract sandbox ID from backend if using sandbox mode
    sandbox_id: str | None = None
    sandbox_meta: dict | None = None
    if backend:
        from deepagents.backends.composite import CompositeBackend

        # Check if it's a CompositeBackend with a real sandbox as the default
        # backend. LocalShellBackend implements SandboxBackendProtocol but is not
        # a remote sandbox, so we require a BaseSandbox subclass.
        if isinstance(backend, CompositeBackend):
            if isinstance(backend.default, BaseSandbox):
                sandbox_id = backend.default.id
                sandbox_meta = getattr(backend.default, "_nova_meta", None)
        elif isinstance(backend, BaseSandbox):
            sandbox_id = backend.id
            sandbox_meta = getattr(backend, "_nova_meta", None)

    # Display sandbox info persistently (survives console.clear())
    display_sandbox_info(
        console, sandbox_type, sandbox_id, setup_script_path, meta=sandbox_meta
    )

    # Display Tavily warning if API key not configured
    display_tavily_warning(console)

    console.print()

    # Display working directory
    display_working_directory(console, sandbox_type)

    # Show memory status (agent.md / NOVA.md loaded)
    display_memory_status(console, assistant_id)

    console.print()

    # Display restored session info if continuing
    if restored_session_data:
        from novacode_cli.ui.session_display import display_restored_session

        session_data, warnings, Nova_md_loaded = restored_session_data
        display_restored_session(
            session_data=session_data,
            warnings=warnings,
            Nova_md_loaded=Nova_md_loaded,
        )
        # Fire session.continue hook
        dispatch_hook_fire_and_forget(
            HookEvent.SESSION_CONTINUE,
            {
                "session_id": session_state.session_id,
                "thread_id": session_state.thread_id,
            },
        )

    # Display auto-approve status if enabled
    display_auto_approve_status(console, session_state.auto_approve)

    # Display keyboard shortcuts and tips
    display_tips(console)

    console.print()

    # Create prompt session and token tracker
    token_tracker = TokenTracker()
    image_tracker = ImageTracker()
    paste_tracker = PasteTracker()
    session = create_prompt_session(assistant_id, session_state, image_tracker, paste_tracker)
    token_tracker.set_baseline(baseline_tokens)
    if model_name:
        token_tracker.set_model(model_name)
    # Store token_tracker on session_state so the toolbar can access it
    session_state.token_tracker = token_tracker
    # Store image_tracker on session_state for remote message processor access
    session_state._image_tracker = image_tracker
    # Store paste_tracker on session_state for remote access
    session_state._paste_tracker = paste_tracker

    # Helper to save session (used by both cleanup and auto-save)
    async def _save_session(*, silent: bool = False) -> bool:
        """Save current session state.

        Args:
            silent: If True, don't print success message

        Returns:
            True if saved successfully, False otherwise
        """
        if not session_manager or not assistant_id:
            return False

        try:
            from novacode_cli.session.session_summarization import (
                should_trigger_summarization,
                summarize_messages_to_memory,
            )
            from novacode_cli.tracking.workspace_anchoring import scan_workspace

            config = {"configurable": {"thread_id": session_state.thread_id}}
            state = await agent.aget_state(config)
            messages = state.values.get("messages", [])
            # Get todos from agent state if available
            todos = state.values.get("todos") or session_state.todos

            if messages:
                # Scan current workspace state
                workspace_state = (
                    scan_workspace(settings.project_root) if settings.project_root else None
                )

                # Extract current task from session state (if available)
                # For now, we'll use a simple heuristic - could be enhanced later
                current_task = getattr(session_state, "current_task", None)

                # Determine task status from state
                task_status = getattr(session_state, "task_status", "active")

                # Get context usage percentage for summarization threshold
                context_breakdown = token_tracker.get_breakdown()
                context_usage_percentage = context_breakdown.usage_percentage

                # Check if we should trigger summarization (only at 80%+ context usage)
                memory_content = None
                if should_trigger_summarization(
                    context_usage_percentage=context_usage_percentage,
                    task_status=task_status,
                ):
                    if not silent:
                        console.print("[dim]Generating session memory summary...[/dim]")
                    try:
                        # Get model for summarization
                        from novacode_cli.config.model_create import create_model

                        summary_model = create_model()
                        # Run the synchronous LLM call in a thread executor so it
                        # doesn't block the event loop and stall exit.
                        memory_content = await asyncio.to_thread(
                            summarize_messages_to_memory,
                            messages=messages,
                            model=summary_model,
                            current_task=current_task,
                        )
                    except Exception as e:
                        console.print(
                            f"[yellow]Warning: Could not generate memory summary: {type(e).__name__}: {e}[/yellow]"
                        )

                session_dir = session_manager.save_session(
                    session_id=session_state.session_id,
                    thread_id=session_state.thread_id,
                    messages=messages,
                    assistant_id=assistant_id,
                    todos=todos,
                    model_name=model_name,
                    project_root=settings.project_root,
                    workspace_state=workspace_state,
                    current_task=current_task,
                    task_status=task_status,
                    memory=memory_content,
                    sandbox_id=sandbox_id,
                    sandbox_type=sandbox_type,
                )
                if not silent:
                    console.print(f"[dim]Session saved to {session_dir}[/dim]")
                # Fire session.save hook
                dispatch_hook_fire_and_forget(
                    HookEvent.SESSION_SAVE,
                    {
                        "session_id": session_state.session_id,
                        "thread_id": session_state.thread_id,
                        "session_dir": str(session_dir),
                        "message_count": len(messages),
                    },
                )
                return True
        except Exception as e:
            error_msg = f"[red]Error saving session: {type(e).__name__}: {e}[/red]"
            console.print(error_msg)  # Always show save errors regardless of silent flag
        return False

    # Helper to clean up and save session on exit
    async def _cleanup_and_save_session() -> None:
        """Clean up managed processes and save session state when user exits.

        All cleanup steps that don't depend on each other run CONCURRENTLY
        with a shared 20s deadline, followed by compaction + save (sequential)
        with a 60s deadline.  This prevents any single hanging operation from
        blocking exit indefinitely.
        """
        # Fire session.end hook (fire-and-forget, doesn't await)
        dispatch_hook_fire_and_forget(
            HookEvent.SESSION_END,
            {
                "session_id": session_state.session_id,
                "thread_id": session_state.thread_id,
                "assistant_id": assistant_id,
            },
        )

        # ═══════════════════════════════════════════════════════════════
        # Parallel cleanup — independent tasks run concurrently so the
        # slowest (not the sum) determines the wall-clock time.
        # Each sub-step also carries its own per-step timeout.
        # ═══════════════════════════════════════════════════════════════

        async def _stop_vixie():
            try:
                await asyncio.wait_for(stop_vixie_server(), timeout=5.0)
            except Exception as e:
                console.print(f"[dim]Could not stop Vixie server: {e}[/dim]")

        async def _stop_processes():
            try:
                manager = ProcessManager.get_instance()
                stopped_count = await asyncio.wait_for(manager.stop_all(), timeout=15.0)
                if stopped_count > 0:
                    console.print(f"[dim]Stopped {stopped_count} managed process(es).[/dim]")
            except Exception as e:
                console.print(f"[dim]Could not stop processes: {e}[/dim]")

        async def _stop_remote_bridges():
            try:
                bridge_mgr = getattr(session_state, "_remote_bridge_manager", None)
                if bridge_mgr:
                    await asyncio.wait_for(bridge_mgr.stop_all(), timeout=5.0)
            except Exception as e:
                console.print(f"[dim]Could not stop remote bridges: {e}[/dim]")

        async def _stop_trello():
            try:
                trello_server = getattr(session_state, "trello_server", None)
                if trello_server and trello_server.is_running:
                    trello_server.stop()
                    session_state.trello_server = None
            except Exception as e:
                console.print(f"[dim]Could not stop Trello server: {e}[/dim]")

        async def _cancel_remote_processor():
            """Cancel remote message processor with brief await."""
            try:
                _rpt = getattr(session_state, "_remote_processor_task", None)
                if _rpt and not _rpt.done():
                    _rpt.cancel()
                    # Give it a brief moment to finish cleanup, but
                    # don't block exit if it's slow to respond.
                    try:
                        await asyncio.wait_for(_rpt, timeout=2.0)
                    except (asyncio.CancelledError, asyncio.TimeoutError):
                        pass
            except Exception:
                pass

        async def _stop_event_sources():
            """Stop the cron scheduler and webhook server (Enhancements 3 / 5)."""
            for attr in ("_cron_scheduler", "_webhook_server"):
                try:
                    src = getattr(session_state, attr, None)
                    if src is not None:
                        await asyncio.wait_for(src.stop(), timeout=3.0)
                except Exception:
                    pass

        # Run all cleanup concurrently with a shared 20s deadline.
        # Individual steps have their own per-step timeouts as well.
        try:
            await asyncio.wait_for(
                asyncio.gather(
                    _stop_vixie(),
                    _stop_processes(),
                    _stop_remote_bridges(),
                    _stop_trello(),
                    _cancel_remote_processor(),
                    _stop_event_sources(),
                ),
                timeout=20.0,
            )
        except (asyncio.TimeoutError, Exception):
            console.print("[dim]Some cleanup tasks timed out, continuing exit...[/dim]")

        # ═══════════════════════════════════════════════════════════════
        # Sequential post-cleanup: compaction check + save.
        # Protected by a 60s deadline so LLM calls can't hang exit.
        # ═══════════════════════════════════════════════════════════════
        try:
            await asyncio.wait_for(
                _maybe_compact_on_exit(),
                timeout=30.0,
            )
        except asyncio.TimeoutError:
            console.print("[dim]Compaction timed out, skipping...[/dim]")

        try:
            await asyncio.wait_for(
                _save_session(silent=False),
                timeout=30.0,
            )
        except asyncio.TimeoutError:
            console.print("[dim]Session save timed out; exiting anyway.[/dim]")

    async def _maybe_compact_on_exit() -> None:
        """Check context usage and perform compaction if needed on exit.

        This analyzes the conversation and automatically compacts if:
        - Context usage is above critical threshold (90%)
        - Context usage is above warning threshold (75%) with many messages
        - Conversation has 100+ messages
        """
        from novacode_cli.compaction import compact_conversation
        from novacode_cli.config.model_create import create_model
        from novacode_cli.context import ContextManager

        try:
            # Get current conversation state
            config = {"configurable": {"thread_id": session_state.thread_id}}
            state = await agent.aget_state(config)
            messages = state.values.get("messages", [])

            if not messages:
                return

            # Get baseline tokens from token tracker (correct attribute name)
            baseline_tokens = getattr(token_tracker, "baseline_context", 0)

            # If the API has already told us the real token count this session,
            # use that directly — it's more accurate than the char/4 estimate
            # from build_context_breakdown(). Bypass re-estimation entirely.
            if token_tracker and getattr(token_tracker, "has_api_data", False):
                api_tokens = token_tracker.current_context
                window = token_tracker.context_window_size
                usage_pct = (api_tokens / window * 100) if window else 0.0
                tokens_avail = max(0, window - api_tokens)
                total_messages = len(messages)

                from novacode_cli.context import (
                    CONTEXT_CRITICAL_THRESHOLD,
                    CONTEXT_WARNING_THRESHOLD,
                    CompactionRecommendation,
                )

                human_ai_tool = sum(
                    1
                    for m in messages
                    if not hasattr(m, "type") or getattr(m, "type", "") != "system"
                )
                should_compact = (
                    usage_pct >= CONTEXT_CRITICAL_THRESHOLD * 100
                    or (usage_pct >= CONTEXT_WARNING_THRESHOLD * 100 and total_messages >= 20)
                    or (usage_pct >= 50 and total_messages >= 50)
                    or total_messages >= 100
                )
                recommendation = CompactionRecommendation(
                    should_compact=should_compact,
                    reason=f"Context at {usage_pct:.1f}% ({api_tokens:,} tokens)",
                    usage_percentage=usage_pct,
                    tokens_used=api_tokens,
                    tokens_available=tokens_avail,
                    messages_count=total_messages,
                )
            else:
                # No API data yet — fall back to char/4 estimation from messages
                recommendation = ContextManager(model_name).recommend_compaction(
                    messages,
                    baseline_tokens=baseline_tokens,
                )

            if not recommendation.should_compact:
                # No compaction needed - just show brief status
                console.print(
                    f"[dim]Context: {recommendation.usage_percentage:.1f}% used "
                    f"({recommendation.tokens_used:,} / {recommendation.tokens_used + recommendation.tokens_available:,} tokens)[/dim]"
                )
                return

            # Show compaction recommendation
            console.print()
            console.print("[bold yellow]Context Optimization[/bold yellow]")
            console.print(f"[dim]{recommendation.reason}[/dim]")
            console.print(
                f"[dim]Messages: {recommendation.messages_count} | "
                f"Tokens: {recommendation.tokens_used:,} ({recommendation.usage_percentage:.1f}%)[/dim]"
            )

            if recommendation.estimated_tokens_saved > 0:
                console.print(
                    f"[dim]Estimated savings: ~{recommendation.estimated_tokens_saved:,} tokens[/dim]"
                )

            # Perform compaction with a per-step timeout so the LLM
            # summarization call can't stall exit indefinitely.
            model = create_model()
            with console.status("[bold]Compacting conversation...[/bold]", spinner="dots"):
                result = await asyncio.wait_for(
                    compact_conversation(
                        agent=agent,
                        model=model,
                        thread_id=session_state.thread_id,
                    ),
                    timeout=25.0,
                )

            if result.success:
                console.print("[green]✓[/green] ", end="")
                console.print("[green]Conversation optimized for next session[/green]")
                console.print(
                    f"[dim]Messages: {result.messages_before} → {result.messages_after} | "
                    f"Tokens saved: ~{result.tokens_saved:,}[/dim]"
                )
                # Reset token tracker after compaction
                token_tracker.reset()
            else:
                console.print(f"[yellow]Compaction skipped: {result.error}[/yellow]")

        except Exception as e:
            # Don't fail exit if compaction fails - just log and continue
            console.print(f"[dim]Could not check context: {e}[/dim]")

    # Helper for auto-save check using AutoSaveManager
    auto_save_manager = AutoSaveManager()

    async def _maybe_auto_save() -> None:
        """Check if auto-save should run and save if needed."""
        if auto_save_manager.should_save():
            if await _save_session(silent=True):
                auto_save_manager.reset_messages()

    # Signal handler for graceful termination using flag-based approach
    # This allows session saving when the terminal is closed or process is terminated
    graceful_shutdown = GracefulShutdown()
    graceful_shutdown.install_handlers()

    # Bounded collection for message IDs — prevents unbounded memory growth
    _seen_message_ids = SeenMessageIds()
    # Store on session_state for remote message processor access
    session_state._seen_message_ids = _seen_message_ids

    # Cancellable task tracking: lets Ctrl+C cancel a running execute_task
    # by injecting CancelledError rather than relying on KeyboardInterrupt
    # propagation (which is unreliable on Windows asyncio).
    _exec_task: asyncio.Task | None = None
    _event_loop = asyncio.get_event_loop()

    def _cancel_exec_task(signum=None, frame=None) -> None:
        nonlocal _exec_task
        if _exec_task is not None and not _exec_task.done():
            _event_loop.call_soon_threadsafe(_exec_task.cancel)
        else:
            # No agent task running — raise so the prompt can handle it
            raise KeyboardInterrupt

    # Register SIGINT handler so Ctrl+C reliably cancels the agent task.
    # prompt_toolkit saves/restores this when prompt_async() is active,
    # so the double-Ctrl+C-to-exit behavior during prompts is unaffected.
    _prev_sigint: object = None
    try:
        _prev_sigint = signal.signal(signal.SIGINT, _cancel_exec_task)
    except (ValueError, OSError):
        pass  # May fail in non-main threads or restricted environments

    while True:
        try:
            user_input = await session.prompt_async()
            if session_state.exit_hint_handle:
                session_state.exit_hint_handle.cancel()
                session_state.exit_hint_handle = None
            session_state.exit_hint_until = None
            user_input = user_input.strip()
            # Resolve any paste placeholders to full text
            user_input = resolve_paste_placeholders(user_input, paste_tracker)
        except EOFError:
            await _cleanup_and_save_session()
            break
        except KeyboardInterrupt:
            # Double-Ctrl+C during prompt exits.  Single Ctrl+C
            # during prompt is handled by prompt_toolkit's own binding
            # (shows hint, second press exits).
            await _cleanup_and_save_session()
            console.print("\nGoodbye!", style=COLORS["primary"])
            break

        # Fire user.message hook
        if user_input:
            dispatch_hook_fire_and_forget(
                HookEvent.USER_MESSAGE,
                {
                    "session_id": session_state.session_id,
                    "thread_id": session_state.thread_id,
                    "message": user_input[:500],  # truncate for safety
                },
            )

        # Wrap the rest of the loop body so that KeyboardInterrupt
        # during execute_task or between task/prompt doesn't crash the
        # CLI — it just returns to the prompt.
        try:
            if not user_input:
                continue

            # /critique shortcut → delegate to the built-in critique-agent subagent
            # via the main agent's `task` tool (not the custom @agent path)
            if user_input.startswith("/critique"):
                critique_args = user_input[len("/critique") :].strip()
                user_input = (
                    f"Use the critique-agent subagent (via the task tool) to: "
                    f"{critique_args or 'Review recent changes for correctness, safety, and regressions'}"
                )

            # Check for slash commands first
            if user_input.startswith("/"):
                result = await handle_command(
                    user_input,
                    agent,
                    token_tracker,
                    session_state,
                    assistant_id,  # type: ignore
                    session_manager=session_manager,
                    model_name=model_name,
                    image_tracker=image_tracker,
                    sandbox_id=sandbox_id,
                    sandbox_type=sandbox_type,
                )
                if result == "exit":
                    await _cleanup_and_save_session()
                    console.print("\nGoodbye!", style=COLORS["primary"])
                    break
                if result:
                    # If result is a string, it's a prompt for the agent to process
                    # Skill invocations return prompts with @ symbols that
                    # should NOT be parsed as file mentions (e.g., @e1, @e2
                    # in agent-browser SKILL.md)
                    if isinstance(result, str):
                        # Process the prompt through the active agent
                        active_agent = agent
                        active_backend = backend
                        if (
                            session_state.plan_mode_enabled
                            and hasattr(session_state, "plan_agent")
                            and session_state.plan_agent is not None
                        ):
                            active_agent = session_state.plan_agent
                            active_backend = session_state.plan_backend

                        _exec_task = asyncio.create_task(
                            execute_task(
                                result,
                                active_agent,
                                assistant_id,
                                session_state,
                                token_tracker,
                                backend=active_backend,
                                is_subagent=False,
                                image_tracker=image_tracker,
                                seen_message_ids=_seen_message_ids,  # type: ignore
                                skip_file_mentions=True,
                            )
                        )
                        try:
                            await _exec_task
                        except asyncio.CancelledError:
                            pass
                        finally:
                            _exec_task = None
                    # Command was handled, continue to next input
                    continue

            # Check for bash commands (!)
            if user_input.startswith("!"):
                execute_bash_command(user_input)
                continue

            # Handle regular quit keywords
            if user_input.lower() in ["quit", "exit", "q"]:
                await _cleanup_and_save_session()
                console.print("\nGoodbye!", style=COLORS["primary"])
                break

            # Check for @agent mentions — route through main agent's task tool
            from novacode_cli.input import parse_agent_mentions

            agent_name, query = parse_agent_mentions(user_input, settings)
            if agent_name:
                console.print(f"\n> @{agent_name} {query}", style=COLORS["user"])
                # The named agent is already registered in SubAgentMiddleware (via
                # build_named_subagents → create_agent_with_config). Route the request
                # through the main agent so it dispatches via the task tool.
                task_input = f"Call the '{agent_name}' subagent to do the following:\n\n{query}"
                _exec_task = asyncio.create_task(
                    execute_task(
                        task_input,
                        agent,
                        assistant_id,
                        session_state,
                        token_tracker,
                        backend=backend,
                        is_subagent=False,
                        image_tracker=image_tracker,
                        seen_message_ids=_seen_message_ids,  # type: ignore
                    )
                )
                try:
                    await _exec_task
                except asyncio.CancelledError:
                    pass
                finally:
                    _exec_task = None

            else:
                # Use plan agent if in plan mode, otherwise use main agent
                active_agent = agent
                active_backend = backend
                if (
                    session_state.plan_mode_enabled
                    and hasattr(session_state, "plan_agent")
                    and session_state.plan_agent is not None
                ):
                    active_agent = session_state.plan_agent
                    active_backend = session_state.plan_backend

                _exec_task = asyncio.create_task(
                    execute_task(
                        user_input,
                        active_agent,
                        assistant_id,
                        session_state,
                        token_tracker,
                        backend=active_backend,
                        is_subagent=False,
                        image_tracker=image_tracker,
                        seen_message_ids=_seen_message_ids,  # type: ignore
                    )
                )
                try:
                    await _exec_task
                except asyncio.CancelledError:
                    pass  # execute_task's CancelledError handler ran cleanup
                finally:
                    _exec_task = None

                # After plan approval, inject approved plan into Nova agent
                approved_plan = session_state.consume_approved_plan()
                if approved_plan:
                    # Inject plan content as a message to Nova agent
                    plan_prompt = (
                        "The user has approved the following plan. "
                        "Execute it step by step, marking each step as complete as you go:\n\n"
                        f"{approved_plan}"
                    )
                    _exec_task = asyncio.create_task(
                        execute_task(
                            plan_prompt,
                            agent,  # Use main Nova agent, not plan agent
                            assistant_id,
                            session_state,
                            token_tracker,
                            backend=backend,
                            is_subagent=False,
                            image_tracker=image_tracker,
                            seen_message_ids=_seen_message_ids,  # type: ignore
                        )
                    )
                    try:
                        await _exec_task
                    except asyncio.CancelledError:
                        pass
                    finally:
                        _exec_task = None

            # Proactive context warning after each turn
            breakdown = token_tracker.get_breakdown()
            if breakdown:
                pct = breakdown.usage_percentage
                if breakdown.is_critical:
                    console.print(
                        f"[bold red]⚠ Context critical: {pct:.0f}% used![/bold red] "
                        f"[red]Use /compact now or risk errors.[/red]"
                    )
                    console.print(f"[dim red]  Use /context to see detailed breakdown.[/dim red]")
                    dispatch_hook_fire_and_forget(
                        HookEvent.CONTEXT_WARNING,
                        {
                            "level": "critical",
                            "usage_percentage": pct,
                            "session_id": session_state.session_id,
                        },
                    )
                elif breakdown.is_warning:
                    console.print(
                        f"[yellow]⚠ Context usage high: {pct:.0f}%[/yellow] "
                        f"[dim]Consider /compact soon.[/dim]"
                    )
                    console.print(f"[dim]  Use /context to see detailed breakdown.[/dim]")
                    dispatch_hook_fire_and_forget(
                        HookEvent.CONTEXT_WARNING,
                        {
                            "level": "warning",
                            "usage_percentage": pct,
                            "session_id": session_state.session_id,
                        },
                    )

            # Track message for auto-save and check if we should save
            auto_save_manager.increment_messages()
            await _maybe_auto_save()

        except KeyboardInterrupt:
            # KeyboardInterrupt during execute_task or between turns:
            # don't exit — just return to the prompt so the user can continue.
            # This prevents accidental CLI exits when Ctrl+C lands between
            # the task finishing and the next prompt appearing.
            _exec_task = None
            console.print("[yellow]Interrupted[/yellow]")
            console.print("[dim]Press Ctrl+C twice during input to exit.[/dim]")
            console.print()
        except SystemExit as _exit_code:
            # sys.exit(2) from _run_agent_session means rate-limit / API error
            # that should NOT crash the CLI — return to the prompt instead.
            if _exit_code.code == 2:
                _exec_task = None
                # Rate-limit/API messages were already printed by the handler above
                console.print("[dim]Press Enter to continue or type 'exit' to quit.[/dim]")
                console.print()
                continue
            # sys.exit(1) = fatal error — let it propagate
            raise
        except Exception as _api_err:
            # Catch rate-limit / API errors that bubble up from execute_task
            # without going through sys.exit — show a friendly message and
            # return to the prompt instead of crashing the CLI.
            _exec_task = None
            if _is_rate_limit_error(_api_err):
                console.print()
                console.print("[bold yellow]Warning: Rate Limit Reached[/bold yellow]")
                console.print("The model provider is rate-limiting requests.")
                console.print(
                    "[dim]Wait a moment and try again, or check your API usage/plan limits.[/dim]"
                )
                console.print()
                continue
            if _is_api_error(_api_err):
                console.print()
                console.print(f"[bold red]API Error[/bold red]: {str(_api_err)[:300]}")
                console.print("[dim]The request failed. Try again or use a different model.[/dim]")
                console.print()
                continue
            # Unknown error — re-raise for the top-level crash handler
            raise


def _is_rate_limit_error(e: Exception) -> bool:
    """Check if an exception is a rate limit or API quota error."""
    msg = str(e).lower()
    if any(kw in msg for kw in ("429", "rate limit", "usage limit", "quota", "too many requests")):
        return True
    try:
        from openai import RateLimitError, APIStatusError

        if isinstance(e, (RateLimitError, APIStatusError)):
            return True
    except ImportError:
        pass
    try:
        from httpx import HTTPStatusError

        if isinstance(e, HTTPStatusError) and getattr(e.response, "status_code", 0) == 429:
            return True
    except ImportError:
        pass
    return False


def _is_api_error(e: Exception) -> bool:
    """Check if an exception is an API/model error that shouldn't crash the CLI."""
    try:
        from openai import APIStatusError, APIConnectionError

        if isinstance(e, (APIStatusError, APIConnectionError)):
            return True
    except ImportError:
        pass
    try:
        from httpx import HTTPStatusError

        if isinstance(e, HTTPStatusError) and getattr(e.response, "status_code", 0) >= 400:
            return True
    except ImportError:
        pass
    return False


async def _shutdown_background_services(session_state) -> None:
    """Best-effort teardown of background services on exit. Never raises.

    The classic REPL does this in ``_cleanup_and_save_session``; the TUI path
    needs the same so the Vixie server, managed processes, remote bridges and
    background tasks don't dangle and throw during event-loop teardown (which
    can leave the terminal in a broken state).
    """

    async def _guard(coro, timeout: float = 4.0) -> None:
        """Await a teardown step but never let it hang or raise on quit."""
        try:
            await asyncio.wait_for(coro, timeout=timeout)
        except BaseException:  # noqa: BLE001 — incl. TimeoutError/CancelledError
            pass

    # Build best-effort stop coroutines and run them CONCURRENTLY, each bounded
    # by its own timeout — a single slow service (websocket, subprocess, bridge
    # socket) must not make /quit hang or feel unresponsive.
    steps: list = []

    steps.append(_guard(stop_vixie_server()))

    try:
        steps.append(_guard(ProcessManager.get_instance().stop_all()))
    except Exception:  # noqa: BLE001
        pass

    bridge_mgr = getattr(session_state, "_remote_bridge_manager", None)
    if bridge_mgr is not None:
        steps.append(_guard(bridge_mgr.stop_all()))

    # Trello task-board server (sync or async stop/close/shutdown).
    trello = getattr(session_state, "trello_server", None)
    if trello is not None:
        stop_fn = (
            getattr(trello, "stop", None)
            or getattr(trello, "close", None)
            or getattr(trello, "shutdown", None)
        )
        if callable(stop_fn):

            async def _stop_trello() -> None:
                res = stop_fn()
                if asyncio.iscoroutine(res):
                    await res

            steps.append(_guard(_stop_trello()))

    if steps:
        try:
            await asyncio.wait_for(asyncio.gather(*steps, return_exceptions=True), timeout=8.0)
        except BaseException:  # noqa: BLE001
            pass

    # Cancel any remote message-processor task (bounded).
    try:
        task = getattr(session_state, "_remote_processor_task", None)
        if task is not None and not task.done():
            task.cancel()
            await _guard(task, timeout=2.0)
    except Exception:  # noqa: BLE001, S110
        pass

    # Catch-all: cancel every other lingering task so asyncio.run's own shutdown
    # (which awaits all pending tasks) can't hang /quit on a slow or
    # uncancellable background coroutine — e.g. a Nova review / skill-creation
    # task, a fire-and-forget hook, or a remote reply still in flight.
    try:
        current = asyncio.current_task()
        pending = [t for t in asyncio.all_tasks() if t is not current and not t.done()]
        for t in pending:
            t.cancel()
        if pending:
            await asyncio.wait(pending, timeout=3.0)
    except Exception:  # noqa: BLE001, S110
        pass


async def _run_agent_session(
    model,
    assistant_id: str,
    session_state,
    sandbox_backend=None,
    sandbox_type: str | None = None,
    setup_script_path: str | None = None,
    initial_messages: list | None = None,
    session_manager=None,
    store: BaseStore | None = None,
    checkpointer: InMemorySaver | None = None,
    restored_session_data: tuple | None = None,
    exec_sandbox: bool = False,
) -> None:
    """Helper to create agent and run CLI session.

    Extracted to avoid duplication between sandbox and local modes.

    Args:
        model: LLM model to use
        assistant_id: Agent identifier for memory storage
        session_state: Session state with auto-approve settings
        sandbox_backend: Optional sandbox backend for remote execution
        sandbox_type: Type of sandbox being used
        exec_sandbox: When True (Pattern A, local mode), confine local shell
            execution to the workspace via an OS kernel sandbox.
        setup_script_path: Path to setup script that was run (if any)
        initial_messages: Optional messages to inject for session continuation
        session_manager: SessionManager for session persistence
        restored_session_data: Tuple of (session_data, warnings, nova_md_loaded) for continuation
    """
    # Create agent with conditional tools.
    # NOTE: several built-in tools are intentionally NOT registered to keep the
    # agent lean — browser automation
    # (browser_automate / capture_browser_console), git tools, and the code-quality
    # tools (lint_code / format_code_file / check_types). LSP tools are likewise
    # not registered. Test running and dev-server management are likewise done via
    # the shell (`execute`) tool, which runs correctly in both local and sandbox
    # modes — so the (previously stubbed) run_tests / *_server tools are not
    # registered either. The agent does all of these via the shell when needed.
    tools = [
        fetch_url,
        # Clarification: ask the user a structured multiple-choice question when a
        # request is ambiguous. Stripped from subagents in _harden_subagent_specs
        # (a question interrupt inside a subagent would crash the turn).
        ask_user_question,
        # Self-planning: the agent can switch itself into plan mode for complex /
        # risky tasks (enter_plan_mode engages read-only enforcement via the agent
        # loop), then present a plan for approval (exit_plan_mode). Both are
        # stripped from subagents in _harden_subagent_specs.
        enter_plan_mode,
        exit_plan_mode,
        # Wiki Tools
        wiki_read,
        wiki_search,
        wiki_update_index,
        wiki_write,
        # Utility tools
        package_info,
        think,
        speak,
        skill_manage,
        query_project_graph,
        # Web search (always available, no API key needed)
        duckduckgo_search,
        docs_search,
        # Web scraping (GitHub trending, HN, LinkedIn, Reddit)
        github_trending,
        hacker_news,
        linkedin_jobs,
        reddit_posts,
        # Memory management (persist across sessions)
        write_memory,
        read_memory,
        # Structured durable memory (key/value via the LangGraph store)
        remember,
        recall,
        list_memories,
        forget,
    ]
    # Conditionally add Semble-powered code search tools
    if code_search is not None:
        tools.append(code_search)
    if find_related_code is not None:
        tools.append(find_related_code)
    if settings.has_tavily:
        tools.append(web_search)

    # Initialize file recovery manager for this session
    from novacode_cli.recovery import get_recovery_manager, list_trash, restore_file

    get_recovery_manager(
        session_id=session_state.session_id or session_state.thread_id,
        workspace_root=Path.cwd(),
    )
    tools.extend([list_trash, restore_file])

    # Heavy initialization with live animated boot status.
    # The BootAnimation context wraps all boot_status() calls from agent
    # creation, MCP discovery, session restore, and token calculation.
    # transient=True means the animation disappears cleanly before simple_cli
    # displays the splash screen.
    from novacode_cli.config.config import BootAnimation

    with BootAnimation.start():
        agent, composite_backend = create_agent_with_config(
            model,
            assistant_id,
            tools,
            sandbox=sandbox_backend,
            sandbox_type=sandbox_type,
            store=store,
            checkpointer=checkpointer,
            is_continuation=bool(initial_messages),
            steering_instructions=session_state.steering_instructions,
            exec_sandbox=exec_sandbox,
        )

        # Set agent context in session state for dynamic model switching
        session_state.set_agent_context(
            agent=agent,
            backend=composite_backend,
            checkpointer=checkpointer,
            store=store,
            tools=tools,
            assistant_id=assistant_id,
            model=model,
            sandbox_type=sandbox_type,
            sandbox_id=getattr(sandbox_backend, "id", None) if sandbox_backend else None,
        )

        # Eagerly preload voice models at the boot banner whenever voice will be
        # used — `enabled` (always-listening) OR `speak_responses` (Nova talks)
        # OR push-to-talk. Gating on `enabled` alone meant PTT / speak-only users
        # paid the (large) model load inline on first use instead of at startup.
        from novacode_cli.config.nova_config import NovaConfig
        from novacode_cli import audio

        cfg = NovaConfig().get_voice_config()
        _voice_wanted = bool(
            cfg.get("enabled") or cfg.get("speak_responses") or cfg.get("mode") == "push_to_talk"
        )
        if _voice_wanted and audio.is_voice_available():
            boot_status("voice: preloading models (downloading if not present)…")
            try:
                from novacode_cli.audio.pipeline import VoicePipeline

                voice_pipeline = VoicePipeline(
                    stt_provider=cfg.get("stt_provider", "faster-whisper"),
                    tts_provider=cfg.get("tts_provider", "piper"),
                    provider_configs=cfg.get("providers", {}),
                    stt_model=cfg.get("stt_model", "base"),
                    stt_device=cfg.get("stt_device", "auto"),
                    tts_voice=cfg.get("tts_voice", "en_US-lessac-medium"),
                )
                await voice_pipeline.warmup()
                session_state._voice_pipeline = voice_pipeline
                boot_status("voice: stack ready", "ok")
            except Exception as e:
                boot_status(f"voice: warmup failed ({e})", "warn")

    # Wire the SteeringMiddleware's instruction list to the session state.
    #
    # The middleware's `_instructions` list was already set to the shared
    # `session_state.steering_instructions` list during agent creation
    # (create_agent_with_config passes it as `steering_instructions=` to
    # SteeringMiddleware.__init__). No post-hoc wiring is needed — the
    # middleware reads that list on every model call, so /steer and live
    # TUI-steer appends take effect immediately on the agent's next step.

    # Store references on session_state so the remote message processor
    # can access them (it runs as a background task, can't close over locals)
    session_state._console = console
    session_state._composite_backend = composite_backend
    # image_tracker and _seen_message_ids are set on session_state
    # by simple_cli() since they're not available in this scope

    # Initialize remote bridge infrastructure
    # Queue for messages from Discord/Telegram; processed by a background task
    # NOTE: This must be set up BEFORE the processor task starts, otherwise
    # the processor gets a None reference and silently crashes
    session_state._remote_message_queue: asyncio.Queue = asyncio.Queue()
    session_state._remote_message_lock = asyncio.Lock()  # serialize remote+local agent calls
    from novacode_cli.remote.bridge import RemoteBridgeManager

    session_state._remote_bridge_manager = RemoteBridgeManager(session_state._remote_message_queue)

    # Wire status callback so bridge events (connect, disconnect, messages)
    # show in the local CLI console
    async def _remote_status_callback(msg: str) -> None:
        try:
            console.print(f"  [dim]\U0001f517 Remote: {msg}[/dim]")
        except Exception:
            pass

    session_state._remote_bridge_manager.set_status_callback(_remote_status_callback)

    # Start remote message processor as a background task
    # This watches the _remote_message_queue and processes Discord/Telegram messages
    _remote_processor_task = None
    _proc_logger = logging.getLogger("novacode_cli.remote")
    try:
        from novacode_cli.remote.processor import remote_message_processor
        from novacode_cli.ui.execution import execute_task

        async def _remote_processor_wrapper(
            _queue=session_state._remote_message_queue,
            _agent=agent,
            _assistant_id=assistant_id,
            _session_state=session_state,
        ):
            """Wrap the processor to catch and log startup/fatal errors."""
            # Immediate diagnostic — this MUST appear if the task ever runs
            _proc_logger.info("Remote processor wrapper started")
            try:
                await remote_message_processor(
                    queue=_queue,
                    agent=_agent,
                    assistant_id=_assistant_id,
                    session_state=_session_state,
                    console=_session_state._console,
                    token_tracker=_session_state.token_tracker,
                    backend=_session_state._composite_backend,
                    image_tracker=_session_state._image_tracker,
                    seen_message_ids=_session_state._seen_message_ids,
                    execute_fn=execute_task,
                )
            except asyncio.CancelledError:
                _proc_logger.info("Remote message processor cancelled")
            except Exception as e:
                _proc_logger.error(f"Remote message processor crashed: {e}", exc_info=True)
                _session_state._console.print(
                    f"\n  [red]\u274c Remote message processor crashed: {e}[/red]\n"
                )

        # Add a done-callback to surface any crashes
        def _on_processor_done(task: asyncio.Task) -> None:
            try:
                exc = task.exception()
            except asyncio.CancelledError:
                return
            if exc:
                console.print(f"\n  [red]\u274c Remote processor task died: {exc}[/red]\n")

        # In TUI mode the Textual app runs its own remote consumer that renders
        # remote prompts through the event stream; skip the legacy console
        # processor so the queue isn't double-consumed and the TUI isn't
        # overwritten by console.print output.
        if not getattr(session_state, "use_tui", False):
            _remote_processor_task = asyncio.create_task(
                _remote_processor_wrapper(),
                name="remote-message-processor",
            )
            _remote_processor_task.add_done_callback(_on_processor_done)
            # Store on session_state to prevent garbage collection
            session_state._remote_processor_task = _remote_processor_task
    except Exception as _remote_proc_exc:
        import logging as _logging

        _logging.getLogger("novacode_cli.remote").error(
            f"Failed to start remote message processor: {_remote_proc_exc}",
            exc_info=True,
        )
        console.print(
            f"  [red]\u274c Failed to start remote message processor: {_remote_proc_exc}[/red]"
        )

    # Resume any persisted cron jobs (Enhancement 3). The scheduler is a queue
    # *producer*, so it works in both CLI and TUI mode (both consume the same
    # queue). Start, keep only if jobs exist \u2014 users who never use /cron pay
    # nothing for an idle ticker.
    try:
        from novacode_cli.memory.store import get_durable_store as _get_store
        from novacode_cli.remote.scheduler import CronScheduler

        _cron_sched = CronScheduler(
            session_state._remote_message_queue, store=_get_store()
        )
        await _cron_sched.start()
        if _cron_sched.list_jobs():
            session_state._cron_scheduler = _cron_sched
            _proc_logger.info(
                "Cron scheduler resumed %d job(s)", len(_cron_sched.list_jobs())
            )
        else:
            await _cron_sched.stop()
    except Exception as _cron_exc:
        logging.getLogger("novacode_cli.remote").error(
            f"Failed to resume cron scheduler: {_cron_exc}", exc_info=True
        )

    # Inject initial messages if continuing a session
    if initial_messages:
        config = {"configurable": {"thread_id": session_state.thread_id}}
        await agent.aupdate_state(
            config=config,  # type: ignore
            values={"messages": initial_messages},
            as_node="model",
        )
        boot_status(f"session: {len(initial_messages)} messages restored")

    # Calculate baseline token count for accurate token tracking
    from novacode_cli.agents.core_agent import get_system_prompt

    from .token_utils import calculate_baseline_tokens

    agent_dir = settings.get_agent_dir(assistant_id)
    system_prompt = get_system_prompt(
        assistant_id=assistant_id, sandbox_type=sandbox_type, exec_sandbox=exec_sandbox
    )
    baseline_tokens = calculate_baseline_tokens(model, agent_dir, system_prompt, assistant_id)

    # Extract model name for context window calculation
    model_name = getattr(model, "model_name", None) or getattr(model, "model", "unknown")

    # Experimental Textual TUI (Phase 1). Opt-in via --tui; the classic REPL
    # The TUI shares the same agent/backend/session
    # but renders via novacode_cli.tui consuming run_agent_stream. Use --legacy-ui
    # to switch back to the classic Rich-based REPL.
    if getattr(session_state, "use_tui", False):
        from novacode_cli.input import ImageTracker
        from novacode_cli.tui import run_tui
        from novacode_cli.ui.ui_elements import TokenTracker

        token_tracker = TokenTracker()
        token_tracker.set_baseline(baseline_tokens)
        if model_name:
            token_tracker.set_model(model_name)
        session_state.token_tracker = token_tracker
        # Prior conversation turns to replay into the transcript on resume.
        _restored_msgs = None
        if restored_session_data:
            try:
                _restored_msgs = getattr(restored_session_data[0], "messages", None)
            except Exception:  # noqa: BLE001
                _restored_msgs = None
        # Extract sandbox_id from backend for TUI's session save
        _tui_sandbox_id: str | None = None
        _tui_sandbox_meta: dict | None = None
        if sandbox_backend:
            _tui_sandbox_id = getattr(sandbox_backend, "id", None)
            _tui_sandbox_meta = getattr(sandbox_backend, "_nova_meta", None)

        try:
            await run_tui(
                agent=agent,
                assistant_id=assistant_id,
                session_state=session_state,
                backend=composite_backend,
                token_tracker=token_tracker,
                image_tracker=ImageTracker(),
                model_name=model_name,
                session_manager=session_manager,
                restored_messages=_restored_msgs,
                sandbox_id=_tui_sandbox_id,
                sandbox_type=sandbox_type,
                sandbox_meta=_tui_sandbox_meta,
            )
        finally:
            # Always tear down background services so quitting can't crash on
            # dangling tasks / servers after the TUI exits.
            await _shutdown_background_services(session_state)
        return

    try:
        await simple_cli(
            agent,
            assistant_id,
            session_state,
            baseline_tokens,
            backend=composite_backend,
            sandbox_type=sandbox_type,
            setup_script_path=setup_script_path,
            no_splash=session_state.no_splash,
            model_name=model_name,
            session_manager=session_manager,
            store=store,
            checkpointer=checkpointer,
            restored_session_data=restored_session_data,
        )
    except Exception as _crash_exc:
        # Failsafe: session crashed unexpectedly — save whatever we have before dying
        if session_manager and session_state.session_id and session_state.thread_id:
            try:
                console.print("\n[bold yellow]⚠ Unexpected crash — saving session...[/bold yellow]")
                # Pull the latest messages straight from the LangGraph checkpointer
                _crash_messages: list = []
                try:
                    _config = {"configurable": {"thread_id": session_state.thread_id}}
                    _snap = await agent.aget_state(_config)  # type: ignore
                    _crash_messages = list(_snap.values.get("messages", []))
                except Exception:
                    pass  # checkpointer may also be broken; save what we can

                _crash_model = (
                    getattr(model, "model_name", None)
                    or getattr(model, "model", None)
                    or model_name
                )
                _crash_dir = session_manager.save_session(
                    session_id=session_state.session_id,
                    thread_id=session_state.thread_id,
                    messages=_crash_messages,
                    assistant_id=assistant_id,
                    model_name=_crash_model,
                    project_root=Path.cwd(),
                    task_status="crashed",
                    sandbox_id=(getattr(sandbox_backend, "id", None) if sandbox_backend else None),
                    sandbox_type=sandbox_type,
                )
                console.print(f"[dim]Session saved → {_crash_dir}[/dim]")
            except Exception as _save_err:
                console.print(f"[dim]Failsafe save failed: {_save_err}[/dim]")
        raise  # re-raise so the traceback still propagates to main()


def _cleanup_old_checkpoints(checkpoints_dir: Path, max_age_days: int = 30) -> None:
    """Remove checkpoint database files older than max_age_days."""
    import time

    cutoff = time.time() - max_age_days * 86400
    for db_file in checkpoints_dir.glob("*.db"):
        try:
            if db_file.stat().st_mtime < cutoff:
                db_file.unlink(missing_ok=True)
        except OSError:
            pass


async def main(
    assistant_id: str,
    session_state,
    sandbox_type: str = "none",
    sandbox_id: str | None = None,
    setup_script_path: str | None = None,
    continue_session: bool | str = False,
    resume: bool = False,
    ports: dict[int, int] | None = None,
    explicit_sandbox: bool = True,
    sandbox_vcpus: int | None = None,
    sandbox_mem_bytes: int | None = None,
    sandbox_fs_capacity_bytes: int | None = None,
    sandbox_snapshot: str | None = None,
    sandbox_snapshot_id: str | None = None,
) -> None:
    """Main entry point with conditional sandbox support.

    Args:
        assistant_id: Agent identifier for memory storage
        session_state: Session state with auto-approve settings
        sandbox_type: Type of sandbox ("none", "modal", "runloop", "daytona", "docker", "langsmith")
        sandbox_id: Optional existing sandbox ID to reuse
        setup_script_path: Optional path to setup script to run in sandbox
        continue_session: If True, continue last session. If string, use as session ID.
        resume: If True, show interactive session picker to select a session to resume.
        ports: Optional port mapping for Docker sandbox {container_port: host_port}
        explicit_sandbox: Whether the user explicitly chose the sandbox. When False
            (the implicit Docker default), a sandbox-creation failure falls back to
            local mode instead of exiting.
        sandbox_vcpus: Number of virtual CPUs (LangSmith only)
        sandbox_mem_bytes: Memory in bytes (LangSmith only)
        sandbox_fs_capacity_bytes: Filesystem capacity in bytes (LangSmith only)
        sandbox_snapshot: Snapshot name to boot from (LangSmith only)
        sandbox_snapshot_id: Snapshot ID to boot from (LangSmith only)
    """
    # Check path approval before creating any resources (model, sandbox, store,
    # checkpointer, Vixie server, etc.). If the user denies access, nothing
    # expensive has been allocated — no cleanup needed.
    if not await check_path_approval():
        console.print()
        console.print(
            "[red]Cannot start nova without path approval.[/red]",
            style="dim",
        )
        console.print("[dim]Path approval is required to ensure safe file system access.[/dim]")
        console.print()
        sys.exit(1)

    # Hydrate API keys stored in the OS keychain into the environment so model
    # clients (which read os.environ) can find them — keys may live only in the
    # keychain, not in .env. Must run before create_model() below.
    from novacode_cli.onboarding import load_secrets_into_env

    load_secrets_into_env()

    # Initialize Vixie WebSocket server for desktop pet integration (non-blocking)
    # Server runs in background; if port is in use, it gracefully skips
    await start_vixie_server()

    from novacode_cli.session.session_persistence import SessionManager
    from novacode_cli.session.session_restore import restore_session

    # Durable, SQLite-backed store at ~/.nova/store.db so structured memory
    # written via the LangGraph store survives restarts (falls back to
    # in-memory if SQLite is unavailable). See novacode_cli/memory/store.py.
    from novacode_cli.memory.store import get_async_durable_store

    store = await get_async_durable_store()

    # Use SQLite-backed checkpointer for cross-restart session continuity when available.
    # Falls back to InMemorySaver if langgraph-checkpoint-sqlite is not installed.
    if _SQLITE_CHECKPOINTER_AVAILABLE:
        checkpoints_dir = settings.nova_dir / "checkpoints"  # type: ignore
        checkpoints_dir.mkdir(parents=True, exist_ok=True)
        # Clean up checkpoint DBs older than 30 days to prevent unbounded growth
        _cleanup_old_checkpoints(checkpoints_dir, max_age_days=30)
        _db_path = str(checkpoints_dir / "nova_checkpoints.db")

        async def _setup_sqlite_checkpointer():
            # AsyncSqliteSaver.from_conn_string() is an *async context manager*,
            # not a saver — entering/leaving it would close the connection while
            # the session is still running. Instead, open a persistent aiosqlite
            # connection and build the saver directly so it lives for the whole
            # session (closed implicitly on process exit).
            import aiosqlite

            # Daemonise aiosqlite's worker thread BEFORE it starts (on await):
            # it's non-daemon by default and is never closed, so it blocks the
            # interpreter at exit — making /quit hang. WAL + per-turn commits
            # mean nothing in-flight is lost when the daemon thread is abandoned.
            _conn_cm = aiosqlite.connect(_db_path)
            _conn_cm.daemon = True
            conn = await _conn_cm
            saver = _AsyncSqliteSaver(conn)  # type: ignore[call-arg]
            await saver.setup()
            # Enable WAL mode on the saver's own connection: concurrent reads
            # don't block writes — critical for async streaming + checkpoint writes.
            try:
                await conn.execute("PRAGMA journal_mode=WAL")
                await conn.execute("PRAGMA synchronous=NORMAL")
                await conn.execute("PRAGMA busy_timeout=5000")
                await conn.commit()
            except Exception:
                pass  # non-fatal — default journal mode still works
            return saver

        # Run model creation (heavy SDK imports) and checkpointer setup (SQLite I/O)
        # concurrently — saves ~1-2s on cold start.
        model, checkpointer = await asyncio.gather(
            asyncio.to_thread(create_model),
            _setup_sqlite_checkpointer(),
        )
    else:
        checkpointer = InMemorySaver()
        model = await asyncio.to_thread(create_model)

    # Initialize session manager for persistence
    session_manager = SessionManager()
    initial_messages: list | None = None

    # Handle --resume: interactive session picker
    if resume:
        from novacode_cli.session.session_restore import select_session_interactive

        selected_id = await select_session_interactive(session_manager)
        if selected_id is None:
            # User cancelled or no sessions available
            return
        # Convert resume selection into a continue_session with the selected ID
        continue_session = selected_id

    # Sandbox identity recovered from a resumed session (for reconnect).
    restored_sandbox_id: str | None = None
    restored_sandbox_type: str | None = None

    # Handle session continuation
    if continue_session:
        from novacode_cli.session.session_prompt_builder import (
            build_continuation_prompt,
            load_NOVA_md,
        )
        from novacode_cli.tracking.workspace_anchoring import (
            detect_drift,
            scan_workspace,
        )

        project_root = Path.cwd()
        session_id = continue_session if isinstance(continue_session, str) else None

        result = restore_session(session_manager, session_id, project_root)
        if result:
            session_data, warnings = result

            from novacode_cli.config.config import get_default_coding_instructions

            # Run independent I/O tasks concurrently:
            #  - load recent messages (DB read)
            #  - scan workspace (git subprocesses, cached)
            #  - load Nova.md (filesystem read)
            recent_messages, current_workspace, nova_md_content = await asyncio.gather(
                asyncio.to_thread(
                    session_manager.load_recent_messages, session_data.meta.session_id
                ),
                asyncio.to_thread(scan_workspace, project_root),
                asyncio.to_thread(load_NOVA_md, project_root),
            )

            if session_data.workspace_state:
                drift_warnings = detect_drift(session_data.workspace_state, current_workspace)
                warnings.extend(drift_warnings)

            base_system_prompt = get_default_coding_instructions()

            # Build the continuation prompt from the FULL prior history (archive +
            # recent, already loaded by restore_session). build_continuation_prompt
            # token-budgets it to the most recent ~30k tokens, so this retains far
            # more of the conversation than the 20-message recent window while
            # still bounding context. Fall back to the recent window if the
            # archive wasn't present.
            full_history = list(session_data.messages or [])
            session_data.messages = full_history or recent_messages
            initial_messages = build_continuation_prompt(
                session_data=session_data,
                system_prompt=base_system_prompt,
                NOVA_md_content=nova_md_content,
                workspace_state=current_workspace,
            )

            # Narrow to the recent window for the on-resume transcript replay so
            # the UI isn't flooded with the entire history.
            session_data.messages = recent_messages
            session_data_for_display = session_data

            # Restore session state
            session_state.session_id = session_data.meta.session_id
            session_state.thread_id = session_data.meta.thread_id
            session_state.is_continued = True

            # Recover the sandbox used last time so we can reconnect to its
            # container (preserving installed deps / in-container state).
            restored_sandbox_id = getattr(session_data.meta, "sandbox_id", None)
            restored_sandbox_type = getattr(session_data.meta, "sandbox_type", None)

            # Restore todos if available
            if session_data.todos:
                session_state.todos = session_data.todos

            # Inject session summary as context if available
            if session_data.memory:
                from langchain_core.messages import SystemMessage

                summary_msg = SystemMessage(
                    content=f"## Session Summary (resumed)\n\n{session_data.memory}"
                )
                initial_messages.insert(0, summary_msg)

            # Create tuple for displaying after splash screen
            restored_session_data = (
                session_data_for_display,
                warnings,
                bool(nova_md_content),
            )
        else:
            console.print()
            console.print("[yellow]No previous session found.[/yellow]")
            console.print("[dim]Starting new session.[/dim]")
            console.print()
            restored_session_data = None
    else:
        restored_session_data = None

    async def _run_local_session() -> None:
        """Run the agent locally on the host.

        ``sandbox_type == "os"`` selects Pattern A — files on the host, but shell
        commands confined to the workspace by an OS kernel sandbox. ``"none"``
        (and the Windows Docker-unavailable fallback) runs unconfined.
        """
        try:
            await _run_agent_session(
                model,
                assistant_id,
                session_state,
                sandbox_backend=None,
                initial_messages=initial_messages,
                session_manager=session_manager,
                store=store,
                checkpointer=checkpointer,
                restored_session_data=restored_session_data,
                exec_sandbox=(sandbox_type == "os"),
            )
        except KeyboardInterrupt:
            console.print("\n\n[yellow]Interrupted[/yellow]")
            sys.exit(0)
        except Exception as e:
            # Rate limit / API quota errors - show friendly message instead of crash
            if _is_rate_limit_error(e):
                console.print()
                console.print("[bold yellow]Warning: Rate Limit Reached[/bold yellow]")
                console.print("The model provider is rate-limiting requests.")
                console.print(
                    "[dim]Wait a moment and try again, or check your API usage/plan limits.[/dim]"
                )
                console.print()
                sys.exit(2)  # Distinct exit code - caller can retry
            if _is_api_error(e):
                console.print()
                console.print(f"[bold red]API Error[/bold red]: {str(e)[:300]}")
                console.print("[dim]The request failed. Try again or use a different model.[/dim]")
                console.print()
                sys.exit(2)
            console.print("[bold red]Fatal error:[/bold red]", str(e))
            console.print_exception()
            logging.getLogger("novacode_cli").error(
                "Fatal error during session: %s", e, exc_info=True
            )
            dispatch_hook_fire_and_forget(
                HookEvent.ERROR,
                {
                    "error": str(e)[:500],
                    "type": type(e).__name__,
                    "session_id": session_state.session_id,
                },
            )
            if session_state.session_id:
                console.print(
                    f"[dim]Session may have been saved -- resume with:[/dim]\n  nova --continue {session_state.session_id}"
                )
            sys.exit(1)

    # Branch 1: User wants a container/cloud sandbox. "none" and "os" both run
    # locally (os = host files + OS-confined shell) and take the local branch.
    if sandbox_type not in ("none", "os"):
        # Try to create sandbox
        try:
            console.print()
            # If resuming and the user didn't pass an explicit --sandbox-id,
            # reconnect to the container recorded in the saved session (when it
            # was a docker session). create_docker_sandbox self-heals to a fresh
            # container if that one no longer exists.
            effective_sandbox_id = sandbox_id
            if (
                not sandbox_id
                and sandbox_type == "docker"
                and restored_sandbox_type == "docker"
                and restored_sandbox_id
            ):
                effective_sandbox_id = restored_sandbox_id
                boot_status(f"sandbox: reconnecting to docker {restored_sandbox_id[:12]}…")

            sandbox_kwargs = {
                "sandbox_id": effective_sandbox_id,
                "setup_script_path": setup_script_path,
            }
            # Docker-only options: bind-mount, port forwarding, persistence.
            if sandbox_type == "docker":
                if ports:
                    sandbox_kwargs["ports"] = ports  # type: ignore
                # Bind-mount the project so the agent operates on the real files
                # in isolation. Used only on fresh/fallback create; a reconnected
                # container keeps its original mount.
                sandbox_kwargs["mount_dir"] = str(Path.cwd())  # type: ignore
                # Persist the container on exit and tie it to this session so a
                # later resume can reconnect (preserving installed deps/state).
                sandbox_kwargs["persist"] = True  # type: ignore
                sandbox_kwargs["session_id"] = session_state.session_id  # type: ignore

            # LangSmith-specific options: resource config, snapshots, ports.
            if sandbox_type == "langsmith":
                if ports:
                    sandbox_kwargs["ports"] = ports  # type: ignore
                if sandbox_vcpus is not None:
                    sandbox_kwargs["vcpus"] = sandbox_vcpus
                if sandbox_mem_bytes is not None:
                    sandbox_kwargs["mem_bytes"] = sandbox_mem_bytes
                if sandbox_fs_capacity_bytes is not None:
                    sandbox_kwargs["fs_capacity_bytes"] = sandbox_fs_capacity_bytes
                if sandbox_snapshot is not None:
                    sandbox_kwargs["snapshot_name"] = sandbox_snapshot
                if sandbox_snapshot_id is not None:
                    sandbox_kwargs["snapshot_id"] = sandbox_snapshot_id

            with create_sandbox(sandbox_type, **sandbox_kwargs) as sandbox_backend:  # type: ignore
                boot_status(f"sandbox: isolated execution ({sandbox_type})", "ok")
                console.print()

                await _run_agent_session(
                    model,
                    assistant_id,
                    session_state,
                    sandbox_backend,
                    sandbox_type=sandbox_type,
                    setup_script_path=setup_script_path,
                    initial_messages=initial_messages,
                    session_manager=session_manager,
                    store=store,
                    checkpointer=checkpointer,
                    restored_session_data=restored_session_data,
                )

                # If this run saved no session (e.g. the user exited immediately
                # without a single turn), don't leave the freshly-created sandbox
                # behind — there's no session to ever reconnect it. Vetoing
                # persistence makes create_sandbox remove it on exit instead of
                # accumulating orphaned containers.
                try:
                    if session_manager is not None:
                        _saved = session_manager.load_session(session_state.session_id)
                        if _saved is None or not _saved.messages:
                            sandbox_backend._nova_discard_on_exit = True  # type: ignore[attr-defined]  # noqa: SLF001
                except Exception:  # noqa: BLE001 - never block exit on cleanup hint
                    pass
        except (ImportError, ValueError, RuntimeError, NotImplementedError) as e:
            console.print()
            if not explicit_sandbox:
                # We defaulted to Docker but it isn't available — fall back to
                # local mode instead of blocking the user.
                console.print(f"[yellow]⚠ Docker sandbox unavailable ({e}).[/yellow]")
                console.print(
                    "[dim]Falling back to local execution. "
                    "Start Docker for isolation, or use --no-sandbox to silence this.[/dim]"
                )
                console.print()
                await _run_local_session()
            else:
                # Sandbox was explicitly requested — fail hard (no silent fallback).
                console.print("[red]❌ Sandbox creation failed[/red]")
                console.print(f"[dim]{e}[/dim]")
                sys.exit(1)
        except KeyboardInterrupt:
            console.print("\n\n[yellow]Interrupted[/yellow]")
            sys.exit(0)
        except Exception as e:
            # Rate limit / API quota errors - show friendly message instead of crash
            if _is_rate_limit_error(e):
                console.print()
                console.print("[bold yellow]Warning: Rate Limit Reached[/bold yellow]")
                console.print("The model provider is rate-limiting requests.")
                console.print(
                    "[dim]Wait a moment and try again, or check your API usage/plan limits.[/dim]"
                )
                console.print()
                sys.exit(2)  # Distinct exit code - caller can retry
            if _is_api_error(e):
                console.print()
                console.print(f"[bold red]API Error[/bold red]: {str(e)[:300]}")
                console.print("[dim]The request failed. Try again or use a different model.[/dim]")
                console.print()
                sys.exit(2)
            console.print("[bold red]Fatal error:[/bold red]", str(e))
            console.print_exception()
            logging.getLogger("novacode_cli").error(
                "Fatal error during session: %s", e, exc_info=True
            )
            dispatch_hook_fire_and_forget(
                HookEvent.ERROR,
                {
                    "error": str(e)[:500],
                    "type": type(e).__name__,
                    "session_id": session_state.session_id,
                },
            )
            if session_state.session_id:
                console.print(
                    f"[dim]Session may have been saved -- resume with:[/dim]\n  nova --continue {session_state.session_id}"
                )
            sys.exit(1)

    # Branch 2: User wants local mode (none or default)
    else:
        await _run_local_session()


def _execute_paths_command(args) -> None:
    """Execute paths management commands."""
    manager = PathApprovalManager()

    if args.paths_command == "list":
        approved_paths = manager.list_approved_paths()

        if not approved_paths:
            console.print()
            console.print("[yellow]No approved paths found.[/yellow]")
            console.print(
                "[dim]Paths will be approved automatically when you first run nova in a directory.[/dim]"
            )
            console.print()
            return

        console.print()
        console.print("[bold]Approved Paths:[/bold]", style=COLORS["primary"])
        console.print()

        for path_str, config in approved_paths.items():
            recursive = config.get("recursive", False)
            scope = "📁 + subdirectories" if recursive else "📁 this directory only"

            console.print(f"  {path_str}")
            console.print(f"    [dim]{scope}[/dim]")
            console.print()

    elif args.paths_command == "revoke":
        path = Path(args.path).resolve()
        if manager.revoke_path(path):
            console.print()
            console.print("✅ ", style="green", end="")
            console.print(f"[green]Revoked approval for:[/green] {path}")
            console.print()
        else:
            console.print()
            console.print("⚠️  ", style="yellow", end="")
            console.print(f"[yellow]Path not found in approved list:[/yellow] {path}")
            console.print()

    elif args.paths_command == "clear":
        from prompt_toolkit import prompt

        console.print()
        console.print("[yellow]⚠ This will clear ALL approved paths.[/yellow]")
        console.print("[dim]You'll need to re-approve paths when you next run nova.[/dim]")
        console.print()

        confirm = prompt("Are you sure? (yes/no): ").strip().lower()
        if confirm in ["yes", "y"]:
            # Clear all paths
            manager._approved_paths = {}
            manager._save_approved_paths()
            console.print()
            console.print("✅ ", style="green", end="")
            console.print("[green]All approved paths cleared.[/green]")
            console.print()
        else:
            console.print()
            console.print("[dim]Cancelled.[/dim]")
            console.print()
    else:
        console.print()
        console.print("[yellow]Please specify a subcommand: list, revoke, or clear[/yellow]")
        console.print()
        console.print("[bold]Usage:[/bold]", style=COLORS["primary"])
        console.print("  nova paths list         List all approved paths")
        console.print("  nova paths revoke PATH  Revoke approval for a path")
        console.print("  nova paths clear        Clear all approved paths")
        console.print()


def _execute_config_command(args) -> None:
    """Execute config command to view/edit configuration."""
    import json

    config_file = HOME_DIR / "config.json"
    command = args.config_command

    if command == "show":
        # Show current configuration (non-secret only)
        if config_file.exists():
            console.print()
            console.print("[bold]Current Configuration:[/bold]")
            console.print()
            try:
                config = json.loads(config_file.read_text(encoding="utf-8"))
                from rich.syntax import Syntax

                syntax = Syntax(
                    json.dumps(config, indent=2),
                    "json",
                    theme="monokai",
                    line_numbers=True,
                )
                console.print(syntax)
            except Exception as e:  # noqa: BLE001
                console.print(f"[red]✗ Error reading config: {e}[/red]")
            console.print()
        else:
            console.print()
            console.print("[yellow]⚠ No configuration file found[/yellow]")
            console.print("[dim]Run 'nova init' to set up configuration[/dim]")
            console.print()

    elif command == "get":
        # Get specific configuration value
        if not args.key:
            console.print("[red]✗ Key required for 'get' command[/red]")
            console.print("[dim]Usage: nova config get <key>[/dim]")
            return

        if config_file.exists():
            try:
                config = json.loads(config_file.read_text(encoding="utf-8"))
                value = config.get(args.key)
                if value is not None:
                    console.print()
                    console.print(f"[bold]{args.key}:[/bold] {value}")
                    console.print()
                else:
                    console.print()
                    console.print(f"[yellow]⚠ Key '{args.key}' not found[/yellow]")
                    console.print()
            except Exception as e:  # noqa: BLE001
                console.print(f"[red]✗ Error reading config: {e}[/red]")
        else:
            console.print("[yellow]⚠ No configuration file found[/yellow]")

    elif command == "set":
        # Set configuration value
        if not args.key or not args.value:
            console.print("[red]✗ Both key and value required for 'set' command[/red]")
            console.print("[dim]Usage: nova config set <key> <value>[/dim]")
            return

        config = {}
        if config_file.exists():
            try:
                config = json.loads(config_file.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001, S110
                pass

        # Parse value (try JSON first, then string)
        try:
            parsed_value = json.loads(args.value)
        except json.JSONDecodeError:
            parsed_value = args.value

        config[args.key] = parsed_value
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_file.write_text(json.dumps(config, indent=2), encoding="utf-8")

        console.print()
        console.print(f"[green]✓ Set {args.key} = {parsed_value}[/green]")
        console.print()


def _execute_secrets_command(args) -> None:
    """Execute secrets command to manage API keys."""
    from prompt_toolkit import prompt

    from novacode_cli.onboarding import SecretManager

    secret_manager = SecretManager()
    command = args.secrets_command

    if command == "list":
        # List all stored secrets
        secrets = secret_manager.list_secrets()
        console.print()
        if secrets:
            console.print("[bold]Configured API keys:[/bold]")
            for secret in secrets:
                # Display without revealing values
                display_name = secret.replace("_api_key", "").replace("_", " ").title()
                console.print(f"  • {display_name} ({secret})")
        else:
            console.print("[yellow]⚠ No API keys configured[/yellow]")
            console.print("[dim]Use 'nova secrets set <key>' to add API keys[/dim]")
        console.print()

    elif command == "set":
        # Set API key
        if not args.key:
            console.print("[red]✗ Key name required for 'set' command[/red]")
            console.print("[dim]Usage: nova secrets set <key> (e.g., 'openai_api_key')[/dim]")
            return

        console.print()
        console.print(f"[bold]Setting {args.key}:[/bold]")
        api_key = prompt("Enter API key: ", is_password=True).strip()

        if api_key:
            if secret_manager.store_secret(args.key, api_key):
                console.print()
                console.print("[green]✓ API key saved to system keychain[/green]")
                console.print()
            else:
                console.print()
                console.print("[red]✗ Failed to save API key[/red]")
                console.print()
        else:
            console.print()
            console.print("[yellow]⚠ No API key provided, cancelled[/yellow]")
            console.print()

    elif command == "delete":
        # Delete API key
        if not args.key:
            console.print("[red]✗ Key name required for 'delete' command[/red]")
            console.print("[dim]Usage: nova secrets delete <key> (e.g., 'openai_api_key')[/dim]")
            return

        console.print()
        console.print(f"[yellow]⚠ Delete API key '{args.key}'?[/yellow]")
        confirm = prompt("Continue? [y/N]: ").strip().lower()

        if confirm == "y":
            if secret_manager.delete_secret(args.key):
                console.print()
                console.print(f"[green]✓ API key '{args.key}' deleted[/green]")
                console.print()
            else:
                console.print()
                console.print("[red]✗ Failed to delete API key[/red]")
                console.print()
        else:
            console.print()
            console.print("[dim]Cancelled[/dim]")
            console.print()


def _run_onboarding() -> bool:
    """Run first-run/reset onboarding, preferring the native Textual screen.

    Falls back to the legacy prompt_toolkit wizard when Textual isn't usable
    (e.g. not an interactive terminal).
    """
    from novacode_cli.onboarding import OnboardingWizard

    try:
        if sys.stdin.isatty() and sys.stdout.isatty():
            from novacode_cli.tui.pickers import run_onboarding_tui

            return run_onboarding_tui()
    except Exception:  # noqa: BLE001 — fall back to the legacy wizard
        pass
    return bool(OnboardingWizard().run())


def cli_main() -> None:
    """Entry point for console script."""
    # Fix for gRPC fork issue on macOS
    # https://github.com/grpc/grpc/issues/37642
    if sys.platform == "darwin":
        os.environ["GRPC_ENABLE_FORK_SUPPORT"] = "0"

    # Check dependencies first
    check_cli_dependencies()

    try:
        args = parse_args()

        # First-run detection (skip for init and doctor commands)
        if args.command not in ["init", "doctor", "help"]:
            if not settings.get_onboarding_status():
                console.print()
                console.print("[yellow]→ First run detected[/yellow]")
                console.print()

                if _run_onboarding():
                    console.print()
                    console.print(
                        "[dim]You can now run your command or start an interactive session.[/dim]"
                    )
                    console.print()
                else:
                    console.print()
                    console.print("[red]✗ Setup incomplete[/red]")
                    console.print("[dim]Run 'nova init --reset' to try again[/dim]")
                    console.print()
                    sys.exit(1)

        if args.command == "init":
            # Check if --reset flag is set (re-run onboarding)
            if args.reset:
                console.print()
                console.print("[yellow]⚠ This will overwrite your current configuration.[/yellow]")
                from prompt_toolkit import prompt

                confirm = prompt("Continue? [y/N]: ").strip().lower()
                if confirm == "y":
                    _run_onboarding()
                else:
                    console.print("[dim]Cancelled.[/dim]")

        elif args.command == "help":
            show_help()
        elif args.command == "list":
            list_agents()
        elif args.command == "reset":
            reset_agent(args.agent, args.source_agent)
        elif args.command == "skills":
            execute_skills_command(args)
        elif args.command == "mcp":
            execute_mcp_command(args)
        elif args.command == "paths":
            _execute_paths_command(args)
        elif args.command == "migrate":
            if args.check:
                check_migration_status()
            else:
                migrate_agents()
        elif args.command == "config":
            _execute_config_command(args)
        elif args.command == "secrets":
            _execute_secrets_command(args)
        elif args.command == "doctor":
            sys.exit(run_doctor())
        else:
            # Create session state from args
            session_state = SessionState(auto_approve=args.auto_approve, no_splash=args.no_splash)
            # Textual TUI is the default UI. Use --legacy-ui to opt out.
            session_state.use_tui = not bool(args.legacy_ui)

            # Ensure the project wiki vault exists from session start, so the user
            # can point Obsidian at .nova/wiki/ without first running a wiki
            # command (the Web Clipper drops into .nova/wiki/Clippings/).
            # Best-effort — skipped silently outside a git project or on any error.
            try:
                from novacode_cli.wiki.manager import WikiManager

                WikiManager().ensure_structure()
            except Exception:  # noqa: BLE001 — never block startup on the wiki
                pass

            # Parse port forwarding argument
            ports = parse_ports(args.ports)

            # Resolve the effective sandbox and whether the user chose it
            # explicitly. Default is OS-confined local execution (Pattern A) on
            # Linux/macOS, and plain host execution + approvals on Windows. An
            # explicit choice (or --no-sandbox) is honored without fallback.
            try:
                sandbox_type, explicit_sandbox = resolve_sandbox_type(args.sandbox, args.no_sandbox)
            except ValueError as e:
                console.print(f"[red]Error: {e}[/red]")
                sys.exit(1)

            # --resume and --continue are mutually exclusive
            if args.resume and args.continue_session:
                console.print("[red]Error: --resume and --continue are mutually exclusive.[/red]")
                console.print(
                    "[dim]Use --resume to pick a session interactively, or --continue <id> to resume a specific session.[/dim]"
                )
                sys.exit(1)

            # API key validation happens in create_model()
            asyncio.run(
                main(
                    args.agent,
                    session_state,
                    sandbox_type,
                    args.sandbox_id,
                    args.sandbox_setup,
                    args.continue_session,
                    resume=args.resume,
                    ports=ports,
                    explicit_sandbox=explicit_sandbox,
                    sandbox_vcpus=args.sandbox_vcpus,
                    sandbox_mem_bytes=args.sandbox_mem_bytes,
                    sandbox_fs_capacity_bytes=args.sandbox_fs_capacity_bytes,
                    sandbox_snapshot=args.sandbox_snapshot,
                    sandbox_snapshot_id=args.sandbox_snapshot_id,
                )
            )
            # main() returned normally — every teardown step has run (session
            # saved, sandbox stopped, background tasks cancelled, connections
            # committed). Force a prompt process exit so a lingering non-daemon
            # thread (sqlite/aiosqlite worker, docker SDK pool, etc.) can't hang
            # /quit during interpreter shutdown. Error paths use sys.exit() and
            # propagate before reaching here, so exit codes are preserved.
            sys.stdout.flush()
            sys.stderr.flush()
            os._exit(0)
    except KeyboardInterrupt:
        # Clean exit on Ctrl+C - suppress ugly traceback
        console.print("\n\n[yellow]Interrupted[/yellow]")
        sys.exit(0)


if __name__ == "__main__":
    cli_main()

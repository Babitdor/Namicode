"""Main entry point and CLI loop for deepagents.

This module provides the primary CLI interface for Nami-Code CLI, including:
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
import warnings
import os

# Suppress "None of PyTorch, TensorFlow >= 2.0, or Flax have been found" warning
os.environ["TRANSFORMERS_VERBOSITY"] = "error"

# Suppress token sequence length warnings from transformers/tiktoken
warnings.filterwarnings(
    "ignore",
    message="Token indices sequence length is longer than",
)
warnings.filterwarnings(
    "ignore",
    message="None of PyTorch, TensorFlow",
)

import argparse
import asyncio
import signal
import sys
import time
from pathlib import Path
from langgraph.store.memory import InMemoryStore
from langgraph.checkpoint.memory import InMemorySaver
from nami_deepagents.backends.protocol import SandboxBackendProtocol

from namicode_cli.agents.core_agent import (
    create_agent_with_config,
    list_agents,
    reset_agent,
)
from namicode_cli.commands.commands import execute_bash_command, handle_command
from namicode_cli.config.config import (
    COLORS,
    HOME_DIR,
    NAMI_CODE_ASCII,
    console,
    settings,
)
from namicode_cli.config.model_create import create_model
from namicode_cli.states.Session import SessionState
from namicode_cli.ui.execution import execute_task
from namicode_cli.input import create_prompt_session, ImageTracker
from namicode_cli.migrate import check_migration_status, migrate_agents
from namicode_cli.integrations.sandbox_factory import (
    create_sandbox,
    get_default_working_dir,
)
from namicode_cli.path_approval import check_path_approval, PathApprovalManager
from namicode_cli.commands.commands import execute_skills_command
from namicode_cli.skills.skill_creation import setup_skills_parser
from namicode_cli.mcp.commands import execute_mcp_command, setup_mcp_parser
from namicode_cli.tools import (
    execute_in_e2b,
    fetch_url,
    http_request,
    web_search,
)
from namicode_cli.server_runner.dev_server import (
    list_servers_tool,
    start_dev_server_tool,
    stop_server_tool,
)
from namicode_cli.server_runner.test_runner import run_tests_tool
from namicode_cli.process_manager import ProcessManager
from namicode_cli.ui.ui_elements import TokenTracker, show_help

# Auto-save configuration
AUTO_SAVE_INTERVAL_SECONDS = 300  # Save session every 5 minutes
AUTO_SAVE_MESSAGE_THRESHOLD = 5  # Also save after every N new messages


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
        print("  pip install deepagents[cli]")
        print("\nOr install all dependencies:")
        print("  pip install 'deepagents[cli]'")
        sys.exit(1)


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="DeepAgents - AI Coding Assistant",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        add_help=False,
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Init command - interactive configuration setup
    init_parser = subparsers.add_parser(
        "init", help="Initialize project or global configuration"
    )
    init_parser.add_argument(
        "--scope",
        choices=["project", "global"],
        help="Create project-specific or global configuration",
    )
    init_parser.add_argument(
        "--style",
        choices=["deepagents", "claude"],
        help="Use .nami/ or .claude/ directory structure",
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
    config_parser = subparsers.add_parser(
        "config", help="View or edit configuration (non-secret)"
    )
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
    paths_subparsers = paths_parser.add_subparsers(
        dest="paths_command", help="Paths command"
    )

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
        default="nami-agent",
        help="Agent identifier for separate memory stores (default: nami-agent).",
    )
    parser.add_argument(
        "--auto-approve",
        action="store_true",
        help="Auto-approve tool usage without prompting (disables human-in-the-loop)",
    )
    parser.add_argument(
        "--sandbox",
        choices=["none", "modal", "daytona", "runloop", "docker"],
        default="none",
        help="Sandbox for code execution (default: none - local only)",
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
        "--no-splash",
        action="store_true",
        help="Disable the startup splash screen",
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
        "--version",
        action="version",
        version=f"{settings.version} (NamiCode)",
        help="Show the version number and exit",
    )
    parser.add_argument(
        "--tui",
        action="store_true",
        help="Launch Textual-based TUI interface instead of CLI",
    )
    parser.add_argument(
        "-h", "--help", action="help", help="Show this help message and exit"
    )

    return parser.parse_args()


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
    store: InMemoryStore | None = None,
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
        sandbox_type: Type of sandbox being used (e.g., "modal", "runloop", "daytona").
        model_name: Name of the model being used for context window calculation.
                     If None, running in local mode.
        setup_script_path: Path to setup script that was run (if any)
        no_splash: If True, skip displaying the startup splash screen
        session_manager: SessionManager for session persistence
        restored_session_data: Tuple of (session_data, warnings, nami_md_loaded) for continuation
    """
    console.clear()
    # Check path approval before proceeding
    if not await check_path_approval():
        console.print()
        console.print(
            "[red]Cannot start nami without path approval.[/red]",
            style=COLORS["dim"],
        )
        console.print(
            "[dim]Path approval is required to ensure safe file system access.[/dim]"
        )
        console.print()
        sys.exit(1)

    if not no_splash:
        console.print(NAMI_CODE_ASCII, style=f"bold {COLORS['primary']}")
        console.print()

    # Extract sandbox ID from backend if using sandbox mode
    sandbox_id: str | None = None
    if backend:
        from nami_deepagents.backends.composite import CompositeBackend

        # Check if it's a CompositeBackend with a sandbox default backend
        if isinstance(backend, CompositeBackend):
            if isinstance(backend.default, SandboxBackendProtocol):
                sandbox_id = backend.default.id
        elif isinstance(backend, SandboxBackendProtocol):
            sandbox_id = backend.id

    # Display sandbox info persistently (survives console.clear())
    if sandbox_type and sandbox_id:
        console.print(
            f"[yellow]⚡ {sandbox_type.capitalize()} sandbox: {sandbox_id}[/yellow]"
        )
        if setup_script_path:
            console.print(
                f"[green]✓ Setup script ({setup_script_path}) completed successfully[/green]"
            )
        console.print()

    if not settings.has_tavily:
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

    console.print()

    if sandbox_type:
        working_dir = get_default_working_dir(sandbox_type)
        console.print(f"  [dim]Local CLI directory: {Path.cwd()}[/dim]")
        console.print(f"  [dim]Code execution: Remote sandbox ({working_dir})[/dim]")
    else:
        console.print(f"  [dim]{Path.cwd()}[/dim]")

    # Show memory status (agent.md / NAMI.md loaded)
    if assistant_id:
        user_agent_md = settings.get_user_agent_md_path(assistant_id)
        has_user_memory = user_agent_md.exists()
    else:
        has_user_memory = False
    project_agent_md = settings.get_project_agent_md_paths()
    has_project_memory = project_agent_md.exists() if project_agent_md else False

    if has_user_memory or has_project_memory:
        memory_parts = []
        if has_user_memory:
            memory_parts.append(f"(~/.nami/agents/{assistant_id}/agent.md)")
        if has_project_memory:
            memory_parts.append("Project: (.nami/NAMI.md)")
        console.print(f"  [dim]Memory: {', '.join(memory_parts)}[/dim]")
    else:
        console.print("  [dim]Memory: none (use /init to create project memory)[/dim]")

    console.print()

    # Display restored session info if continuing
    if restored_session_data:
        from namicode_cli.ui.session_display import display_restored_session

        session_data, warnings, nami_md_loaded = restored_session_data
        display_restored_session(
            session_data=session_data,
            warnings=warnings,
            nami_md_loaded=nami_md_loaded,
        )

    if session_state.auto_approve:
        console.print(
            "  [yellow]⚡ Auto-approve: ON[/yellow] [dim](tools run without confirmation)[/dim]"
        )
        console.print()

    # Localize modifier names and show key symbols (macOS vs others)
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

    # Create prompt session and token tracker
    session = create_prompt_session(assistant_id, session_state)
    token_tracker = TokenTracker()
    image_tracker = ImageTracker()
    token_tracker.set_baseline(baseline_tokens)
    if model_name:
        token_tracker.set_model(model_name)

    # Auto-save state tracking
    last_save_time = time.time()
    messages_since_save = 0

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
            from namicode_cli.tracking.workspace_anchoring import scan_workspace
            from namicode_cli.session.session_summarization import (
                should_trigger_summarization,
                summarize_messages_to_memory,
            )

            config = {"configurable": {"thread_id": session_state.thread_id}}
            state = await agent.aget_state(config)
            messages = state.values.get("messages", [])
            # Get todos from agent state if available
            todos = state.values.get("todos") or session_state.todos

            if messages:
                # Scan current workspace state
                workspace_state = (
                    scan_workspace(settings.project_root)
                    if settings.project_root
                    else None
                )

                # Extract current task from session state (if available)
                # For now, we'll use a simple heuristic - could be enhanced later
                current_task = getattr(session_state, "current_task", None)

                # Determine task status from state
                task_status = getattr(session_state, "task_status", "active")

                # Check if we should trigger summarization
                memory_content = None
                if should_trigger_summarization(len(messages)):
                    if not silent:
                        console.print("[dim]Generating session memory summary...[/dim]")
                    try:
                        # Get model for summarization
                        from namicode_cli.config.model_create import create_model

                        summary_model = create_model()
                        memory_content = summarize_messages_to_memory(
                            messages=messages,
                            model=summary_model,
                            current_task=current_task,
                        )
                    except Exception as e:
                        if not silent:
                            console.print(
                                f"[dim]Could not generate memory summary: {e}[/dim]"
                            )

                session_manager.save_session(
                    session_id=session_state.session_id or session_state.thread_id,
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
                )
                if not silent:
                    console.print("[dim]Session saved.[/dim]")
                return True
        except Exception as e:
            if not silent:
                console.print(f"[dim]Could not save session: {e}[/dim]")
        return False

    # Helper to clean up and save session on exit
    async def _cleanup_and_save_session() -> None:
        """Clean up managed processes and save session state when user exits."""
        # Stop all managed dev servers/processes
        try:
            manager = ProcessManager.get_instance()
            stopped_count = await manager.stop_all()
            if stopped_count > 0:
                console.print(
                    f"[dim]Stopped {stopped_count} managed process(es).[/dim]"
                )
        except Exception as e:
            console.print(f"[dim]Could not stop processes: {e}[/dim]")

        # Save session
        await _save_session(silent=False)

    # Helper for auto-save check
    async def _maybe_auto_save() -> None:
        """Check if auto-save should run and save if needed."""
        nonlocal last_save_time, messages_since_save

        current_time = time.time()
        time_since_save = current_time - last_save_time

        # Auto-save if enough time has passed or enough messages accumulated
        should_save = (
            time_since_save >= AUTO_SAVE_INTERVAL_SECONDS
            or messages_since_save >= AUTO_SAVE_MESSAGE_THRESHOLD
        )

        if should_save and messages_since_save > 0:
            if await _save_session(silent=True):
                last_save_time = current_time
                messages_since_save = 0

    # Signal handler for graceful termination (SIGTERM, SIGHUP)
    # This allows session saving when the terminal is closed or process is terminated
    shutdown_requested = False

    def _signal_handler(signum, frame):
        """Handle termination signals by requesting graceful shutdown."""
        nonlocal shutdown_requested
        shutdown_requested = True
        # Re-raise as KeyboardInterrupt to trigger normal cleanup path
        raise KeyboardInterrupt()

    # Register signal handlers (Unix-only, Windows doesn't support all signals)
    if sys.platform != "win32":
        try:
            signal.signal(signal.SIGTERM, _signal_handler)
            signal.signal(signal.SIGHUP, _signal_handler)
        except (ValueError, OSError):
            # Signal handling may fail in some contexts (e.g., threads)
            pass

    while True:
        try:
            user_input = await session.prompt_async()
            if session_state.exit_hint_handle:
                session_state.exit_hint_handle.cancel()
                session_state.exit_hint_handle = None
            session_state.exit_hint_until = None
            user_input = user_input.strip()
        except EOFError:
            await _cleanup_and_save_session()
            break
        except KeyboardInterrupt:
            await _cleanup_and_save_session()
            console.print("\nGoodbye!", style=COLORS["primary"])
            break

        if not user_input:
            continue

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
            )
            if result == "exit":
                await _cleanup_and_save_session()
                console.print("\nGoodbye!", style=COLORS["primary"])
                break
            if result:
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

        # Check for @agent mentions
        from namicode_cli.input import parse_agent_mentions
        from namicode_cli.commands.commands import invoke_subagent
        agent_name, query = parse_agent_mentions(user_input, settings)
        if agent_name:
            console.print()
            # console.print(
            #     f"[bold cyan]@{agent_name}[/bold cyan] [dim]processing...[/dim]"
            # )
            # console.print()

            subagent, _ = invoke_subagent(
                agent_name,
                settings=settings,
                store=store,
                checkpointer=checkpointer,
            )
            await execute_task(
                query,
                subagent,
                agent_name,
                session_state,
                token_tracker,
                backend=backend,
                is_subagent=True,
                image_tracker=image_tracker,
            )

        else:
            await execute_task(
                user_input,
                agent,
                assistant_id,
                session_state,
                token_tracker,
                backend=backend,
                is_subagent=False,
                image_tracker=image_tracker,
            )

        # Track message for auto-save and check if we should save
        messages_since_save += 1
        await _maybe_auto_save()


async def _run_agent_session(
    model,
    assistant_id: str,
    session_state,
    sandbox_backend=None,
    sandbox_type: str | None = None,
    setup_script_path: str | None = None,
    initial_messages: list | None = None,
    session_manager=None,
    store: InMemoryStore | None = None,
    checkpointer: InMemorySaver | None = None,
    restored_session_data: tuple | None = None,
) -> None:
    """Helper to create agent and run CLI session.

    Extracted to avoid duplication between sandbox and local modes.

    Args:
        model: LLM model to use
        assistant_id: Agent identifier for memory storage
        session_state: Session state with auto-approve settings
        sandbox_backend: Optional sandbox backend for remote execution
        sandbox_type: Type of sandbox being used
        setup_script_path: Path to setup script that was run (if any)
        initial_messages: Optional messages to inject for session continuation
        session_manager: SessionManager for session persistence
        restored_session_data: Tuple of (session_data, warnings, nami_md_loaded) for continuation
    """
    # Create agent with conditional tools
    tools = [
        http_request,
        fetch_url,
        execute_in_e2b,
        run_tests_tool,
        start_dev_server_tool,
        stop_server_tool,
        list_servers_tool,
    ]
    if settings.has_tavily:
        tools.append(web_search)

    agent, composite_backend = create_agent_with_config(
        model,
        assistant_id,
        tools,
        sandbox=sandbox_backend,
        sandbox_type=sandbox_type,
        store=store,
        checkpointer=checkpointer,
    )

    # Inject initial messages if continuing a session
    if initial_messages:
        config = {"configurable": {"thread_id": session_state.thread_id}}
        await agent.aupdate_state(
            config=config,  # type: ignore
            values={"messages": initial_messages},
        )
        console.print(
            f"[dim]Restored {len(initial_messages)} messages from previous session.[/dim]"
        )

    # Calculate baseline token count for accurate token tracking
    from namicode_cli.agents.core_agent import get_system_prompt
    from .token_utils import calculate_baseline_tokens

    agent_dir = settings.get_agent_dir(assistant_id)
    system_prompt = get_system_prompt(
        assistant_id=assistant_id, sandbox_type=sandbox_type
    )
    baseline_tokens = calculate_baseline_tokens(
        model, agent_dir, system_prompt, assistant_id
    )

    # Extract model name for context window calculation
    model_name = getattr(model, "model_name", None) or getattr(
        model, "model", "unknown"
    )

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


async def main(
    assistant_id: str,
    session_state,
    sandbox_type: str = "none",
    sandbox_id: str | None = None,
    setup_script_path: str | None = None,
    continue_session: bool | str = False,
) -> None:
    """Main entry point with conditional sandbox support.

    Args:
        assistant_id: Agent identifier for memory storage
        session_state: Session state with auto-approve settings
        sandbox_type: Type of sandbox ("none", "modal", "runloop", "daytona")
        sandbox_id: Optional existing sandbox ID to reuse
        setup_script_path: Optional path to setup script to run in sandbox
        continue_session: If True, continue last session. If string, use as session ID.
    """
    from namicode_cli.session.session_persistence import SessionManager
    from namicode_cli.session.session_restore import restore_session

    model = create_model()
    store = InMemoryStore()
    checkpointer = InMemorySaver()
    # Initialize session manager for persistence
    session_manager = SessionManager()
    initial_messages: list | None = None

    # Handle session continuation
    if continue_session:
        from namicode_cli.tracking.workspace_anchoring import (
            scan_workspace,
            detect_drift,
        )
        from namicode_cli.session.session_prompt_builder import (
            build_continuation_prompt,
            load_nami_md,
        )

        project_root = Path.cwd()
        session_id = continue_session if isinstance(continue_session, str) else None

        result = restore_session(session_manager, session_id, project_root)
        if result:
            session_data, warnings = result

            # Load only recent messages for context (not all messages)
            # The continuation prompt builder will handle the full context
            recent_messages = session_manager.load_recent_messages(
                session_data.meta.session_id
            )

            # Scan current workspace and detect drift
            current_workspace = scan_workspace(project_root)
            if session_data.workspace_state:
                drift_warnings = detect_drift(
                    session_data.workspace_state, current_workspace
                )
                warnings.extend(drift_warnings)

            # Load NAMI.md for continuation prompt
            nami_md_content = load_nami_md(project_root)

            # Store session display data to show after splash screen
            session_data_for_display = session_data
            session_data_for_display.messages = recent_messages

            # Build continuation messages with proper prompt structure
            # Note: We use recent messages here, not all messages
            session_data_with_recent = session_data
            session_data_with_recent.messages = recent_messages

            # Get base system prompt (will be used by build_continuation_prompt)
            from namicode_cli.config.config import get_default_coding_instructions

            base_system_prompt = get_default_coding_instructions()

            # Build continuation prompt with correct order
            initial_messages = build_continuation_prompt(
                session_data=session_data_with_recent,
                system_prompt=base_system_prompt,
                nami_md_content=nami_md_content,
                workspace_state=current_workspace,
            )

            # Restore session state
            session_state.session_id = session_data.meta.session_id
            session_state.thread_id = session_data.meta.thread_id
            session_state.is_continued = True

            # Restore todos if available
            if session_data.todos:
                session_state.todos = session_data.todos

            # Create tuple for displaying after splash screen
            restored_session_data = (
                session_data_for_display,
                warnings,
                bool(nami_md_content),
            )
        else:
            console.print()
            console.print("[yellow]No previous session found.[/yellow]")
            console.print("[dim]Starting new session.[/dim]")
            console.print()
            restored_session_data = None
    else:
        restored_session_data = None

    # Branch 1: User wants a sandbox
    if sandbox_type != "none":
        # Try to create sandbox
        try:
            console.print()
            with create_sandbox(
                sandbox_type, sandbox_id=sandbox_id, setup_script_path=setup_script_path
            ) as sandbox_backend:
                console.print(
                    f"[yellow]⚡ Remote execution enabled ({sandbox_type})[/yellow]"
                )
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
        except (ImportError, ValueError, RuntimeError, NotImplementedError) as e:
            # Sandbox creation failed - fail hard (no silent fallback)
            console.print()
            console.print("[red]❌ Sandbox creation failed[/red]")
            console.print(f"[dim]{e}[/dim]")
            sys.exit(1)
        except KeyboardInterrupt:
            console.print("\n\n[yellow]Interrupted[/yellow]")
            sys.exit(0)
        except Exception as e:
            console.print(f"\n[bold red]Error:[/bold red] {e}\n")
            console.print_exception()
            sys.exit(1)

    # Branch 2: User wants local mode (none or default)
    else:
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
            )
        except KeyboardInterrupt:
            console.print("\n\n[yellow]Interrupted[/yellow]")
            sys.exit(0)
        except Exception as e:
            console.print(f"\n[bold red]Error:[/bold red] {e}\n")
            console.print_exception()
            sys.exit(1)


async def main_tui(
    assistant_id: str,
    session_state,
    sandbox_type: str = "none",
    sandbox_id: str | None = None,
    setup_script_path: str | None = None,
    continue_session: bool | str = False,
) -> None:
    """Main entry point for TUI mode with conditional sandbox support.

    Args:
        assistant_id: Agent identifier for memory storage
        session_state: Session state with auto-approve settings
        sandbox_type: Type of sandbox ("none", "modal", "runloop", "daytona")
        sandbox_id: Optional existing sandbox ID to reuse
        setup_script_path: Optional path to setup script to run in sandbox
        continue_session: If True, continue last session. If string, use as session ID.
    """
    from namicode_cli.session.session_persistence import SessionManager
    from namicode_cli.session.session_restore import restore_session
    from namicode_cli.app import run_textual_app
    from namicode_cli.config.config import settings as app_settings

    model = create_model()
    store = InMemoryStore()
    checkpointer = InMemorySaver()
    session_manager = SessionManager()
    initial_messages: list | None = None

    # Handle session continuation
    if continue_session:
        from namicode_cli.tracking.workspace_anchoring import (
            scan_workspace,
            detect_drift,
        )
        from namicode_cli.session.session_prompt_builder import (
            build_continuation_prompt,
            load_nami_md,
        )

        project_root = Path.cwd()
        session_id = continue_session if isinstance(continue_session, str) else None

        result = restore_session(session_manager, session_id, project_root)
        if result:
            session_data, warnings = result

            # Load only recent messages for context
            recent_messages = session_manager.load_recent_messages(
                session_data.meta.session_id
            )

            # Scan current workspace and detect drift
            current_workspace = scan_workspace(project_root)
            if session_data.workspace_state:
                drift_warnings = detect_drift(
                    session_data.workspace_state, current_workspace
                )
                warnings.extend(drift_warnings)

            # Load NAMI.md for continuation prompt
            nami_md_content = load_nami_md(project_root)

            # Build continuation messages with proper prompt structure
            session_data_with_recent = session_data
            session_data_with_recent.messages = recent_messages

            # Get base system prompt
            from namicode_cli.config.config import get_default_coding_instructions

            base_system_prompt = get_default_coding_instructions()

            # Build continuation prompt with correct order
            initial_messages = build_continuation_prompt(
                session_data=session_data_with_recent,
                system_prompt=base_system_prompt,
                nami_md_content=nami_md_content,
                workspace_state=current_workspace,
            )

            # Restore session state
            session_state.session_id = session_data.meta.session_id
            session_state.thread_id = session_data.meta.thread_id
            session_state.is_continued = True

            # Restore todos if available
            if session_data.todos:
                session_state.todos = session_data.todos
        else:
            console.print()
            console.print("[yellow]No previous session found.[/yellow]")
            console.print("[dim]Starting new session.[/dim]")
            console.print()

    # Create agent with tools
    tools = [
        http_request,
        fetch_url,
        execute_in_e2b,
        run_tests_tool,
        start_dev_server_tool,
        stop_server_tool,
        list_servers_tool,
    ]
    if settings.has_tavily:
        tools.append(web_search)

    # Branch 1: User wants a sandbox
    if sandbox_type != "none":
        try:
            console.print()
            with create_sandbox(
                sandbox_type, sandbox_id=sandbox_id, setup_script_path=setup_script_path
            ) as sandbox_backend:
                console.print(
                    f"[yellow]⚡ Remote execution enabled ({sandbox_type})[/yellow]"
                )
                console.print()

                agent, composite_backend = create_agent_with_config(
                    model,
                    assistant_id,
                    tools,
                    sandbox=sandbox_backend,
                    sandbox_type=sandbox_type,
                    store=store,
                    checkpointer=checkpointer,
                )

                # Inject initial messages if continuing a session
                if initial_messages:
                    config = {"configurable": {"thread_id": session_state.thread_id}}
                    await agent.aupdate_state(
                        config=config,
                        values={"messages": initial_messages},
                    )

                # Get model name for context window calculation
                model_name = getattr(model, "model_name", None) or getattr(
                    model, "model", "unknown"
                )

                await run_textual_app(
                    agent=agent,
                    assistant_id=assistant_id,
                    backend=composite_backend,
                    auto_approve=session_state.auto_approve,
                    cwd=Path.cwd(),
                    thread_id=session_state.thread_id,
                    session_state=session_state,
                    session_manager=session_manager,
                    store=store,
                    checkpointer=checkpointer,
                    model_name=model_name,
                    settings=app_settings,
                )
        except (ImportError, ValueError, RuntimeError, NotImplementedError) as e:
            console.print()
            console.print("[red]❌ Sandbox creation failed[/red]")
            console.print(f"[dim]{e}[/dim]")
            sys.exit(1)
        except KeyboardInterrupt:
            console.print("\n\n[yellow]Interrupted[/yellow]")
            sys.exit(0)
        except Exception as e:
            console.print(f"\n[bold red]Error:[/bold red] {e}\n")
            console.print_exception()
            sys.exit(1)

    # Branch 2: User wants local mode (none or default)
    else:
        try:
            agent, composite_backend = create_agent_with_config(
                model,
                assistant_id,
                tools,
                sandbox=None,
                sandbox_type=None,
                store=store,
                checkpointer=checkpointer,
            )

            # Inject initial messages if continuing a session
            if initial_messages:
                config = {"configurable": {"thread_id": session_state.thread_id}}
                await agent.aupdate_state(
                    config=config,
                    values={"messages": initial_messages},
                )

            # Get model name for context window calculation
            model_name = getattr(model, "model_name", None) or getattr(
                model, "model", "unknown"
            )

            await run_textual_app(
                agent=agent,
                assistant_id=assistant_id,
                backend=composite_backend,
                auto_approve=session_state.auto_approve,
                cwd=Path.cwd(),
                thread_id=session_state.thread_id,
                session_state=session_state,
                session_manager=session_manager,
                store=store,
                checkpointer=checkpointer,
                model_name=model_name,
                settings=app_settings,
            )
        except KeyboardInterrupt:
            console.print("\n\n[yellow]Interrupted[/yellow]")
            sys.exit(0)
        except Exception as e:
            console.print(f"\n[bold red]Error:[/bold red] {e}\n")
            console.print_exception()
            sys.exit(1)


def _execute_paths_command(args) -> None:
    """Execute paths management commands."""
    manager = PathApprovalManager()

    if args.paths_command == "list":
        approved_paths = manager.list_approved_paths()

        if not approved_paths:
            console.print()
            console.print("[yellow]No approved paths found.[/yellow]")
            console.print(
                "[dim]Paths will be approved automatically when you first run nami in a directory.[/dim]"
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
        console.print(
            "[dim]You'll need to re-approve paths when you next run nami.[/dim]"
        )
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
        console.print(
            "[yellow]Please specify a subcommand: list, revoke, or clear[/yellow]"
        )
        console.print()
        console.print("[bold]Usage:[/bold]", style=COLORS["primary"])
        console.print("  nami paths list         List all approved paths")
        console.print("  nami paths revoke PATH  Revoke approval for a path")
        console.print("  nami paths clear        Clear all approved paths")
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
            console.print("[dim]Run 'nami init' to set up configuration[/dim]")
            console.print()

    elif command == "get":
        # Get specific configuration value
        if not args.key:
            console.print("[red]✗ Key required for 'get' command[/red]")
            console.print("[dim]Usage: nami config get <key>[/dim]")
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
            console.print("[dim]Usage: nami config set <key> <value>[/dim]")
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
    from namicode_cli.onboarding import SecretManager
    from prompt_toolkit import prompt

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
            console.print("[dim]Use 'nami secrets set <key>' to add API keys[/dim]")
        console.print()

    elif command == "set":
        # Set API key
        if not args.key:
            console.print("[red]✗ Key name required for 'set' command[/red]")
            console.print(
                "[dim]Usage: nami secrets set <key> (e.g., 'openai_api_key')[/dim]"
            )
            return

        console.print()
        console.print(f"[bold]Setting {args.key}:[/bold]")
        api_key = prompt("Enter API key: ", is_password=True).strip()

        if api_key:
            if secret_manager.store_secret(args.key, api_key):
                console.print()
                console.print(f"[green]✓ API key saved to system keychain[/green]")
                console.print()
            else:
                console.print()
                console.print(f"[red]✗ Failed to save API key[/red]")
                console.print()
        else:
            console.print()
            console.print("[yellow]⚠ No API key provided, cancelled[/yellow]")
            console.print()

    elif command == "delete":
        # Delete API key
        if not args.key:
            console.print("[red]✗ Key name required for 'delete' command[/red]")
            console.print(
                "[dim]Usage: nami secrets delete <key> (e.g., 'openai_api_key')[/dim]"
            )
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
                console.print(f"[red]✗ Failed to delete API key[/red]")
                console.print()
        else:
            console.print()
            console.print("[dim]Cancelled[/dim]")
            console.print()


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
                from namicode_cli.onboarding import OnboardingWizard

                console.print()
                console.print("[yellow]→ First run detected[/yellow]")
                console.print()

                wizard = OnboardingWizard()
                if wizard.run():
                    console.print()
                    console.print(
                        "[dim]You can now run your command or start an interactive session.[/dim]"
                    )
                    console.print()
                else:
                    console.print()
                    console.print("[red]✗ Setup incomplete[/red]")
                    console.print("[dim]Run 'nami init --reset' to try again[/dim]")
                    console.print()
                    sys.exit(1)

        if args.command == "init":
            # Check if --reset flag is set (re-run onboarding)
            if args.reset:
                from namicode_cli.onboarding import OnboardingWizard

                console.print()
                console.print(
                    "[yellow]⚠ This will overwrite your current configuration.[/yellow]"
                )
                from prompt_toolkit import prompt

                confirm = prompt("Continue? [y/N]: ").strip().lower()
                if confirm == "y":
                    wizard = OnboardingWizard()
                    wizard.run()
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
            from namicode_cli.doctor import run_doctor

            sys.exit(run_doctor())
        else:
            # Create session state from args
            session_state = SessionState(
                auto_approve=args.auto_approve, no_splash=args.no_splash
            )

            # Check if TUI mode is requested
            if getattr(args, 'tui', False):
                asyncio.run(
                    main_tui(
                        args.agent,
                        session_state,
                        args.sandbox,
                        args.sandbox_id,
                        args.sandbox_setup,
                        args.continue_session,
                    )
                )
            else:
                # API key validation happens in create_model()
                asyncio.run(
                    main(
                        args.agent,
                        session_state,
                        args.sandbox,
                        args.sandbox_id,
                        args.sandbox_setup,
                        args.continue_session,
                    )
                )
    except KeyboardInterrupt:
        # Clean exit on Ctrl+C - suppress ugly traceback
        console.print("\n\n[yellow]Interrupted[/yellow]")
        sys.exit(0)


if __name__ == "__main__":
    cli_main()

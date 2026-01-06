"""Command handlers for slash commands and bash execution."""

import asyncio
import subprocess
from pathlib import Path

from langgraph.checkpoint.memory import InMemorySaver

from langchain.agents.middleware.human_in_the_loop import (
    ActionRequest,
    ApproveDecision,
    Decision,
    HITLRequest,
    HITLResponse,
    RejectDecision,
)
from langgraph.pregel import Pregel
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from pydantic import TypeAdapter, ValidationError

from .config import COLORS, DEEP_AGENTS_ASCII, Settings, TOOL_ICONS, console
from .execution import execute_task
from .ui import (
    TokenTracker,
    show_interactive_help,
)
from langgraph.types import Command, Interrupt
from .mcp.config import MCPConfig, MCPServerConfig
from .mcp import presets as mcp_presets
from .model_manager import ModelManager, MODEL_PRESETS, get_ollama_models
from .process_manager import ProcessManager

from .dev_server import list_servers, stop_server
from nami_deepagents.backends import CompositeBackend
from .test_runner import run_tests, detect_test_framework, get_default_test_command
from namicode_cli.subagent import create_subagent


async def _handle_init_command(
    agent, session_state, assistant_id: str, token_tracker: TokenTracker
):
    """Handle the /init command to explore codebase and create NAMI.md file."""
    console.print()

    # Create a nice header
    header = Text()
    header.append("🔍 ", style="bold")
    header.append("NAMI.md Initialization", style=f"bold {COLORS['primary']}")

    panel = Panel(
        Text(
            "Exploring your codebase to create comprehensive documentation for AI assistants",
            style="dim",
        ),
        title=header,
        border_style=COLORS["primary"],
        padding=(1, 2),
    )
    console.print(panel)
    console.print()

    # Check if we're in a project directory
    settings = Settings.from_environment()
    project_root = settings.project_root

    if not project_root:
        console.print("❌ ", style="red", end="")
        console.print("[bold red]Not in a project directory[/bold red]")
        console.print(
            "   [dim]The /init command requires a .git directory in the project root.[/dim]"
        )
        console.print()
        return

    # Show project info
    console.print("📁 ", style=COLORS["primary"], end="")
    console.print(f"[bold]Project:[/bold] {project_root.name}")
    console.print(f"   [dim]{project_root}[/dim]")
    console.print()

    # Check if NAMI.md already exists
    nami_md_path = project_root / ".nami" / "NAMI.md"
    if nami_md_path.exists():
        console.print("⚠️  ", style="yellow", end="")
        console.print("[yellow]NAMI.md already exists[/yellow]")
        console.print("   [dim]It will be updated with fresh analysis[/dim]")
        console.print()

    # Create the exploration prompt
    exploration_prompt = f"""I need you to explore this codebase and create a comprehensive NAMI.md file.

The NAMI.md file should be similar to a CLAUDE.md file used by Claude Code - it provides guidance and context about the codebase for AI assistants working with this project.

Project root: {project_root}

Please follow these steps:

1. **Explore the codebase structure:**
   - Use glob to find key files (README, package.json, pyproject.toml, Cargo.toml, etc.)
   - Identify the primary programming language(s)
   - Find main entry points and important directories
   - Look for configuration files

2. **Analyze the architecture:**
   - Read key files to understand the project structure
   - Identify main modules/packages/components
   - Understand the technology stack
   - Note any frameworks or libraries used

3. **Document development setup:**
   - Find setup/installation instructions
   - Identify build tools and commands
   - Note testing frameworks and commands
   - Document linting/formatting tools

4. **Create NAMI.md with the following sections:**

## NAMI.md Structure:

```markdown
# NAMI.md

This file provides guidance to AI assistants when working with code in this repository.

## Project Overview

[Brief description of what this project does]

## Technology Stack

[Languages, frameworks, key dependencies]

## Project Structure

[Directory layout and purpose of main directories]

## Development Setup

[How to set up the development environment]
[Installation commands]
[Environment variables if applicable]

## Development Commands

[Common commands for development, testing, building]

## Architecture

[Key architectural patterns or design decisions]
[Main modules/components and their purposes]

## Important Files

[List of critical files and what they do]

## Common Workflows

[Typical development tasks and how to do them]

## Testing

[How to run tests]
[Testing philosophy/approach]

## Code Style and Conventions

[Coding standards, naming conventions, etc.]

## Additional Notes

[Any other important information for developers]
```

5. **Write the file:**
   - Use write_file to create {nami_md_path}
   - Make it comprehensive but concise
   - Focus on information that would help an AI assistant understand and work with the codebase

Please start exploring now and create the NAMI.md file."""

    # Show status
    console.print("🤖 ", style=COLORS["primary"], end="")
    console.print("[bold]Starting AI exploration...[/bold]")
    console.print(
        "   [dim]The agent will automatically explore and document your codebase[/dim]"
    )
    console.print()

    # Temporarily enable auto-approve for this operation since user explicitly requested /init
    original_auto_approve = session_state.auto_approve
    session_state.auto_approve = True

    try:
        # Use the existing execute_task function to handle the exploration
        # This properly handles all tool calls, approvals, streaming, etc.
        await execute_task(
            exploration_prompt,
            agent,
            assistant_id,
            session_state,
            token_tracker,
        )

        console.print()

        # Check if file was created and show appropriate message
        if nami_md_path.exists():
            # Read the file to show a preview
            try:
                content = nami_md_path.read_text()
                lines = content.split("\n")
                file_size = len(content)
                line_count = len(lines)

                # Create success panel
                success_text = Text()
                success_text.append("✓ ", style="bold green")
                success_text.append("NAMI.md Created Successfully", style="bold green")

                info_lines = [
                    f"📍 Location: {nami_md_path}",
                    f"📄 Size: {file_size:,} characters, {line_count} lines",
                    "",
                    "📋 Preview:",
                ]

                # Add first few lines as preview
                preview_lines = [line for line in lines[:10] if line.strip()][:5]
                for line in preview_lines:
                    info_lines.append(f"   {line[:80]}")
                if line_count > 10:
                    info_lines.append("   ...")

                info_lines.append("")
                info_lines.append(
                    "💡 Tip: The NAMI.md file helps AI assistants understand your project"
                )
                info_lines.append(
                    "   It will be automatically loaded in future sessions"
                )

                panel = Panel(
                    "\n".join(info_lines),
                    title=success_text,
                    border_style="green",
                    padding=(1, 2),
                )
                console.print(panel)
            except Exception:
                # Fallback to simple message if we can't read the file
                console.print("✅ ", style="bold green", end="")
                console.print("[bold green]NAMI.md created successfully![/bold green]")
                console.print(f"   [dim]Location: {nami_md_path}[/dim]")
        else:
            console.print("⚠️  ", style="yellow", end="")
            console.print("[bold yellow]NAMI.md was not created[/bold yellow]")
            console.print(
                "   [dim]The agent may need additional guidance. Try running /init again.[/dim]"
            )
        console.print()

    except Exception as e:
        console.print()
        console.print("❌ ", style="red", end="")
        console.print(f"[bold red]Error during exploration:[/bold red] {e}")
        import traceback

        console.print()
        console.print("[dim]Traceback:[/dim]")
        console.print(f"[dim]{traceback.format_exc()}[/dim]")
        console.print()
    finally:
        # Restore original auto-approve setting
        session_state.auto_approve = original_auto_approve


async def _handle_mcp_command() -> bool:
    """Handle the /mcp command for MCP server management."""
    from prompt_toolkit import PromptSession

    session = PromptSession()

    console.print()
    console.print("[bold]MCP Server Management[/bold]", style=COLORS["primary"])
    console.print()

    # Show menu
    console.print("What would you like to do?", style=COLORS["primary"])
    console.print("  1. List available MCP presets")
    console.print("  2. Install a preset MCP")
    console.print("  3. Add custom MCP")
    console.print("  4. List configured MCPs")
    console.print("  5. Remove an MCP")
    console.print("  6. Cancel")
    console.print()

    choice = (await session.prompt_async("Choose (1-6): ")).strip()

    if choice == "1":
        # List presets
        presets = mcp_presets.list_presets()
        console.print()
        console.print("[bold]Available MCP Presets:[/bold]", style=COLORS["primary"])
        console.print()
        for preset_id, preset in presets.items():
            console.print(f"  • [bold]{preset_id}[/bold]", style=COLORS["primary"])
            console.print(f"    {preset['name']}", style=COLORS["dim"])
            console.print(f"    {preset['description']}", style=COLORS["dim"])
            console.print()

    elif choice == "2":
        # Install preset
        presets = mcp_presets.list_presets()
        console.print()
        console.print("[bold]Available Presets:[/bold]", style=COLORS["primary"])
        for i, (preset_id, preset) in enumerate(presets.items(), 1):
            console.print(f"  {i}. {preset['name']} ({preset_id})")
            console.print(f"     {preset['description']}", style=COLORS["dim"])

        console.print()
        preset_choice = (
            await session.prompt_async("Choose preset number (or 'cancel'): ")
        ).strip()

        if preset_choice.lower() != "cancel":
            try:
                preset_idx = int(preset_choice) - 1
                preset_items = list(presets.items())
                if 0 <= preset_idx < len(preset_items):
                    preset_id, preset = preset_items[preset_idx]

                    # Collect user inputs for configuration
                    user_inputs = {}

                    if "setup_prompt" in preset:
                        value = (
                            await session.prompt_async(f"{preset['setup_prompt']} ")
                        ).strip()
                        user_inputs[preset["setup_key"]] = value

                    if "setup_secondary_prompt" in preset:
                        value = (
                            await session.prompt_async(
                                f"{preset['setup_secondary_prompt']} "
                            )
                        ).strip()
                        user_inputs[preset["setup_secondary_key"]] = value

                    # Create config from preset
                    config = mcp_presets.create_config_from_preset(
                        preset_id, user_inputs
                    )

                    if config:
                        # Save to MCP config
                        mcp_config = MCPConfig()
                        mcp_config.add_server(preset_id, config)

                        console.print()
                        console.print(
                            f"✓ MCP '{preset['name']}' installed successfully!",
                            style=COLORS["primary"],
                        )
                        console.print(
                            f"   Configuration saved to: {mcp_config.config_path}",
                            style=COLORS["dim"],
                        )
                        console.print()
                        console.print(
                            "[dim]Restart your session for changes to take effect.[/dim]"
                        )
                else:
                    console.print()
                    console.print("[yellow]Invalid choice[/yellow]")
            except (ValueError, IndexError):
                console.print()
                console.print("[yellow]Invalid choice[/yellow]")

    elif choice == "3":
        # Add custom MCP
        console.print()
        console.print("[bold]Add Custom MCP[/bold]", style=COLORS["primary"])
        console.print()

        name = (
            await session.prompt_async("Server name (e.g., my-custom-mcp): ")
        ).strip()
        if not name:
            console.print("[yellow]Cancelled[/yellow]")
            return True

        console.print()
        console.print("Transport type:")
        console.print("  1. stdio (local command)")
        console.print("  2. HTTP (remote server)")
        transport_choice = (
            await session.prompt_async("Choose (1 or 2): ", default="1")
        ).strip()

        transport = "stdio" if transport_choice == "1" else "http"

        if transport == "stdio":
            command = (
                await session.prompt_async("Command to run (e.g., npx, python, node): ")
            ).strip()
            args_input = (
                await session.prompt_async(
                    "Arguments (space-separated, optional): ", default=""
                )
            ).strip()
            args = args_input.split() if args_input else []

            env_input = (
                await session.prompt_async(
                    "Environment variables (KEY=VALUE, comma-separated, optional): ",
                    default="",
                )
            ).strip()
            env = {}
            if env_input:
                for pair in env_input.split(","):
                    if "=" in pair:
                        key, value = pair.split("=", 1)
                        env[key.strip()] = value.strip()

            description = (
                await session.prompt_async("Description (optional): ", default="")
            ).strip()

            config = MCPServerConfig(
                transport="stdio",
                command=command,
                args=args,
                env=env,
                description=description or None,
            )
        else:
            url = (await session.prompt_async("Server URL: ")).strip()
            description = (
                await session.prompt_async("Description (optional): ", default="")
            ).strip()

            config = MCPServerConfig(
                transport="http",
                url=url,
                description=description or None,
            )

        mcp_config = MCPConfig()
        mcp_config.add_server(name, config)

        console.print()
        console.print(
            f"✓ Custom MCP '{name}' added successfully!",
            style=COLORS["primary"],
        )
        console.print(
            f"   Configuration saved to: {mcp_config.config_path}",
            style=COLORS["dim"],
        )
        console.print()
        console.print("[dim]Restart your session for changes to take effect.[/dim]")

    elif choice == "4":
        # List configured MCPs
        mcp_config = MCPConfig()
        servers = mcp_config.list_servers()

        console.print()
        if servers:
            console.print(
                "[bold]Configured MCP Servers:[/bold]", style=COLORS["primary"]
            )
            console.print()
            for name, config in servers.items():
                console.print(f"  • [bold]{name}[/bold]", style=COLORS["primary"])
                console.print(f"    Transport: {config.transport}", style=COLORS["dim"])
                if config.transport == "http":
                    console.print(f"    URL: {config.url}", style=COLORS["dim"])
                elif config.transport == "stdio":
                    console.print(f"    Command: {config.command}", style=COLORS["dim"])
                    if config.args:
                        console.print(
                            f"    Args: {' '.join(config.args)}", style=COLORS["dim"]
                        )
                if config.description:
                    console.print(f"    {config.description}", style=COLORS["dim"])
                console.print()
        else:
            console.print("[yellow]No MCP servers configured[/yellow]")
            console.print("[dim]Use /mcp to install preset or custom MCP servers[/dim]")

    elif choice == "5":
        # Remove MCP
        mcp_config = MCPConfig()
        servers = mcp_config.list_servers()

        if not servers:
            console.print()
            console.print("[yellow]No MCP servers configured[/yellow]")
            return True

        console.print()
        console.print("[bold]Configured MCPs:[/bold]", style=COLORS["primary"])
        for i, name in enumerate(servers.keys(), 1):
            console.print(f"  {i}. {name}")

        console.print()
        remove_choice = (
            await session.prompt_async("Choose MCP to remove (or 'cancel'): ")
        ).strip()

        if remove_choice.lower() != "cancel":
            try:
                remove_idx = int(remove_choice) - 1
                server_names = list(servers.keys())
                if 0 <= remove_idx < len(server_names):
                    name = server_names[remove_idx]
                    if mcp_config.remove_server(name):
                        console.print()
                        console.print(
                            f"✓ MCP '{name}' removed successfully!",
                            style=COLORS["primary"],
                        )
                        console.print()
                        console.print(
                            "[dim]Restart your session for changes to take effect.[/dim]"
                        )
                else:
                    console.print()
                    console.print("[yellow]Invalid choice[/yellow]")
            except (ValueError, IndexError):
                console.print()
                console.print("[yellow]Invalid choice[/yellow]")

    console.print()
    return True


async def _handle_model_command() -> bool:
    """Handle the /model command for LLM provider management."""
    from prompt_toolkit import PromptSession

    session = PromptSession()
    model_manager = ModelManager()

    console.print()
    console.print("[bold]Model Provider Management[/bold]", style=COLORS["primary"])
    console.print()

    # Show current model
    current = model_manager.get_current_provider()
    if current:
        provider_name, model_name = current
        console.print(
            f"[bold]Current:[/bold] {provider_name} - {model_name}",
            style=COLORS["primary"],
        )
        console.print()

    # Show menu
    console.print("What would you like to do?", style=COLORS["primary"])
    console.print("  1. View available providers")
    console.print("  2. Switch provider")
    console.print("  3. View current provider details")
    console.print("  4. Cancel")
    console.print()

    choice = (await session.prompt_async("Choose (1-4): ")).strip()

    if choice == "1":
        # List available providers
        available = model_manager.get_available_providers()
        console.print()
        console.print("[bold]Available Providers:[/bold]", style=COLORS["primary"])
        console.print()

        if not available:
            console.print("[yellow]No providers configured[/yellow]")
            console.print(
                "[dim]Configure API keys in environment variables to enable providers[/dim]"
            )
            console.print()
            console.print("[bold]Required environment variables:[/bold]")
            for provider_id, preset in MODEL_PRESETS.items():
                if preset["requires_api_key"]:
                    console.print(f"  • {preset['name']}: {preset['api_key_var']}")
        else:
            for provider_id, preset in available:
                icon = "✓" if current and preset["name"] == current[0] else " "
                console.print(
                    f"  {icon} [bold]{preset['name']}[/bold]", style=COLORS["primary"]
                )
                console.print(f"    {preset['description']}", style=COLORS["dim"])
                console.print(
                    f"    Default model: {preset['default_model']}", style=COLORS["dim"]
                )
                console.print()

    elif choice == "2":
        # Switch provider
        available = model_manager.get_available_providers()

        if not available:
            console.print()
            console.print("[yellow]No providers available[/yellow]")
            console.print("[dim]Configure API keys to enable more providers[/dim]")
            return True

        console.print()
        console.print("[bold]Available Providers:[/bold]", style=COLORS["primary"])
        for i, (provider_id, preset) in enumerate(available, 1):
            console.print(f"  {i}. {preset['name']} ({preset['default_model']})")

        console.print()
        provider_choice = (
            await session.prompt_async("Choose provider number (or 'cancel'): ")
        ).strip()

        if provider_choice.lower() != "cancel":
            try:
                provider_idx = int(provider_choice) - 1
                if 0 <= provider_idx < len(available):
                    provider_id, preset = available[provider_idx]

                    # Ask if user wants to specify a different model
                    console.print()
                    console.print(
                        f"[bold]Available models for {preset['name']}:[/bold]",
                        style=COLORS["primary"],
                    )

                    # Get models list (dynamic for Ollama, static for others)
                    if provider_id == "ollama":
                        models_list = get_ollama_models()
                        console.print(
                            f"[dim]  Found {len(models_list)} Ollama models on your system[/dim]"
                        )
                        console.print()
                    else:
                        models_list = preset["models"]

                    for i, model in enumerate(models_list, 1):
                        default_marker = (
                            " (default)" if model == preset["default_model"] else ""
                        )
                        console.print(f"  {i}. {model}{default_marker}")

                    console.print()
                    model_choice = (
                        await session.prompt_async(
                            "Choose model number (or press Enter for default): ",
                            default="",
                        )
                    ).strip()

                    model_name = None
                    if model_choice and model_choice.isdigit():
                        model_idx = int(model_choice) - 1
                        if 0 <= model_idx < len(models_list):
                            model_name = models_list[model_idx]

                    # Set the provider
                    try:
                        model_manager.set_provider(provider_id, model_name)  # type: ignore[arg-type]
                        console.print()
                        console.print(
                            f"✓ Switched to {preset['name']}!",
                            style=COLORS["primary"],
                        )
                        console.print()
                        console.print(
                            "[green]✓ Configuration saved to ~/.nami/nami.config.json[/green]"
                        )
                        console.print()
                        console.print(
                            "[yellow]⚠ Note: Model change will take effect after restarting the CLI[/yellow]"
                        )
                        console.print(
                            "[dim]The saved configuration will be loaded automatically on next start[/dim]"
                        )
                    except ValueError as e:
                        console.print()
                        console.print(f"[bold red]Error:[/bold red] {e}")
                else:
                    console.print()
                    console.print("[yellow]Invalid choice[/yellow]")
            except (ValueError, IndexError):
                console.print()
                console.print("[yellow]Invalid choice[/yellow]")

    elif choice == "3":
        # View current provider details
        console.print()
        if current:
            provider_name, model_name = current
            console.print(
                f"[bold]Current Provider:[/bold] {provider_name}",
                style=COLORS["primary"],
            )
            console.print(
                f"[bold]Current Model:[/bold] {model_name}", style=COLORS["primary"]
            )
            console.print()

            # Find preset info
            for provider_id, preset in MODEL_PRESETS.items():
                if preset["name"] == provider_name:
                    console.print(f"[bold]Description:[/bold] {preset['description']}")
                    console.print()
                    console.print("[bold]Available models:[/bold]")
                    for model in preset["models"]:
                        current_marker = " (current)" if model == model_name else ""
                        console.print(
                            f"  • {model}{current_marker}", style=COLORS["dim"]
                        )
                    break
        else:
            console.print("[yellow]No provider currently active[/yellow]")
        console.print()

    console.print()
    return True


async def _handle_context_command(token_tracker: TokenTracker) -> bool:
    """Handle the /context command to display detailed context usage.

    Args:
        token_tracker: The token tracker instance

    Returns:
        True (command always handled)
    """
    token_tracker.display_context()
    return True


async def _handle_sessions_command(session_state) -> bool:
    """Handle the /sessions command - list, select, delete sessions.

    Args:
        session_state: Current session state

    Returns:
        True (command always handled)
    """
    from prompt_toolkit import PromptSession
    from .session_persistence import SessionManager
    from .session_restore import format_session_age

    ps = PromptSession()
    session_manager = SessionManager()

    console.print()
    console.print("[bold]Session Management[/bold]", style=COLORS["primary"])
    console.print()

    # Show current session if any
    if session_state.session_id:
        console.print(
            f"[bold]Current session:[/bold] {session_state.session_id[:8]}...",
            style=COLORS["primary"],
        )
        console.print()

    # Show menu
    console.print("What would you like to do?", style=COLORS["primary"])
    console.print("  1. List saved sessions")
    console.print("  2. Delete a session")
    console.print("  3. Cancel")
    console.print()

    choice = (await ps.prompt_async("Choose (1-3): ")).strip()

    if choice == "1":
        # List sessions
        sessions = session_manager.list_sessions(limit=20)

        console.print()
        if sessions:
            console.print("[bold]Saved Sessions:[/bold]", style=COLORS["primary"])
            console.print()
            for meta in sessions:
                age = format_session_age(meta.last_active)
                project = (
                    Path(meta.project_root).name if meta.project_root else "no project"
                )
                model = meta.model_name or "unknown model"

                # Mark current session
                is_current = session_state.session_id == meta.session_id
                marker = " ← current" if is_current else ""

                console.print(
                    f"  • [bold]{meta.session_id[:8]}[/bold]{marker}",
                    style=COLORS["primary"],
                )
                console.print(
                    f"    {project} ({model}), {meta.message_count} messages",
                    style=COLORS["dim"],
                )
                console.print(f"    {age}", style=COLORS["dim"])
                console.print()
        else:
            console.print("[yellow]No saved sessions found[/yellow]")
            console.print("[dim]Sessions are saved automatically on exit[/dim]")

    elif choice == "2":
        # Delete session
        sessions = session_manager.list_sessions(limit=20)

        if not sessions:
            console.print()
            console.print("[yellow]No sessions to delete[/yellow]")
            return True

        console.print()
        console.print("[bold]Select session to delete:[/bold]", style=COLORS["primary"])
        for i, meta in enumerate(sessions, 1):
            age = format_session_age(meta.last_active)
            project = (
                Path(meta.project_root).name if meta.project_root else "no project"
            )
            console.print(f"  {i}. {meta.session_id[:8]} - {project} ({age})")

        console.print()
        delete_choice = (
            await ps.prompt_async("Choose session number (or 'cancel'): ")
        ).strip()

        if delete_choice.lower() != "cancel":
            try:
                delete_idx = int(delete_choice) - 1
                if 0 <= delete_idx < len(sessions):
                    meta = sessions[delete_idx]

                    # Confirm deletion
                    confirm = (
                        (
                            await ps.prompt_async(
                                f"Delete session {meta.session_id[:8]}? (y/N): ",
                                default="n",
                            )
                        )
                        .strip()
                        .lower()
                    )

                    if confirm == "y":
                        if session_manager.delete_session(meta.session_id):
                            console.print()
                            console.print(
                                f"✓ Session {meta.session_id[:8]} deleted",
                                style=COLORS["primary"],
                            )
                        else:
                            console.print()
                            console.print("[red]Failed to delete session[/red]")
                    else:
                        console.print()
                        console.print("[yellow]Cancelled[/yellow]")
                else:
                    console.print()
                    console.print("[yellow]Invalid choice[/yellow]")
            except (ValueError, IndexError):
                console.print()
                console.print("[yellow]Invalid choice[/yellow]")

    console.print()
    return True


async def _handle_save_command(
    agent,
    session_state,
    assistant_id: str,
    session_manager=None,
    model_name: str | None = None,
) -> bool:
    """Handle the /save command - manually save current session.

    Args:
        agent: The LangGraph agent
        session_state: Current session state
        assistant_id: Agent identifier
        session_manager: Session manager instance
        model_name: Name of the model being used

    Returns:
        True (command always handled)
    """
    if session_manager is None:
        from .session_persistence import SessionManager

        session_manager = SessionManager()

    console.print()

    try:
        # Get current messages from agent state
        config = {"configurable": {"thread_id": session_state.thread_id}}
        state = await agent.aget_state(config)
        messages = state.values.get("messages", [])

        if not messages:
            console.print("[yellow]No conversation to save yet[/yellow]")
            console.print()
            return True

        # Generate session_id if not set
        import uuid

        if not session_state.session_id:
            session_state.session_id = str(uuid.uuid4())

        # Get project root
        project_root = Path.cwd()

        # Save the session
        session_manager.save_session(
            session_id=session_state.session_id,
            thread_id=session_state.thread_id,
            messages=messages,
            assistant_id=assistant_id,
            todos=session_state.todos,
            model_name=model_name,
            project_root=project_root,
        )

        console.print(
            f"✓ Session saved: {session_state.session_id[:8]}...",
            style=COLORS["primary"],
        )
        console.print(f"  [dim]{len(messages)} messages saved[/dim]")
        console.print(f"  [dim]Use 'nami --continue' to resume this session[/dim]")

    except Exception as e:
        console.print(f"[red]Failed to save session: {e}[/red]")

    console.print()
    return True


async def _handle_compact_command(
    agent,
    session_state,
    token_tracker: TokenTracker,
    focus_instructions: str | None = None,
) -> bool:
    """Handle the /compact command to summarize conversation history.

    Args:
        agent: The LangGraph agent
        session_state: Current session state
        token_tracker: Token tracker instance
        focus_instructions: Optional user instructions (e.g., "Focus on X and Y")

    Returns:
        True (command always handled)
    """
    from namicode_cli.compaction import compact_conversation
    from namicode_cli.config import create_model

    console.print()
    console.print("[bold]Compacting Conversation[/bold]", style=COLORS["primary"])
    console.print()

    # Get the model for summarization
    model = create_model()

    with console.status("[bold]Summarizing conversation...[/bold]", spinner="dots"):
        result = await compact_conversation(
            agent=agent,
            model=model,
            thread_id=session_state.thread_id,
            focus_instructions=focus_instructions,
        )

    if result.success:
        console.print("[green]✓[/green] ", end="")
        console.print("[green]Conversation compacted successfully![/green]")
        console.print()

        # Show statistics
        console.print(
            f"  [dim]Messages: {result.messages_before} → {result.messages_after}[/dim]"
        )
        console.print(f"  [dim]Tokens saved: ~{result.tokens_saved:,}[/dim]")
        console.print()

        # Show summary preview (first 500 chars)
        console.print("[bold]Summary Preview:[/bold]", style=COLORS["primary"])
        preview = result.summary[:500]
        if len(result.summary) > 500:
            preview += "..."
        console.print(f"[dim]{preview}[/dim]")
        console.print()

        # Reset token tracker counters
        token_tracker.reset()

    else:
        console.print("[red]✗[/red] ", end="")
        console.print(f"[red]Compaction failed: {result.error}[/red]")
        console.print()

    return True


async def _handle_servers_command(session_state) -> bool:
    """Handle /servers - list and manage dev servers.

    Args:
        session_state: Current session state

    Returns:
        True (command always handled)
    """
    from prompt_toolkit import PromptSession
    import webbrowser

    ps = PromptSession()

    console.print()
    console.print("[bold]Dev Server Management[/bold]", style=COLORS["primary"])
    console.print()

    # Get running servers
    servers = list_servers()

    if not servers:
        console.print("[yellow]No dev servers running[/yellow]")
        console.print("[dim]Use the start_dev_server tool to start a server[/dim]")
        console.print()
        return True

    # Display servers in a table
    table = Table(show_header=True, header_style="bold")
    table.add_column("PID", style="dim")
    table.add_column("Name")
    table.add_column("URL")
    table.add_column("Status")
    table.add_column("Command", style="dim")

    for server in servers:
        status_style = "green" if server.status.value == "healthy" else "yellow"
        table.add_row(
            str(server.pid),
            server.name,
            server.url,
            f"[{status_style}]{server.status.value}[/{status_style}]",
            server.command[:40] + "..." if len(server.command) > 40 else server.command,
        )

    console.print(table)
    console.print()

    # Show menu
    console.print("What would you like to do?", style=COLORS["primary"])
    console.print("  1. Open server in browser")
    console.print("  2. Stop a server")
    console.print("  3. Stop all servers")
    console.print("  4. Cancel")
    console.print()

    choice = (await ps.prompt_async("Choose (1-4): ")).strip()

    if choice == "1":
        # Open in browser
        if len(servers) == 1:
            webbrowser.open(servers[0].url)
            console.print(f"[green]✓ Opened {servers[0].url} in browser[/green]")
        else:
            console.print()
            console.print(
                "[bold]Select server to open:[/bold]", style=COLORS["primary"]
            )
            for i, server in enumerate(servers, 1):
                console.print(f"  {i}. {server.name} ({server.url})")
            console.print()
            server_choice = (await ps.prompt_async("Choose server number: ")).strip()
            try:
                idx = int(server_choice) - 1
                if 0 <= idx < len(servers):
                    webbrowser.open(servers[idx].url)
                    console.print(
                        f"[green]✓ Opened {servers[idx].url} in browser[/green]"
                    )
                else:
                    console.print("[yellow]Invalid choice[/yellow]")
            except ValueError:
                console.print("[yellow]Invalid choice[/yellow]")

    elif choice == "2":
        # Stop a server
        if len(servers) == 1:
            result = await stop_server(pid=servers[0].pid)
            if result:
                console.print(
                    f"[green]✓ Stopped server '{servers[0].name}' (PID: {servers[0].pid})[/green]"
                )
            else:
                console.print("[red]Failed to stop server[/red]")
        else:
            console.print()
            console.print(
                "[bold]Select server to stop:[/bold]", style=COLORS["primary"]
            )
            for i, server in enumerate(servers, 1):
                console.print(f"  {i}. {server.name} (PID: {server.pid})")
            console.print()
            server_choice = (await ps.prompt_async("Choose server number: ")).strip()
            try:
                idx = int(server_choice) - 1
                if 0 <= idx < len(servers):
                    result = await stop_server(pid=servers[idx].pid)
                    if result:
                        console.print(
                            f"[green]✓ Stopped server '{servers[idx].name}'[/green]"
                        )
                    else:
                        console.print("[red]Failed to stop server[/red]")
                else:
                    console.print("[yellow]Invalid choice[/yellow]")
            except ValueError:
                console.print("[yellow]Invalid choice[/yellow]")

    elif choice == "3":
        # Stop all servers
        manager = ProcessManager.get_instance()
        count = await manager.stop_all()
        console.print(f"[green]✓ Stopped {count} server(s)[/green]")

    console.print()
    return True


async def _handle_tests_command(session_state, cmd_args: str | None = None) -> bool:
    """Handle /tests - run project tests.

    Args:
        session_state: Current session state
        cmd_args: Optional test command arguments

    Returns:
        True (command always handled)
    """
    console.print()
    console.print("[bold]Running Tests[/bold]", style=COLORS["primary"])
    console.print()

    working_dir = str(Path.cwd())

    # Detect framework if no command specified
    if not cmd_args:
        framework = detect_test_framework(working_dir)
        command = get_default_test_command(framework)

        if not command:
            console.print("[yellow]Could not auto-detect test framework[/yellow]")
            console.print(
                "[dim]Specify a command: /tests pytest or /tests npm test[/dim]"
            )
            console.print()
            return True

        console.print(f"[dim]Detected framework: {framework.value}[/dim]")
        console.print(f"[dim]Running: {command}[/dim]")
    else:
        command = cmd_args.strip()
        console.print(f"[dim]Running: {command}[/dim]")

    console.print()

    # Stream output callback
    def output_callback(line: str) -> None:
        console.print(f"[dim]{line}[/dim]", markup=False)

    # Run tests with streaming output
    result = await run_tests(
        command=command,
        working_dir=working_dir,
        output_callback=output_callback,
    )

    console.print()

    # Show summary
    if result.success:
        console.print("[green]✓ Tests passed![/green]")
    else:
        console.print("[red]✗ Tests failed[/red]")

    # Show statistics if available
    stats_parts = []
    if result.tests_run is not None:
        stats_parts.append(f"{result.tests_run} tests")
    if result.tests_passed is not None:
        stats_parts.append(f"{result.tests_passed} passed")
    if result.tests_failed is not None:
        stats_parts.append(f"{result.tests_failed} failed")
    if result.duration_seconds is not None:
        stats_parts.append(f"{result.duration_seconds:.2f}s")

    if stats_parts:
        console.print(f"[dim]{', '.join(stats_parts)}[/dim]")

    if result.error:
        console.print(f"[red]Error: {result.error}[/red]")

    console.print()
    return True


async def _handle_kill_command(session_state, cmd_args: str | None = None) -> bool:
    """Handle /kill - kill a running process by PID or name.

    Args:
        session_state: Current session state
        cmd_args: Optional PID or name to kill

    Returns:
        True (command always handled)
    """
    from prompt_toolkit import PromptSession

    ps = PromptSession()
    manager = ProcessManager.get_instance()

    console.print()

    # If argument provided, try to kill directly
    if cmd_args:
        arg = cmd_args.strip()

        # Try as PID first
        try:
            pid = int(arg)
            result = await manager.stop_process(pid)
            if result:
                console.print(f"[green]✓ Killed process {pid}[/green]")
            else:
                console.print(f"[yellow]No process found with PID {pid}[/yellow]")
            console.print()
            return True
        except ValueError:
            pass

        # Try as name
        result = await manager.stop_by_name(arg)
        if result:
            console.print(f"[green]✓ Killed process '{arg}'[/green]")
        else:
            console.print(f"[yellow]No process found with name '{arg}'[/yellow]")
        console.print()
        return True

    # No argument - show list and let user choose
    processes = manager.list_processes(alive_only=True)

    if not processes:
        console.print("[yellow]No managed processes running[/yellow]")
        console.print()
        return True

    console.print("[bold]Running Processes[/bold]", style=COLORS["primary"])
    console.print()

    for i, info in enumerate(processes, 1):
        port_info = f" (port {info.port})" if info.port else ""
        console.print(f"  {i}. [{info.pid}] {info.name}{port_info}")
        console.print(
            f"     [dim]{info.command[:60]}...[/dim]"
            if len(info.command) > 60
            else f"     [dim]{info.command}[/dim]"
        )

    console.print()
    choice = (await ps.prompt_async("Enter number to kill (or 'cancel'): ")).strip()

    if choice.lower() == "cancel":
        console.print("[dim]Cancelled[/dim]")
        console.print()
        return True

    try:
        idx = int(choice) - 1
        if 0 <= idx < len(processes):
            info = processes[idx]
            result = await manager.stop_process(info.pid)
            if result:
                console.print(
                    f"[green]✓ Killed '{info.name}' (PID: {info.pid})[/green]"
                )
            else:
                console.print("[red]Failed to kill process[/red]")
        else:
            console.print("[yellow]Invalid choice[/yellow]")
    except ValueError:
        console.print("[yellow]Invalid choice[/yellow]")

    console.print()
    return True


async def _handle_skills_command(cmd_args: str | None, assistant_id: str) -> bool:
    """Handle the /skills command with interactive menu.

    Args:
        cmd_args: Optional subcommand (create/list) or skill name
        assistant_id: Agent identifier for skill storage

    Returns:
        True (command always handled)
    """
    from prompt_toolkit import PromptSession

    from .skills.commands import (
        _generate_skill_with_scripts,
        _get_static_template,
        _validate_name,
    )
    from .skills.load import list_skills

    settings = Settings.from_environment()
    ps = PromptSession()

    console.print()
    console.print("[bold]Skills Manager[/bold]", style=COLORS["primary"])
    console.print()

    # Check if a subcommand was provided
    action = None
    extra_args = None

    if cmd_args:
        parts = cmd_args.strip().split(maxsplit=1)
        first_arg = parts[0].lower()
        extra_args = parts[1] if len(parts) > 1 else None

        if first_arg in ("create", "new", "add"):
            action = "create"
        elif first_arg in ("list", "ls", "show"):
            action = "list"
        else:
            # Assume it's a skill name for creation
            action = "create"
            extra_args = cmd_args.strip()

    # If no action, show menu
    if not action:
        console.print("  1. Create a new skill")
        console.print("  2. List available skills")
        console.print()

        choice = (await ps.prompt_async("Choose (1-2, or 'cancel'): ")).strip()

        if choice.lower() in ("cancel", "c", "q"):
            console.print("[dim]Cancelled[/dim]")
            console.print()
            return True

        if choice == "1":
            action = "create"
        elif choice == "2":
            action = "list"
        else:
            console.print("[yellow]Invalid choice[/yellow]")
            console.print()
            return True

    # Handle LIST action
    if action == "list":
        return await _skills_list_interactive(ps, settings, assistant_id)

    # Handle CREATE action
    return await _skills_create_interactive(ps, settings, assistant_id, extra_args)


async def _skills_list_interactive(ps, settings, assistant_id: str) -> bool:
    """List skills interactively with scope selection.

    Args:
        ps: PromptSession instance
        settings: Settings instance
        assistant_id: Agent identifier

    Returns:
        True (always handled)
    """
    from .skills.load import list_skills

    console.print()
    console.print("[bold]List Skills[/bold]", style=COLORS["primary"])
    console.print()

    # Ask for scope
    in_project = settings.project_root is not None

    if in_project:
        console.print("  1. Global skills (shared across projects)")
        console.print("  2. Project skills (current project only)")
        console.print("  3. Both")
        console.print()

        choice = (await ps.prompt_async("Choose (1-3, default=3): ")).strip() or "3"

        if choice == "1":
            scope = "global"
        elif choice == "2":
            scope = "project"
        else:
            scope = "both"
    else:
        scope = "global"
        console.print("[dim]Not in a project directory. Showing global skills.[/dim]")

    console.print()

    # Get skills based on scope
    user_skills_dir = settings.ensure_user_skills_dir(assistant_id)
    project_skills_dir = settings.get_project_skills_dir() if in_project else None

    if scope == "global":
        skills = list_skills(user_skills_dir=user_skills_dir, project_skills_dir=None)
    elif scope == "project":
        skills = list_skills(
            user_skills_dir=None, project_skills_dir=project_skills_dir
        )
    else:
        skills = list_skills(
            user_skills_dir=user_skills_dir, project_skills_dir=project_skills_dir
        )

    if not skills:
        console.print("[yellow]No skills found.[/yellow]")
        console.print(
            "[dim]Use '/skills create' or '/skills' → 1 to create a new skill.[/dim]"
        )
        console.print()
        return True

    # Group by source
    global_skills = [s for s in skills if s["source"] == "user"]
    project_skills = [s for s in skills if s["source"] == "project"]

    if global_skills and scope in ("global", "both"):
        console.print("[bold cyan]Global Skills:[/bold cyan]")
        for skill in global_skills:
            console.print(f"  • [bold]{skill['name']}[/bold]")
            console.print(f"    [dim]{skill['description']}[/dim]")
        console.print()

    if project_skills and scope in ("project", "both"):
        console.print("[bold green]Project Skills:[/bold green]")
        for skill in project_skills:
            console.print(f"  • [bold]{skill['name']}[/bold]")
            console.print(f"    [dim]{skill['description']}[/dim]")
        console.print()

    total = len(global_skills) + len(project_skills)
    console.print(f"[dim]Total: {total} skill(s)[/dim]")
    console.print()
    return True


async def _agents_list(settings) -> bool:
    """List all available custom agents from both global and project scopes.

    Args:
        settings: Settings instance

    Returns:
        True (always handled)
    """
    console.print()
    console.print("[bold]Available Agents:[/bold]", style=COLORS["primary"])
    console.print()

    # Get all agents from both scopes using the new Settings method
    all_agents = settings.get_all_agents()

    if not all_agents:
        console.print("[yellow]No agents found.[/yellow]")
        console.print("[dim]Use '/agents' to create a new agent.[/dim]")
        console.print()
        return True

    # Separate by scope
    global_agents = []
    project_agents = []

    for agent_name, agent_dir, scope in all_agents:
        agent_md = agent_dir / "agent.md"
        # Read first non-empty line for description
        try:
            content = agent_md.read_text(encoding="utf-8")
            lines = content.split("\n")
            description = ""
            for line in lines:
                line = line.strip()
                if line and not line.startswith("#"):
                    description = line[:80]
                    if len(line) > 80:
                        description += "..."
                    break
        except Exception:
            description = "[unable to read]"

        if scope == "project":
            project_agents.append((agent_name, description, agent_dir))
        else:
            global_agents.append((agent_name, description, agent_dir))

    # Display project agents first (they take precedence)
    if project_agents:
        console.print("[bold green]Project Agents:[/bold green]")
        console.print("[dim](Only available in this project)[/dim]")
        console.print()
        for name, description, _agent_dir in sorted(project_agents):
            console.print(f"  @[bold]{name}[/bold]", style=COLORS["primary"])
            if description:
                console.print(f"    [dim]{description}[/dim]")
        console.print()

    # Display global agents
    if global_agents:
        console.print("[bold cyan]Global Agents:[/bold cyan]")
        console.print("[dim](Available in all projects)[/dim]")
        console.print()
        for name, description, _agent_dir in sorted(global_agents):
            # Check if this global agent is shadowed by a project agent
            is_shadowed = any(pa[0] == name for pa in project_agents)
            if is_shadowed:
                console.print(
                    f"  @[bold]{name}[/bold] [dim](shadowed by project agent)[/dim]",
                    style=COLORS["primary"],
                )
            else:
                console.print(f"  @[bold]{name}[/bold]", style=COLORS["primary"])
            if description:
                console.print(f"    [dim]{description}[/dim]")
        console.print()

    total = len(global_agents) + len(project_agents)
    console.print(f"[dim]Total: {total} agent(s)[/dim]")
    console.print("[dim]Use @<agent_name> <query> to invoke an agent.[/dim]")
    console.print()
    return True


async def _agents_create_interactive(ps, settings) -> bool:
    """Create a new custom agent interactively.

    Args:
        ps: PromptSession instance
        settings: Settings instance

    Returns:
        True (always handled)
    """
    console.print()
    console.print("[bold]Create New Agent[/bold]", style=COLORS["primary"])
    console.print()

    console.print(
        "[dim]Agents are specialized AI assistants with custom system prompts.[/dim]"
    )
    console.print(
        "[dim]Examples: code-reviewer, debugger, architect, documentation-writer[/dim]"
    )
    console.print()

    # Get agent name
    agent_name = (await ps.prompt_async("Agent name: ")).strip()

    if not agent_name:
        console.print("[yellow]Cancelled - no agent name provided[/yellow]")
        console.print()
        return True

    # Validate agent name
    if not settings._is_valid_agent_name(agent_name):
        console.print("[red]Invalid agent name.[/red]")
        console.print(
            "[dim]Use only letters, numbers, hyphens, underscores, and spaces.[/dim]"
        )
        console.print()
        return True

    # Ask for scope (global vs project)
    in_project = settings.project_root is not None
    use_project = False

    if in_project:
        console.print()
        console.print("[bold]Where should this agent be stored?[/bold]")
        console.print("  1. Global (available in all projects)")
        console.print("  2. Project (only available in this project)")
        console.print()
        scope_choice = (
            await ps.prompt_async("Scope (1-2, default=1): ")
        ).strip() or "1"
        use_project = scope_choice == "2"

    # Determine target directory based on scope
    if use_project:
        agents_dir = settings.ensure_project_agents_dir()
        if not agents_dir:
            console.print("[red]Error: Not in a project directory.[/red]")
            console.print()
            return True
        agent_dir = agents_dir / agent_name
        scope_label = "project"
    else:
        agent_dir = settings.get_agents_root_dir() / agent_name
        scope_label = "global"

    # Check if agent already exists in the chosen scope
    if agent_dir.exists():
        console.print(
            f"[yellow]Agent '{agent_name}' already exists at {agent_dir}[/yellow]"
        )
        console.print()
        return True

    # Also warn if agent exists in the other scope
    if use_project:
        global_agent_dir = settings.get_agents_root_dir() / agent_name
        if global_agent_dir.exists():
            console.print(
                f"[dim]Note: A global agent with the same name exists at {global_agent_dir}[/dim]"
            )
            console.print(
                "[dim]The project agent will take precedence when invoked from this project.[/dim]"
            )
            console.print()
    else:
        project_agents_dir = settings.get_project_agents_dir()
        if project_agents_dir:
            project_agent_dir = project_agents_dir / agent_name
            if project_agent_dir.exists():
                console.print(
                    f"[dim]Note: A project agent with the same name exists at {project_agent_dir}[/dim]"
                )
                console.print(
                    "[dim]The project agent will take precedence when invoked from this project.[/dim]"
                )
                console.print()

    # Get description
    console.print()
    console.print("[dim]Describe what this agent specializes in:[/dim]")
    description = (await ps.prompt_async("Description: ")).strip()

    if not description:
        console.print("[yellow]Cancelled - no description provided[/yellow]")
        console.print()
        return True

    # Generate system prompt using LLM
    console.print()
    console.print("[dim]Generating system prompt...[/dim]")

    system_prompt = await _generate_agent_system_prompt(agent_name, description)

    if not system_prompt:
        console.print("[red]Failed to generate system prompt.[/red]")
        console.print()
        return True

    # Create agent directory and file
    agent_dir.mkdir(parents=True, exist_ok=True)
    agent_md = agent_dir / "agent.md"
    agent_md.write_text(system_prompt, encoding="utf-8")

    console.print()
    console.print(
        f"[green]Agent '{agent_name}' created successfully! ({scope_label})[/green]"
    )
    console.print(f"[dim]Location: {agent_dir}[/dim]")
    console.print()
    console.print("[dim]Use @" + agent_name + " <query> to invoke this agent.[/dim]")
    console.print()
    return True


async def _agents_delete_interactive(ps, settings) -> bool:
    """Delete an existing agent from either global or project scope.

    Args:
        ps: PromptSession instance
        settings: Settings instance

    Returns:
        True (always handled)
    """
    import shutil

    console.print()
    console.print("[bold]Delete Agent[/bold]", style=COLORS["primary"])
    console.print()

    # Get all agents from both scopes
    all_agents = settings.get_all_agents()

    if not all_agents:
        console.print("[yellow]No agents found.[/yellow]")
        console.print()
        return True

    # Separate by scope for display
    project_agents = [
        (name, path) for name, path, scope in all_agents if scope == "project"
    ]
    global_agents = [
        (name, path) for name, path, scope in all_agents if scope == "global"
    ]

    # Build a combined list with scope labels
    agents_list: list[tuple[str, Path, str]] = []

    console.print("[bold]Available agents:[/bold]", style=COLORS["primary"])
    console.print()

    idx = 1
    if project_agents:
        console.print("[green]Project agents:[/green]")
        for name, path in sorted(project_agents):
            console.print(f"  {idx}. {name}")
            agents_list.append((name, path, "project"))
            idx += 1
        console.print()

    if global_agents:
        console.print("[cyan]Global agents:[/cyan]")
        for name, path in sorted(global_agents):
            console.print(f"  {idx}. {name}")
            agents_list.append((name, path, "global"))
            idx += 1
        console.print()

    choice = (
        await ps.prompt_async("Choose agent number to delete (or 'cancel'): ")
    ).strip()

    if choice.lower() == "cancel":
        console.print("[dim]Cancelled[/dim]")
        console.print()
        return True

    try:
        idx = int(choice) - 1
        if 0 <= idx < len(agents_list):
            agent_name, agent_dir, scope = agents_list[idx]
            scope_label = "project" if scope == "project" else "global"

            # Confirm deletion
            confirm = (
                (
                    await ps.prompt_async(
                        f"Delete {scope_label} agent '{agent_name}'? This cannot be undone. (y/N): ",
                        default="n",
                    )
                )
                .strip()
                .lower()
            )

            if confirm == "y":
                shutil.rmtree(agent_dir)
                console.print()
                console.print(
                    f"[green]{scope_label.capitalize()} agent '{agent_name}' deleted.[/green]"
                )
            else:
                console.print()
                console.print("[dim]Cancelled[/dim]")
        else:
            console.print()
            console.print("[yellow]Invalid choice[/yellow]")
    except (ValueError, IndexError):
        console.print()
        console.print("[yellow]Invalid choice[/yellow]")

    console.print()
    return True


def invoke_subagent(
    agent_name: str, settings: Settings, backend=None
) -> tuple[Pregel, CompositeBackend]:
    """Invoke a custom agent as an isolated subagent using the deepagents SubAgent pattern.

    This follows the LangGraph subagent architecture where:
    - Each subagent has its own isolated execution environment
    - Subagents are configured with their own system prompt and tools
    - Subagents get the SAME tools as the main agent (filesystem, shell, web, etc.)
    - Results return to the main agent for reconciliation
    - UI observability shows tool calls as they happen (like main agent)

    Args:
        agent_name: Name of the agent to invoke
        query: The task/query for the agent
        main_agent: Reference to main agent (kept for API consistency)
        settings: Settings instance
        session_state: Current session state (reserved for future state access)
        backend: Optional backend for filesystem operations (CompositeBackend)

    Returns:
        Agent's response/result as string
    """

    from namicode_cli.config import create_model
    from namicode_cli.tools import fetch_url, http_request, web_search
    from namicode_cli.dev_server import (
        list_servers_tool,
        start_dev_server_tool,
        stop_server_tool,
    )
    from namicode_cli.test_runner import run_tests_tool
    from namicode_cli.config import settings as global_settings

    tools = [
        http_request,
        fetch_url,
        run_tests_tool,
        start_dev_server_tool,
        stop_server_tool,
        list_servers_tool,
    ]
    if global_settings.has_tavily:
        tools.append(web_search)

    subagent, subagent_backend = create_subagent(
        agent_name=agent_name,
        tools=tools,
        model=create_model(),
        settings=settings,
        backend=backend,
    )

    return subagent, subagent_backend


async def _generate_agent_system_prompt(
    agent_name: str, description: str
) -> str | None:
    """Generate a full system prompt for a custom agent using the configured LLM.

    Args:
        agent_name: Name of the agent
        description: Description of what the agent specializes in

    Returns:
        Generated system prompt, or None if generation failed
    """
    from namicode_cli.config import create_model

    try:
        model = create_model()

        generation_prompt = f"""Generate a comprehensive system prompt for an AI coding assistant agent named "{agent_name}".

Agent Description: {description}

Create a detailed system prompt that includes:

1. **Core Identity**: A clear statement of who this agent is and what they specialize in.

2. **Expertise Areas**: 3-5 specific domains or skills this agent excels at.

3. **Communication Style**: How this agent should communicate (tone, verbosity, format preferences).

4. **Working Guidelines**: Step-by-step approach this agent should follow when handling requests.

5. **Tool Usage**: Guidelines for how this agent should use available tools (file reading, editing, searching, web browsing, etc.).

6. **Best Practices**: Domain-specific best practices this agent should follow.

7. **Example Interactions**: 2-3 brief examples of how this agent would handle typical requests.

Format the output as a clean markdown document that can be used directly as a system prompt.
Start with a header: # {agent_name} - AI Assistant

Keep the prompt focused and actionable. Aim for 300-500 words."""

        response = await model.ainvoke(generation_prompt)

        if hasattr(response, "content"):
            content = response.content
            if isinstance(content, str):
                return content
            elif isinstance(content, list):
                # Handle list of content blocks
                return "".join(str(c) for c in content)
        return str(response)

    except Exception as e:
        console.print(f"[red]Error generating prompt: {e}[/red]")
        return None


async def _handle_agents_command(
    cmd_args: str | None, assistant_id: str
) -> bool:  # noqa: ARG001
    """Handle the /agents command with interactive menu.

    Args:
        cmd_args: Optional subcommand (view/create/delete)
        assistant_id: Agent identifier (unused but kept for consistency with other handlers)

    Returns:
        True (command always handled)
    """
    from prompt_toolkit import PromptSession

    settings = Settings.from_environment()
    ps = PromptSession()

    console.print()
    console.print("[bold]Agents Manager[/bold]", style=COLORS["primary"])
    console.print()

    # Check if a subcommand was provided
    action = None

    if cmd_args:
        first_arg = cmd_args.strip().lower()

        if first_arg in ("view", "list", "ls", "show"):
            action = "view"
        elif first_arg in ("create", "new", "add"):
            action = "create"
        elif first_arg in ("delete", "remove", "rm"):
            action = "delete"

    # If no action, show menu
    if not action:
        console.print("  1. View agents")
        console.print("  2. Create a new agent")
        console.print("  3. Delete an agent")
        console.print()

        choice = (await ps.prompt_async("Choose (1-3, or 'cancel'): ")).strip()

        if choice.lower() in ("cancel", "c", "q"):
            console.print("[dim]Cancelled[/dim]")
            console.print()
            return True

        if choice == "1":
            action = "view"
        elif choice == "2":
            action = "create"
        elif choice == "3":
            action = "delete"
        else:
            console.print("[yellow]Invalid choice[/yellow]")
            console.print()
            return True

    # Handle actions
    if action == "view":
        return await _agents_list(settings)
    elif action == "create":
        return await _agents_create_interactive(ps, settings)
    elif action == "delete":
        return await _agents_delete_interactive(ps, settings)

    return True


async def _skills_create_interactive(
    ps, settings, assistant_id: str, skill_name: str | None
) -> bool:
    """Create a skill interactively.

    Args:
        ps: PromptSession instance
        settings: Settings instance
        assistant_id: Agent identifier
        skill_name: Optional pre-provided skill name

    Returns:
        True (always handled)
    """
    from .skills.commands import (
        _generate_skill_with_scripts,
        _get_static_template,
        _validate_name,
    )

    console.print()
    console.print("[bold]Create New Skill[/bold]", style=COLORS["primary"])
    console.print()

    # Get skill name if not provided
    if not skill_name:
        console.print(
            "[dim]Skills are reusable workflows that guide the agent for specific tasks.[/dim]"
        )
        console.print(
            "[dim]Examples: web-research, code-review, docker-deploy, api-testing[/dim]"
        )
        console.print()
        skill_name = (await ps.prompt_async("Skill name: ")).strip()

    if not skill_name:
        console.print("[yellow]Cancelled - no skill name provided[/yellow]")
        console.print()
        return True

    # Validate skill name
    is_valid, error_msg = _validate_name(skill_name)
    if not is_valid:
        console.print(f"[red]Invalid skill name: {error_msg}[/red]")
        console.print("[dim]Use only letters, numbers, hyphens, and underscores.[/dim]")
        console.print()
        return True

    # Ask for description
    console.print()
    console.print(
        "[dim]Describe what this skill should do (or press Enter to auto-generate):[/dim]"
    )
    description = (await ps.prompt_async("Description: ")).strip()

    # Ask for scope
    in_project = settings.project_root is not None

    if in_project:
        console.print()
        console.print("  1. Global (available in all projects)")
        console.print("  2. Project (only in this project)")
        console.print()
        scope_choice = (
            await ps.prompt_async("Scope (1-2, default=1): ")
        ).strip() or "1"
        use_project = scope_choice == "2"
    else:
        use_project = False

    # Determine target directory
    if use_project:
        skills_dir = settings.ensure_project_skills_dir()
    else:
        skills_dir = settings.ensure_user_skills_dir(assistant_id)

    skill_dir = skills_dir / skill_name

    if skill_dir.exists():
        console.print(
            f"[yellow]Skill '{skill_name}' already exists at {skill_dir}[/yellow]"
        )
        console.print()
        return True

    # Create skill directory
    skill_dir.mkdir(parents=True, exist_ok=True)

    # Generate content with LLM (includes web search for context)
    console.print()

    # Generate skill content and scripts using the new unified function
    content, scripts = _generate_skill_with_scripts(
        skill_name, description if description else None
    )

    if content is None:
        content = _get_static_template(skill_name)
        scripts = []
        used_llm = False
    else:
        used_llm = True

    # Write the skill file
    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text(content, encoding="utf-8")

    # Write supporting scripts
    scripts_written = []
    for script in scripts:
        if not isinstance(script, dict):
            continue
        filename = script.get("filename", "")
        script_content = script.get("content", "")
        if filename and script_content:
            # Validate filename to prevent path traversal
            if "/" in filename or "\\" in filename or ".." in filename:
                continue
            script_path = skill_dir / filename
            script_path.write_text(script_content, encoding="utf-8")
            scripts_written.append(filename)

    console.print()
    scope_label = "project" if use_project else "global"
    console.print(
        f"[green]✓ Skill '{skill_name}' created successfully! ({scope_label})[/green]"
    )
    console.print(f"[dim]Location: {skill_dir}[/dim]")
    console.print()

    if used_llm:
        files_created = ["SKILL.md"] + scripts_written
        console.print(f"[dim]Files created: {', '.join(files_created)}[/dim]")
        console.print("[dim]The skill was generated using AI with web research.[/dim]")
        console.print("[dim]Review and customize as needed.[/dim]")
    else:
        console.print("[dim]Edit the SKILL.md file to customize the skill.[/dim]")

    console.print()
    return True


async def handle_command(
    command: str,
    agent,
    token_tracker: TokenTracker,
    session_state,
    assistant_id: str,
    session_manager=None,
    model_name: str | None = None,
) -> str | bool:
    """Handle slash commands. Returns 'exit' to exit, True if handled, False to pass to agent."""
    # Parse command and optional arguments
    cmd_parts = command.strip().lstrip("/").split(maxsplit=1)
    cmd = cmd_parts[0].lower()
    cmd_args = cmd_parts[1] if len(cmd_parts) > 1 else None

    if cmd in ["quit", "exit", "q"]:
        return "exit"

    if cmd == "clear":
        # Reset agent conversation state
        agent.checkpointer = InMemorySaver()

        # Reset token tracking to baseline
        token_tracker.reset()

        # Clear screen and show fresh UI
        console.clear()
        console.print(DEEP_AGENTS_ASCII, style=f"bold {COLORS['primary']}")
        console.print()
        console.print(
            "... Fresh start! Screen cleared and conversation reset.",
            style=COLORS["agent"],
        )
        console.print()
        return True

    if cmd == "help":
        show_interactive_help()
        return True

    if cmd == "tokens":
        token_tracker.display_session()
        return True

    if cmd == "context":
        # Show detailed context window usage
        try:
            return await _handle_context_command(token_tracker)
        except Exception as e:
            console.print(f"[red]Error running /context command: {e}[/red]")
            import traceback

            console.print(f"[dim]{traceback.format_exc()}[/dim]")
            console.print()
        return True

    if cmd == "compact":
        # Summarize and compress conversation history
        try:
            return await _handle_compact_command(
                agent, session_state, token_tracker, focus_instructions=cmd_args
            )
        except Exception as e:
            console.print(f"[red]Error running /compact command: {e}[/red]")
            import traceback

            console.print(f"[dim]{traceback.format_exc()}[/dim]")
            console.print()
        return True

    if cmd == "init":
        # Run the async init command
        try:
            await _handle_init_command(
                agent, session_state, assistant_id, token_tracker
            )
        except Exception as e:
            console.print(f"[red]Error running /init command: {e}[/red]")
            import traceback

            console.print(f"[dim]{traceback.format_exc()}[/dim]")
            console.print()
        return True

    if cmd == "mcp":
        # Run the MCP management command
        try:
            return await _handle_mcp_command()
        except Exception as e:
            console.print(f"[red]Error running /mcp command: {e}[/red]")
            import traceback

            console.print(f"[dim]{traceback.format_exc()}[/dim]")
            console.print()
        return True

    if cmd == "model":
        # Run the model provider management command
        try:
            return await _handle_model_command()
        except Exception as e:
            console.print(f"[red]Error running /model command: {e}[/red]")
            import traceback

            console.print(f"[dim]{traceback.format_exc()}[/dim]")
            console.print()
        return True

    if cmd == "sessions":
        # Run the sessions management command
        try:
            return await _handle_sessions_command(session_state)
        except Exception as e:
            console.print(f"[red]Error running /sessions command: {e}[/red]")
            import traceback

            console.print(f"[dim]{traceback.format_exc()}[/dim]")
            console.print()
        return True

    if cmd == "save":
        # Manually save current session
        try:
            return await _handle_save_command(
                agent, session_state, assistant_id, session_manager, model_name
            )
        except Exception as e:
            console.print(f"[red]Error running /save command: {e}[/red]")
            import traceback

            console.print(f"[dim]{traceback.format_exc()}[/dim]")
            console.print()
        return True

    if cmd == "servers":
        # Manage dev servers
        try:
            return await _handle_servers_command(session_state)
        except Exception as e:
            console.print(f"[red]Error running /servers command: {e}[/red]")
            import traceback

            console.print(f"[dim]{traceback.format_exc()}[/dim]")
            console.print()
        return True

    if cmd == "tests":
        # Run project tests
        try:
            return await _handle_tests_command(session_state, cmd_args)
        except Exception as e:
            console.print(f"[red]Error running /tests command: {e}[/red]")
            import traceback

            console.print(f"[dim]{traceback.format_exc()}[/dim]")
            console.print()
        return True

    if cmd == "kill":
        # Kill a running process
        try:
            return await _handle_kill_command(session_state, cmd_args)
        except Exception as e:
            console.print(f"[red]Error running /kill command: {e}[/red]")
            import traceback

            console.print(f"[dim]{traceback.format_exc()}[/dim]")
            console.print()
        return True

    if cmd == "skills":
        # Create a new skill interactively
        try:
            return await _handle_skills_command(cmd_args, assistant_id)
        except Exception as e:
            console.print(f"[red]Error running /skills command: {e}[/red]")
            import traceback

            console.print(f"[dim]{traceback.format_exc()}[/dim]")
            console.print()
        return True

    if cmd == "agents":
        # Manage custom agents
        try:
            return await _handle_agents_command(cmd_args, assistant_id)
        except Exception as e:
            console.print(f"[red]Error running /agents command: {e}[/red]")
            import traceback

            console.print(f"[dim]{traceback.format_exc()}[/dim]")
            console.print()
        return True

    if cmd == "trace":
        # Manage LangSmith tracing
        try:
            return await _handle_trace_command(cmd_args) # type: ignore
        except Exception as e:
            console.print(f"[red]Error running /trace command: {e}[/red]")
            import traceback

            console.print(f"[dim]{traceback.format_exc()}[/dim]")
            console.print()
        return True

    console.print()
    console.print(f"[yellow]Unknown command: /{cmd}[/yellow]")
    console.print("[dim]Type /help for available commands.[/dim]")
    console.print()
    return True


async def _handle_trace_command(cmd_args: list[str]) -> bool:
    """Handle /trace command for LangSmith tracing management.

    Args:
        cmd_args: Command arguments (e.g., ["status"], ["enable"], ["projects"])

    Returns:
        True (always handled)
    """
    from .tracing import (
        configure_tracing,
        get_tracing_status,
        is_tracing_enabled,
        get_tracing_config,
        list_projects,
        get_traces,
    )
    from .config import settings

    console.print()

    # Parse subcommand
    subcmd = cmd_args[0].lower() if cmd_args else "status"

    if subcmd == "status":
        # Show current tracing status
        status = get_tracing_status()

        header = Text()
        header.append("📊 ", style="bold")
        header.append("LangSmith Tracing Status", style=f"bold {COLORS['primary']}")

        if status["available"]:
            if status["configured"]:
                config = get_tracing_config()
                console.print(
                    Panel(
                        f"✅ LangSmith tracing is [bold]ENABLED[/bold]\n\n"
                        f"Project: {config.project_name}\n"
                        f"Workspace: {config.workspace_id or '[dim]default[/dim]'}\n"
                        f"\n[dim]View traces at:[/dim]\n"
                        f"[link=https://smith.langchain.com]https://smith.langchain.com[/link]",
                        title=header,
                        border_style=COLORS["primary"],
                        padding=(1, 2),
                    )
                )
            else:
                console.print(
                    Panel(
                        f"⚠️  LangSmith tracing is [bold]NOT CONFIGURED[/bold]\n\n"
                        f"To enable tracing:\n"
                        f"1. Set LANGSMITH_API_KEY environment variable\n"
                        f"2. Set LANGSMITH_TRACING=true\n"
                        f"3. Optionally set LANGSMITH_PROJECT for custom project name",
                        title=header,
                        border_style=COLORS["warning"],
                        padding=(1, 2),
                    )
                )
        else:
            console.print(
                Panel(
                    Text(
                        "❌ LangSmith library is not installed.\n\n"
                        "Install with: pip install langsmith",
                        style="dim",
                    ),
                    title=header,
                    border_style=COLORS["error"],
                    padding=(1, 2),
                )
            )

    elif subcmd in ("enable", "on"):
        # Enable tracing
        api_key = cmd_args[1] if len(cmd_args) > 1 else None
        project_name = None
        for i, arg in enumerate(cmd_args):
            if arg == "--project" and i + 1 < len(cmd_args):
                project_name = cmd_args[i + 1]
                break

        config = configure_tracing(
            api_key=api_key,
            project_name=project_name, # type: ignore
            enable=True,
        )

        if config.is_configured():
            console.print(
                f"✅ [bold]LangSmith tracing enabled[/bold]",
                style=COLORS["success"],
            )
            console.print(f"   Project: {config.project_name}")
            console.print(
                f"   [dim]Configure LANGSMITH_API_KEY in .env for persistent settings[/dim]"
            )
        else:
            console.print(
                "❌ [bold]Failed to enable tracing[/bold]",
                style=COLORS["error"],
            )
            console.print("   LANGSMITH_API_KEY is required to enable tracing.")

    elif subcmd in ("disable", "off"):
        # Disable tracing
        import os

        os.environ["LANGSMITH_TRACING"] = "false"
        console.print(
            "✅ [bold]LangSmith tracing disabled[/bold]", style=COLORS["success"]
        )
        console.print(
            "   [dim]This only affects the current session. "
            "Remove or set LANGSMITH_TRACING=false in .env for persistent effect.[/dim]"
        )

    elif subcmd == "projects":
        # List tracing projects
        projects = list_projects()

        header = Text()
        header.append("📁 ", style="bold")
        header.append("LangSmith Projects", style=f"bold {COLORS['primary']}")

        if projects:
            from rich.table import Table

            table = Table(show_header=True, header_style="bold")
            table.add_column("Project")
            table.add_column("URL")

            for p in projects[:20]:  # Limit to 20
                table.add_row(p["name"], p["url"])

            console.print(Panel(table, title=header, border_style=COLORS["primary"]))
        else:
            console.print(
                Panel(
                    Text("No projects found or tracing not configured.", style="dim"),
                    title=header,
                    border_style=COLORS["dim"],
                )
            )

    elif subcmd in ("traces", "recent"):
        # Show recent traces
        limit = 10
        for i, arg in enumerate(cmd_args):
            if arg in ("-n", "--limit") and i + 1 < len(cmd_args):
                try:
                    limit = int(cmd_args[i + 1])
                except ValueError:
                    pass

        traces = get_traces(limit=limit)

        header = Text()
        header.append("🧵 ", style="bold")
        header.append(
            f"Recent Traces (last {limit})", style=f"bold {COLORS['primary']}"
        )

        if traces:
            from rich.table import Table

            table = Table(show_header=True, header_style="bold")
            table.add_column("Name")
            table.add_column("Created")
            table.add_column("Inputs", width=40)

            for t in traces[:10]:
                created = t.get("created_at", "unknown")[:19] or "unknown"
                inputs = str(t.get("inputs", {}))[:40]
                table.add_row(t["name"], created, inputs)

            console.print(Panel(table, title=header, border_style=COLORS["primary"]))
        else:
            console.print(
                Panel(
                    Text(
                        "No traces found. Make a request with tracing enabled first.",
                        style="dim",
                    ),
                    title=header,
                    border_style=COLORS["dim"],
                )
            )

    elif subcmd in ("-h", "--help", "help"):
        # Show help for trace command
        header = Text()
        header.append("🔧 ", style="bold")
        header.append("/trace Command Help", style=f"bold {COLORS['primary']}")

        console.print(
            Panel(
                Text(
                    "/trace - Manage LangSmith tracing for debugging and observability\n\n"
                    "[bold]Subcommands:[/bold]\n"
                    "  status      Show current tracing configuration\n"
                    "  enable      Enable tracing (optionally with API key and project name)\n"
                    "              Usage: /trace enable [API_KEY] [--project PROJECT_NAME]\n"
                    "  disable     Disable tracing for current session\n"
                    "  projects    List all projects in LangSmith\n"
                    "  traces      Show recent traces\n"
                    "              Usage: /trace traces [--limit N]\n"
                    "  help        Show this help message\n\n"
                    "[bold]Environment Variables:[/bold]\n"
                    "  LANGSMITH_TRACING     Set to 'true' to enable tracing\n"
                    "  LANGSMITH_API_KEY     Your LangSmith API key\n"
                    "  LANGSMITH_PROJECT     Project name (default: 'Nami-Code')\n"
                    "  LANGSMITH_WORKSPACE_ID Workspace ID for multi-tenant setups\n\n"
                    "[bold]Links:[/bold]\n"
                    "  📊 LangSmith Dashboard: https://smith.langchain.com\n"
                    "  📚 Docs: https://docs.smith.langchain.com",
                    style="dim",
                ),
                title=header,
                border_style=COLORS["primary"],
                padding=(1, 2),
            )
        )

    else:
        console.print(f"[yellow]Unknown trace subcommand: {subcmd}[/yellow]")
        console.print("[dim]Use /trace help for available commands.[/dim]")

    console.print()
    return True


def execute_bash_command(command: str) -> bool:
    """Execute a bash command and display output. Returns True if handled."""
    cmd = command.strip().lstrip("!")

    if not cmd:
        return True

    try:
        console.print()
        console.print(f"[dim]$ {cmd}[/dim]")

        # Execute the command
        result = subprocess.run(
            cmd,
            check=False,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=Path.cwd(),
        )

        # Display output
        if result.stdout:
            console.print(result.stdout, style=COLORS["dim"], markup=False)
        if result.stderr:
            console.print(result.stderr, style="red", markup=False)

        # Show return code if non-zero
        if result.returncode != 0:
            console.print(f"[dim]Exit code: {result.returncode}[/dim]")

        console.print()
        return True

    except subprocess.TimeoutExpired:
        console.print("[red]Command timed out after 30 seconds[/red]")
        console.print()
        return True
    except Exception as e:
        console.print(f"[red]Error executing command: {e}[/red]")
        console.print()
        return True

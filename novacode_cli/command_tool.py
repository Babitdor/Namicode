"""Command tool for invoking CLI slash commands from the agent.

This module provides a tool that allows the agent to invoke the same
slash commands available in the CLI interface, enabling programmatic
access to session management, MCP servers, skills, and other features.

Available Commands:
- /help - Show available commands
- /init - Initialize project configuration
- /mcp - Manage MCP servers
- /model - Switch AI models
- /sessions - List saved sessions
- /save - Save current session
- /servers - List running servers
- /tests - Run tests
- /kill - Kill a background process
- /skills - Manage skills
- /agents - Manage agents
- /files - List tracked files
- /plan - Plan mode
- /verbose - Toggle verbose mode
- /images - Manage images
- /restore - Restore from checkpoint
- /research - Research mode
"""

from typing import Any, Literal


async def run_command(
    command: str,
    args: str | None = None,
) -> dict[str, Any]:
    """Execute a CLI slash command from the agent.

    This tool allows the agent to invoke CLI commands programmatically,
    providing access to session management, MCP servers, skills, and
    other features without user interaction.

    Args:
        command: The command to run (without the leading /). Examples:
            - "help" - Show available commands
            - "init" - Initialize project configuration
            - "mcp" - Manage MCP servers (use args for subcommands)
            - "model" - Switch AI models
            - "sessions" - List saved sessions
            - "save" - Save current session
            - "servers" - List running servers
            - "tests" - Run tests
            - "kill" - Kill a background process
            - "skills" - Manage skills
            - "agents" - Manage agents
            - "files" - List tracked files
            - "plan" - Enter plan mode
            - "verbose" - Toggle verbose mode
            - "images" - Manage images
            - "restore" - Restore from checkpoint
            - "research" - Research mode
        args: Optional arguments for the command. Examples:
            - For "mcp": "list", "add <name>", "remove <name>"
            - For "model": "claude-sonnet", "gpt-4", etc.
            - For "tests": "pytest", "npm test", etc.
            - For "skills": "list", "enable <name>", "disable <name>"
            - For "research": "academic <query>", "market <query>", etc.

    Returns:
        Dictionary containing:
        - success: Whether the command succeeded
        - output: Command output (if any)
        - error: Error message (if failed)
        - command: The command that was executed

    Example:
        # List MCP servers
        run_command("mcp", "list")

        # Switch model
        run_command("model", "claude-sonnet")

        # List skills
        run_command("skills", "list")

        # Run tests
        run_command("tests", "pytest -x")

        # Research mode
        run_command("research", "academic quantum computing")
    """
    # Import here to avoid circular imports
    from novacode_cli.commands.commands import handle_command
    from novacode_cli.states.Session import SessionState
    from novacode_cli.ui.ui_elements import TokenTracker

    # Build full command string
    full_command = f"/{command}"
    if args:
        full_command = f"/{command} {args}"

    # Create minimal session state for command execution
    # This is needed because some commands require session state
    session_state = SessionState()
    token_tracker = TokenTracker()

    try:
        # Execute the command
        result = await handle_command(
            command=full_command,
            agent=None,  # Some commands don't need agent
            token_tracker=token_tracker,
            session_state=session_state,
            assistant_id="default",
        )

        # Handle different return types
        if result == "exit":
            return {
                "success": True,
                "output": "Command executed successfully. Session would exit.",
                "command": full_command,
            }
        elif result is True:
            return {
                "success": True,
                "output": "Command executed successfully.",
                "command": full_command,
            }
        elif isinstance(result, str):
            return {
                "success": True,
                "output": result,
                "command": full_command,
            }
        elif result is False:
            # Command not recognized, should be passed to agent
            return {
                "success": False,
                "error": f"Unknown command: {full_command}",
                "command": full_command,
                "suggestion": "Use /help to see available commands.",
            }
        else:
            return {
                "success": True,
                "output": str(result) if result else "Command executed.",
                "command": full_command,
            }

    except Exception as e:
        return {
            "success": False,
            "error": f"Command failed: {e!s}",
            "command": full_command,
        }


def list_commands() -> dict[str, Any]:
    """List all available CLI commands with descriptions.

    Returns:
        Dictionary containing:
        - commands: List of available commands with descriptions
        - categories: Commands grouped by category

    Example:
        list_commands()
        # Returns: {"commands": [...], "categories": {...}}
    """
    commands = [
        # Session Management
        {
            "command": "help",
            "description": "Show available commands and their usage",
            "args": None,
            "category": "session",
        },
        {
            "command": "init",
            "description": "Initialize project configuration and setup",
            "args": None,
            "category": "session",
        },
        {
            "command": "sessions",
            "description": "List saved sessions",
            "args": None,
            "category": "session",
        },
        {
            "command": "save",
            "description": "Save current session state",
            "args": None,
            "category": "session",
        },
        {
            "command": "clear",
            "description": "Clear conversation history and start fresh",
            "args": None,
            "category": "session",
        },
        {
            "command": "compact",
            "description": "Compact conversation context to save tokens",
            "args": "Optional focus instructions",
            "category": "session",
        },
        {
            "command": "verbose",
            "description": "Toggle verbose mode (show internal context)",
            "args": None,
            "category": "session",
        },
        # MCP & Servers
        {
            "command": "mcp",
            "description": "Manage MCP servers (list, add, remove)",
            "args": "list | add <name> | remove <name>",
            "category": "servers",
        },
        {
            "command": "servers",
            "description": "List running background servers",
            "args": None,
            "category": "servers",
        },
        {
            "command": "kill",
            "description": "Kill a background process by name or PID",
            "args": "<name | PID>",
            "category": "servers",
        },
        # Model & Agents
        {
            "command": "model",
            "description": "Switch AI models",
            "args": "<model_name>",
            "category": "model",
        },
        {
            "command": "agents",
            "description": "Manage custom agents",
            "args": "list | create | edit | delete",
            "category": "model",
        },
        # Skills & Features
        {
            "command": "skills",
            "description": "Manage skills (list, enable, disable)",
            "args": "list | enable <name> | disable <name>",
            "category": "features",
        },
        {
            "command": "plan",
            "description": "Enter plan mode for complex tasks",
            "args": None,
            "category": "features",
        },
        {
            "command": "research",
            "description": "Research mode (academic, market, technical)",
            "args": "[mode] <query>",
            "category": "features",
        },
        {
            "command": "dream",
            "description": "Dream mode for creative exploration",
            "args": None,
            "category": "features",
        },
        {
            "command": "ralph",
            "description": "Ralph iteration mode for autonomous work",
            "args": "[--resume | --stop]",
            "category": "features",
        },
        # Files & Images
        {
            "command": "files",
            "description": "List tracked files in session",
            "args": None,
            "category": "files",
        },
        {
            "command": "images",
            "description": "Manage images in session",
            "args": "list | clear",
            "category": "files",
        },
        {
            "command": "restore",
            "description": "Restore from checkpoint",
            "args": "<checkpoint_id>",
            "category": "files",
        },
        # Testing
        {
            "command": "tests",
            "description": "Run tests with auto-detection",
            "args": "[test_command]",
            "category": "testing",
        },
        # Debugging
        {
            "command": "tokens",
            "description": "Display token usage statistics",
            "args": None,
            "category": "debug",
        },
        {
            "command": "context",
            "description": "Display context window usage",
            "args": None,
            "category": "debug",
        },
        {
            "command": "trace",
            "description": "Trace tool calls and execution",
            "args": "[on | off | show]",
            "category": "debug",
        },
        {
            "command": "hooks",
            "description": "Manage hooks configuration",
            "args": "list | enable | disable",
            "category": "debug",
        },
        # Browser
        {
            "command": "browser-use",
            "description": "Browser automation mode",
            "args": "[options]",
            "category": "browser",
        },
    ]

    # Group by category
    categories = {}
    for cmd in commands:
        cat = cmd["category"]
        if cat not in categories:
            categories[cat] = []
        categories[cat].append(cmd["command"])

    return {
        "success": True,
        "commands": commands,
        "categories": categories,
        "total": len(commands),
    }


# Export
__all__ = ["run_command", "list_commands"]
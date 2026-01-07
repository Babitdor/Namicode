"""MCP server presets and templates.

Provides pre-configured templates for popular MCP servers that can be easily
installed and configured through the /mcp command.
"""

from typing import Any

from namicode_cli.mcp.config import MCPServerConfig

# Pre-defined MCP server presets
MCP_PRESETS: dict[str, dict[str, Any]] = {
    "filesystem": {
        "name": "Filesystem MCP",
        "description": "Secure file operations with configurable access controls",
        "package": "@modelcontextprotocol/server-filesystem",
        "config": {
            "transport": "stdio",
            "command": "npx",
            "args": [
                "-y",
                "@modelcontextprotocol/server-filesystem",
                "{allowed_directories}",
            ],
            "env": {},
        },
        "setup_prompt": "Enter allowed directories (comma-separated, e.g., /workspace,/tmp):",
        "setup_key": "allowed_directories",
    },
    "github": {
        "name": "GitHub MCP",
        "description": "Interact with GitHub repositories, issues, and PRs",
        "package": "ghcr.io/github/github-mcp-server",
        "config": {
            "transport": "stdio",
            "command": "docker",
            "args": [
                "run",
                "-i",
                "--rm",
                "--init",
                "-e",
                "GITHUB_PERSONAL_ACCESS_TOKEN",
                "ghcr.io/github/github-mcp-server",
                "stdio",
            ],
            "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": "{github_token}"},
        },
        "setup_prompt": "Enter your GitHub personal access token:",
        "setup_key": "github_token",
        "env_mapping": {"github_token": "GITHUB_PERSONAL_ACCESS_TOKEN"},
    },
    "brave-search": {
        "name": "Brave Search MCP",
        "description": "Web search using Brave Search API",
        "package": "@modelcontextprotocol/server-brave-search",
        "config": {
            "transport": "stdio",
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-brave-search"],
            "env": {"BRAVE_API_KEY": "{brave_api_key}"},
        },
        "setup_prompt": "Enter your Brave Search API key:",
        "setup_key": "brave_api_key",
        "env_mapping": {"brave_api_key": "BRAVE_API_KEY"},
    },
    "memory": {
        "name": "Memory MCP",
        "description": "Persistent memory storage across sessions",
        "package": "@modelcontextprotocol/server-memory",
        "config": {
            "transport": "stdio",
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-memory"],
            "env": {},
        },
    },
    "postgres": {
        "name": "PostgreSQL MCP",
        "description": "Query and interact with PostgreSQL databases (patched fork)",
        "package": "@zeddotdev/postgres-context-server",
        "config": {
            "transport": "stdio",
            "command": "npx",
            "args": ["-y", "@zeddotdev/postgres-context-server"],
            "env": {"POSTGRES_CONNECTION_STRING": "{connection_string}"},
        },
        "setup_prompt": "Enter PostgreSQL connection string (postgresql://user:pass@host:port/db):",
        "setup_key": "connection_string",
        "env_mapping": {"connection_string": "POSTGRES_CONNECTION_STRING"},
    },
    "slack": {
        "name": "Slack MCP",
        "description": "Send messages and interact with Slack",
        "package": "@modelcontextprotocol/server-slack",
        "config": {
            "transport": "stdio",
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-slack"],
            "env": {
                "SLACK_BOT_TOKEN": "{slack_bot_token}",
                "SLACK_TEAM_ID": "{slack_team_id}",
            },
        },
        "setup_prompt": "Enter your Slack bot token:",
        "setup_key": "slack_bot_token",
        "setup_secondary_prompt": "Enter your Slack team ID:",
        "setup_secondary_key": "slack_team_id",
        "env_mapping": {
            "slack_bot_token": "SLACK_BOT_TOKEN",
            "slack_team_id": "SLACK_TEAM_ID",
        },
    },
    "google-drive": {
        "name": "Google Drive MCP",
        "description": "Access and manage Google Drive files (requires OAuth setup)",
        "package": "@modelcontextprotocol/server-gdrive",
        "config": {
            "transport": "stdio",
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-gdrive"],
            "env": {"GDRIVE_CREDENTIALS_PATH": "{credentials_path}"},
        },
        "setup_prompt": "Enter path to Google Drive credentials JSON file:",
        "setup_key": "credentials_path",
        "env_mapping": {"credentials_path": "GDRIVE_CREDENTIALS_PATH"},
    },
    "playwright": {
        "name": "Playwright MCP",
        "description": "Browser automation using Playwright for web scraping and testing",
        "package": "@playwright/mcp",
        "config": {
            "transport": "stdio",
            "command": "npx",
            "args": [
                "-y",
                "@playwright/mcp@latest",
                "--browser=chrome",
                "--viewport-size=1280x720",
                "--headless",
                "--timeout-action=30000",
                "--timeout-navigation=30000",
            ],  #  Headless by default; remove for headed
            "env": {},
        },
    },
    "git": {
        "name": "Git MCP",
        "description": "Tools to read, search, and manipulate Git repositories",
        "package": "@modelcontextprotocol/server-git",
        "config": {
            "transport": "stdio",
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-git"],
            "env": {},
        },
    },
    "fetch": {
        "name": "Fetch MCP",
        "description": "Web content fetching and conversion for LLM usage",
        "package": "@modelcontextprotocol/server-fetch",
        "config": {
            "transport": "stdio",
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-fetch"],
            "env": {},
        },
    },
    "time": {
        "name": "Time MCP",
        "description": "Time and timezone conversion capabilities",
        "package": "@modelcontextprotocol/server-time",
        "config": {
            "transport": "stdio",
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-time"],
            "env": {},
        },
    },
    "sqlite": {
        "name": "SQLite MCP",
        "description": "Interact with local SQLite databases",
        "package": "@modelcontextprotocol/server-sqlite",
        "config": {
            "transport": "stdio",
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-sqlite", "{db_path}"],
            "env": {},
        },
        "setup_prompt": "Enter SQLite database path:",
        "setup_key": "db_path",
    },
    "stripe": {
        "name": "Stripe MCP",
        "description": "Interact with Stripe payments API (official)",
        "package": "@stripe/mcp",
        "config": {
            "transport": "stdio",
            "command": "npx",
            "args": ["-y", "@stripe/mcp", "--tools=all", "--api-key={stripe_key}"],
            "env": {},
        },
        "setup_prompt": "Enter Stripe secret API key:",
        "setup_key": "stripe_key",
    },
    "everything": {
        "name": "Everything MCP",
        "description": "Reference/test server with prompts, resources, and tools",
        "package": "@modelcontextprotocol/server-everything",
        "config": {
            "transport": "stdio",
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-everything"],
            "env": {},
        },
    },
    "serena": {
        "name": "Serena MCP",
        "description": "Semantic code editing and analysis with LSP integration",
        "package": "serena",
        "config": {
            "transport": "stdio",
            "command": "uvx",
            "args": [
                "--from",
                "git+https://github.com/oraios/serena",
                "serena",
                "start-mcp-server",
                "--project-from-cwd",
                "--context",
                "agent",
            ],
            "env": {},
        },
    },
    "n8n-mcp": {
        "name": "n8n MCP",
        "description": "n8n workflow automation MCP server (Docker required)",
        "package": "ghcr.io/czlonkowski/n8n-mcp:latest",
        "config": {
            "transport": "stdio",
            "command": "docker",
            "args": [
                "run",
                "-i",
                "--rm",
                "--init",
                "-e",
                "-e",
                "MCP_MODE=stdio",
                "-e",
                "LOG_LEVEL=error",
                "-e",
                "DISABLE_CONSOLE_OUTPUT=true",
                "-e",
                "N8N_API_URL=http://host.docker.internal:5678",
                "-e",
                "N8N_API_KEY=your-api-key",
                "ghcr.io/czlonkowski/n8n-mcp:latest",
            ],
            "env": {},
        },
    },
}


def get_preset(name: str) -> dict[str, Any] | None:
    """Get MCP preset by name.

    Args:
        name: Preset identifier (e.g., 'filesystem', 'github')

    Returns:
        Preset configuration dict or None if not found
    """
    return MCP_PRESETS.get(name)


def list_presets() -> dict[str, dict[str, Any]]:
    """List all available MCP presets.

    Returns:
        Dictionary of all presets
    """
    return MCP_PRESETS.copy()


def create_config_from_preset(
    preset_name: str, user_inputs: dict[str, str] | None = None
) -> MCPServerConfig | None:
    """Create an MCPServerConfig from a preset with user inputs.

    Args:
        preset_name: Name of the preset to use
        user_inputs: Dictionary of user-provided values for placeholders

    Returns:
        Configured MCPServerConfig or None if preset not found
    """
    preset = get_preset(preset_name)
    if not preset:
        return None

    config = preset["config"].copy()
    user_inputs = user_inputs or {}

    # Replace placeholders in args
    if config.get("args"):
        config["args"] = [
            arg.format(**user_inputs) if "{" in arg else arg for arg in config["args"]
        ]

    # Replace placeholders in env
    if config.get("env"):
        env_mapping = preset.get("env_mapping", {})
        new_env = {}
        for env_key, env_value in config["env"].items():
            if "{" in env_value:
                # Find the corresponding user input
                for input_key, mapped_env_key in env_mapping.items():
                    if mapped_env_key == env_key and input_key in user_inputs:
                        new_env[env_key] = user_inputs[input_key]
                        break
            else:
                new_env[env_key] = env_value
        config["env"] = new_env

    # Add description from preset
    config["description"] = preset["description"]

    return MCPServerConfig(**config)

"""MCP server presets and templates.

Provides pre-configured templates for popular MCP servers that can be easily
installed and configured through the /mcp command.
"""

from typing import Any

from novacode_cli.mcp.config import MCPServerConfig

# Pre-defined MCP server presets
MCP_PRESETS: dict[str, dict[str, Any]] = {
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
    "context7": {
        "name": "Context7 MCP",
        "description": "Upstash Context7 MCP server for context management",
        "package": "@upstash/context7-mcp",
        "config": {
            "transport": "stdio",
            "command": "npx",
            "args": ["-y", "@upstash/context7-mcp", "--api-key", "{context7_api_key}"],
            "env": {},
        },
        "setup_prompt": "Enter your Upstash Context7 API key:",
        "setup_key": "context7_api_key",
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

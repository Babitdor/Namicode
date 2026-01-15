"""CLI commands for MCP server management.

These commands are registered with the CLI via main.py:
- nami mcp add <name> --transport <type> <connection_details>
- nami mcp remove <name>
- nami mcp list
- nami mcp install <url>
"""

import argparse
import sys
from typing import Any
from pathlib import Path
from namicode_cli.config.config import COLORS, console
from namicode_cli.mcp.config import MCPConfig, MCPServerConfig


def _add(
    name: str,
    transport: str,
    url: str | None = None,
    command: str | None = None,
    args: list[str] | None = None,
    env: dict[str, str] | None = None,
    description: str | None = None,
) -> None:
    """Add or update an MCP server configuration.

    Args:
        name: Server name/identifier
        transport: Transport type (http or stdio)
        url: Server URL (required for HTTP transport)
        command: Command to execute (required for stdio transport)
        args: Command arguments (optional, for stdio transport)
        env: Environment variables (optional)
        description: Server description (optional)
    """
    try:
        config = MCPServerConfig(
            transport=transport,  # type: ignore[arg-type]
            url=url,
            command=command,
            args=args or [],
            env=env or {},
            description=description,
        )

        mcp_config = MCPConfig()
        mcp_config.add_server(name, config)

        console.print(
            f"✓ MCP server '{name}' added successfully!",
            style=COLORS["primary"],
        )
        console.print(f"Transport: {transport}", style=COLORS["dim"])
        if url:
            console.print(f"URL: {url}", style=COLORS["dim"])
        if command:
            console.print(f"Command: {command}", style=COLORS["dim"])
            if args:
                console.print(f"Args: {' '.join(args)}", style=COLORS["dim"])
        console.print(
            f"\nConfiguration saved to: {mcp_config.config_path}",
            style=COLORS["dim"],
        )

    except ValueError as e:
        console.print(f"[bold red]Error:[/bold red] Invalid configuration: {e}")
        sys.exit(1)


def _remove(name: str) -> None:
    """Remove an MCP server configuration.

    Args:
        name: Server name/identifier
    """
    mcp_config = MCPConfig()

    if mcp_config.remove_server(name):
        console.print(
            f"✓ MCP server '{name}' removed successfully!",
            style=COLORS["primary"],
        )
    else:
        console.print(
            f"[bold red]Error:[/bold red] MCP server '{name}' not found.",
        )
        console.print("\n[dim]Available servers:[/dim]", style=COLORS["dim"])
        servers = mcp_config.list_servers()
        if servers:
            for server_name in servers:
                console.print(f"  - {server_name}", style=COLORS["dim"])
        else:
            console.print("  (none)", style=COLORS["dim"])
        sys.exit(1)


def _list() -> None:
    """List all configured MCP servers."""
    mcp_config = MCPConfig()
    servers = mcp_config.list_servers()

    if not servers:
        console.print("[yellow]No MCP servers configured.[/yellow]")
        console.print(
            "\n[dim]Add a server with:[/dim]",
            style=COLORS["dim"],
        )
        console.print(
            "  nami mcp add <name> --transport http --url <url>",
            style=COLORS["dim"],
        )
        console.print(
            "  nami mcp add <name> --transport stdio --command <cmd>",
            style=COLORS["dim"],
        )
        return

    console.print("\n[bold]Configured MCP Servers:[/bold]\n", style=COLORS["primary"])

    for name, config in servers.items():
        console.print(f"  • [bold]{name}[/bold]", style=COLORS["primary"])
        if config.description:
            console.print(f"    {config.description}", style=COLORS["dim"])

        console.print(f"    Transport: {config.transport}", style=COLORS["dim"])

        if config.transport == "http" and config.url:
            console.print(f"    URL: {config.url}", style=COLORS["dim"])
        elif config.transport == "stdio" and config.command:
            console.print(f"    Command: {config.command}", style=COLORS["dim"])
            if config.args:
                console.print(
                    f"    Args: {' '.join(config.args)}",
                    style=COLORS["dim"],
                )

        if config.env:
            console.print("    Environment:", style=COLORS["dim"])
            for key, value in config.env.items():
                console.print(f"      {key}={value}", style=COLORS["dim"])

        console.print()

    console.print(
        f"Configuration file: {mcp_config.config_path}",
        style=COLORS["dim"],
    )


def _install(url: str, name: str | None = None) -> None:
    """Install an MCP server from a URL with auto-discovery.

    This is a placeholder for future auto-discovery functionality.
    Currently, it guides users to use the add command.

    Args:
        url: URL to discover and install the MCP server from
        name: Optional custom name for the server
    """
    console.print(
        "[yellow]MCP auto-discovery is not yet implemented.[/yellow]",
    )
    console.print(
        "\nTo manually add an MCP server, use:",
        style=COLORS["dim"],
    )
    console.print(
        f"  nami mcp add {name or 'server-name'} --transport http --url {url}",
        style=COLORS["dim"],
    )
    console.print(
        "\nFor stdio-based servers:",
        style=COLORS["dim"],
    )
    console.print(
        "  nami mcp add server-name --transport stdio --command 'python -m mcp_server'",
        style=COLORS["dim"],
    )


def setup_mcp_parser(subparsers: Any) -> argparse.ArgumentParser:
    """Setup the MCP subcommand parser with all its subcommands.

    Args:
        subparsers: The subparsers object from argparse

    Returns:
        The MCP parser instance
    """
    mcp_parser = subparsers.add_parser(
        "mcp",
        help="Manage MCP (Model Context Protocol) servers",
        description="Manage MCP servers - add, remove, list, and install servers",
    )
    mcp_subparsers = mcp_parser.add_subparsers(
        dest="mcp_command",
        help="MCP command",
    )

    # MCP add
    add_parser = mcp_subparsers.add_parser(
        "add",
        help="Add an MCP server",
        description="Add or update an MCP server configuration",
    )
    add_parser.add_argument("name", help="Server name/identifier")
    add_parser.add_argument(
        "--transport",
        required=True,
        choices=["http", "stdio"],
        help="Transport type (http or stdio)",
    )
    add_parser.add_argument(
        "--url",
        help="Server URL (required for HTTP transport)",
    )
    add_parser.add_argument(
        "--command",
        help="Command to execute (required for stdio transport)",
    )
    add_parser.add_argument(
        "--args",
        nargs="*",
        help="Command arguments (for stdio transport)",
    )
    add_parser.add_argument(
        "--env",
        action="append",
        help="Environment variables in KEY=VALUE format (can be specified multiple times)",
    )
    add_parser.add_argument(
        "--description",
        help="Server description",
    )

    # MCP remove
    remove_parser = mcp_subparsers.add_parser(
        "remove",
        help="Remove an MCP server",
        description="Remove an MCP server configuration",
    )
    remove_parser.add_argument("name", help="Server name/identifier to remove")

    # MCP list
    mcp_subparsers.add_parser(
        "list",
        help="List all MCP servers",
        description="List all configured MCP servers",
    )

    # MCP install
    install_parser = mcp_subparsers.add_parser(
        "install",
        help="Install an MCP server from URL",
        description="Auto-discover and install an MCP server from a URL",
    )
    install_parser.add_argument("url", help="URL to discover the MCP server from")
    install_parser.add_argument(
        "--name",
        help="Custom name for the server (auto-detected if not provided)",
    )

    return mcp_parser


async def execute_bash_command_async(command: str) -> None:
    """Execute a bash command and return output as a string.

    Args:
        command: The bash command to execute

    Returns:
        Output string
    """
    import subprocess

    try:
        # Execute the command
        result = subprocess.run(
            command,
            check=False,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=Path.cwd(),
        )

        output_lines = []

        # Show the command
        output_lines.append(f"$ {command}")
        output_lines.append("")

        # Add output
        if result.stdout:
            output_lines.append(result.stdout.strip())
        if result.stderr:
            output_lines.append(f"[stderr]\n{result.stderr.strip()}")

        # Show return code if non-zero
        if result.returncode != 0:
            output_lines.append(f"\nExit code: {result.returncode}")

        return "\n".join(output_lines)  # type: ignore

    except subprocess.TimeoutExpired:
        return "Command timed out after 30 seconds"  # type: ignore
    except Exception as e:
        return f"Error executing command: {e}"  # type: ignore


def execute_mcp_command(args: argparse.Namespace) -> None:
    """Execute MCP subcommands based on parsed arguments.

    Args:
        args: Parsed command line arguments with mcp_command attribute
    """
    if args.mcp_command == "add":
        # Parse environment variables
        env = {}
        if args.env:
            for env_var in args.env:
                if "=" not in env_var:
                    console.print(
                        f"[bold red]Error:[/bold red] Invalid environment variable format: {env_var}",
                    )
                    console.print(
                        "[dim]Use KEY=VALUE format (e.g., --env ROOT_DIR=/workspace)[/dim]",
                        style=COLORS["dim"],
                    )
                    sys.exit(1)
                key, value = env_var.split("=", 1)
                env[key] = value

        _add(
            name=args.name,
            transport=args.transport,
            url=args.url,
            command=args.command,
            args=args.args,
            env=env,
            description=args.description,
        )

    elif args.mcp_command == "remove":
        _remove(args.name)

    elif args.mcp_command == "list":
        _list()

    elif args.mcp_command == "install":
        _install(args.url, args.name)

    else:
        # No subcommand provided, show help
        console.print(
            "[yellow]Please specify an MCP subcommand: add, remove, list, or install[/yellow]",
        )
        console.print("\n[bold]Usage:[/bold]", style=COLORS["primary"])
        console.print("  nami mcp <command> [options]\n")
        console.print("[bold]Available commands:[/bold]", style=COLORS["primary"])
        console.print("  add       Add or update an MCP server")
        console.print("  remove    Remove an MCP server")
        console.print("  list      List all configured MCP servers")
        console.print("  install   Install an MCP server from URL")
        console.print("\n[bold]Examples:[/bold]", style=COLORS["primary"])
        console.print(
            "  nami mcp add docs-langchain --transport http --url https://docs.langchain.com/mcp",
        )
        console.print(
            "  nami mcp add filesystem --transport stdio --command 'python -m mcp_server_filesystem'",
        )
        console.print("  nami mcp list")
        console.print("  nami mcp remove docs-langchain")
        console.print(
            "\n[dim]For more help on a specific command:[/dim]", style=COLORS["dim"]
        )
        console.print("  nami mcp <command> --help", style=COLORS["dim"])


__all__ = [
    "execute_mcp_command",
    "setup_mcp_parser",
]

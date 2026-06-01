"""MCP configuration management.

Handles loading, saving, and validating MCP server configurations.
Configuration is stored at ~/.nova/mcp.json in the following format:

{
  "mcpServers": {
    "server-name": {
      "transport": "http" | "stdio",
      "url": "https://...",  // for HTTP transport
      "command": "...",      // for stdio transport
      "args": [...],         // optional, for stdio transport
      "env": {...},          // optional environment variables
      "description": "..."   // optional description
    }
  }
}
"""

import json
import logging
import os
import shutil
import time
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

logger = logging.getLogger(__name__)

# Environment variables that could be used for code injection
_DANGEROUS_ENV_VARS = {
    "LD_PRELOAD",
    "LD_LIBRARY_PATH",
    "DYLD_INSERT_LIBRARIES",
    "PYTHONPATH",
}

# Shell metacharacters that indicate command injection
_SHELL_METACHARACTERS = set("`$|;&")


def _atomic_write_json(path: Path, data: dict) -> None:
    """Write JSON data atomically via temp file + replace.

    Uses Path.replace (os.replace), not rename: on Windows rename raises
    FileExistsError when the target exists; replace overwrites atomically.
    """
    tmp_path = path.with_suffix(".tmp." + str(os.getpid()))
    try:
        tmp_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp_path.replace(path)
    except Exception:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass
        raise


def _acquire_lock(lock_path: Path, timeout: float = 5.0) -> bool:
    """Try to acquire an exclusive lock file with a timeout."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            return True
        except FileExistsError:
            try:
                mtime = lock_path.stat().st_mtime
                if time.time() - mtime > 2.0:
                    lock_path.unlink(missing_ok=True)
                    continue
            except OSError:
                pass
            time.sleep(0.05)
    return False


def _release_lock(lock_path: Path) -> None:
    """Release an exclusive lock file."""
    try:
        lock_path.unlink(missing_ok=True)
    except OSError:
        pass


class MCPServerConfig(BaseModel):
    """Configuration for a single MCP server."""

    transport: Literal["http", "stdio"]
    url: str | None = None
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    description: str | None = None

    @field_validator("command")
    @classmethod
    def validate_command(cls, v: str | None) -> str | None:
        """Reject commands containing shell metacharacters, path traversal, or missing binaries."""
        if v is not None:
            if any(c in v for c in _SHELL_METACHARACTERS):
                msg = "Shell metacharacters not allowed in command"
                raise ValueError(msg)
            if ".." in v:
                msg = "Path traversal not allowed in command"
                raise ValueError(msg)
            # Validate binary exists: absolute path must be a file;
            # simple name must be found on PATH.
            if "/" in v:
                if not Path(v).is_file():
                    msg = f"Command binary not found: {v}"
                    raise ValueError(msg)
            elif not shutil.which(v):
                msg = f"Command not found on PATH: {v}"
                raise ValueError(msg)
        return v

    @field_validator("args")
    @classmethod
    def validate_args(cls, v: list[str]) -> list[str]:
        """Reject args containing shell metacharacters."""
        for arg in v:
            if any(c in arg for c in _SHELL_METACHARACTERS):
                msg = f"Shell metacharacters not allowed in args: {arg}"
                raise ValueError(msg)
        return v

    @field_validator("env")
    @classmethod
    def validate_env(cls, v: dict[str, str]) -> dict[str, str]:
        """Reject dangerous environment variables."""
        for key in v:
            if key in _DANGEROUS_ENV_VARS:
                msg = f"Dangerous environment variable not allowed: {key}"
                raise ValueError(msg)
        return v

    @model_validator(mode="after")
    def validate_transport_requirements(self) -> "MCPServerConfig":
        """Validate that transport-specific requirements are met."""
        if self.transport == "http" and not self.url:
            msg = "HTTP transport requires a URL"
            raise ValueError(msg)
        if self.transport == "stdio" and not self.command:
            msg = "stdio transport requires a command"
            raise ValueError(msg)
        return self


class MCPConfig:
    """Manages MCP server configurations."""

    def __init__(self, config_path: Path | None = None) -> None:
        """Initialize MCP config.

        Args:
            config_path: Path to mcp.json config file. Defaults to ~/.nova/mcp.json
        """
        if config_path is None:
            config_path = Path.home() / ".nova" / "mcp.json"
        self.config_path = config_path
        self._ensure_config_dir()

    def _ensure_config_dir(self) -> None:
        """Ensure the config directory exists."""
        self.config_path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> dict[str, MCPServerConfig]:
        """Load MCP server configurations from disk.

        Returns:
            Dictionary mapping server names to configurations.
            Returns empty dict on error (graceful degradation).
        """
        if not self.config_path.exists():
            return {}

        try:
            with self.config_path.open() as f:
                data = json.load(f)

            servers = data.get("mcpServers", {})
            return {name: MCPServerConfig(**config) for name, config in servers.items()}
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(
                "Failed to load MCP config from %s: %s",
                self.config_path,
                e,
                exc_info=True,
            )
            return {}

    def save(self, servers: dict[str, MCPServerConfig]) -> None:
        """Save MCP server configurations to disk atomically.

        Args:
            servers: Dictionary mapping server names to configurations
        """
        data = {
            "mcpServers": {
                name: config.model_dump(exclude_none=True) for name, config in servers.items()
            }
        }

        lock_path = self.config_path.with_suffix(".lock")
        if not _acquire_lock(lock_path):
            msg = f"Could not acquire lock for {self.config_path}"
            raise RuntimeError(msg)
        try:
            _atomic_write_json(self.config_path, data)
        finally:
            _release_lock(lock_path)

    def add_server(self, name: str, config: MCPServerConfig) -> None:
        """Add or update an MCP server configuration.

        Args:
            name: Server name/identifier
            config: Server configuration
        """
        servers = self.load()
        servers[name] = config
        self.save(servers)

    def remove_server(self, name: str) -> bool:
        """Remove an MCP server configuration.

        Args:
            name: Server name/identifier

        Returns:
            True if server was removed, False if not found
        """
        servers = self.load()
        if name not in servers:
            return False
        del servers[name]
        self.save(servers)
        return True

    def get_server(self, name: str) -> MCPServerConfig | None:
        """Get configuration for a specific server.

        Args:
            name: Server name/identifier

        Returns:
            Server configuration or None if not found
        """
        servers = self.load()
        return servers.get(name)

    def list_servers(self) -> dict[str, MCPServerConfig]:
        """List all configured MCP servers.

        Returns:
            Dictionary mapping server names to configurations
        """
        return self.load()

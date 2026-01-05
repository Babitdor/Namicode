"""Configuration, constants, and model creation for the CLI.

This module provides centralized configuration management for the CLI, including:
- Color scheme and UI styling constants
- Environment variable parsing and settings management
- Model creation for multiple LLM providers (OpenAI, Anthropic, Ollama, Google)
- Project root detection and working directory management
- Session state management
- Rich console initialization with proper encoding

Key Components:
- create_model(): Factory function for creating chat models from configuration
- settings(): Global settings object with environment variable access
- COLORS: Color scheme constants for UI styling
- DEEP_AGENTS_ASCII: ASCII art banner for CLI startup
- SessionState: Dataclass for tracking session state

Supported Model Providers:
- OpenAI (default): Requires OPENAI_API_KEY
- Anthropic: Requires ANTHROPIC_API_KEY
- Ollama: Local models, requires OLLAMA_BASE_URL
- Google: Requires GOOGLE_API_KEY

Environment Configuration:
- API keys loaded from environment variables or .env files
- Configuration files in ~/.nami/ and .nami/
- Project-specific settings override global settings
"""

import os
import re
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

import dotenv
from langchain_core.language_models import BaseChatModel
from rich.console import Console

dotenv.load_dotenv()

# Color scheme - Red & White Theme
COLORS = {
    "primary": "#ef4444",  # Bright red (primary actions, headings)
    "secondary": "#dc2626",  # Deep red (highlights, important text)
    "accent": "#fca5a5",  # Light red (accents, borders)
    "dim": "#9ca3af",  # Gray (secondary text)
    "user": "#ffffff",  # White (user messages)
    "agent": "#ef4444",  # Bright red (agent messages)
    "thinking": "#f87171",  # Medium red (thinking/processing)
    "tool": "#dc2626",  # Deep red (tool calls)
    "success": "#10b981",  # Green (success states)
    "warning": "#f59e0b",  # Orange (warnings)
    "error": "#dc2626",  # Deep red (errors)
}

# ASCII art banner - Sleek red design
DEEP_AGENTS_ASCII = """
                                                                     
       ███╗   ██╗ █████╗ ███╗   ███╗██╗     ██████╗ ██████╗ ██████╗ ███████╗   
       ████╗  ██║██╔══██╗████╗ ████║██║    ██╔════╝██╔═══██╗██╔══██╗██╔════╝   
       ██╔██╗ ██║███████║██╔████╔██║██║    ██║     ██║   ██║██║  ██║█████╗     
       ██║╚██╗██║██╔══██║██║╚██╔╝██║██║    ██║     ██║   ██║██║  ██║██╔══╝     
       ██║ ╚████║██║  ██║██║ ╚═╝ ██║██║    ╚██████╗╚██████╔╝██████╔╝███████╗   
       ╚═╝  ╚═══╝╚═╝  ╚═╝╚═╝     ╚═╝╚═╝     ╚═════╝ ╚═════╝ ╚═════╝ ╚══════╝   

"""

# Interactive commands
COMMANDS = {
    "clear": "Clear screen and reset conversation",
    "help": "Show help information",
    "tokens": "Show token usage for current session",
    "context": "Show detailed context window usage with visual breakdown",
    "compact": "Summarize conversation to free up context (e.g., /compact Focus on X)",
    "init": "Explore codebase and create NAMI.MD file",
    "mcp": "Manage MCP servers (install presets, add custom, list, remove)",
    "model": "Manage LLM providers (view, switch between OpenAI, Anthropic, Ollama, Google)",
    "skills": "Manage skills - create or list (e.g., /skills, /skills create, /skills list)",
    "agents": "Manage custom agents - view, create, or delete (e.g., /agents)",
    "sessions": "List and manage saved sessions",
    "save": "Manually save current session (auto-saved on exit)",
    "servers": "List and manage running dev servers",
    "tests": "Run project tests (e.g., /tests or /tests pytest -v)",
    "kill": "Kill a running process by PID or name (e.g., /kill 1234)",
    "exit": "Exit the CLI",
}


# Maximum argument length for display
MAX_ARG_LENGTH = 150

# Tool icons for display in tool calls
TOOL_ICONS = {
    "read_file": "📄",
    "write_file": "✍️",
    "edit_file": "📝",
    "shell": "💻",
    "ls": "📁",
    "glob": "🔍",
    "grep": "🔎",
    "web_search": "🌐",
    "http_request": "📡",
    "fetch_url": "🌍",
    "task": "🤖",
    "write_todos": "📋",
    "mcp": "🔌",
    "run_tests": "🧪",
    "start_dev_server": "🚀",
    "stop_dev_server": "🛑",
    "list_servers": "📋",
    "default": "🔧",
}

# Agent configuration
config = {"recursion_limit": 1000}

# Rich console instance
# Force UTF-8 encoding on Windows to support Unicode characters in ASCII art
if sys.platform == "win32":
    import io

    console = Console(
        highlight=False, file=io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    )
else:
    console = Console(highlight=False)


def _find_project_root(start_path: Path | None = None) -> Path | None:
    """Find the project root by looking for .git directory.

    Walks up the directory tree from start_path (or cwd) looking for a .git
    directory, which indicates the project root.

    Args:
        start_path: Directory to start searching from. Defaults to current working directory.

    Returns:
        Path to the project root if found, None otherwise.
    """
    current = Path(start_path or Path.cwd()).resolve()

    # Walk up the directory tree
    for parent in [current, *list(current.parents)]:
        git_dir = parent / ".git"
        if git_dir.exists():
            return parent

    return None


def _find_project_agent_md(project_root: Path) -> list[Path]:
    """Find project-specific CLAUDE.md and NAMI.md file(s).

    Checks multiple locations and returns ALL that exist (in priority order):
    1. project_root/.claude/CLAUDE.md (Claude Code primary)
    2. project_root/CLAUDE.md (Claude Code fallback)
    3. project_root/.nami/NAMI.md (Nami primary)
    4. project_root/NAMI.md (Nami fallback - created by /init command)

    All files found will be loaded and combined hierarchically.

    Args:
        project_root: Path to the project root directory.

    Returns:
        List of paths to project config files (may contain 0-4 paths).
    """
    paths = []

    # Priority 1: .claude/CLAUDE.md (Claude Code style)
    claude_dir_md = project_root / ".claude" / "CLAUDE.md"
    if claude_dir_md.exists():
        paths.append(claude_dir_md)

    # Priority 2: CLAUDE.md in root (Claude Code fallback)
    root_claude_md = project_root / "CLAUDE.md"
    if root_claude_md.exists():
        paths.append(root_claude_md)

    # Priority 3: .nami/NAMI.md (Nami primary)
    nami_dir_md = project_root / ".nami" / "NAMI.md"
    if nami_dir_md.exists():
        paths.append(nami_dir_md)

    # Priority 4: NAMI.md in root (created by /init command)
    root_nami_md = project_root / "NAMI.md"
    if root_nami_md.exists():
        paths.append(root_nami_md)

    return paths


@dataclass
class Settings:
    """Global settings and environment detection for deepagents-cli.

    This class is initialized once at startup and provides access to:
    - Available models and API keys
    - Current project information
    - Tool availability (e.g., Tavily)
    - File system paths

    Attributes:
        project_root: Current project root directory (if in a git project)

        openai_api_key: OpenAI API key if available
        anthropic_api_key: Anthropic API key if available
        tavily_api_key: Tavily API key if available
    """

    # API keys
    openai_api_key: str | None
    anthropic_api_key: str | None
    google_api_key: str | None
    tavily_api_key: str | None

    # Ollama configuration
    ollama_host: str | None

    # Project information
    project_root: Path | None

    version: str = "1.0.0"

    @classmethod
    def from_environment(cls, *, start_path: Path | None = None) -> "Settings":
        """Create settings by detecting the current environment.

        Args:
            start_path: Directory to start project detection from (defaults to cwd)

        Returns:
            Settings instance with detected configuration
        """
        # Detect API keys
        openai_key = os.environ.get("OPENAI_API_KEY")
        anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
        google_key = os.environ.get("GOOGLE_API_KEY")
        tavily_key = os.environ.get("TAVILY_API_KEY")

        # Detect Ollama host configuration
        ollama_host = os.environ.get("OLLAMA_HOST")

        # Detect project
        project_root = _find_project_root(start_path)

        return cls(
            openai_api_key=openai_key,
            anthropic_api_key=anthropic_key,
            google_api_key=google_key,
            tavily_api_key=tavily_key,
            ollama_host=ollama_host,
            project_root=project_root,
        )

    @property
    def has_openai(self) -> bool:
        """Check if OpenAI API key is configured."""
        return self.openai_api_key is not None

    @property
    def has_anthropic(self) -> bool:
        """Check if Anthropic API key is configured."""
        return self.anthropic_api_key is not None

    @property
    def has_google(self) -> bool:
        """Check if Google API key is configured."""
        return self.google_api_key is not None

    @property
    def has_tavily(self) -> bool:
        """Check if Tavily API key is configured."""
        return self.tavily_api_key is not None

    @property
    def has_project(self) -> bool:
        """Check if currently in a git project."""
        return self.project_root is not None

    @property
    def user_deepagents_dir(self) -> Path:
        """Get the base user-level .nami directory.

        Returns:
            Path to ~/.nami
        """
        return Path.home() / ".nami"

    def get_agents_root_dir(self) -> Path:
        """Get the global agents root directory.

        Returns:
            Path to ~/.nami/agents/
        """
        return self.user_deepagents_dir / "agents"

    def get_project_agents_dir(self) -> Path | None:
        """Get project-level agents directory path.

        Returns:
            Path to {project_root}/.nami/agents/, or None if not in a project
        """
        if not self.project_root:
            return None
        return self.project_root / ".nami" / "agents"

    def ensure_project_agents_dir(self) -> Path | None:
        """Ensure project-level agents directory exists and return its path.

        Returns:
            Path to {project_root}/.nami/agents/, or None if not in a project
        """
        if not self.project_root:
            return None
        agents_dir = self.get_project_agents_dir()
        if agents_dir:
            agents_dir.mkdir(parents=True, exist_ok=True)
        return agents_dir

    def get_all_agents(self) -> list[tuple[str, Path, str]]:
        """Get all available agents from both global and project scopes.

        Returns:
            List of (agent_name, agent_dir_path, scope) tuples.
            scope is either "global" or "project"
        """
        agents: list[tuple[str, Path, str]] = []

        # Global agents (~/.nami/agents/)
        global_agents_dir = self.get_agents_root_dir()
        if global_agents_dir.exists():
            for agent_dir in global_agents_dir.iterdir():
                if agent_dir.is_dir() and (agent_dir / "agent.md").exists():
                    agents.append((agent_dir.name, agent_dir, "global"))

        # Project agents ({project_root}/.nami/agents/)
        project_agents_dir = self.get_project_agents_dir()
        if project_agents_dir and project_agents_dir.exists():
            for agent_dir in project_agents_dir.iterdir():
                if agent_dir.is_dir() and (agent_dir / "agent.md").exists():
                    agents.append((agent_dir.name, agent_dir, "project"))

        return agents

    def find_agent(self, agent_name: str) -> tuple[Path, str] | None:
        """Find an agent by name, checking project scope first then global.

        Project-specific agents take precedence over global agents with the same name.

        Args:
            agent_name: Name of the agent to find

        Returns:
            Tuple of (agent_dir_path, scope) if found, None otherwise
        """
        # Check project agents first (higher priority)
        project_agents_dir = self.get_project_agents_dir()
        if project_agents_dir:
            project_agent_dir = project_agents_dir / agent_name
            if project_agent_dir.exists() and (project_agent_dir / "agent.md").exists():
                return (project_agent_dir, "project")

        # Check global agents
        global_agent_dir = self.get_agents_root_dir() / agent_name
        if global_agent_dir.exists() and (global_agent_dir / "agent.md").exists():
            return (global_agent_dir, "global")

        return None

    def get_global_skills_dir(self) -> Path:
        """Get the global skills directory (shared across all agents).

        Returns:
            Path to ~/.nami/skills/
        """
        return self.user_deepagents_dir / "skills"

    def get_user_agent_md_path(self, agent_name: str) -> Path:
        """Get user-level agent.md path for a specific agent.

        Returns path regardless of whether the file exists.

        Args:
            agent_name: Name of the agent

        Returns:
            Path to ~/.nami/agents/{agent_name}/agent.md
        """
        return self.get_agents_root_dir() / agent_name / "agent.md"

    def get_project_agent_md_path(self) -> Path | None:
        """Get project-level agent.md path (legacy single-file method).

        DEPRECATED: Use get_project_agent_md_paths() for full multi-file support.

        Returns path regardless of whether the file exists.

        Returns:
            Path to {project_root}/.nami/agent.md, or None if not in a project
        """
        if not self.project_root:
            return None
        return self.project_root / ".nami" / "agent.md"

    def get_project_agent_md_paths(self) -> list[Path]:
        """Get all project-level memory file paths (CLAUDE.md, NAMI.md).

        Finds all existing memory files and returns them in priority order.
        All found files will be loaded and combined hierarchically.

        Search locations (in order):
        1. {project_root}/.claude/CLAUDE.md (Claude Code primary)
        2. {project_root}/CLAUDE.md (Claude Code fallback)
        3. {project_root}/.nami/NAMI.md (Nami primary)
        4. {project_root}/NAMI.md (Nami fallback - created by /init command)

        Returns:
            List of existing paths (may be empty if not in a project or no files found)
        """
        if not self.project_root:
            return []
        return _find_project_agent_md(self.project_root)

    @staticmethod
    def _is_valid_agent_name(agent_name: str) -> bool:
        """Validate prevent invalid filesystem paths and security issues."""
        if not agent_name or not agent_name.strip():
            return False
        # Allow only alphanumeric, hyphens, underscores, and whitespace
        return bool(re.match(r"^[a-zA-Z0-9_\-\s]+$", agent_name))

    def get_agent_dir(self, agent_name: str) -> Path:
        """Get the global agent directory path.

        Args:
            agent_name: Name of the agent

        Returns:
            Path to ~/.nami/agents/{agent_name}
        """
        if not self._is_valid_agent_name(agent_name):
            msg = (
                f"Invalid agent name: {agent_name!r}. "
                "Agent names can only contain letters, numbers, hyphens, underscores, and spaces."
            )
            raise ValueError(msg)
        return self.get_agents_root_dir() / agent_name

    def ensure_agent_dir(self, agent_name: str) -> Path:
        """Ensure the global agent directory exists and return its path.

        Args:
            agent_name: Name of the agent

        Returns:
            Path to ~/.nami/agents/{agent_name}
        """
        if not self._is_valid_agent_name(agent_name):
            msg = (
                f"Invalid agent name: {agent_name!r}. "
                "Agent names can only contain letters, numbers, hyphens, underscores, and spaces."
            )
            raise ValueError(msg)
        agent_dir = self.get_agent_dir(agent_name)
        agent_dir.mkdir(parents=True, exist_ok=True)
        return agent_dir

    def ensure_project_deepagents_dir(self) -> Path | None:
        """Ensure the project .nami directory exists and return its path.

        Returns:
            Path to project .nami directory, or None if not in a project
        """
        if not self.project_root:
            return None

        project_deepagents_dir = self.project_root / ".nami"
        project_deepagents_dir.mkdir(parents=True, exist_ok=True)
        return project_deepagents_dir

    def get_user_skills_dir(self, agent_name: str | None = None) -> Path:
        """Get user-level skills directory path (global, shared across agents).

        Args:
            agent_name: DEPRECATED - kept for backward compatibility, ignored.
                       Skills are now global at ~/.nami/skills/

        Returns:
            Path to ~/.nami/skills/ (global skills directory)
        """
        # Skills are now global, not per-agent
        return self.get_global_skills_dir()

    def ensure_user_skills_dir(self, agent_name: str | None = None) -> Path:
        """Ensure user-level skills directory exists and return its path.

        Args:
            agent_name: DEPRECATED - kept for backward compatibility, ignored.
                       Skills are now global at ~/.nami/skills/

        Returns:
            Path to ~/.nami/skills/ (global skills directory)
        """
        # Skills are now global, not per-agent
        skills_dir = self.get_global_skills_dir()
        skills_dir.mkdir(parents=True, exist_ok=True)
        return skills_dir

    def get_project_skills_dir(self) -> Path | None:
        """Get project-level skills directory path (legacy .nami/skills/).

        Returns:
            Path to {project_root}/.nami/skills/, or None if not in a project
        """
        if not self.project_root:
            return None
        return self.project_root / ".nami" / "skills"

    def get_project_skills_dirs(self) -> list[Path]:
        """Get all project-level skills directories (both .claude/ and .nami/).

        Checks both:
        - {project_root}/.claude/skills/
        - {project_root}/.nami/skills/

        Returns:
            List of existing skills directory paths (may be empty if not in a project)
        """
        if not self.project_root:
            return []

        from namicode_cli.project_utils import find_project_skills

        return find_project_skills(self.project_root)

    def ensure_project_skills_dir(self) -> Path | None:
        """Ensure project-level skills directory exists and return its path.

        Returns:
            Path to {project_root}/.nami/skills/, or None if not in a project
        """
        if not self.project_root:
            return None
        skills_dir = self.get_project_skills_dir()
        if skills_dir:
            skills_dir.mkdir(parents=True, exist_ok=True)
        return skills_dir


# Global settings instance (initialized once)
settings = Settings.from_environment()


class SessionState:
    """Holds mutable session state (auto-approve mode, etc)."""

    def __init__(self, auto_approve: bool = False, no_splash: bool = False) -> None:
        self.auto_approve = auto_approve
        self.no_splash = no_splash
        self.exit_hint_until: float | None = None
        self.exit_hint_handle = None
        self.thread_id = str(uuid.uuid4())
        # Session persistence fields
        self.session_id: str | None = None
        self.is_continued: bool = False
        self.todos: list[dict] | None = None

    def toggle_auto_approve(self) -> bool:
        """Toggle auto-approve and return new state."""
        self.auto_approve = not self.auto_approve
        return self.auto_approve


def get_default_coding_instructions() -> str:
    """Get the default coding agent instructions.

    These are the immutable base instructions that cannot be modified by the agent.
    Long-term memory (agent.md) is handled separately by the middleware.
    """
    default_prompt_path = Path(__file__).parent / "default_agent_prompt.md"
    return default_prompt_path.read_text()


def create_model() -> BaseChatModel:
    """Create the appropriate model based on available API keys.

    Priority order:
    1. Saved configuration from nami.config.json (highest priority)
    2. Environment variables from .env file
    3. Default to Ollama (fallback)

    Returns:
        ChatModel instance (OpenAI, Anthropic, Google, or Ollama)
    """
    # Load saved configuration - this takes precedence over .env
    from namicode_cli.nami_config import NamiConfig

    nami_config = NamiConfig()
    saved_model_config = nami_config.get_model_config()

    # If we have a saved config, use it directly (bypasses .env settings)
    if saved_model_config:
        provider = saved_model_config["provider"]
        model_name = saved_model_config["model"]

        console.print(f"[dim]Using saved configuration: {provider}/{model_name}[/dim]")

        # Create model directly based on saved config
        if provider == "ollama":
            from langchain_ollama import ChatOllama

            return ChatOllama(
                model=model_name,
                temperature=0,
                disable_streaming=True,
                keep_alive=600,
                num_ctx=200000,
            )

        elif provider == "openai":
            from langchain_openai import ChatOpenAI

            # Verify API key is available
            if not os.environ.get("OPENAI_API_KEY"):
                console.print(
                    "[yellow]Warning: OPENAI_API_KEY not set, falling back to Ollama[/yellow]"
                )
            else:
                return ChatOpenAI(model=model_name)

        elif provider == "anthropic":
            from langchain_anthropic import ChatAnthropic

            # Verify API key is available
            if not os.environ.get("ANTHROPIC_API_KEY"):
                console.print(
                    "[yellow]Warning: ANTHROPIC_API_KEY not set, falling back to Ollama[/yellow]"
                )
            else:
                return ChatAnthropic(
                    model_name=model_name,
                    max_tokens=20_000,  # type: ignore[arg-type]
                )

        elif provider == "google":
            from langchain_google_genai import ChatGoogleGenerativeAI

            # Verify API key is available
            if not os.environ.get("GOOGLE_API_KEY"):
                console.print(
                    "[yellow]Warning: GOOGLE_API_KEY not set, falling back to Ollama[/yellow]"
                )
            else:
                return ChatGoogleGenerativeAI(
                    model=model_name,
                    temperature=0,
                    max_tokens=None,
                )

    # No saved config - fall back to environment variables and .env file
    # Check available API keys in order of priority
    if settings.has_openai:
        from langchain_openai import ChatOpenAI

        model_name = os.environ.get("OPENAI_MODEL", "gpt-5-mini")
        console.print(f"[dim]Using OpenAI model: {model_name}[/dim]")
        return ChatOpenAI(
            model=model_name,
        )
    if settings.has_anthropic:
        from langchain_anthropic import ChatAnthropic

        model_name = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5-20250929")
        console.print(f"[dim]Using Anthropic model: {model_name}[/dim]")
        return ChatAnthropic(
            model_name=model_name,
            # The attribute exists, but it has a Pydantic alias which
            # causes issues in IDEs/type checkers.
            max_tokens=20_000,  # type: ignore[arg-type]
        )
    if settings.has_google:
        from langchain_google_genai import ChatGoogleGenerativeAI

        model_name = os.environ.get("GOOGLE_MODEL", "gemini-3-pro-preview")
        console.print(f"[dim]Using Google Gemini model: {model_name}[/dim]")
        return ChatGoogleGenerativeAI(
            model=model_name,
            temperature=0,
            max_tokens=None,
        )

    # Default to Ollama if no API keys are configured
    from langchain_ollama import ChatOllama

    model_name = os.environ.get("OLLAMA_MODEL", "qwen3-coder:480b-cloud")
    console.print(
        f"[dim]No API keys configured. Defaulting to Ollama model: {model_name}[/dim]"
    )
    return ChatOllama(
        model=model_name,
        temperature=0,
        disable_streaming=True,
        keep_alive=600,
        num_ctx=200000,
    )

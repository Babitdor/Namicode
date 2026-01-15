"""Configuration, constants, and model creation for the CLI.

This module provides centralized configuration management for the CLI, including:
- Color scheme and UI styling constants
- Environment variable parsing and settings management
- Project root detection and working directory management
- Rich console initialization with proper encoding

Key Components:
- create_model(): Factory function for creating chat models from configuration
- settings(): Global settings object with environment variable access
- COLORS: Color scheme constants for UI styling
- ASCII art banner for CLI startup

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

# Home directory for Nami configuration
HOME_DIR = Path.home() / ".nami"

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
    "subagent": "#30c3f0",  # Medium red (sub-agent messages)
}

# Agent color registry - stores colors for custom agents
_agent_colors: dict[str, str] = {}


def extract_agent_description(agent_md: Path) -> str:
    """Extract description from agent.md YAML frontmatter or first content line.

    Args:
        agent_md: Path to the agent.md file.

    Returns:
        Extracted description string.
    """
    try:
        content = agent_md.read_text(encoding="utf-8")

        # YAML front-matter
        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                front_matter = parts[1]
                for line in front_matter.splitlines():
                    line = line.strip()
                    if line.startswith("description:"):
                        return line.split(":", 1)[1].strip()[:80]

        # Fallback: first non-empty, non-heading line
        for line in content.splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                return (line[:80] + "...") if len(line) > 80 else line

    except Exception:
        pass

    return "[unable to read]"


def get_agent_color(agent_name: str) -> str:
    """Get the color for an agent by name.

    Args:
        agent_name: The name of the agent.

    Returns:
        The color string (hex or name), or default subagent color if not set.
    """
    return _agent_colors.get(agent_name, COLORS["subagent"])


def set_agent_color(agent_name: str, color: str) -> None:
    """Set the color for an agent.

    Args:
        agent_name: The name of the agent.
        color: The color string (hex code like '#ef4444' or color name).
    """
    _agent_colors[agent_name] = color


def clear_agent_colors() -> None:
    """Clear all registered agent colors."""
    _agent_colors.clear()


def parse_agent_color(agent_md_path: Path) -> str | None:
    """Parse color from agent.md YAML frontmatter.

    Looks for a color field in YAML frontmatter at the start of the file:
    ```
    ---
    color: #ef4444
    ---
    ```

    Args:
        agent_md_path: Path to the agent.md file.

    Returns:
        Color string if found, None otherwise.
    """
    try:
        content = agent_md_path.read_text(encoding="utf-8")

        # Match YAML frontmatter between --- delimiters
        frontmatter_pattern = r"^---\s*\n(.*?)\n---\s*\n"
        match = re.match(frontmatter_pattern, content, re.DOTALL)

        if not match:
            return None

        frontmatter = match.group(1)

        # Parse color from frontmatter
        for line in frontmatter.split("\n"):
            kv_match = re.match(r"^color:\s*(.+)$", line.strip())
            if kv_match:
                return kv_match.group(1).strip().strip('"').strip("'")

        return None
    except Exception:
        return None


# ASCII art banner - Sleek red design
NAMI_CODE_ASCII = """
                                                                     
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
    "trace": "Manage LangSmith tracing (status, enable, disable, projects)",
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


def find_project_skills(project_root: Path) -> list[Path]:
    """Find project-specific skills directories.

    Checks for skills in both .claude/ and .nami/ directories.

    Args:
        project_root: Path to the project root directory.

    Returns:
        List of skills directory paths that exist.
    """
    skills_dirs = []

    # Check .claude/skills/
    claude_skills = project_root / ".claude" / "skills"
    if claude_skills.exists() and claude_skills.is_dir():
        skills_dirs.append(claude_skills)

    # Check .nami/skills/
    deepagents_skills = project_root / ".nami" / "skills"
    if deepagents_skills.exists() and deepagents_skills.is_dir():
        skills_dirs.append(deepagents_skills)

    return skills_dirs


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


def _find_project_agent_md(project_root: Path) -> Path | None:
    """Find project-specific CLAUDE.md and NAMI.md file(s).

    Checks multiple locations and returns one that exist (in priority order):
    1. project_root/.claude/CLAUDE.md (Claude Code primary)
    2. project_root/CLAUDE.md (Claude Code fallback)
    3. project_root/.nami/NAMI.md (Nami primary)
    4. project_root/NAMI.md (Nami fallback - created by /init command)

    Args:
        project_root: Path to the project root directory.

    Returns:
        paths to project config files.
    """

    # Priority 1: .claude/CLAUDE.md (Claude Code style)
    claude_dir_md = project_root / ".claude" / "CLAUDE.md"
    if claude_dir_md.exists():
        return claude_dir_md

    # Priority 2: CLAUDE.md in root (Claude Code fallback)
    root_claude_md = project_root / "CLAUDE.md"
    if root_claude_md.exists():
        return root_claude_md

    # Priority 3: .nami/NAMI.md (Nami primary)
    nami_dir_md = project_root / ".nami" / "NAMI.md"
    if nami_dir_md.exists():
        return nami_dir_md

    # Priority 4: NAMI.md in root (created by /init command)
    root_nami_md = project_root / "NAMI.md"
    if root_nami_md.exists():
        return root_nami_md


def get_default_coding_instructions() -> str:
    """Get the default coding agent instructions.

    These are the immutable base instructions that cannot be modified by the agent.
    Long-term memory (agent.md) is handled separately by the middleware.
    """
    default_prompt_path = Path(__file__).parent / "default_agent_prompt.md"
    return default_prompt_path.read_text(encoding="utf-8")


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
    langsmith_api_key: str | None

    # Ollama configuration
    ollama_host: str | None

    # Project information
    project_root: Path | None

    # LangSmith configuration
    langsmith_project: str = "Nami-Code"
    langsmith_workspace_id: str | None = None
    langsmith_tracing_enabled: bool = False

    version: str = "1.0.0"

    @classmethod
    def from_environment(cls, *, start_path: Path | None = None) -> "Settings":
        """Create settings by detecting the current environment.

        Priority order for API keys:
        1. OS keychain (via SecretManager)
        2. Environment variables
        3. None (not configured)

        Args:
            start_path: Directory to start project detection from (defaults to cwd)

        Returns:
            Settings instance with detected configuration
        """
        # Import SecretManager here to avoid circular imports
        # (SecretManager imports from config, config imports SecretManager)
        try:
            from namicode_cli.onboarding import SecretManager

            secret_manager = SecretManager()
        except ImportError:
            # If onboarding module not available yet, skip keyring
            secret_manager = None

        # Detect API keys - check keyring first, then environment variables
        if secret_manager:
            openai_key = secret_manager.get_secret("openai_api_key") or os.environ.get(
                "OPENAI_API_KEY"
            )
            anthropic_key = secret_manager.get_secret(
                "anthropic_api_key"
            ) or os.environ.get("ANTHROPIC_API_KEY")
            google_key = secret_manager.get_secret("google_api_key") or os.environ.get(
                "GOOGLE_API_KEY"
            )
            tavily_key = secret_manager.get_secret("tavily_api_key") or os.environ.get(
                "TAVILY_API_KEY"
            )
        else:
            openai_key = os.environ.get("OPENAI_API_KEY")
            anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
            google_key = os.environ.get("GOOGLE_API_KEY")
            tavily_key = os.environ.get("TAVILY_API_KEY")

        langsmith_key = os.environ.get("LANGSMITH_API_KEY")

        # Detect Ollama host configuration
        ollama_host = os.environ.get("OLLAMA_HOST")

        # Detect project
        project_root = _find_project_root(start_path)

        # LangSmith configuration
        langsmith_enabled = os.environ.get("LANGSMITH_TRACING", "").lower() == "true"
        langsmith_project = os.environ.get("LANGSMITH_PROJECT", "Nami-Code")
        langsmith_workspace = os.environ.get("LANGSMITH_WORKSPACE_ID")

        return cls(
            openai_api_key=openai_key,
            anthropic_api_key=anthropic_key,
            google_api_key=google_key,
            tavily_api_key=tavily_key,
            langsmith_api_key=langsmith_key,
            ollama_host=ollama_host,
            project_root=project_root,
            langsmith_project=langsmith_project,
            langsmith_workspace_id=langsmith_workspace,
            langsmith_tracing_enabled=langsmith_enabled,
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
    def has_langsmith(self) -> bool:
        """Check if LangSmith is configured and enabled."""
        return self.langsmith_api_key is not None and self.langsmith_tracing_enabled

    @property
    def has_project(self) -> bool:
        """Check if currently in a git project."""
        return self.project_root is not None

    def get_onboarding_status(self) -> bool:
        """Check if onboarding has been completed.

        Returns:
            True if onboarding completed, False otherwise
        """
        config_file = HOME_DIR / "config.json"
        onboarded_marker = HOME_DIR / ".onboarded"

        # Check if either marker exists
        if onboarded_marker.exists():
            return True

        # Check config.json for onboarding_completed flag
        if config_file.exists():
            try:
                import json

                config = json.loads(config_file.read_text(encoding="utf-8"))
                return config.get("onboarding_completed", False)
            except Exception:  # noqa: BLE001, S110
                return False

        return False

    def mark_onboarding_complete(self) -> None:
        """Mark onboarding as completed.

        Creates completion markers in config.json and .onboarded file.
        """
        import json

        config_file = HOME_DIR / "config.json"
        onboarded_marker = HOME_DIR / ".onboarded"

        # Update config.json
        config = {}
        if config_file.exists():
            try:
                config = json.loads(config_file.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001, S110
                pass

        config["onboarding_completed"] = True
        config_file.parent.mkdir(parents=True, exist_ok=True)
        config_file.write_text(json.dumps(config, indent=2), encoding="utf-8")

        # Create marker file
        onboarded_marker.touch()

    @property
    def user_deepagents_dir(self) -> Path:
        """Get the base user-level .nami directory.

        Returns:
            Path to ~/.nami
        """
        return HOME_DIR

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
            Path to {project_root}/.nami/NAMI.md, or None if not in a project
        """
        if not self.project_root:
            return None
        return self.project_root / ".nami" / "NAMI.md"

    def get_project_agent_md_paths(self) -> Path | None:
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
            return None
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
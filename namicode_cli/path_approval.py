"""Path approval system for controlling access to directories."""

import json
from pathlib import Path
from typing import Optional

from rich.panel import Panel
from rich.text import Text

from .config.config import COLORS, console


class PathApprovalManager:
    """Manages approved paths for nami access."""

    def __init__(self):
        """Initialize the path approval manager."""
        self.config_dir = Path.home() / ".nami"
        self.config_file = self.config_dir / "approved_paths.json"
        self._approved_paths = self._load_approved_paths()

    def _load_approved_paths(self) -> dict:
        """Load approved paths from config file."""
        if not self.config_file.exists():
            return {}

        try:
            with open(self.config_file, "r") as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_approved_paths(self) -> None:
        """Save approved paths to config file."""
        self.config_dir.mkdir(parents=True, exist_ok=True)
        with open(self.config_file, "w") as f:
            json.dump(self._approved_paths, f, indent=2)

    def is_path_approved(self, path: Path) -> bool:
        """Check if a path is approved for access.

        Args:
            path: The path to check

        Returns:
            True if the path or any parent is approved, False otherwise
        """
        path = path.resolve()
        path_str = str(path)

        # Check exact match
        if path_str in self._approved_paths:
            return True

        # Check if any parent directory is approved with recursive access
        for approved_path_str, config in self._approved_paths.items():
            approved_path = Path(approved_path_str)
            if config.get("recursive", False):
                try:
                    # Check if current path is under the approved path
                    path.relative_to(approved_path)
                    return True
                except ValueError:
                    # Not a subdirectory
                    continue

        return False

    def approve_path(self, path: Path, recursive: bool = True) -> None:
        """Approve a path for access.

        Args:
            path: The path to approve
            recursive: If True, also approve all subdirectories
        """
        path = path.resolve()
        path_str = str(path)

        self._approved_paths[path_str] = {
            "recursive": recursive,
            "approved_at": Path.cwd().as_posix(),
        }
        self._save_approved_paths()

    def revoke_path(self, path: Path) -> bool:
        """Revoke approval for a path.

        Args:
            path: The path to revoke

        Returns:
            True if path was revoked, False if it wasn't approved
        """
        path = path.resolve()
        path_str = str(path)

        if path_str in self._approved_paths:
            del self._approved_paths[path_str]
            self._save_approved_paths()
            return True
        return False

    def list_approved_paths(self) -> dict:
        """Get all approved paths.

        Returns:
            Dictionary of approved paths and their configurations
        """
        return self._approved_paths.copy()

    async def prompt_for_approval(self, path: Path) -> bool:
        """Prompt user to approve a path.

        Args:
            path: The path requesting approval

        Returns:
            True if user approved, False otherwise
        """
        console.print()

        # Create header
        header = Text()
        header.append("🔒 ", style="yellow")
        header.append("Path Access Request", style=f"bold yellow")

        # Create message
        message_lines = [
            f"Nami is requesting access to:",
            "",
            f"  📁 {path}",
            "",
            "This allows nami to:",
            "  • Read files in this directory",
            "  • Write and modify files",
            "  • Execute commands in this context",
            "",
            "Do you want to grant access?",
        ]

        panel = Panel(
            "\n".join(message_lines),
            title=header,
            border_style="yellow",
            padding=(1, 2),
        )
        console.print(panel)
        console.print()

        # Prompt for approval
        console.print("[bold]Options:[/bold]")
        console.print("  [green]y[/green] - Yes, approve this directory and subdirectories")
        console.print("  [green]o[/green] - Yes, approve only this directory (not subdirectories)")
        console.print("  [red]n[/red] - No, deny access")
        console.print()

        while True:
            try:
                from prompt_toolkit import PromptSession

                session = PromptSession()
                choice = await session.prompt_async("Your choice (y/o/n): ")
                choice = choice.strip().lower()

                if choice in ["y", "yes"]:
                    self.approve_path(path, recursive=True)
                    console.print()
                    console.print("✅ ", style="green", end="")
                    console.print("[green]Access granted (including subdirectories)[/green]")
                    console.print()
                    return True
                elif choice in ["o", "only"]:
                    self.approve_path(path, recursive=False)
                    console.print()
                    console.print("✅ ", style="green", end="")
                    console.print("[green]Access granted (this directory only)[/green]")
                    console.print()
                    return True
                elif choice in ["n", "no"]:
                    console.print()
                    console.print("❌ ", style="red", end="")
                    console.print("[red]Access denied[/red]")
                    console.print()
                    return False
                else:
                    console.print("[yellow]Invalid choice. Please enter y, o, or n.[/yellow]")
            except (EOFError, KeyboardInterrupt):
                console.print()
                console.print("❌ ", style="red", end="")
                console.print("[red]Access denied[/red]")
                console.print()
                return False


async def check_path_approval(path: Optional[Path] = None) -> bool:
    """Check if the current path is approved, prompting if needed.

    Args:
        path: The path to check (defaults to current directory)

    Returns:
        True if approved, False otherwise
    """
    if path is None:
        path = Path.cwd()

    manager = PathApprovalManager()

    if manager.is_path_approved(path):
        return True

    return await manager.prompt_for_approval(path)

#!/usr/bin/env python3
"""
Ralph Mode - Autonomous looping for DeepAgents

Ralph is an autonomous looping pattern created by Geoff Huntley.
Each loop starts with fresh context. The filesystem and git serve as memory.

Usage:
    uv pip install deepagents-cli
    python ralph_mode.py "Build a Python course. Use git."
    python ralph_mode.py "Build a REST API" --iterations 5
    python ralph_mode.py "Create a CLI tool" --workdir ./my-project
"""
import warnings

warnings.filterwarnings("ignore", message="Core Pydantic V1 functionality")

import argparse
import asyncio
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional

from namicode_cli.agents.core_agent import create_agent_with_config
from namicode_cli.config.config import console, COLORS
from namicode_cli.states.Session import SessionState
from namicode_cli.config.model_create import create_model
from namicode_cli.config.model_manager import ModelManager
from namicode_cli.ui.execution import execute_task
from namicode_cli.ui.ui_elements import TokenTracker


def initialize_git_repo(work_dir: Path, auto_commit: bool = False):
    """Initialize a git repository in the work directory."""
    try:
        subprocess.run(
            ["git", "init"],
            cwd=work_dir,
            check=True,
            capture_output=True,
        )

        # Create a .gitignore file
        gitignore = work_dir / ".gitignore"
        if not gitignore.exists():
            gitignore.write_text(
                "__pycache__/\n*.pyc\n.DS_Store\n*.egg-info/\ndist/\nbuild/\n.venv/\nvenv/\n"
            )

        if auto_commit:
            subprocess.run(
                ["git", "add", "."],
                cwd=work_dir,
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["git", "commit", "-m", "Initial commit - Ralph Mode"],
                cwd=work_dir,
                check=True,
                capture_output=True,
            )

        console.print(f"[green]✓[/green] Git repository initialized in {work_dir}")
        return True
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        console.print(f"[yellow]⚠[/yellow] Could not initialize git: {e}")
        return False


def commit_iteration(work_dir: Path, iteration: int):
    """Commit the current state of the work directory."""
    try:
        subprocess.run(
            ["git", "add", "-A"],
            cwd=work_dir,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            [
                "git",
                "commit",
                "-m",
                f"Ralph iteration {iteration} - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            ],
            cwd=work_dir,
            check=True,
            capture_output=True,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def show_summary(work_dir: Path, iteration: int, start_time: datetime):
    """Show a summary of the Ralph session."""
    elapsed = datetime.now() - start_time

    console.print(f"\n[bold {COLORS['primary']}]{'='*60}[/bold {COLORS['primary']}]")
    console.print(
        f"[bold {COLORS['primary']}]RALPH SESSION SUMMARY[/bold {COLORS['primary']}]"
    )
    console.print(f"[bold {COLORS['primary']}]{'='*60}[/bold {COLORS['primary']}]\n")

    console.print(f"[bold]Iterations completed:[/bold] {iteration}")
    console.print(f"[bold]Duration:[/bold] {elapsed}")
    console.print(f"[bold]Working directory:[/bold] {work_dir}\n")

    # Count files and directories
    files = sum(1 for f in work_dir.rglob("*") if f.is_file() and ".git" not in str(f))
    dirs = sum(1 for d in work_dir.rglob("*") if d.is_dir() and ".git" not in str(d))

    console.print(f"[bold]Files created:[/bold] {files}")
    console.print(f"[bold]Directories created:[/bold] {dirs}\n")

    # Show git history if available
    if (work_dir / ".git").exists():
        try:
            result = subprocess.run(
                ["git", "log", "--oneline"],
                cwd=work_dir,
                check=True,
                capture_output=True,
                text=True,
            )
            if result.stdout.strip():
                console.print("[bold]Git history:[/bold]")
                for line in result.stdout.strip().split("\n")[
                    :10
                ]:  # Show last 10 commits
                    console.print(f"  {line}")
        except (subprocess.CalledProcessError, FileNotFoundError):
            pass

    # Show created files (limited to prevent overflow)
    console.print(f"\n[bold]Files created:[/bold]")
    file_list = sorted(
        [
            f.relative_to(work_dir)
            for f in work_dir.rglob("*")
            if f.is_file() and ".git" not in str(f)
        ]
    )

    for i, f in enumerate(file_list):
        if i >= 20:  # Limit to 20 files
            console.print(f"  ... and {len(file_list) - 20} more files", style="dim")
            break
        console.print(f"  {f}", style="dim")


async def ralph(
    task: str,
    max_iterations: int = 0,
    work_dir: Optional[Path] = None,
    model_name: Optional[str] = "glm-4.7:cloud",
    provider: Optional[str] = "ollama",
    auto_commit: bool = False,
    commit_each: bool = False,
):
    """Run agent in Ralph loop with beautiful CLI output."""
    # Determine working directory
    if work_dir is None:
        work_dir = Path(tempfile.mkdtemp(prefix="ralph-"))
    else:
        work_dir = Path(work_dir)
        work_dir.mkdir(parents=True, exist_ok=True)

    # Create model
    if model_name and provider:
        model_manager = ModelManager()
        try:
            model = model_manager.create_model_for_provider(
                provider=provider, model_name=model_name  # type: ignore
            )
        except (ValueError, KeyError) as e:
            console.print(f"[red]✗[/red] Invalid model '{model_name}': {e}")
            console.print(f"[yellow]Using default model instead[/yellow]")
            model = create_model()
    else:
        model = create_model()

    # Create agent
    agent, backend = create_agent_with_config(
        model=model,
        assistant_id="ralph",
        tools=[],
        auto_approve=True,
    )
    session_state = SessionState(auto_approve=True)
    token_tracker = TokenTracker()

    # Initialize git if requested
    git_initialized = False
    if auto_commit or commit_each:
        git_initialized = initialize_git_repo(work_dir, auto_commit=auto_commit)

    # Print header
    console.print(f"\n[bold {COLORS['primary']}]Ralph Mode[/bold {COLORS['primary']}]")
    console.print(f"[dim]Task: {task}[/dim]")
    console.print(
        f"[dim]Iterations: {'unlimited (Ctrl+C to stop)' if max_iterations == 0 else max_iterations}[/dim]"
    )
    console.print(f"[dim]Working directory: {work_dir}[/dim]")
    console.print(f"[dim]Model: {model_name}[/dim]")
    console.print(f"[dim]Auto-commit: {git_initialized}[/dim]\n")

    iteration = 1
    start_time = datetime.now()

    try:
        while max_iterations == 0 or iteration <= max_iterations:
            console.print(f"\n[bold cyan]{'='*60}[/bold cyan]")
            console.print(f"[bold cyan]RALPH ITERATION {iteration}[/bold cyan]")
            console.print(f"[bold cyan]{'='*60}[/bold cyan]\n")

            iter_display = (
                f"{iteration}/{max_iterations}"
                if max_iterations > 0
                else str(iteration)
            )

            prompt = f"""## Iteration {iter_display}

Your previous work is in the filesystem. Check what exists and keep building.

TASK:
{task}

Make progress. You'll be called again."""

            await execute_task(
                prompt,
                agent,
                "ralph",
                session_state,
                token_tracker,
                backend=backend,
            )

            # Commit after each iteration if requested
            if commit_each and git_initialized:
                if commit_iteration(work_dir, iteration):
                    console.print(f"[green]✓[/green] Committed iteration {iteration}")

            if max_iterations == 0 or iteration < max_iterations:
                console.print(
                    f"\n[dim]...continuing to iteration {iteration + 1}[/dim]"
                )
            iteration += 1

    except KeyboardInterrupt:
        console.print(
            f"\n[bold yellow]Stopped after {iteration} iterations[/bold yellow]"
        )
    except Exception as e:
        console.print(f"\n[red]✗[/red] Error during iteration {iteration}: {e}")
        import traceback

        console.print(traceback.format_exc())
    finally:
        # Show summary
        show_summary(work_dir, iteration - 1, start_time)


def main():
    parser = argparse.ArgumentParser(
        description="Ralph Mode - Autonomous looping for DeepAgents",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic usage (unlimited iterations, temp directory)
  python ralph_mode.py "Build a Python course. Use git."

  # Limited iterations
  python ralph_mode.py "Build a REST API" --iterations 5

  # Use specific working directory (preserved after session)
  python ralph_mode.py "Create a CLI tool" --workdir ./my-project

  # Use a different model
  python ralph_mode.py "Build a website" --model claude-haiku-4-5-20251001

  # Initialize git and auto-commit after each iteration
  python ralph_mode.py "Build a React app" --git --commit-each

  # Initialize git with initial commit only
  python ralph_mode.py "Build a Docker setup" --git
        """,
    )
    parser.add_argument("task", help="Task to work on (declarative, what you want)")
    parser.add_argument(
        "--iterations",
        type=int,
        default=0,
        help="Max iterations (0 = unlimited, default: unlimited)",
    )
    parser.add_argument(
        "--workdir",
        type=str,
        default=None,
        help="Working directory (default: temporary directory, deleted after session)",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Model to use (e.g., claude-opus-4-5-20251001, claude-haiku-4-5-20251001)",
    )
    parser.add_argument(
        "--provider",
        type=str,
        default=None,
        help="Model to use (e.g., claude-opus-4-5-20251001, claude-haiku-4-5-20251001)",
    )
    parser.add_argument(
        "--git",
        action="store_true",
        help="Initialize git repository in working directory",
    )
    parser.add_argument(
        "--commit-each",
        action="store_true",
        help="Auto-commit after each iteration (requires --git)",
    )
    args = parser.parse_args()

    # Validate commit-each requires git
    if args.commit_each and not args.git:
        parser.error("--commit-each requires --git")

    try:
        asyncio.run(
            ralph(
                task=args.task,
                max_iterations=args.iterations,
                work_dir=Path(args.workdir) if args.workdir else None,
                model_name=args.model,
                auto_commit=args.git,
                commit_each=args.commit_each,
            )
        )
    except KeyboardInterrupt:
        pass  # Clean exit on Ctrl+C


if __name__ == "__main__":
    main()

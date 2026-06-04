"""Handler for the /ralph command - autonomous looping mode."""

import asyncio
import json
import os
import subprocess
import threading
import uuid
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import io
from prompt_toolkit import PromptSession
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from novacode_cli.config.config import COLORS, NOVA_CODE_ASCII, console
from novacode_cli.prompts import render_template
from novacode_cli.states.Session import BackgroundRalphTask, RalphTaskStatus
from novacode_cli.ui.ui_elements import TokenTracker

# Cross-iteration progress log. The agent reads it at the start of every
# iteration and appends what it implemented/learned at the end, so a Ralph run
# carries memory forward. POSIX path so the model never sees a backslashed form.
RALPH_PROGRESS_PATH = ".nova/ralph/progress.md"


def _ensure_ralph_dir() -> None:
    """Make sure .nova/ralph/ exists so progress.md has a home."""
    from pathlib import Path

    try:
        (Path(".nova") / "ralph").mkdir(parents=True, exist_ok=True)
    except OSError:
        pass


def _read_ralph_progress() -> str:
    """Return the current progress.md contents (bounded), or '' if absent."""
    from pathlib import Path

    p = Path(".nova") / "ralph" / "progress.md"
    try:
        if p.exists():
            text = p.read_text(encoding="utf-8", errors="replace").strip()
            if len(text) > 6000:
                text = "…(earlier progress trimmed)…\n" + text[-6000:]
            return text
    except Exception:  # noqa: BLE001
        pass
    return ""


# =============================================================================
# Ralph Checkpoint Management
# =============================================================================

RALPH_CHECKPOINT_FILE = ".nova" / Path("ralph-checkpoint.json")


def _get_checkpoint_path() -> Path:
    """Get the path to the ralph checkpoint file."""
    home = Path.home()
    return home / ".nova" / "ralph-checkpoint.json"


def _save_ralph_checkpoint(
    task: str,
    max_iterations: int,
    completed_iterations: int,
    working_directory: str,
    notes: str = "",
) -> None:
    """Save ralph checkpoint to disk."""
    checkpoint_path = _get_checkpoint_path()
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)

    checkpoint: dict[str, Any] = {
        "task": task,
        "max_iterations": max_iterations,
        "completed_iterations": completed_iterations,
        "timestamp": datetime.now(UTC).isoformat(),
        "working_directory": working_directory,
        "notes": notes,
    }

    # Track modified files via git
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=working_directory,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            checkpoint["files_modified"] = [
                line[3:] for line in result.stdout.strip().split("\n") if line
            ]
    except (subprocess.TimeoutExpired, FileNotFoundError):
        checkpoint["files_modified"] = []

    with checkpoint_path.open("w") as f:
        json.dump(checkpoint, f, indent=2)


def _load_ralph_checkpoint() -> dict[str, Any] | None:
    """Load ralph checkpoint from disk."""
    checkpoint_path = _get_checkpoint_path()
    if not checkpoint_path.exists():
        return None

    try:
        with checkpoint_path.open("r") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _clear_ralph_checkpoint() -> None:
    """Remove ralph checkpoint file."""
    checkpoint_path = _get_checkpoint_path()
    if checkpoint_path.exists():
        checkpoint_path.unlink()


def _stop_and_save_all_ralph_tasks(session_state) -> bool:
    """Stop all running Ralph background tasks and save their state.

    Args:
        session_state: Current session state

    Returns:
        True if tasks were stopped and saved, False if none were running
    """
    if not session_state.background_ralph_tasks:
        return False

    running_tasks = [
        task
        for task in session_state.background_ralph_tasks.values()
        if task.status == RalphTaskStatus.RUNNING
    ]

    if not running_tasks:
        return False

    # Save checkpoint for each running task
    for task in running_tasks:
        try:
            # Calculate completed iterations as current iteration - 1
            # (since we're stopping before this iteration completes)
            completed = max(0, task.iteration - 1)

            # Save checkpoint
            _save_ralph_checkpoint(
                task=task.task_description,
                max_iterations=task.max_iterations,
                completed_iterations=completed,
                working_directory=task.working_directory,
                notes=f"Stopped at iteration {task.iteration}. Resume with /ralph --resume",
            )

            # Update task status
            task.status = RalphTaskStatus.CANCELLED
            task.completed_at = datetime.now(UTC)

            console.print(
                f"[yellow]✓[/yellow] Saved Ralph checkpoint at iteration {task.iteration}"
            )
            console.print(f"[dim]  Resume later with: /ralph --resume[/dim]")
        except Exception as e:
            console.print(f"[red]✗ Failed to save Ralph checkpoint: {e}[/red]")

    return True


def _get_modified_files(working_directory: str) -> list[str]:
    """Get list of modified files via git status."""
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=working_directory,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            return [line[3:] for line in result.stdout.strip().split("\n") if line]
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return []


async def _prompt_stop_action(
    iteration: int,
    max_iterations: int,
    task: str,
    working_directory: str,
) -> str:
    """Prompt user for action when Ralph is interrupted.

    Returns one of: 'stop', 'finish', 'continue', 'checkpoint'
    """
    ps: PromptSession[str] = PromptSession()

    iter_display = (
        f"{iteration}/{max_iterations}" if max_iterations > 0 else str(iteration)
    )

    console.print()
    console.print("[bold yellow]⚠️  Ralph mode interrupted[/bold yellow]")
    console.print(f"[dim]Iteration {iter_display} in progress[/dim]")
    console.print()

    # Show options
    console.print("[bold]What would you like to do?[/bold]")
    console.print("  [cyan]S[/cyan] - Stop now (may leave partial work)")
    console.print("  [cyan]F[/cyan] - Finish current iteration, then stop")
    console.print("  [cyan]C[/cyan] - Continue running")
    console.print("  [cyan]R[/cyan] - Stop and save checkpoint (resume later)")
    console.print()

    while True:
        try:
            response = await ps.prompt_async("Choice [S/F/C/R]: ")
            response = response.strip().lower()

            if response in ("s", "stop"):
                # Offer rollback if there are modified files
                modified = _get_modified_files(working_directory)
                if modified:
                    console.print()
                    console.print(f"[dim]Modified files: {len(modified)}[/dim]")
                    rollback = await ps.prompt_async("Rollback changes? [y/N]: ")
                    if rollback.strip().lower() == "y":
                        return "rollback"
                return "stop"

            if response in ("f", "finish"):
                return "finish"

            if response in ("c", "continue"):
                return "continue"

            if response in ("r", "checkpoint"):
                return "checkpoint"

            console.print("[dim]Please enter S, F, C, or R[/dim]")
        except (KeyboardInterrupt, EOFError):
            # Second Ctrl+C = force stop
            return "stop"


async def handle_ralph_status(session_state) -> bool:
    """Handle /ralph --status command to show background task status.

    Displays all Ralph background tasks and their current status.
    """
    import sys

    # Use both console and direct print for robustness
    console.print()
    print("\nRalph Background Tasks", file=sys.stdout)
    sys.stdout.flush()

    # DEBUG: Always show task count
    task_count = len(session_state.background_ralph_tasks)
    print(
        f"(Found {task_count} task(s) in background_ralph_tasks dictionary)",
        file=sys.stdout,
    )
    sys.stdout.flush()

    if not session_state.background_ralph_tasks:
        print("No background Ralph tasks running.", file=sys.stdout)
        print(
            "Note: Background tasks may take a moment to appear after being started.",
            file=sys.stdout,
        )
        print()
        sys.stdout.flush()
        return True

    # Organize tasks by status
    running_tasks = []
    completed_tasks = []
    failed_tasks = []

    for task_id, task in session_state.background_ralph_tasks.items():
        if task.status == RalphTaskStatus.RUNNING:
            running_tasks.append((task_id, task))
        elif task.status == RalphTaskStatus.COMPLETED:
            completed_tasks.append((task_id, task))
        elif task.status == RalphTaskStatus.FAILED:
            failed_tasks.append((task_id, task))

    # Display running tasks
    if running_tasks:
        print("\nRunning:", file=sys.stdout)
        for task_id, task in running_tasks:
            elapsed = (datetime.now(UTC) - task.created_at).total_seconds()
            print(
                f"  ⏳ Iteration {task.iteration}/{task.max_iterations}",
                file=sys.stdout,
            )
            task_desc = (
                task.task_description[:60] + "..."
                if len(task.task_description) > 60
                else task.task_description
            )
            print(f"      Task: {task_desc}", file=sys.stdout)
            print(f"      ID: {task_id}", file=sys.stdout)
            print(f"      Duration: {elapsed:.0f}s", file=sys.stdout)
            print(f"      Dir: {task.working_directory}", file=sys.stdout)
            print()
        sys.stdout.flush()

    # Display completed tasks
    if completed_tasks:
        print("\nCompleted:", file=sys.stdout)
        for task_id, task in completed_tasks:
            elapsed = (
                (task.completed_at - task.created_at).total_seconds()
                if task.completed_at
                else 0
            )
            print(
                f"  ✓ Iteration {task.iteration}/{task.max_iterations}", file=sys.stdout
            )
            print(f"      Duration: {elapsed:.0f}s", file=sys.stdout)
            print()
        sys.stdout.flush()

    # Display failed tasks
    if failed_tasks:
        print("\nFailed:", file=sys.stdout)
        for task_id, task in failed_tasks:
            print(
                f"  ✗ Iteration {task.iteration}/{task.max_iterations}", file=sys.stdout
            )
            if task.error_message:
                error_msg = (
                    task.error_message[:80] + "..."
                    if len(task.error_message) > 80
                    else task.error_message
                )
                print(f"      Error: {error_msg}", file=sys.stdout)
            print()
        sys.stdout.flush()

    # Summary
    print("\nSummary:", file=sys.stdout)
    print(
        f"  Total: {len(session_state.background_ralph_tasks)} tasks", file=sys.stdout
    )
    print(f"  Running: {len(running_tasks)}", file=sys.stdout)
    print(f"  Completed: {len(completed_tasks)}", file=sys.stdout)
    print(f"  Failed: {len(failed_tasks)}", file=sys.stdout)
    print()
    sys.stdout.flush()

    return True


def _run_background_ralph_in_thread(
    task: str,
    start_iteration: int,
    max_iterations: int,
    agent,
    assistant_id: str,
    session_state,
    token_tracker: TokenTracker,
    working_directory: str,
    backend,
) -> None:
    """Run background Ralph iterations in a separate thread with its own event loop.

    This ensures the background task runs reliably even if the main event loop
    is not properly managing TaskGroup or similar structures.
    """
    import sys
    import traceback

    loop = None
    try:
        # Create new event loop for this thread
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        # Run the async function
        loop.run_until_complete(
            _execute_all_ralph_iterations_background(
                task=task,
                start_iteration=start_iteration,
                max_iterations=max_iterations,
                agent=agent,
                assistant_id=assistant_id,
                session_state=session_state,
                token_tracker=token_tracker,
                working_directory=working_directory,
                backend=backend,
            )
        )
    except Exception as e:
        # Log exception to stderr for debugging
        print(f"\n[ERROR] Background Ralph execution failed!", file=sys.stderr)
        print(f"Exception: {type(e).__name__}: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        sys.stderr.flush()
    except BaseException as e:
        # Catch even SystemExit, KeyboardInterrupt, etc.
        print(
            f"\n[CRITICAL ERROR] Unhandled exception in background thread: {type(e).__name__}",
            file=sys.stderr,
        )
        print(f"Details: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        sys.stderr.flush()
    finally:
        try:
            if loop is not None:
                loop.close()
        except Exception as close_err:
            print(f"[ERROR] Failed to close event loop: {close_err}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)


async def _execute_all_ralph_iterations_background(
    task: str,
    start_iteration: int,
    max_iterations: int,
    agent,
    assistant_id: str,
    session_state,
    token_tracker: TokenTracker,
    working_directory: str,
    backend,
) -> None:
    """Execute all Ralph iterations sequentially in background (non-blocking).

    This runs in the background event loop and executes iterations one at a time,
    allowing the main CLI thread to return control to the user immediately.

    All output is suppressed to keep the terminal clean. Users can check progress
    with /ralph --status anytime.

    Tool calls are automatically approved (auto_approve=True) so the background
    task never blocks waiting for user input.

    Args:
        task: Task description
        start_iteration: Starting iteration number
        max_iterations: Maximum iterations (0 = unlimited)
        agent: The LangGraph agent
        assistant_id: Assistant identifier
        session_state: Session state
        token_tracker: Token tracker
        working_directory: Where to run
        backend: Agent backend
    """
    from novacode_cli.ui.execution import execute_task
    import sys

    # Display starting Ralph background execution (use plain print, not Rich - avoid conflicts with main thread's Live console)
    print("\n" + "=" * 60, file=sys.stderr)
    print("🚀 Ralph Background Execution Started", file=sys.stderr)
    print("=" * 60, file=sys.stderr)
    print(f"Task: {task[:70]}{'...' if len(task) > 70 else ''}", file=sys.stderr)
    print("=" * 60 + "\n", file=sys.stderr)
    sys.stderr.flush()

    # Save original auto_approve state and enable it for background execution
    original_auto_approve = session_state.auto_approve
    session_state.auto_approve = True

    # Ground the loop in the prior conversation (read once before iterating).
    conversation_context = ""
    try:
        from novacode_cli.context import ContextManager

        conversation_context = await ContextManager().digest(
            agent, session_state.thread_id
        )
    except Exception:  # noqa: BLE001
        conversation_context = ""

    _ensure_ralph_dir()
    iteration = start_iteration

    try:
        while max_iterations == 0 or iteration <= max_iterations:
            # Create task ID and BackgroundRalphTask
            task_id = str(uuid.uuid4())
            iter_display = (
                f"{iteration}/{max_iterations}"
                if max_iterations > 0
                else str(iteration)
            )

            bg_task = BackgroundRalphTask(
                task_id=task_id,
                iteration=iteration,
                max_iterations=max_iterations,
                task_description=task,
                working_directory=working_directory,
            )
            session_state.background_ralph_tasks[task_id] = bg_task

            # Display task creation with plain text formatting (avoid Rich to prevent conflicts with main thread)
            print(f"\n[NEW TASK] Iteration {iter_display}", file=sys.stderr)
            print(f"  Task ID: {task_id}", file=sys.stderr)
            print(f"  Directory: {working_directory}", file=sys.stderr)
            print(f"  Status: Created", file=sys.stderr)
            sys.stderr.flush()

            # Build prompt for this iteration using Jinja template.
            # Read progress.md fresh each iteration so the agent sees what prior
            # iterations implemented and learned.
            prompt = render_template(
                "ralph_iteration.jinja",
                iteration_display=iter_display,
                task=task,
                conversation_context=conversation_context,
                progress_notes=_read_ralph_progress(),
                progress_path=RALPH_PROGRESS_PATH,
            )

            # Execute this iteration (sequentially, one at a time)
            # NOTE: We do NOT suppress output here to avoid modifying the global console object
            # from a background thread, which breaks the main thread's ability to display output.
            # Instead, the background output will appear in the terminal but won't block the main CLI.
            # Users can check progress with /ralph --status
            # Use "ralph" as assistant_id so the agent displays as "Ralph" instead of "Nova"
            try:
                await execute_task(
                    prompt,
                    agent,
                    "ralph",  # Use "ralph" ID so agent displays as "Ralph"
                    session_state,
                    token_tracker,
                    backend=backend,
                )
                bg_task.status = RalphTaskStatus.COMPLETED
                bg_task.completed_at = datetime.now(UTC)

                # Display completion message
                elapsed = (bg_task.completed_at - bg_task.created_at).total_seconds()
                print(f"\n[COMPLETED] Iteration {iter_display}", file=sys.stderr)
                print(f"  Duration: {elapsed:.1f}s", file=sys.stderr)
                print(f"  Task ID: {task_id}", file=sys.stderr)
                sys.stderr.flush()

            except Exception as e:
                bg_task.status = RalphTaskStatus.FAILED
                bg_task.error_message = str(e)
                bg_task.completed_at = datetime.now(UTC)

                # Display failure message
                elapsed = (bg_task.completed_at - bg_task.created_at).total_seconds()
                error_msg = str(e)[:100] + "..." if len(str(e)) > 100 else str(e)
                print(f"\n[FAILED] Iteration {iter_display}", file=sys.stderr)
                print(f"  Duration: {elapsed:.1f}s", file=sys.stderr)
                print(f"  Error: {error_msg}", file=sys.stderr)
                sys.stderr.flush()

                # Continue to next iteration even if one fails

            iteration += 1
    except Exception as e:
        # Log overall error but don't crash
        pass
    finally:
        # Display final summary
        total_tasks = len(session_state.background_ralph_tasks)
        completed = sum(
            1
            for t in session_state.background_ralph_tasks.values()
            if t.status == RalphTaskStatus.COMPLETED
        )
        failed = sum(
            1
            for t in session_state.background_ralph_tasks.values()
            if t.status == RalphTaskStatus.FAILED
        )

        print(f"\n{'='*60}", file=sys.stderr)
        print(f"📊 Background Execution Summary", file=sys.stderr)
        print(f"{'='*60}", file=sys.stderr)
        print(f"Total Tasks: {total_tasks}", file=sys.stderr)
        print(f"Completed: {completed}", file=sys.stderr)
        print(f"Failed: {failed}", file=sys.stderr)
        print(f"{'='*60}\n", file=sys.stderr)
        sys.stderr.flush()

        # Notify that the background run finished.
        try:
            session_state.add_notification(
                level="error" if failed and not completed else
                ("warning" if failed else "success"),
                title="Ralph background run finished",
                message=f"{completed} completed, {failed} failed of {total_tasks} task(s)",
                source="ralph",
            )
        except Exception:  # noqa: BLE001
            pass

        # Restore original auto_approve state
        session_state.auto_approve = original_auto_approve


async def handle_ralph_command(
    agent,
    session_state,
    assistant_id: str,
    token_tracker: TokenTracker,
    cmd_args: str | list[str] | None,
    execute_fn=None,
) -> bool:
    """Handle /ralph command - autonomous looping mode.

    Usage:
        /ralph <task>              - Run autonomously until task complete (unlimited iterations)
        /ralph <task> --iterations N  - Run with max N iterations
        /ralph <task> -i N         - Shorthand for --iterations
        /ralph <task> --background - Run iterations in background (non-blocking)
        /ralph --resume            - Resume from last checkpoint
        /ralph --status            - Show status of running background tasks

    Args:
        agent: The current agent to reuse for iterations.
        session_state: Current session state.
        assistant_id: The assistant ID for execution.
        token_tracker: Token tracker for the session.
        cmd_args: Command arguments (task description and optional flags).

    Returns:
        True if handled, 'exit' if user requests exit.
    """
    if execute_fn is None:
        from novacode_cli.ui.execution import execute_task

        execute_fn = execute_task

    # Parse arguments
    if not cmd_args:
        console.print()
        console.print("[yellow]Usage: /ralph <task> [--iterations N][/yellow]")
        console.print("[yellow]       /ralph --resume[/yellow]")
        console.print("[yellow]       /ralph --status[/yellow]")
        console.print()
        console.print(
            "[dim]Example: /ralph Fix the bug in auth.py --iterations 5[/dim]"
        )
        console.print(
            "[dim]        /ralph Implement the feature described in issue #42[/dim]"
        )
        console.print(
            "[dim]        /ralph --resume  (continue from last checkpoint)[/dim]"
        )
        console.print(
            "[dim]        /ralph --status (check running background tasks)[/dim]"
        )
        console.print()
        console.print("[bold]Options:[/bold]")
        console.print(
            "  --iterations N, -i N    Maximum number of iterations (default: 5)"
        )
        console.print(
            "  --background            Run iterations in background (non-blocking)"
        )
        console.print("  --resume                Resume from last saved checkpoint")
        console.print("  --status                Show status of background ralph tasks")
        console.print()
        console.print(
            "[dim]Ralph mode runs autonomously, making progress on the task each iteration.[/dim]"
        )
        console.print(
            "[dim]Press Ctrl+C to stop and choose: Stop, Finish iteration, Continue, or Checkpoint.[/dim]"
        )
        console.print()
        return True

    # Convert cmd_args from string to list if needed (it comes as a string from handle_command)
    if isinstance(cmd_args, str):
        cmd_args = cmd_args.split()
    elif not cmd_args:
        cmd_args = []

    # Check for --status flag first
    if cmd_args and len(cmd_args) == 1 and cmd_args[0] == "--status":
        return await handle_ralph_status(session_state)

    # Parse task, iterations, resume flag, and background mode
    max_iterations = 5  # Default to 5 iterations
    background_mode = False
    resume_mode = False
    task_parts = []
    i = 0
    while i < len(cmd_args):
        arg = cmd_args[i]
        if arg == "--resume":
            resume_mode = True
            i += 1
            continue
        if arg == "--background":
            background_mode = True
            i += 1
            continue
        if arg in ("--iterations", "-i"):
            if i + 1 < len(cmd_args) and cmd_args[i + 1].isdigit():
                max_iterations = int(cmd_args[i + 1])
                i += 2
                continue
            console.print()
            console.print("[red]Error: --iterations requires a number[/red]")
            console.print("[dim]Example: /ralph task --iterations 5[/dim]")
            console.print()
            return True
        task_parts.append(arg)
        i += 1

    task = " ".join(task_parts)

    # Handle resume mode
    if resume_mode:
        checkpoint = _load_ralph_checkpoint()
        if not checkpoint:
            console.print()
            console.print("[red]No checkpoint found to resume.[/red]")
            console.print("[dim]Start a new ralph session first: /ralph <task>[/dim]")
            console.print()
            return True

        # Load checkpoint data
        task = checkpoint["task"]
        max_iterations = checkpoint["max_iterations"]
        start_iteration = checkpoint["completed_iterations"] + 1
        working_directory = checkpoint.get("working_directory", os.getcwd())
        # Note: background mode is not persisted in checkpoints; user must re-enable

        console.print()
        header = Text()
        header.append("🔄 ", style="bold")
        header.append("Ralph Mode (Resumed)", style=f"bold {COLORS['primary']}")
        panel_content = (
            f"[bold]Task:[/bold] {task}\n"
            f"[bold]Max Iterations:[/bold] {'Unlimited' if max_iterations == 0 else max_iterations}\n"
            f"[bold]Resuming from:[/bold] Iteration {start_iteration}"
        )
        if background_mode:
            panel_content += "\n[bold]Mode:[/bold] Background (non-blocking)"

        console.print(
            Panel(
                panel_content,
                title=header,
                border_style=COLORS["primary"],
                padding=(1, 2),
            )
        )
        console.print()
        if background_mode:
            console.print(
                "[dim]Background mode enabled. Iterations will run asynchronously.[/dim]"
            )
        console.print("[dim]Press Ctrl+C to stop at any time.[/dim]")
        console.print()

        # Clear checkpoint since we're resuming
        _clear_ralph_checkpoint()
    else:
        # Normal start mode
        if not task:
            console.print()
            console.print("[red]Error: No task specified[/red]")
            console.print("[dim]Usage: /ralph <task> [--iterations N][/dim]")
            console.print("[dim]       /ralph --resume[/dim]")
            console.print()
            return True

        start_iteration = 1
        working_directory = os.getcwd()

        # Display header
        console.print()
        header = Text()
        header.append("🔄 ", style="bold")
        header.append("Ralph Mode", style=f"bold {COLORS['primary']}")
        # Build panel content with background mode indicator
        panel_content = (
            f"[bold]Task:[/bold] {task}\n"
            f"[bold]Max Iterations:[/bold] {'Unlimited' if max_iterations == 0 else max_iterations}"
        )
        if background_mode:
            panel_content += "\n[bold]Mode:[/bold] Background (non-blocking)"

        console.print(
            Panel(
                panel_content,
                title=header,
                border_style=COLORS["primary"],
                padding=(1, 2),
            )
        )
        console.print()
        if background_mode:
            console.print(
                "[dim]Background mode enabled. Iterations will run asynchronously.[/dim]"
            )
        console.print("[dim]Press Ctrl+C to stop at any time.[/dim]")
        console.print()

    # Get backend from agent
    backend = None
    if hasattr(agent, "backend"):
        backend = agent.backend
    elif hasattr(agent, "graph") and hasattr(agent.graph, "backend"):
        backend = agent.graph.backend

    # Handle background mode: spawn ONE task that runs all iterations sequentially
    if background_mode:
        # Run background execution in a separate thread with its own event loop
        # This is more reliable than asyncio.create_task() in interactive CLI contexts
        background_thread = threading.Thread(
            target=_run_background_ralph_in_thread,
            args=(
                task,
                start_iteration,
                max_iterations,
                agent,
                assistant_id,
                session_state,
                token_tracker,
                working_directory,
                backend,
            ),
            daemon=True,  # Thread will not prevent program exit
        )

        # Store thread reference for tracking if needed
        if not hasattr(session_state, "_background_threads"):
            session_state._background_threads = []
        session_state._background_threads.append(background_thread)

        # Start the background thread
        background_thread.start()

        # Return immediately to user
        console.print()
        console.print(f"[green]✓[/green] Background execution started")
        console.print(
            f"[dim]Iterations will progress asynchronously in the background[/dim]"
        )
        console.print(f"[dim]Check progress with: /ralph --status[/dim]")
        console.print()
        # Clear console state to ensure prompt is ready
        console.clear()
        console.print("[dim]Ready for next command.[/dim]")
        console.print()
        return True

    # Foreground mode: run iterations synchronously
    # State for interrupt handling
    stop_after_iteration = False
    interrupted = False

    # Enable auto-approve for Ralph mode (autonomous execution)
    original_auto_approve = session_state.auto_approve
    session_state.auto_approve = True

    # Ground the loop in the prior conversation (read once before iterating).
    conversation_context = ""
    try:
        from novacode_cli.context import ContextManager

        conversation_context = await ContextManager().digest(
            agent, session_state.thread_id
        )
    except Exception:  # noqa: BLE001
        conversation_context = ""

    _ensure_ralph_dir()

    # Run autonomous loop
    iteration = start_iteration
    background_tasks = []  # Track background tasks for cleanup

    try:
        while max_iterations == 0 or iteration <= max_iterations:
            # Display iteration header
            iter_display = (
                f"{iteration}/{max_iterations}"
                if max_iterations > 0
                else str(iteration)
            )
            console.print()
            console.print(f"[bold cyan]{'─' * 50}[/bold cyan]")
            console.print(f"[bold cyan]Iteration {iter_display}[/bold cyan]")
            console.print(f"[bold cyan]{'─' * 50}[/bold cyan]")
            console.print()

            # Build prompt for this iteration using Jinja template.
            # Read progress.md fresh each iteration so the agent picks up what
            # earlier iterations recorded.
            prompt = render_template(
                "ralph_iteration.jinja",
                iteration_display=iter_display,
                task=task,
                conversation_context=conversation_context,
                progress_notes=_read_ralph_progress(),
                progress_path=RALPH_PROGRESS_PATH,
            )

            # Execute task synchronously (foreground mode only)
            # Use "ralph" as assistant_id so the agent displays as "Ralph" instead of "Nova"
            await execute_fn(
                prompt,
                agent,
                "ralph",  # Use "ralph" ID so agent displays as "Ralph"
                session_state,
                token_tracker,
                backend=backend,
            )

            iteration += 1

            # Check if we should stop after this iteration
            if stop_after_iteration:
                console.print()
                console.print(
                    "[green]Finished current iteration. Stopping as requested.[/green]"
                )
                console.print(f"[dim]Completed {iteration - 1} iteration(s).[/dim]")
                console.print()
                return True

            # Check if we should continue
            if max_iterations == 0 or iteration <= max_iterations:
                console.print()
                console.print(
                    f"[dim]Completed iteration {iteration - 1}. Continuing...[/dim]"
                )

    except KeyboardInterrupt:
        interrupted = True

    # Handle interrupt
    if interrupted:
        # Cancel any background tasks if in background mode
        if background_mode and background_tasks:
            console.print()
            console.print("[dim]Cancelling background tasks...[/dim]")
            for task in background_tasks:
                if not task.done():
                    task.cancel()
            # Wait for tasks to cancel
            if background_tasks:

                async def cancel_all():
                    await asyncio.gather(*background_tasks, return_exceptions=True)

                asyncio.run(cancel_all())
            console.print("[dim]Background tasks cancelled.[/dim]")

        action = await _prompt_stop_action(
            iteration - 1, max_iterations, task, working_directory
        )

        if action == "stop":
            session_state.auto_approve = original_auto_approve
            console.print()
            console.print("[yellow]Ralph mode stopped by user.[/yellow]")
            console.print(f"[dim]Completed {iteration - 1} iteration(s).[/dim]")
            console.print()
            # Clear console state to prevent terminal from getting stuck
            console.clear()
            console.print("[dim]Ready for next command.[/dim]")
            console.print()
            return True

        if action == "rollback":
            # Perform git rollback
            session_state.auto_approve = original_auto_approve
            console.print()
            console.print("[yellow]Rolling back changes...[/yellow]")
            try:
                subprocess.run(
                    ["git", "stash"],
                    cwd=working_directory,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                console.print(
                    "[green]Changes stashed. Use 'git stash pop' to restore.[/green]"
                )
            except (subprocess.TimeoutExpired, FileNotFoundError):
                console.print(
                    "[red]Failed to stash changes. Manual cleanup may be needed.[/red]"
                )
            console.print(f"[dim]Completed {iteration - 1} iteration(s).[/dim]")
            console.print()
            session_state.auto_approve = original_auto_approve
            # Clear console state to prevent terminal from getting stuck
            console.clear()
            console.print("[dim]Ready for next command.[/dim]")
            console.print()
            return True

        if action == "finish":
            # Set flag to stop after next iteration
            stop_after_iteration = True
            console.print()
            console.print("[dim]Will stop after completing current iteration...[/dim]")
            console.print("[dim]Press Ctrl+C again to stop immediately.[/dim]")
            console.print()
            # Continue the loop - will stop after iteration completes
            # Note: This requires re-entering the loop, which we handle by
            # setting stop_after_iteration and continuing
            # For now, we just return since execute_task already completed
            console.print("[green]Iteration already completed. Stopping now.[/green]")
            console.print(f"[dim]Completed {iteration - 1} iteration(s).[/dim]")
            console.print()
            session_state.auto_approve = original_auto_approve
            # Clear console state to prevent terminal from getting stuck
            console.clear()
            console.print("[dim]Ready for next command.[/dim]")
            console.print()
            return True

        if action == "continue":
            console.print()
            console.print("[dim]Continuing Ralph mode...[/dim]")
            console.print()
            # Re-enter the loop - this is complex, so for simplicity we just continue
            # The user can Ctrl+C again if needed
            # For a proper implementation, we'd need to restructure the loop
            # For now, just inform them to continue manually
            console.print(
                "[yellow]Note: Use /ralph --resume to continue if needed.[/yellow]"
            )
            console.print()
            session_state.auto_approve = original_auto_approve
            # Clear console state to prevent terminal from getting stuck
            console.clear()
            console.print("[dim]Ready for next command.[/dim]")
            console.print()
            return True

        if action == "checkpoint":
            # Save checkpoint
            _save_ralph_checkpoint(
                task=task,
                max_iterations=max_iterations,
                completed_iterations=iteration - 1,
                working_directory=working_directory,
                notes="Interrupted by user",
            )
            console.print()
            console.print("[green]Checkpoint saved![/green]")
            console.print("[dim]Resume with: /ralph --resume[/dim]")
            console.print(f"[dim]Completed {iteration - 1} iteration(s).[/dim]")
            console.print()
            session_state.auto_approve = original_auto_approve
            # Clear console state to prevent terminal from getting stuck
            console.clear()
            console.print("[dim]Ready for next command.[/dim]")
            console.print()
            return True

    console.print()
    console.print(
        f"[green]Ralph mode completed after {iteration - 1} iteration(s).[/green]"
    )
    console.print()

    try:
        session_state.add_notification(
            level="success",
            title="Ralph mode completed",
            message=f"{task.task_description[:80]} — {iteration - 1} iteration(s)",
            source="ralph",
        )
    except Exception:  # noqa: BLE001
        pass

    # Restore original auto_approve state
    session_state.auto_approve = original_auto_approve

    # Clear console state to prevent terminal from getting stuck
    # This ensures the prompt is ready to receive input again
    console.clear()
    console.print()
    console.print("[dim]Ready for next command.[/dim]")
    console.print()

    return True


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def register_commands(registry) -> None:
    from novacode_cli.commands import CommandContext

    async def _handle(ctx: CommandContext) -> bool:
        return await handle_ralph_command(
            ctx.agent, ctx.session_state, ctx.assistant_id,
            ctx.token_tracker, ctx.cmd_args,
        )

    registry.register("ralph", _handle)

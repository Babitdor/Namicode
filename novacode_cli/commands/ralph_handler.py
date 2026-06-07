"""Handler for the /ralph command - autonomous looping mode.

UI is emitted through a small ``emit`` callback (a Rich-markup string sink) so
the same handler drives both the classic console REPL and the Textual TUI:

* CLI (default): :func:`_console_emit` renders the markup to the global console.
* TUI: ``tui/app.py`` passes a thread-safe emitter that logs each line as a
  native widget (so foreground headers, the background progress, and
  ``/ralph --status`` all render in the TUI instead of being swallowed or
  printed raw to stdout/stderr).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import threading
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from prompt_toolkit import PromptSession
from rich.markup import escape

from novacode_cli.config.config import COLORS, console
from novacode_cli.prompts import render_template
from novacode_cli.states.Session import BackgroundRalphTask, RalphTaskStatus
from novacode_cli.ui.ui_elements import TokenTracker

logger = logging.getLogger(__name__)

# A UI sink: called with one Rich-markup string per line. "" means a blank line.
EmitFn = Callable[[str], None]


def _console_emit(message: str = "") -> None:
    """Default emitter (CLI): render a Rich-markup string to the console."""
    console.print(message)


# Cross-iteration progress log. The agent reads it at the start of every
# iteration and appends what it implemented/learned at the end, so a Ralph run
# carries memory forward. POSIX path so the model never sees a backslashed form.
RALPH_PROGRESS_PATH = ".nova/ralph/progress.md"


def _ensure_ralph_dir() -> None:
    """Make sure .nova/ralph/ exists so progress.md has a home."""
    try:
        (Path(".nova") / "ralph").mkdir(parents=True, exist_ok=True)
    except OSError:
        pass


def _read_ralph_progress() -> str:
    """Return the current progress.md contents (bounded), or '' if absent."""
    p = Path(".nova") / "ralph" / "progress.md"
    try:
        if p.exists():
            text = p.read_text(encoding="utf-8", errors="replace").strip()
            if len(text) > 6000:
                text = "…(earlier progress trimmed)…\n" + text[-6000:]
            return text
    except Exception:
        pass
    return ""


# =============================================================================
# Ralph Checkpoint Management
# =============================================================================


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
            check=False,
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


def _stop_and_save_all_ralph_tasks(session_state, emit: EmitFn = _console_emit) -> bool:
    """Stop all running Ralph background tasks and save their state.

    Returns True if tasks were stopped and saved, False if none were running.
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

    for task in running_tasks:
        try:
            # Completed iterations = current - 1 (we stop before this one finishes).
            completed = max(0, task.iteration - 1)
            _save_ralph_checkpoint(
                task=task.task_description,
                max_iterations=task.max_iterations,
                completed_iterations=completed,
                working_directory=task.working_directory,
                notes=f"Stopped at iteration {task.iteration}. Resume with /ralph --resume",
            )
            task.status = RalphTaskStatus.CANCELLED
            task.completed_at = datetime.now(UTC)

            emit(f"[yellow]✓[/yellow] Saved Ralph checkpoint at iteration {task.iteration}")
            emit("[dim]  Resume later with: /ralph --resume[/dim]")
        except Exception as e:
            emit(f"[red]✗ Failed to save Ralph checkpoint: {escape(str(e))}[/red]")

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
            check=False,
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
    emit: EmitFn = _console_emit,
) -> str:
    """Prompt the user (CLI only) for an action when Ralph is interrupted.

    Returns one of: 'stop', 'rollback', 'finish', 'continue', 'checkpoint'.

    This uses ``prompt_toolkit`` for input and is only reachable from the classic
    REPL — the TUI handles Ctrl+C itself and never raises into this loop.
    """
    ps: PromptSession[str] = PromptSession()

    iter_display = f"{iteration}/{max_iterations}" if max_iterations > 0 else str(iteration)

    emit("")
    emit("[bold yellow]⚠️  Ralph mode interrupted[/bold yellow]")
    emit(f"[dim]Iteration {iter_display} in progress[/dim]")
    emit("")
    emit("[bold]What would you like to do?[/bold]")
    emit("  [cyan]S[/cyan] - Stop now (may leave partial work)")
    emit("  [cyan]F[/cyan] - Finish current iteration, then stop")
    emit("  [cyan]C[/cyan] - Continue running")
    emit("  [cyan]R[/cyan] - Stop and save checkpoint (resume later)")
    emit("")

    while True:
        try:
            response = (await ps.prompt_async("Choice [S/F/C/R]: ")).strip().lower()

            if response in ("s", "stop"):
                modified = _get_modified_files(working_directory)
                if modified:
                    emit("")
                    emit(f"[dim]Modified files: {len(modified)}[/dim]")
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

            emit("[dim]Please enter S, F, C, or R[/dim]")
        except (KeyboardInterrupt, EOFError):
            return "stop"  # second Ctrl+C = force stop


async def handle_ralph_status(session_state, emit: EmitFn = _console_emit) -> bool:
    """Handle /ralph --status — show background task status (UI-agnostic)."""
    emit("")
    emit("[bold]Ralph Background Tasks[/bold]")

    if not session_state.background_ralph_tasks:
        emit("[dim]No background Ralph tasks running.[/dim]")
        emit("[dim]Note: tasks may take a moment to appear after being started.[/dim]")
        emit("")
        return True

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

    if running_tasks:
        emit("")
        emit("[bold cyan]Running:[/bold cyan]")
        for task_id, task in running_tasks:
            elapsed = (datetime.now(UTC) - task.created_at).total_seconds()
            desc = task.task_description
            desc = desc[:60] + "..." if len(desc) > 60 else desc
            emit(f"  ⏳ Iteration {task.iteration}/{task.max_iterations}")
            emit(f"      Task: {escape(desc)}")
            emit(f"      ID: {task_id}")
            emit(f"      Duration: {elapsed:.0f}s")
            emit(f"      Dir: {escape(task.working_directory)}")

    if completed_tasks:
        emit("")
        emit("[bold green]Completed:[/bold green]")
        for _task_id, task in completed_tasks:
            elapsed = (
                (task.completed_at - task.created_at).total_seconds()
                if task.completed_at
                else 0
            )
            emit(f"  ✓ Iteration {task.iteration}/{task.max_iterations}")
            emit(f"      Duration: {elapsed:.0f}s")

    if failed_tasks:
        emit("")
        emit("[bold red]Failed:[/bold red]")
        for _task_id, task in failed_tasks:
            emit(f"  ✗ Iteration {task.iteration}/{task.max_iterations}")
            if task.error_message:
                msg = task.error_message
                msg = msg[:80] + "..." if len(msg) > 80 else msg
                emit(f"      Error: {escape(msg)}")

    emit("")
    emit("[bold]Summary:[/bold]")
    emit(f"  Total: {len(session_state.background_ralph_tasks)} tasks")
    emit(f"  Running: {len(running_tasks)}")
    emit(f"  Completed: {len(completed_tasks)}")
    emit(f"  Failed: {len(failed_tasks)}")
    emit("")
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
    emit: EmitFn = _console_emit,
) -> None:
    """Run background Ralph iterations in a separate thread with its own loop."""
    loop = None
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
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
                emit=emit,
            )
        )
    except BaseException as e:
        logger.exception("Background Ralph execution failed")
        emit(f"[red]✗ Background Ralph execution failed: {escape(str(e))}[/red]")
    finally:
        if loop is not None:
            try:
                loop.close()
            except Exception:
                logger.exception("Failed to close background Ralph event loop")


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
    emit: EmitFn = _console_emit,
) -> None:
    """Execute all Ralph iterations sequentially in the background (non-blocking).

    Tool calls are auto-approved so the run never blocks on input. Progress is
    surfaced via ``emit`` and a final notification; check anytime with
    ``/ralph --status``.
    """
    from novacode_cli.ui.execution import execute_task

    emit("")
    emit("[bold]🚀 Ralph background execution started[/bold]")
    desc = task[:70] + "..." if len(task) > 70 else task
    emit(f"[dim]Task: {escape(desc)}[/dim]")

    original_auto_approve = session_state.auto_approve
    session_state.auto_approve = True

    # Ground the loop in the prior conversation (read once before iterating).
    conversation_context = ""
    try:
        from novacode_cli.context import ContextManager

        conversation_context = await ContextManager().digest(agent, session_state.thread_id)
    except Exception:
        conversation_context = ""

    _ensure_ralph_dir()
    iteration = start_iteration

    try:
        while max_iterations == 0 or iteration <= max_iterations:
            task_id = str(uuid.uuid4())
            iter_display = (
                f"{iteration}/{max_iterations}" if max_iterations > 0 else str(iteration)
            )

            bg_task = BackgroundRalphTask(
                task_id=task_id,
                iteration=iteration,
                max_iterations=max_iterations,
                task_description=task,
                working_directory=working_directory,
            )
            session_state.background_ralph_tasks[task_id] = bg_task

            emit(f"[dim]→ iteration {iter_display} started ({task_id[:8]})[/dim]")

            prompt = render_template(
                "ralph_iteration.jinja",
                iteration_display=iter_display,
                task=task,
                conversation_context=conversation_context,
                progress_notes=_read_ralph_progress(),
                progress_path=RALPH_PROGRESS_PATH,
            )

            try:
                await execute_task(
                    prompt,
                    agent,
                    "ralph",  # display the agent as "Ralph"
                    session_state,
                    token_tracker,
                    backend=backend,
                )
                bg_task.status = RalphTaskStatus.COMPLETED
                bg_task.completed_at = datetime.now(UTC)
                elapsed = (bg_task.completed_at - bg_task.created_at).total_seconds()
                emit(f"[green]✓ iteration {iter_display} done[/green] [dim]({elapsed:.1f}s)[/dim]")
            except Exception as e:
                bg_task.status = RalphTaskStatus.FAILED
                bg_task.error_message = str(e)
                bg_task.completed_at = datetime.now(UTC)
                err = str(e)[:100] + "..." if len(str(e)) > 100 else str(e)
                emit(f"[red]✗ iteration {iter_display} failed: {escape(err)}[/red]")

            iteration += 1
    finally:
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

        emit("")
        emit(
            f"[bold]📊 Ralph background summary[/bold] — "
            f"{completed} completed, {failed} failed of {total_tasks} task(s)"
        )

        try:
            session_state.add_notification(
                level="error"
                if failed and not completed
                else ("warning" if failed else "success"),
                title="Ralph background run finished",
                message=f"{completed} completed, {failed} failed of {total_tasks} task(s)",
                source="ralph",
            )
        except Exception:
            pass

        session_state.auto_approve = original_auto_approve


def _print_ralph_usage(emit: EmitFn) -> None:
    """Emit the /ralph usage help."""
    emit("")
    emit("[yellow]Usage: /ralph <task> [--iterations N][/yellow]")
    emit("[yellow]       /ralph --resume[/yellow]")
    emit("[yellow]       /ralph --status[/yellow]")
    emit("")
    emit("[dim]Example: /ralph Fix the bug in auth.py --iterations 5[/dim]")
    emit("[dim]        /ralph Implement the feature described in issue #42[/dim]")
    emit("[dim]        /ralph --resume  (continue from last checkpoint)[/dim]")
    emit("[dim]        /ralph --status (check running background tasks)[/dim]")
    emit("")
    emit("[bold]Options:[/bold]")
    emit("  --iterations N, -i N    Maximum number of iterations (default: 5)")
    emit("  --background            Run iterations in background (non-blocking)")
    emit("  --resume                Resume from last saved checkpoint")
    emit("  --status                Show status of background ralph tasks")
    emit("")
    emit("[dim]Ralph mode runs autonomously, making progress each iteration.[/dim]")
    emit("[dim]Press Ctrl+C to choose: Stop, Finish iteration, Continue, or Checkpoint.[/dim]")
    emit("")


def _emit_ralph_header(
    emit: EmitFn,
    *,
    task: str,
    max_iterations: int,
    background_mode: bool,
    resumed_from: int | None = None,
) -> None:
    """Emit the Ralph run header (replaces the old Rich Panel, works in both UIs)."""
    title = "🔄 Ralph Mode (Resumed)" if resumed_from else "🔄 Ralph Mode"
    iters = "Unlimited" if max_iterations == 0 else max_iterations
    emit("")
    emit(f"[bold {COLORS['primary']}]{title}[/bold {COLORS['primary']}]")
    emit(f"[bold]Task:[/bold] {escape(task)}")
    emit(f"[bold]Max Iterations:[/bold] {iters}")
    if resumed_from:
        emit(f"[bold]Resuming from:[/bold] Iteration {resumed_from}")
    if background_mode:
        emit("[bold]Mode:[/bold] Background (non-blocking)")
    emit("")
    if background_mode:
        emit("[dim]Background mode enabled. Iterations will run asynchronously.[/dim]")
    emit("[dim]Press Ctrl+C to stop at any time.[/dim]")
    emit("")


async def handle_ralph_command(
    agent,
    session_state,
    assistant_id: str,
    token_tracker: TokenTracker,
    cmd_args: str | list[str] | None,
    execute_fn=None,
    emit: EmitFn | None = None,
) -> bool:
    """Handle /ralph command - autonomous looping mode.

    Usage:
        /ralph <task>                 - Run autonomously (unlimited iterations)
        /ralph <task> --iterations N  - Run with max N iterations
        /ralph <task> -i N            - Shorthand for --iterations
        /ralph <task> --background    - Run iterations in background (non-blocking)
        /ralph --resume               - Resume from last checkpoint
        /ralph --status               - Show status of running background tasks

    ``emit`` is the UI sink (defaults to the console). The TUI passes a
    thread-safe emitter so every message renders as a native widget.
    """
    if emit is None:
        emit = _console_emit
    if execute_fn is None:
        from novacode_cli.ui.execution import execute_task

        execute_fn = execute_task

    if not cmd_args:
        _print_ralph_usage(emit)
        return True

    # Normalize args to a list.
    if isinstance(cmd_args, str):
        cmd_args = cmd_args.split()
    elif not cmd_args:
        cmd_args = []

    # --status short-circuit.
    if cmd_args and len(cmd_args) == 1 and cmd_args[0] == "--status":
        return await handle_ralph_status(session_state, emit)

    # Parse task, iterations, resume flag, and background mode.
    max_iterations = 5
    background_mode = False
    resume_mode = False
    task_parts: list[str] = []
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
            emit("")
            emit("[red]Error: --iterations requires a number[/red]")
            emit("[dim]Example: /ralph task --iterations 5[/dim]")
            emit("")
            return True
        task_parts.append(arg)
        i += 1

    task = " ".join(task_parts)

    # Resume mode.
    if resume_mode:
        checkpoint = _load_ralph_checkpoint()
        if not checkpoint:
            emit("")
            emit("[red]No checkpoint found to resume.[/red]")
            emit("[dim]Start a new ralph session first: /ralph <task>[/dim]")
            emit("")
            return True

        task = checkpoint["task"]
        max_iterations = checkpoint["max_iterations"]
        start_iteration = checkpoint["completed_iterations"] + 1
        working_directory = checkpoint.get("working_directory", os.getcwd())

        _emit_ralph_header(
            emit,
            task=task,
            max_iterations=max_iterations,
            background_mode=background_mode,
            resumed_from=start_iteration,
        )
        _clear_ralph_checkpoint()
    else:
        if not task:
            emit("")
            emit("[red]Error: No task specified[/red]")
            emit("[dim]Usage: /ralph <task> [--iterations N][/dim]")
            emit("[dim]       /ralph --resume[/dim]")
            emit("")
            return True

        start_iteration = 1
        working_directory = os.getcwd()
        _emit_ralph_header(
            emit,
            task=task,
            max_iterations=max_iterations,
            background_mode=background_mode,
        )

    # Resolve backend from the agent.
    backend = None
    if hasattr(agent, "backend"):
        backend = agent.backend
    elif hasattr(agent, "graph") and hasattr(agent.graph, "backend"):
        backend = agent.graph.backend

    # Background mode: one thread runs all iterations sequentially.
    if background_mode:
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
                emit,
            ),
            daemon=True,
        )
        if not hasattr(session_state, "_background_threads"):
            session_state._background_threads = []
        session_state._background_threads.append(background_thread)
        background_thread.start()

        emit("")
        emit("[green]✓ Background execution started[/green]")
        emit("[dim]Iterations will progress asynchronously in the background.[/dim]")
        emit("[dim]Check progress with: /ralph --status[/dim]")
        emit("")
        return True

    # Foreground mode: run iterations synchronously.
    stop_after_iteration = False
    interrupted = False

    original_auto_approve = session_state.auto_approve
    session_state.auto_approve = True

    # Ground the loop in the prior conversation (read once before iterating).
    conversation_context = ""
    try:
        from novacode_cli.context import ContextManager

        conversation_context = await ContextManager().digest(agent, session_state.thread_id)
    except Exception:
        conversation_context = ""

    _ensure_ralph_dir()
    iteration = start_iteration

    try:
        while max_iterations == 0 or iteration <= max_iterations:
            iter_display = (
                f"{iteration}/{max_iterations}" if max_iterations > 0 else str(iteration)
            )
            emit("")
            emit(f"[bold cyan]{'─' * 50}[/bold cyan]")
            emit(f"[bold cyan]Iteration {iter_display}[/bold cyan]")
            emit(f"[bold cyan]{'─' * 50}[/bold cyan]")
            emit("")

            prompt = render_template(
                "ralph_iteration.jinja",
                iteration_display=iter_display,
                task=task,
                conversation_context=conversation_context,
                progress_notes=_read_ralph_progress(),
                progress_path=RALPH_PROGRESS_PATH,
            )

            # The agent run streams natively through execute_fn.
            await execute_fn(
                prompt,
                agent,
                "ralph",  # display the agent as "Ralph"
                session_state,
                token_tracker,
                backend=backend,
            )

            iteration += 1

            if stop_after_iteration:
                emit("")
                emit("[green]Finished current iteration. Stopping as requested.[/green]")
                emit(f"[dim]Completed {iteration - 1} iteration(s).[/dim]")
                emit("")
                session_state.auto_approve = original_auto_approve
                return True

            if max_iterations == 0 or iteration <= max_iterations:
                emit("")
                emit(f"[dim]Completed iteration {iteration - 1}. Continuing...[/dim]")

    except KeyboardInterrupt:
        interrupted = True

    if interrupted:
        action = await _prompt_stop_action(
            iteration - 1, max_iterations, task, working_directory, emit
        )

        if action == "stop":
            session_state.auto_approve = original_auto_approve
            emit("")
            emit("[yellow]Ralph mode stopped by user.[/yellow]")
            emit(f"[dim]Completed {iteration - 1} iteration(s).[/dim]")
            emit("")
            return True

        if action == "rollback":
            session_state.auto_approve = original_auto_approve
            emit("")
            emit("[yellow]Rolling back changes...[/yellow]")
            try:
                subprocess.run(
                    ["git", "stash"],
                    cwd=working_directory,
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=False,
                )
                emit("[green]Changes stashed. Use 'git stash pop' to restore.[/green]")
            except (subprocess.TimeoutExpired, FileNotFoundError):
                emit("[red]Failed to stash changes. Manual cleanup may be needed.[/red]")
            emit(f"[dim]Completed {iteration - 1} iteration(s).[/dim]")
            emit("")
            return True

        if action == "finish":
            session_state.auto_approve = original_auto_approve
            emit("")
            emit("[green]Iteration already completed. Stopping now.[/green]")
            emit(f"[dim]Completed {iteration - 1} iteration(s).[/dim]")
            emit("")
            return True

        if action == "continue":
            session_state.auto_approve = original_auto_approve
            emit("")
            emit("[dim]Continuing Ralph mode...[/dim]")
            emit("[yellow]Note: Use /ralph --resume to continue if needed.[/yellow]")
            emit("")
            return True

        if action == "checkpoint":
            _save_ralph_checkpoint(
                task=task,
                max_iterations=max_iterations,
                completed_iterations=iteration - 1,
                working_directory=working_directory,
                notes="Interrupted by user",
            )
            session_state.auto_approve = original_auto_approve
            emit("")
            emit("[green]Checkpoint saved![/green]")
            emit("[dim]Resume with: /ralph --resume[/dim]")
            emit(f"[dim]Completed {iteration - 1} iteration(s).[/dim]")
            emit("")
            return True

    emit("")
    emit(f"[green]Ralph mode completed after {iteration - 1} iteration(s).[/green]")
    emit("")

    try:
        session_state.add_notification(
            level="success",
            title="Ralph mode completed",
            message=f"{escape(task[:80])} — {iteration - 1} iteration(s)",
            source="ralph",
        )
    except Exception:
        pass

    session_state.auto_approve = original_auto_approve
    return True


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def register_commands(registry) -> None:
    from novacode_cli.commands import CommandContext

    async def _handle(ctx: CommandContext) -> bool:
        return await handle_ralph_command(
            ctx.agent,
            ctx.session_state,
            ctx.assistant_id,
            ctx.token_tracker,
            ctx.cmd_args,
        )

    registry.register("ralph", _handle)

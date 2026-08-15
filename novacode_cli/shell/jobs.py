"""Cooperative control for the currently-running foreground shell command.

The shell/execute tool runs its subprocess inside a detached thread with its own
event loop (see ``ShellMiddleware._run_async``), so the TUI cannot reach it via
normal Textual task cancellation — which is why a hung command used to freeze the
UI for the full timeout and could crash on force-quit.

While a foreground command runs, the middleware publishes a :class:`ForegroundControl`
here. The TUI sets its events from keybinds (Esc → ``kill``, Ctrl+B → ``detach``)
and the middleware's read loop polls them each iteration. There is at most one
foreground command at a time (TUI turns are exclusive), so a single global slot
is enough.

# ponytail: single global foreground slot — one turn runs at a time. If nested
# subagent shells ever need independent control, key this by tool_call_id.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass
class ForegroundControl:
    """Signals the middleware's foreground read loop polls each iteration."""

    command: str
    kill: threading.Event = field(default_factory=threading.Event)
    """Set by the TUI (Esc) → the loop kills the subprocess and returns an error."""
    detach: threading.Event = field(default_factory=threading.Event)
    """Set by the TUI (Ctrl+B) → the loop hands the process to a background job."""


_current: ForegroundControl | None = None
_lock = threading.Lock()


def set_current(command: str) -> ForegroundControl:
    """Publish a fresh control for the foreground command about to run."""
    global _current
    ctl = ForegroundControl(command=command)
    with _lock:
        _current = ctl
    return ctl


def get_current() -> ForegroundControl | None:
    """Return the live foreground control, or None if nothing is running."""
    with _lock:
        return _current


def clear_current(ctl: ForegroundControl) -> None:
    """Clear the slot iff ``ctl`` is still the current one (avoids clobbering a
    newer command that started after this one finished)."""
    global _current
    with _lock:
        if _current is ctl:
            _current = None


def request_kill() -> bool:
    """Ask the running foreground command to die. Returns True if one was running."""
    ctl = get_current()
    if ctl is not None:
        ctl.kill.set()
        return True
    return False


def request_detach() -> bool:
    """Ask the running foreground command to detach to the background.

    Returns True if a command was running and not already being killed.
    """
    ctl = get_current()
    if ctl is not None and not ctl.kill.is_set():
        ctl.detach.set()
        return True
    return False


# ---------------------------------------------------------------------------
# Background jobs — a detached command keeps running and reports on completion.
# ---------------------------------------------------------------------------


@dataclass
class BackgroundJob:
    """A shell/execute command that was detached to run in the background."""

    id: int
    command: str
    tool_name: str
    started_at: float
    status: str = "running"  # running | done
    exit_code: int | None = None
    output: str = ""
    finished_at: float | None = None
    _done: threading.Event = field(default_factory=threading.Event, repr=False)


class JobRegistry:
    """Process-global registry of background jobs.

    The middleware's detached drain thread calls :meth:`complete` when a job
    finishes; the TUI registers a completion callback (notify + transcript note)
    and the agent inspects jobs via :meth:`list_jobs` / :meth:`wait`.
    """

    def __init__(self) -> None:
        self._jobs: dict[int, BackgroundJob] = {}
        self._next_id = 1
        self._lock = threading.Lock()
        self._on_complete: Callable[[BackgroundJob], None] | None = None

    def add(self, command: str, tool_name: str) -> BackgroundJob:
        with self._lock:
            job_id = self._next_id
            self._next_id += 1
            job = BackgroundJob(
                id=job_id, command=command, tool_name=tool_name, started_at=time.time()
            )
            self._jobs[job_id] = job
            return job

    def complete(self, job_id: int, output: str, exit_code: int | None) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.status != "running":
                return
            job.output = output
            job.exit_code = exit_code
            job.status = "done"
            job.finished_at = time.time()
            job._done.set()
            cb = self._on_complete
        if cb is not None:
            try:
                cb(job)
            except Exception:  # noqa: BLE001 — a bad callback must not wedge the job
                pass

    def get(self, job_id: int) -> BackgroundJob | None:
        with self._lock:
            return self._jobs.get(job_id)

    def list_jobs(self) -> list[BackgroundJob]:
        with self._lock:
            return list(self._jobs.values())

    def wait(self, job_id: int, timeout: float | None = None) -> BackgroundJob | None:
        """Block until the job finishes (or ``timeout``). None if no such job."""
        job = self.get(job_id)
        if job is None:
            return None
        job._done.wait(timeout)
        return job

    def set_completion_callback(self, cb: Callable[[BackgroundJob], None] | None) -> None:
        self._on_complete = cb


_registry: JobRegistry | None = None


def get_registry() -> JobRegistry:
    """Return the process-global background-job registry."""
    global _registry
    if _registry is None:
        _registry = JobRegistry()
    return _registry


# ---------------------------------------------------------------------------
# Shared background event loop — lets a detached command's drain outlive the
# synchronous tool call that started it.
# ---------------------------------------------------------------------------
#
# LangChain runs our sync shell tool via `run_in_executor`, so the tool body
# has no running loop and would normally do a per-call `asyncio.run(coro)` that
# blocks the worker thread until the command exits. That can't support Ctrl+B:
# to hand the agent a "backgrounded" result mid-command while the process keeps
# being read, the coroutine must run somewhere that outlives the tool return.
# We run it on one persistent loop (daemon thread) and merely *wait* on it from
# the tool thread — on detach we stop waiting; the coroutine keeps draining here.

import asyncio  # noqa: E402

_bg_loop: asyncio.AbstractEventLoop | None = None
_bg_loop_lock = threading.Lock()


def get_background_loop() -> asyncio.AbstractEventLoop:
    """Return the shared background event loop, starting it on first use.

    The loop runs in a daemon thread (dies with the process). On Windows the
    default policy yields a Proactor loop, which supports subprocesses.
    """
    global _bg_loop
    with _bg_loop_lock:
        if _bg_loop is None or _bg_loop.is_closed():
            loop = asyncio.new_event_loop()
            threading.Thread(
                target=loop.run_forever, name="nova-shell-bg-loop", daemon=True
            ).start()
            _bg_loop = loop
        return _bg_loop


if __name__ == "__main__":
    # ponytail: self-check for the slot lifecycle (no subprocess needed).
    assert get_current() is None
    assert request_kill() is False  # nothing running
    c = set_current("sleep 100")
    assert get_current() is c
    assert request_kill() is True and c.kill.is_set()
    # kill wins over detach: a killed command can't be detached
    assert request_detach() is False
    clear_current(c)
    assert get_current() is None
    # detach on a fresh command
    c2 = set_current("npm run build")
    assert request_detach() is True and c2.detach.is_set()
    # clear only clears the matching control
    c3 = set_current("other")
    clear_current(c2)  # stale — must NOT clear c3
    assert get_current() is c3
    clear_current(c3)

    # registry: add → complete fires callback and unblocks wait
    reg = get_registry()
    fired: list[int] = []
    reg.set_completion_callback(lambda j: fired.append(j.id))
    job = reg.add("npm run build", "shell")
    assert reg.wait(job.id, timeout=0.1).status == "running"  # not done yet
    reg.complete(job.id, "built ok", 0)
    assert job.status == "done" and job.exit_code == 0 and fired == [job.id]
    assert reg.wait(job.id, timeout=0.1).output == "built ok"
    reg.complete(job.id, "x", 1)  # second complete is a no-op
    assert job.exit_code == 0 and fired == [job.id]
    print("shell.jobs self-check ok")

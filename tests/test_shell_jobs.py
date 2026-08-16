"""Foreground shell control: Esc must kill a hung command promptly.

The shell tool runs its subprocess in a detached thread+loop that Textual task
cancellation can't reach, so before this a hung command froze the UI for the
full timeout (and could crash on force-quit). ``shell.jobs`` publishes a control
the TUI sets on Esc; the middleware read loop polls it and terminates.
"""

from __future__ import annotations

import asyncio
import os
import sys
import threading
import time

import pytest

from novacode_cli.shell import jobs
from novacode_cli.shell.middleware import ShellMiddleware


def test_jobs_slot_lifecycle() -> None:
    assert jobs.get_current() is None
    assert jobs.request_kill() is False
    c = jobs.set_current("sleep 100")
    assert jobs.get_current() is c
    assert jobs.request_kill() is True and c.kill.is_set()
    assert jobs.request_detach() is False  # kill wins
    jobs.clear_current(c)
    assert jobs.get_current() is None


@pytest.mark.timeout(30)
def test_kill_terminates_hung_command_promptly() -> None:
    """A 60s-hung command must die within a few seconds once kill is requested —
    not after the middleware's (here 120s) timeout."""
    mw = ShellMiddleware(workspace_root=os.getcwd(), timeout=120.0)
    # Run via `prog` (create_subprocess_exec) so a spaced interpreter path never
    # trips shell quoting — a reliable 60s hang on any platform.
    prog = [sys.executable, "-c"]
    cmd = "import time; time.sleep(60)"

    def kill_soon() -> None:
        for _ in range(100):  # wait up to 10s for the control to be published
            if jobs.get_current() is not None:
                break
            time.sleep(0.1)
        time.sleep(0.3)
        jobs.request_kill()

    t = threading.Thread(target=kill_soon)
    t.start()
    start = time.time()
    msg = asyncio.run(mw._async_local_shell(cmd, tool_call_id="t1", prog=prog))
    elapsed = time.time() - start
    t.join()

    assert elapsed < 15, f"kill should be prompt, took {elapsed:.1f}s"
    assert msg.status == "error"
    assert "killed by user" in (msg.content or "")
    assert jobs.get_current() is None  # cleared in finally


@pytest.mark.timeout(40)
def test_detach_backgrounds_then_job_completes() -> None:
    """Ctrl+B detach: the tool returns '[backgrounded: job N]' promptly while the
    command keeps running on the shared background loop and completes with its
    full output + exit code (firing the completion callback)."""
    mw = ShellMiddleware(workspace_root=os.getcwd(), timeout=30.0)
    prog = [sys.executable, "-u", "-c"]
    code = "import time\nfor i in range(4):\n print('line', i, flush=True)\n time.sleep(1)"

    reg = jobs.get_registry()
    completed: list[object] = []
    reg.set_completion_callback(completed.append)

    box: dict[str, object] = {}

    def run() -> None:
        box["msg"] = mw._run_local_command(code, tool_call_id="d", prog=prog)

    th = threading.Thread(target=run)
    th.start()
    for _ in range(100):  # wait for the command to publish
        if jobs.get_current() is not None:
            break
        time.sleep(0.1)
    time.sleep(1.2)
    assert jobs.request_detach() is True
    th.join(timeout=10)

    msg = box["msg"]
    assert "backgrounded: task_" in msg.content  # returned before the command ended

    # The command keeps running; wait for the drain to finish.
    for _ in range(120):
        if completed:
            break
        time.sleep(0.1)
    assert completed, "completion callback never fired"
    job = completed[0]
    assert job.status == "done"
    assert job.exit_code == 0
    assert "line 3" in job.output  # full output captured after detach

    reg.set_completion_callback(None)  # don't leak the callback into other tests


@pytest.mark.timeout(40)
def test_launch_terminate_and_restart_background_task() -> None:
    """Launch a background task, stream its logs, terminate it (process-group
    kill), then restart it as a fresh task."""
    mw = ShellMiddleware(workspace_root=os.getcwd(), timeout=30.0)
    reg = jobs.get_registry()
    prog = [sys.executable, "-u", "-c"]
    code = "import time\nwhile True:\n print('tick', flush=True)\n time.sleep(0.3)"

    job = mw._launch_background(code, prog)
    assert job.status == "running" and job.task_id.startswith("task_")

    for _ in range(60):  # live logs stream in
        if "tick" in job.output:
            break
        time.sleep(0.1)
    assert "tick" in job.output

    assert reg.terminate(job.id) is True
    for _ in range(80):  # drain loop kills the tree and marks terminated
        if job.status != "running":
            break
        time.sleep(0.1)
    assert job.status == "terminated"

    j2 = reg.restart(job.id)
    assert j2 is not None and j2.id != job.id and j2.status == "running"
    reg.terminate(j2.id)  # cleanup
    for _ in range(80):
        if j2.status != "running":
            break
        time.sleep(0.1)
    assert j2.status == "terminated"

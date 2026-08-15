"""Agent tools for background shell/execute jobs.

A shell/execute command detached with Ctrl+B (or auto-backgrounded) keeps running
as a background job. These tools let the agent see those jobs and collect their
output when it chooses to — so it can start something long, move on to other work,
and come back for the result.
"""

from __future__ import annotations

from langchain.tools import tool


@tool
def list_jobs() -> str:
    """List background shell/execute jobs and their status.

    Use this to see what long-running commands are still running or have
    finished. Retrieve a finished job's output with ``wait_for_job``.
    """
    from novacode_cli.shell.jobs import get_registry

    jobs = get_registry().list_jobs()
    if not jobs:
        return "No background jobs."
    lines = []
    for j in jobs:
        state = j.status + (f" (exit {j.exit_code})" if j.status == "done" else "")
        lines.append(f"job {j.id}: {state} — {j.command[:80]}")
    return "\n".join(lines)


@tool
def wait_for_job(job_id: int, timeout_seconds: int = 120) -> str:
    """Wait for a backgrounded shell/execute job to finish and return its output.

    Blocks up to ``timeout_seconds`` for the job to complete. If it finishes,
    returns the exit code and full captured output. If it is still running when
    the timeout elapses, returns a "still running" note — call again to keep
    waiting, or do other work and check back.

    Args:
        job_id: The background job id (from the "[backgrounded: job N]" message
            or ``list_jobs``).
        timeout_seconds: How long to wait before giving up (default 120).
    """
    from novacode_cli.shell.jobs import get_registry

    job = get_registry().wait(job_id, timeout=max(0, timeout_seconds))
    if job is None:
        return f"No background job with id {job_id}. Use list_jobs() to see current jobs."
    if job.status != "done":
        return (
            f"Job {job_id} is still running after {timeout_seconds}s "
            f"(command: {job.command}). Call wait_for_job({job_id}) again to keep waiting."
        )
    return (
        f"Job {job_id} finished (exit {job.exit_code}).\n\n"
        f"Command: {job.command}\n\nOutput:\n{job.output}"
    )


__all__ = ["list_jobs", "wait_for_job"]

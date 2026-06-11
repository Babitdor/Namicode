"""Local shell execution: stream to completion, no 5s prompt-detection cap.

The old ``_run_local_command`` ran with a 5s timeout and reported any command that
took longer as a timeout error (and killed it) — so builds/installs/tests in local
mode falsely failed. These lock in the rewrite: commands run to the full
``self._timeout`` on a single process, with output returned in the ToolMessage.
"""

from __future__ import annotations

from novacode_cli.shell.middleware import ShellMiddleware

# Calling the sync entry point (which bridges to asyncio in a worker thread / fresh
# loop) avoids pytest-asyncio event-loop-policy issues with subprocesses on Windows.


def _mw(timeout: float = 30.0) -> ShellMiddleware:
    return ShellMiddleware(workspace_root=".", timeout=timeout)


def test_quick_command_returns_output():
    r = _mw()._run_local_command('python -c "print(7*6)"', tool_call_id="t")
    assert "42" in r.content
    assert r.status == "success"


def test_nonzero_exit_is_reported_as_error_with_code():
    r = _mw()._run_local_command('python -c "import sys; sys.exit(3)"', tool_call_id="t")
    assert r.status == "error"
    assert "Exit code: 3" in r.content


def test_command_longer_than_5s_runs_to_completion():
    # Regression: the old path killed every command at 5s. A ~6s command must
    # complete successfully, not return a timeout error.
    r = _mw(timeout=30.0)._run_local_command(
        'python -c "import time; time.sleep(6); print(\'finished\')"',
        tool_call_id="t",
    )
    assert r.status == "success", r.content
    assert "finished" in r.content


def test_runaway_command_is_terminated_at_timeout():
    r = _mw(timeout=2.0)._run_local_command(
        'python -c "import time; time.sleep(60)"', tool_call_id="t"
    )
    assert r.status == "error"
    assert "terminated" in r.content

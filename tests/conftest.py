"""Shared test fixtures."""

import pytest


@pytest.fixture(autouse=True)
def _reset_shell_jobs():
    """Isolate the process-global background-job registry between tests.

    Jobs, observers, and completion callbacks are a module singleton; without a
    reset, a running job (or a stale TUI observer) from one test leaks into the
    next — e.g. starting the ⚙ tasks-bar ticker inside an unrelated TUI test.
    """
    from novacode_cli.shell.jobs import get_registry

    get_registry().reset()
    yield
    get_registry().reset()

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


@pytest.fixture(autouse=True)
def _isolate_tui_slash_commands():
    """Undo runtime mutation of the global slash-command list.

    ``tui/app.py`` builds ``_TUI_SLASH_COMMANDS`` from the built-in table, then
    ``_load_plugin_commands()`` APPENDS the developer's installed plugin commands
    to it at app mount. Once any test boots a NovaApp those entries persist for
    the rest of the process and leak into every later test's autocomplete.

    Looked up via ``sys.modules`` so this costs nothing for the many tests that
    never import the (heavy) TUI module.
    """
    import sys

    yield

    mod = sys.modules.get("novacode_cli.tui.app")
    if mod is None:
        return
    # Rebuild from the built-in table rather than restoring a snapshot: a
    # snapshot taken at setup already contains whatever an earlier test leaked,
    # so it would preserve the pollution instead of removing it.
    mod._TUI_SLASH_COMMANDS[:] = [f"/{name}" for name in mod.TUI_COMMANDS]


@pytest.fixture(autouse=True)
def _reap_leaked_session_children():
    """Kill any spawned-session child process a test left behind.

    ``SessionSupervisor`` tracks live children in a module-global set for its
    atexit sweep. A test that fails before closing one would leave a real
    process holding pipes open, stalling later tests; reap them here instead.
    """
    yield

    from novacode_cli.sessions import supervisor as sup

    for child in list(sup._live):
        proc = getattr(child, "proc", None)
        if proc is not None and proc.returncode is None:
            try:
                proc.kill()
            except Exception:  # noqa: BLE001 — already gone
                pass
        sup._live.discard(child)

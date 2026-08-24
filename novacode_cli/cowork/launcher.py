"""Launch (or reuse) the Nova Cowork desktop server.

The "desktop app" is the existing FastAPI server (agent WS chat + SessionManager)
plus the /cowork UI + workspace-broker routes, run on a random localhost port in
a daemon thread. `/cowork` opens it in the browser. Single instance per process.
"""

from __future__ import annotations

import socket
import threading
import time
import urllib.request

_state: dict = {"url": None, "server": None, "error": None}
_lock = threading.Lock()


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_ready(url: str, timeout: float = 20.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url + "/health", timeout=1) as r:
                if r.getcode() == 200:
                    return True
        except Exception:  # noqa: BLE001
            time.sleep(0.2)
    return False


def ensure_cowork_server() -> str:
    """Start the cowork server if needed; return its base URL.

    Raises RuntimeError with a friendly message if the agent/server can't start
    (e.g. no model configured) — the caller surfaces it in the TUI.
    """
    with _lock:
        if _state["url"]:
            return _state["url"]
        try:
            import uvicorn

            from novacode_cli.server.app import app
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(f"cowork server deps unavailable: {e}") from e

        # No agent is built here: Cowork is default-deny, so the confined,
        # workspace-rooted agent is built lazily on the first /sessions call
        # AFTER the user grants a folder (server/app._get_cowork_agent).
        port = _free_port()
        cfg = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
        server = uvicorn.Server(cfg)
        threading.Thread(target=server.run, daemon=True, name="nova-cowork-server").start()
        url = f"http://127.0.0.1:{port}"

    if not _wait_ready(url):
        raise RuntimeError("cowork server did not become ready in time")
    with _lock:
        _state.update(url=url, server=server)
    return url


def grant_cwd_if_needed() -> None:
    """Auto-grant the directory the CLI is working in.

    The user launched Nova against this folder, so denying Cowork all access
    until they retype a path they're already in is pointless friction — the CLI
    already has full access here. Done from the trusted CLI process (not the
    tokenless page). Deduped (skipped if an active grant already covers cwd) and
    still shown as a revocable grant. Default-deny stays in force everywhere else.
    """
    from pathlib import Path

    from novacode_cli.cowork.policy import get_policy

    pol = get_policy()
    cwd = Path.cwd()
    if not pol.authorize(cwd, "read").allowed:
        pol.grant(cwd)


def cowork_url(session_id: str | None = None, task: str | None = None) -> str:
    """Ensure the server is up and return the /cowork page URL (with optional
    session id + initial task passed through). Auto-grants the CLI's cwd."""
    from urllib.parse import urlencode

    from novacode_cli.server.app import get_cowork_token

    base = ensure_cowork_server()
    grant_cwd_if_needed()
    params = {"token": get_cowork_token()}  # the page needs it to reach the gated routes
    if session_id:
        params["session"] = session_id
    if task:
        params["task"] = task
    return f"{base}/cowork?{urlencode(params)}"

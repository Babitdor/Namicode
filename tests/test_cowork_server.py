"""Cowork server routes: the SPA is served and the workspace-broker API enforces
default-deny grant/authorize/revoke over HTTP (no agent build required)."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def client(tmp_path: Path):
    import novacode_cli.cowork.policy as P

    P._policy = P.WorkspacePolicy(store_path=tmp_path / "store.json")  # isolate
    try:
        from fastapi.testclient import TestClient
    except Exception:  # noqa: BLE001
        pytest.skip("fastapi TestClient/httpx unavailable")
    from novacode_cli.server.app import app, get_cowork_token

    # Authenticated by default: the IPC token gates every sensitive route.
    return TestClient(app, headers={"X-Cowork-Token": get_cowork_token()})


@pytest.fixture
def noauth_client():
    """A client with NO token — used to prove the routes reject unauthenticated calls."""
    try:
        from fastapi.testclient import TestClient
    except Exception:  # noqa: BLE001
        pytest.skip("fastapi TestClient/httpx unavailable")
    from novacode_cli.server.app import app

    return TestClient(app)


def test_cowork_spa_served(client):
    r = client.get("/cowork")
    assert r.status_code == 200
    assert "Nova Cowork" in r.text


def test_workspace_grant_authorize_revoke_flow(client, tmp_path: Path):
    proj = tmp_path / "proj"
    (proj / "src").mkdir(parents=True)
    (proj / "src" / "a.py").write_text("x")

    def authz(path, op="read"):
        return client.get("/api/authorize", params={"path": str(path), "op": op}).json()

    assert client.get("/api/workspace").json() == {"grants": []}
    # default-deny before any grant
    assert authz(proj / "src" / "a.py")["code"] == "ACCESS_DENIED_OUTSIDE_WORKSPACE"

    g = client.post("/api/workspace/grant", json={"path": str(proj)}).json()
    assert "grant" in g
    gid = g["grant"]["id"]

    assert authz(proj / "src" / "a.py")["allowed"] is True         # in-workspace
    assert authz(tmp_path / "elsewhere")["allowed"] is False       # outside

    assert client.post("/api/workspace/revoke", json={"id": gid}).json()["revoked"] is True
    assert authz(proj / "src" / "a.py")["allowed"] is False        # denied after revoke


def test_grant_cwd_is_deduped(tmp_path: Path, monkeypatch):
    """Launching from the CLI auto-grants its cwd once; re-launching from the same
    folder doesn't pile up duplicate grants."""
    import novacode_cli.cowork.policy as P
    from novacode_cli.cowork.launcher import grant_cwd_if_needed

    P._policy = P.WorkspacePolicy(store_path=tmp_path / "store.json")  # isolate
    monkeypatch.chdir(tmp_path)

    grant_cwd_if_needed()
    grant_cwd_if_needed()  # second launch from the same cwd

    active = P._policy.active_grants()
    assert len(active) == 1
    assert P._policy.authorize(tmp_path / "anything.txt", "read").allowed is True


def test_grant_nonexistent_path_rejected(client, tmp_path: Path):
    r = client.post("/api/workspace/grant", json={"path": str(tmp_path / "nope")})
    assert r.status_code == 400


def test_sessions_refused_without_grant(client):
    """Default-deny at the agent level: no session (no agent) until a folder is
    granted. This returns 503 BEFORE building any agent."""
    r = client.post("/sessions")
    assert r.status_code == 503
    assert "Grant a workspace" in r.json()["error"]


# ── IPC auth: unauthenticated callers cannot reach the boundary ───────────
def test_unauthenticated_routes_rejected(noauth_client, tmp_path: Path):
    """Without the IPC token, no sensitive route is reachable — so a stray local
    process cannot grant itself a folder and bypass the WorkspacePolicy boundary."""
    c = noauth_client
    assert c.get("/cowork").status_code == 401
    assert c.get("/api/workspace").status_code == 401
    assert c.post("/api/workspace/grant", json={"path": str(tmp_path)}).status_code == 401
    assert c.post("/api/workspace/revoke", json={"id": "x"}).status_code == 401
    assert c.get("/api/authorize", params={"path": str(tmp_path)}).status_code == 401
    assert c.post("/sessions").status_code == 401
    # /health stays open (the launcher polls it before the token is known).
    assert c.get("/health").status_code == 200


def test_bad_token_rejected(noauth_client, tmp_path: Path):
    r = noauth_client.get("/api/workspace", headers={"X-Cowork-Token": "wrong"})
    assert r.status_code == 401


def test_token_via_query_param_accepted(noauth_client):
    from novacode_cli.server.app import get_cowork_token

    r = noauth_client.get("/api/workspace", params={"token": get_cowork_token()})
    assert r.status_code == 200


def test_websocket_requires_token(client):
    """The WS carries the token as a query param (browsers can't set WS headers);
    a connection without it is closed, with it the 'session not found' path runs."""
    from starlette.websockets import WebSocketDisconnect

    from novacode_cli.server.app import get_cowork_token

    # No token → server closes with policy-violation code 1008 before accept.
    with pytest.raises(WebSocketDisconnect) as ei:
        with client.websocket_connect("/ws/nope"):
            pass
    assert ei.value.code == 1008

    # Valid token → connection is accepted; unknown session yields an error event.
    with client.websocket_connect(f"/ws/nope?token={get_cowork_token()}") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "error"


# ── ask_user_question interrupt round-trip ───────────────────────────────
def _install_fake_question_agent(monkeypatch, captured: list):
    """Monkeypatch iterate_agent_events to yield one question interrupt then Done,
    capturing the interrupt future so tests can assert on it."""
    import asyncio

    from novacode_cli import ui_events
    from novacode_cli.server import app as server_app

    async def _fake_iterate(*args, **kwargs):
        fut = asyncio.get_running_loop().create_future()
        captured.append(fut)
        yield ui_events.InterruptRequest(
            kind="question",
            payload={
                "question": "Which dataset?",
                "options": ["a", "b"],
                "question_type": "structured",
            },
            future=fut,
        )
        yield ui_events.Done(had_response=True)

    monkeypatch.setattr(server_app, "iterate_agent_events", _fake_iterate)


def test_question_interrupt_round_trip(client, monkeypatch):
    """An ask_user_question interrupt is surfaced to the SPA and the run resumes
    with the user's answer (not the empty default)."""
    from novacode_cli.server.app import get_cowork_token, session_manager

    captured: list = []
    _install_fake_question_agent(monkeypatch, captured)

    class _FakeAgent:
        pass

    sid = session_manager.create_session(
        _FakeAgent(), {"configurable": {"thread_id": "t-roundtrip"}}
    ).session_id
    try:
        with client.websocket_connect(f"/ws/{sid}?token={get_cowork_token()}") as ws:
            ws.send_json({"type": "message", "data": {"content": "hi"}})

            # The interrupt event reaches the client with the question payload.
            msg = ws.receive_json()
            assert msg["type"] == "interrupt"
            assert msg["data"]["kind"] == "question"
            assert msg["data"]["payload"]["question"] == "Which dataset?"

            # The SPA answers; the run resumes and completes.
            ws.send_json({
                "type": "interrupt_response",
                "data": {"response": {"answer": "a", "selected_index": 0}},
            })
            msg = ws.receive_json()
            assert msg["type"] == "assistant_done"
    finally:
        session_manager.delete_session(sid)

    # The future was resolved with the clean answer (top-level "answer" key is
    # what ask_user_question reads), not the empty default.
    assert captured and captured[0].done()
    assert captured[0].result() == {"answer": "a", "selected_index": 0}


def test_question_interrupt_falls_back_on_disconnect(client, monkeypatch):
    """If the client disconnects while a question is pending, the interrupt is
    resolved to the benign default so the run never hangs."""
    import time

    from novacode_cli.server.app import get_cowork_token, session_manager

    captured: list = []
    _install_fake_question_agent(monkeypatch, captured)

    class _FakeAgent:
        pass

    sid = session_manager.create_session(
        _FakeAgent(), {"configurable": {"thread_id": "t-disconnect"}}
    ).session_id
    try:
        with client.websocket_connect(f"/ws/{sid}?token={get_cowork_token()}") as ws:
            ws.send_json({"type": "message", "data": {"content": "hi"}})
            msg = ws.receive_json()
            assert msg["type"] == "interrupt"
            # Exit the context without answering — the server must clean up.
    finally:
        session_manager.delete_session(sid)

    # The pending future is resolved to the default (empty dict) shortly after
    # the disconnect, so the agent loop can unwind instead of awaiting forever.
    deadline = time.time() + 5
    while time.time() < deadline and (not captured or not captured[0].done()):
        time.sleep(0.05)
    assert captured and captured[0].done()
    assert captured[0].result() == {}

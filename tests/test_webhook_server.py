"""Tests for webhook ingress (Loop-Engineering Enhancement 5).

Covers signature verification + task extraction in the adapters, and the
server's verify→enqueue→reject flow over a fake aiohttp request.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from types import SimpleNamespace

import pytest

from novacode_cli.hermes import config
from novacode_cli.remote.bridge import RemotePlatform
from novacode_cli.remote.webhook_adapters import (
    parse_generic,
    parse_github,
    parse_linear,
)
from novacode_cli.remote.webhook_server import WebhookServer

_SECRET = "topsecret"


def _sign(body: bytes, secret: str = _SECRET) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


class FakeStore:
    def __init__(self) -> None:
        self.data: dict[tuple, dict] = {}

    async def aget(self, namespace, key):
        ns = self.data.get(tuple(namespace), {})
        return SimpleNamespace(value=dict(ns[key])) if key in ns else None

    async def aput(self, namespace, key, value):
        self.data.setdefault(tuple(namespace), {})[key] = dict(value)


class FakeRequest:
    def __init__(self, source: str, headers: dict, body: bytes) -> None:
        self.match_info = {"source": source}
        self.headers = headers
        self._body = body

    async def read(self) -> bytes:
        return self._body


# ── adapters: signature verification ─────────────────────────────────────────


class TestGithubAdapter:
    def test_valid_signature_push(self):
        body = json.dumps(
            {
                "repository": {"full_name": "me/repo"},
                "commits": [1, 2],
                "head_commit": {"message": "fix bug"},
            }
        ).encode()
        headers = {"X-Hub-Signature-256": f"sha256={_sign(body)}", "X-GitHub-Event": "push"}
        msg = parse_github(headers, body, _SECRET)
        assert msg is not None
        assert msg.platform is RemotePlatform.WEBHOOK
        assert "me/repo" in msg.text
        assert "fix bug" in msg.text

    def test_invalid_signature_rejected(self):
        body = b'{"repository": {"full_name": "me/repo"}}'
        headers = {"X-Hub-Signature-256": "sha256=deadbeef", "X-GitHub-Event": "push"}
        assert parse_github(headers, body, _SECRET) is None

    def test_event_not_in_allowlist_rejected(self):
        body = b"{}"
        headers = {"X-Hub-Signature-256": f"sha256={_sign(body)}", "X-GitHub-Event": "issues"}
        assert parse_github(headers, body, _SECRET, allowed_events={"push"}) is None

    def test_event_in_allowlist_accepted(self):
        body = json.dumps(
            {"action": "opened", "number": 7, "pull_request": {"title": "T"}}
        ).encode()
        headers = {
            "x-hub-signature-256": f"sha256={_sign(body)}",  # lowercase header
            "x-github-event": "pull_request",
        }
        msg = parse_github(headers, body, _SECRET, allowed_events={"pull_request"})
        assert msg is not None
        assert "#7" in msg.text


class TestLinearAdapter:
    def test_valid_signature(self):
        body = json.dumps({"action": "create", "type": "Issue", "data": {"title": "Bug"}}).encode()
        headers = {"Linear-Signature": _sign(body)}
        msg = parse_linear(headers, body, _SECRET)
        assert msg is not None
        assert "Issue" in msg.text and "Bug" in msg.text

    def test_bad_signature(self):
        body = b"{}"
        assert parse_linear({"Linear-Signature": "nope"}, body, _SECRET) is None


class TestGenericAdapter:
    def test_matching_secret_and_task(self):
        body = json.dumps({"task": "run the smoke tests"}).encode()
        msg = parse_generic({"X-Nova-Secret": _SECRET}, body, _SECRET)
        assert msg is not None
        assert msg.text == "run the smoke tests"

    def test_wrong_secret(self):
        body = json.dumps({"task": "x"}).encode()
        assert parse_generic({"X-Nova-Secret": "wrong"}, body, _SECRET) is None

    def test_missing_task_field(self):
        body = json.dumps({"nope": "x"}).encode()
        assert parse_generic({"X-Nova-Secret": _SECRET}, body, _SECRET) is None

    def test_task_length_capped(self):
        body = json.dumps({"task": "A" * 5000}).encode()
        msg = parse_generic({"X-Nova-Secret": _SECRET}, body, _SECRET)
        assert msg is not None
        assert len(msg.text) <= 2000


# ── server handler flow ──────────────────────────────────────────────────────


class TestWebhookServerHandle:
    async def _server(self):
        store = FakeStore()
        queue: asyncio.Queue = asyncio.Queue()
        server = WebhookServer(queue, store=store)
        await server.register_source("github", _SECRET, event_types=["push"])
        return server, queue, store

    async def test_valid_request_enqueues(self):
        server, queue, _ = await self._server()
        body = json.dumps({"repository": {"full_name": "me/repo"}, "commits": []}).encode()
        req = FakeRequest(
            "github",
            {"X-Hub-Signature-256": f"sha256={_sign(body)}", "X-GitHub-Event": "push"},
            body,
        )
        resp = await server._handle(req)
        assert resp.status == 202
        assert queue.qsize() == 1

    async def test_bad_signature_401_no_enqueue(self):
        server, queue, _ = await self._server()
        body = b"{}"
        req = FakeRequest(
            "github",
            {"X-Hub-Signature-256": "sha256=bad", "X-GitHub-Event": "push"},
            body,
        )
        resp = await server._handle(req)
        assert resp.status == 401
        assert queue.qsize() == 0

    async def test_unknown_source_404(self):
        server, queue, _ = await self._server()
        resp = await server._handle(FakeRequest("nope", {}, b"{}"))
        assert resp.status == 404

    async def test_unregistered_source_401(self):
        server, queue, _ = await self._server()
        body = json.dumps({"task": "x"}).encode()
        # 'generic' adapter exists but was never registered (no secret).
        req = FakeRequest("generic", {"X-Nova-Secret": "x"}, body)
        resp = await server._handle(req)
        assert resp.status == 401
        assert queue.qsize() == 0

    async def test_event_not_allowed_rejected(self):
        server, queue, _ = await self._server()  # only 'push' allowed
        body = json.dumps({"action": "opened"}).encode()
        req = FakeRequest(
            "github",
            {"X-Hub-Signature-256": f"sha256={_sign(body)}", "X-GitHub-Event": "pull_request"},
            body,
        )
        resp = await server._handle(req)
        assert resp.status == 401
        assert queue.qsize() == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

"""Webhook payload adapters — Loop-Engineering Enhancement 5 (event-driven).

Each ``parse_*`` function turns a raw inbound HTTP request (headers + body bytes
+ the source's shared secret) into a :class:`~novacode_cli.remote.bridge.RemoteMessage`
ready for the shared queue, or ``None`` when the request is unauthenticated or
its event type isn't allowed. They are pure (no I/O) so the security-critical
verification is trivially unit-testable.

Signature verification is timing-safe (:func:`hmac.compare_digest`). An empty
secret means "unconfigured" and always rejects — a webhook source must be
explicitly registered before it can trigger a run.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

    from novacode_cli.remote.bridge import RemoteMessage

logger = logging.getLogger("nova.remote.webhook")

_MAX_TASK_CHARS = 2000


def _clean_task(text: str) -> str:
    """Sanitise inbound task text: drop null bytes, cap length, strip."""
    return text.replace("\x00", "")[:_MAX_TASK_CHARS].strip()


def _header(headers: Mapping[str, str], name: str) -> str:
    """Case-insensitive header lookup returning ``""`` when absent."""
    lowered = name.lower()
    for key, value in headers.items():
        if key.lower() == lowered:
            return value
    return ""


def _verify_hmac_sha256(body: bytes, secret: str, provided_hex: str) -> bool:
    """Timing-safe HMAC-SHA256 check of ``body`` against ``provided_hex``."""
    if not secret or not provided_hex:
        return False
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, provided_hex.strip())


def _make_message(text: str) -> RemoteMessage:
    """Build a WEBHOOK ``RemoteMessage`` (no chat to reply to → no-op reply)."""
    from novacode_cli.remote.bridge import RemoteMessage, RemotePlatform

    return RemoteMessage(
        platform=RemotePlatform.WEBHOOK,
        chat_id="webhook",
        user_name="webhook",
        text=_clean_task(text),
        reply_fn=_noop_reply,
    )


async def _noop_reply(_text: str) -> None:
    """Reply sink — a webhook's HTTP response is already sent by the time we run."""


def _load_json(body: bytes) -> dict:
    """Parse a JSON body into a dict, or ``{}`` on any error."""
    try:
        data = json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def parse_github(
    headers: Mapping[str, str],
    body: bytes,
    secret: str,
    *,
    allowed_events: set[str] | None = None,
) -> RemoteMessage | None:
    """GitHub webhook → task. Verifies ``X-Hub-Signature-256`` (HMAC-SHA256)."""
    signature = _header(headers, "X-Hub-Signature-256").removeprefix("sha256=")
    if not _verify_hmac_sha256(body, secret, signature):
        return None
    event = _header(headers, "X-GitHub-Event") or "event"
    if allowed_events is not None and event not in allowed_events:
        return None

    payload = _load_json(body)
    repo = (payload.get("repository") or {}).get("full_name", "?")
    if event == "push":
        commits = payload.get("commits") or []
        head = (payload.get("head_commit") or {}).get("message", "")
        text = f"GitHub push to {repo} ({len(commits)} commit(s)). Latest: {head}"
    elif event == "pull_request":
        pr = payload.get("pull_request") or {}
        text = (
            f"GitHub PR {payload.get('action', '')} #{payload.get('number', '?')} "
            f"on {repo}: {pr.get('title', '')}"
        )
    elif event == "workflow_run":
        wf = payload.get("workflow_run") or {}
        text = (
            f"GitHub workflow '{wf.get('name', '?')}' {wf.get('conclusion', wf.get('status', ''))} "
            f"on {repo}"
        )
    else:
        text = f"GitHub {event} event on {repo}"
    return _make_message(text)


def parse_linear(
    headers: Mapping[str, str],
    body: bytes,
    secret: str,
    *,
    allowed_events: set[str] | None = None,
) -> RemoteMessage | None:
    """Linear webhook → task. Verifies the ``Linear-Signature`` header."""
    signature = _header(headers, "Linear-Signature")
    if not _verify_hmac_sha256(body, secret, signature):
        return None
    payload = _load_json(body)
    action = payload.get("action", "")
    entity = payload.get("type", "event")
    if allowed_events is not None and entity not in allowed_events:
        return None
    data = payload.get("data") or {}
    title = data.get("title") or data.get("name") or ""
    text = f"Linear {entity} {action}: {title}".strip()
    return _make_message(text)


def parse_generic(
    headers: Mapping[str, str],
    body: bytes,
    secret: str,
    *,
    allowed_events: set[str] | None = None,  # noqa: ARG001 — uniform adapter signature
) -> RemoteMessage | None:
    """Generic webhook → task. Requires a matching ``X-Nova-Secret`` header.

    Body must be JSON ``{"task": "..."}``. Used for ad-hoc integrations that
    can't produce an HMAC signature.
    """
    provided = _header(headers, "X-Nova-Secret")
    if not secret or not provided or not hmac.compare_digest(secret, provided):
        return None
    payload = _load_json(body)
    task = payload.get("task")
    if not isinstance(task, str) or not task.strip():
        return None
    return _make_message(task)


#: Source name → adapter. The webhook server dispatches on the URL path segment.
ADAPTERS = {
    "github": parse_github,
    "linear": parse_linear,
    "generic": parse_generic,
}

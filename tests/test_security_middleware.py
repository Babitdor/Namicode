"""Tests for SecurityMiddleware — URL-arg screening (warn + sanitize).

Covers:
- hidden Unicode is stripped from URL args in place (and the tool runs with it)
- spoofing / hidden-char findings emit a TUI-safe security event
- non-URL args are left untouched (no blanket sanitization)
- safe URLs pass through unchanged with no event
"""

from __future__ import annotations

import pytest

from novacode_cli.security.middleware import SecurityMiddleware


class _Req:
    def __init__(self, name: str, args: dict) -> None:
        self.tool_call = {"name": name, "args": args, "id": "t1"}


def _drain_events() -> list[tuple]:
    from novacode_cli.hermes.middleware import nova_event_log

    events = list(nova_event_log)
    nova_event_log.clear()
    return events


@pytest.fixture(autouse=True)
def _clear_events():
    _drain_events()  # start each test with an empty buffer
    yield
    _drain_events()


async def _run(req: _Req):
    captured: dict = {}

    async def handler(request):
        captured["args"] = dict(request.tool_call["args"] or {})
        return "ok"

    result = await SecurityMiddleware().awrap_tool_call(req, handler)
    return result, captured


class TestUrlArgScreening:
    async def test_strips_hidden_unicode_from_url(self):
        # ZERO WIDTH SPACE (U+200B) hidden in the URL path.
        req = _Req("fetch_url", {"url": "https://example.com/​path"})
        result, captured = await _run(req)
        assert result == "ok"
        # Hidden char removed both in the live args and what the tool received.
        assert req.tool_call["args"]["url"] == "https://example.com/path"
        assert captured["args"]["url"] == "https://example.com/path"
        events = _drain_events()
        assert any(et == "nova_security" for et, *_ in events), events

    async def test_mixed_script_domain_warns_but_proceeds(self):
        # 'а' is Cyrillic (U+0430) — "exаmple" mixes Latin + Cyrillic scripts.
        req = _Req("fetch_url", {"url": "https://exаmple.com"})
        result, captured = await _run(req)
        assert result == "ok"  # warn + sanitize → not blocked
        # Confusables aren't invisible, so the URL itself isn't altered here.
        assert captured["args"]["url"] == "https://exаmple.com"
        events = _drain_events()
        assert any(et == "nova_security" for et, *_ in events), events

    async def test_non_url_arg_is_untouched(self):
        # Hidden char in a NON-URL arg must NOT be stripped (no blanket sanitize).
        dirty = "code​with​zwsp"
        req = _Req("write_file", {"file_path": "/a.py", "content": dirty})
        _, captured = await _run(req)
        assert req.tool_call["args"]["content"] == dirty
        assert captured["args"]["content"] == dirty
        assert _drain_events() == []

    async def test_safe_url_passes_through(self):
        req = _Req("fetch_url", {"url": "https://example.com/docs"})
        _, captured = await _run(req)
        assert captured["args"]["url"] == "https://example.com/docs"
        assert _drain_events() == []

    async def test_non_dict_args_do_not_crash(self):
        req = _Req("weird", None)  # type: ignore[arg-type]
        result, _ = await _run(req)
        assert result == "ok"

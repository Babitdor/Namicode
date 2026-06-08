"""Tests for the /chat Council web UI — the council event generator, score
parsing, and an end-to-end SSE round-trip through the HTTP server.
"""

from __future__ import annotations

import asyncio
import json
import threading
import urllib.error
import urllib.parse
import urllib.request

import pytest

from novacode_cli import council
from novacode_cli.commands import chat_handler as ch

# ---------------------------------------------------------------------------
# Fake model
# ---------------------------------------------------------------------------


class _Chunk:
    def __init__(self, content: str) -> None:
        self.content = content


class FakeModel:
    """Streams two tokens per answer; votes everyone's favourite = The Architect."""

    async def astream(self, messages):
        for tok in ["Hel", "lo"]:
            yield _Chunk(tok)

    async def ainvoke(self, messages):
        # Score every known persona; the parser filters out self + unknowns.
        scores = [
            {"agent": p.name, "score": 9 if p.id == "architect" else 5, "reason": "ok"}
            for p in council.PERSONAS
        ]
        return _Chunk(json.dumps({"scores": scores}))


# ---------------------------------------------------------------------------
# _parse_scores
# ---------------------------------------------------------------------------


def test_parse_scores_filters_invalid_and_clamps():
    valid = {"The Architect", "The Skeptic"}
    raw = json.dumps(
        {
            "scores": [
                {"agent": "The Architect", "score": 99, "reason": "great"},
                {"agent": "The Skeptic", "score": 0, "reason": "weak"},
                {"agent": "The Pragmatist", "score": 7, "reason": "not in set"},
                {"agent": "The Architect", "score": 4, "reason": "dup ignored"},
            ]
        }
    )
    out = council._parse_scores(raw, valid)
    assert out == [("The Architect", 10, "great"), ("The Skeptic", 1, "weak")]


def test_parse_scores_handles_fenced_json():
    raw = '```json\n{"scores":[{"agent":"The Skeptic","score":6,"reason":"x"}]}\n```'
    assert council._parse_scores(raw, {"The Skeptic"}) == [("The Skeptic", 6, "x")]


def test_parse_scores_returns_empty_on_garbage():
    assert council._parse_scores("no json here", {"The Architect"}) == []


def test_content_text_handles_block_lists():
    assert council._content_text(_Chunk("hi")) == "hi"
    blocks = _Chunk([{"type": "text", "text": "a"}, {"type": "text", "text": "b"}])
    assert council._content_text(blocks) == "ab"


# ---------------------------------------------------------------------------
# run_council generator
# ---------------------------------------------------------------------------


async def _collect(topic: str, model) -> list[dict]:
    return [e async for e in council.run_council(topic, model)]


def test_format_history_compacts_rounds():
    history = [
        {
            "topic": "caching",
            "transcript": [["The Architect", "x" * 999], ["The Skeptic", "short"]],
            "winner": "The Architect",
        }
    ]
    block = council._format_history(history)
    assert "Round 1 — topic: caching" in block
    assert "The Architect:" in block
    assert "…" in block  # long answer trimmed
    assert "Verdict: The Architect won" in block
    assert council._format_history(None) == ""


async def test_history_is_passed_into_personas():
    """A follow-up round should include prior-round context in the persona prompt."""
    seen: list[str] = []

    class CapturingModel(FakeModel):
        async def astream(self, messages):
            # messages = [("system", ...), ("human", convo)]
            seen.append(messages[-1][1])
            async for c in super().astream(messages):
                yield c

    history = [
        {
            "topic": "first topic",
            "transcript": [["The Architect", "my earlier point"]],
            "winner": "The Architect",
        }
    ]
    _ = [e async for e in council.run_council("follow up", CapturingModel(), history=history)]
    assert seen, "no persona prompts captured"
    # Every persona's prompt should carry the prior discussion.
    assert all("Earlier in this council session" in p for p in seen)
    assert all("first topic" in p for p in seen)


async def test_council_persona_can_web_search(monkeypatch):
    """A tool-capable model can call web search; it surfaces as an agent_tool event."""
    from novacode_cli.tools import web_tools

    monkeypatch.setattr(
        web_tools,
        "duckduckgo_search",
        lambda *a, **k: {  # noqa: ARG005
            "success": True,
            "results": [{"title": "T", "body": "B", "url": "u"}],
        },
        raising=True,
    )

    class _ToolChunk:
        def __init__(self, content="", tool_calls=None):
            self.content = content
            self.tool_calls = tool_calls or []

        def __add__(self, other):
            return _ToolChunk(
                self.content + other.content, self.tool_calls + other.tool_calls
            )

    class ToolModel:
        def bind_tools(self, tools):
            return self

        async def astream(self, messages):
            has_result = any(
                isinstance(m, dict) and m.get("role") == "tool" for m in messages
            )
            if not has_result:
                yield _ToolChunk(
                    tool_calls=[
                        {"name": "council_web_search", "args": {"query": "q"}, "id": "c1"}
                    ]
                )
            else:
                for tok in ["Hel", "lo"]:
                    yield _ToolChunk(content=tok)

        async def ainvoke(self, messages):
            scores = [{"agent": p.name, "score": 5, "reason": "ok"} for p in council.PERSONAS]
            return _ToolChunk(content=json.dumps({"scores": scores}))

    events = [e async for e in council.run_council("topic", ToolModel())]
    types = [e["type"] for e in events]
    assert "agent_tool" in types
    tool_ev = next(e for e in events if e["type"] == "agent_tool")
    assert tool_ev["query"] == "q"
    # After searching, each persona still produces a streamed answer.
    done = [e for e in events if e["type"] == "agent_done"]
    assert all(e["text"] == "Hello" for e in done)


async def test_run_council_event_sequence_and_verdict():
    events = await _collect("How should we cache?", FakeModel())
    types = [e["type"] for e in events]

    n = len(council.PERSONAS)
    assert types[0] == "council_start"
    assert types.count("agent_start") == n
    assert types.count("agent_done") == n
    assert types.count("agent_delta") == n * 2  # two tokens each
    assert types.count("vote_start") == 1
    assert types.count("vote") == n
    assert types[-2] == "verdict"
    assert types[-1] == "done"

    # Each agent streamed "Hel" + "lo" -> "Hello"
    done = [e for e in events if e["type"] == "agent_done"]
    assert all(e["text"] == "Hello" for e in done)

    # The Architect was scored 9 by the other four voters -> clear winner.
    verdict = next(e for e in events if e["type"] == "verdict")
    assert verdict["winner_id"] == "architect"
    assert verdict["totals"]["architect"] == 9 * (n - 1)
    # No one scores themselves.
    assert verdict["totals"]["pragmatist"] == 5 * (n - 1)


# ---------------------------------------------------------------------------
# End-to-end SSE through the HTTP server
# ---------------------------------------------------------------------------


@pytest.fixture
def council_server(monkeypatch):
    """Start the chat server with the council backed by a fake model."""
    monkeypatch.setattr(council, "get_council_model", lambda: FakeModel(), raising=True)

    loop = asyncio.new_event_loop()
    t = threading.Thread(target=loop.run_forever, daemon=True)
    t.start()

    ch.set_agent_refs(object(), "assistant", object(), loop)
    url = ch.start_chat_server()
    yield url

    ch.stop_chat_server()
    loop.call_soon_threadsafe(loop.stop)
    t.join(timeout=2)
    loop.close()


def _read_sse(url: str, topic: str) -> list[tuple[str, dict]]:
    full = url + "/api/council?topic=" + urllib.parse.quote(topic)
    out: list[tuple[str, dict]] = []
    event = None
    with urllib.request.urlopen(full, timeout=10) as resp:  # noqa: S310 - localhost
        assert "text/event-stream" in resp.headers.get("Content-Type", "")
        for raw in resp:
            line = raw.decode().rstrip("\n")
            if line.startswith("event: "):
                event = line[len("event: "):]
            elif line.startswith("data: "):
                out.append((event, json.loads(line[len("data: "):])))
                # Real EventSource clients close on the terminal event; do the
                # same so we don't block waiting for the server to drop the conn.
                if event == "done":
                    break
            elif line == "":
                event = None
    return out


def test_sse_round_trip(council_server):
    frames = _read_sse(council_server, "What database?")
    types = [t for t, _ in frames]
    assert types[0] == "council_start"
    assert "vote_start" in types
    assert types[-1] == "done"
    verdict = next(d for t, d in frames if t == "verdict")
    assert verdict["winner_id"] == "architect"


def test_sse_empty_topic_errors(council_server):
    frames = _read_sse(council_server, "   ")
    types = [t for t, _ in frames]
    assert "council_error" in types
    assert types[-1] == "done"


def test_sse_run_records_and_resets_history(council_server):
    assert ch._council_history == []  # fresh server
    _read_sse(council_server, "topic one")
    # The completed round is recorded so follow-ups can build on it.
    assert len(ch._council_history) == 1
    assert ch._council_history[0]["topic"] == "topic one"
    assert ch._council_history[0]["winner"] == "The Architect"
    # The reset endpoint clears it.
    with urllib.request.urlopen(  # noqa: S310 - localhost
        council_server + "/api/council/reset", timeout=10
    ) as resp:
        assert resp.status == 204
    assert ch._council_history == []

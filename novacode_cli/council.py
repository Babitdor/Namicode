"""Council of agents — a multi-persona debate with peer voting.

A *council* takes a single topic and runs it past five distinct personas, each
backed by the session's configured model but given its own personality. They
speak **in sequence, chatroom-style** — every persona sees what the previous
ones said and can react. Once everyone has spoken, each persona **scores the
others' answers** (1–10); the highest total wins and its answer is the verdict.

:func:`run_council` is a pure async generator yielding plain ``dict`` events, so
it can be unit-tested without HTTP and rendered by the ``/chat`` web server as
Server-Sent Events (see :mod:`novacode_cli.commands.chat_handler`).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

# Max web searches a single persona may run before it must answer.
_MAX_TOOL_ROUNDS = 2

# Tool offered to each persona, as a plain OpenAI-style schema dict. Passing a
# dict (rather than a LangChain ``@tool``) keeps this module import-light — it
# avoids importing ``langchain_core`` (which pulls in transformers) at import
# time; the configured model already brings LangChain with it at run time.
_SEARCH_TOOL_NAME = "council_web_search"
_SEARCH_TOOL_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": _SEARCH_TOOL_NAME,
        "description": (
            "Search the web (DuckDuckGo) for current, factual information. Use a "
            "focused query. Call this only when you genuinely need up-to-date or "
            "factual grounding for your perspective."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The search query."}
            },
            "required": ["query"],
        },
    },
}


def _run_council_tool(name: str, args: dict[str, Any]) -> str:
    """Execute a council tool call by name and return its string result."""
    if name == _SEARCH_TOOL_NAME:
        from novacode_cli.tools.web_tools import duckduckgo_search

        try:
            res = duckduckgo_search(str(args.get("query", "")), max_results=4)  # type: ignore
        except Exception as exc:  # noqa: BLE001
            return f"(search error: {exc})"
        if not res.get("success"):
            return f"(search failed: {res.get('error', 'unknown error')})"
        results = res.get("results", [])
        if not results:
            return "(no results)"
        return "\n".join(
            f"- {r.get('title', '')}: {r.get('body', '')} ({r.get('url', '')})"
            for r in results
        )
    return f"(unknown tool: {name})"


@dataclass(frozen=True)
class Persona:
    """One council member: an id, display identity, and a system prompt."""

    id: str
    name: str
    avatar: str
    color: str
    system: str


PERSONAS: list[Persona] = [
    Persona(
        id="architect",
        name="The Architect",
        avatar="🏛️",
        color="#6ea8fe",
        system=(
            "You are The Architect. You think in systems, boundaries, and the "
            "long view: structure, separation of concerns, data flow, and how a "
            "choice ages over years. You value maintainability over cleverness."
        ),
    ),
    Persona(
        id="pragmatist",
        name="The Pragmatist",
        avatar="🛠️",
        color="#4cae8a",
        system=(
            "You are The Pragmatist. You care about shipping working software. "
            "You favor the simplest thing that solves the real problem, weigh "
            "effort against payoff, and call out over-engineering and YAGNI."
        ),
    ),
    Persona(
        id="skeptic",
        name="The Skeptic",
        avatar="🔍",
        color="#d4a13b",
        system=(
            "You are The Skeptic. You hunt for what breaks: edge cases, failure "
            "modes, race conditions, security holes, and hidden assumptions. You "
            "are constructive but you do not let risks go unnamed."
        ),
    ),
    Persona(
        id="innovator",
        name="The Innovator",
        avatar="🚀",
        color="#b06ae8",
        system=(
            "You are The Innovator. You look for the non-obvious, modern, or "
            "creative approach others miss. You bring fresh techniques and "
            "question whether the framing of the problem is even right."
        ),
    ),
    Persona(
        id="minimalist",
        name="The Minimalist",
        avatar="✂️",
        color="#d46a6a",
        system=(
            "You are The Minimalist. You strip problems to their essence and "
            "prefer the least code, the fewest moving parts, and the clearest "
            "solution. You delete before you add."
        ),
    ),
]

_RESPONSE_GUIDE = (
    " You are one of five advisors in a council debating a topic. Stay in "
    "character, speak in the first person, and be technically substantive. Keep "
    "it focused — under ~160 words. React to earlier advisors when relevant, but "
    "make your own distinct point rather than echoing them. If you need current "
    "or factual information, you may call the web search tool first, then answer."
)

_VOTE_GUIDE = (
    " You are scoring the OTHER advisors' answers as yourself, in character. "
    "Judge usefulness and correctness. Respond with ONLY a JSON object of the "
    'form {"scores":[{"agent":"<exact name>","score":<integer 1-10>,'
    '"reason":"<one short sentence>"}]} and nothing else.'
)


# How much prior-round context to carry into a follow-up council.
_MAX_HISTORY_ROUNDS = 6
_HISTORY_ANSWER_CHARS = 400


def _format_history(history: list[dict[str, Any]] | None) -> str:
    """Render prior council rounds into a compact context block for follow-ups.

    Each round is ``{"topic": str, "transcript": [[name, text], ...],
    "winner": str}``. Older rounds and long answers are trimmed so the prompt
    stays bounded while preserving the thread of discussion.
    """
    if not history:
        return ""
    lines = ["Earlier in this council session (for context, so you can follow up):"]
    for idx, rnd in enumerate(history[-_MAX_HISTORY_ROUNDS:], 1):
        lines.append(f"\nRound {idx} — topic: {rnd.get('topic', '')}")
        for entry in rnd.get("transcript", []):
            try:
                name, text = entry
            except (ValueError, TypeError):
                continue
            text = (text or "").strip()
            if len(text) > _HISTORY_ANSWER_CHARS:
                text = text[:_HISTORY_ANSWER_CHARS] + "…"
            lines.append(f"  {name}: {text}")
        if rnd.get("winner"):
            lines.append(f"  -> Verdict: {rnd['winner']} won that round.")
    return "\n".join(lines)


def _content_text(message: Any) -> str:
    """Extract plain text from a LangChain message/chunk ``.content``.

    Content may be a string or a list of content blocks (e.g. Anthropic), so we
    coalesce any text parts and ignore the rest.
    """
    content = getattr(message, "content", message)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                text = block.get("text") or block.get("content")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts)
    return str(content) if content is not None else ""


def _parse_scores(raw: str, valid_names: set[str]) -> list[tuple[str, int, str]]:
    """Parse a voter's JSON scorecard, keeping only entries for *valid_names*.

    Tolerant of code fences / surrounding prose: extracts the first JSON object.
    Scores are clamped to 1–10. Self-votes and unknown names are dropped.
    """
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return []
    try:
        data = json.loads(match.group(0))
    except (json.JSONDecodeError, ValueError):
        return []

    out: list[tuple[str, int, str]] = []
    seen: set[str] = set()
    for entry in data.get("scores", []) if isinstance(data, dict) else []:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("agent", "")).strip()
        if name not in valid_names or name in seen:
            continue
        try:
            score = round(float(entry.get("score", 0)))
        except (TypeError, ValueError):
            continue
        score = max(1, min(10, score))
        reason = str(entry.get("reason", "")).strip()
        out.append((name, score, reason))
        seen.add(name)
    return out


def get_council_model() -> Any:
    """Build a chat model for the council from the session's configured provider.

    Reuses :class:`~novacode_cli.config.model_manager.ModelManager` so the
    council speaks with whatever model the user picked via ``/model`` (Ollama by
    default). Raises if no provider can be created.
    """
    from novacode_cli.config.model_manager import MODEL_PRESETS, ModelManager

    mm = ModelManager()
    current = mm.get_current_provider()  # (display_name, model_name) | None
    provider_id = "ollama"
    model_name: str | None = None
    if current:
        display, model_name = current
        for pid, preset in MODEL_PRESETS.items():
            if preset["name"] == display:
                provider_id = pid
                break
    return mm.create_model_for_provider(provider_id, model_name)  # type: ignore[arg-type]


async def _stream_persona_turn(
    persona: Persona, convo: str, model: Any
) -> AsyncIterator[tuple[str, str]]:
    """Stream one persona's turn, allowing bounded web-search tool calls.

    Yields ``("delta", text)`` for streamed prose and ``("tool", query)`` when
    the persona runs a web search. Models without tool support (or that can't
    stream tool calls) fall back to plain streaming.
    """
    system_text = persona.system + _RESPONSE_GUIDE

    model_tools = None
    if hasattr(model, "bind_tools"):
        try:
            model_tools = model.bind_tools([_SEARCH_TOOL_SCHEMA])
        except Exception:  # noqa: BLE001 - provider may not support tools
            model_tools = None

    if model_tools is None:
        async for chunk in model.astream([("system", system_text), ("human", convo)]):
            piece = _content_text(chunk)
            if piece:
                yield ("delta", piece)
        return

    # Dict-form messages so we don't import langchain_core.messages here; the
    # model converts them. The model's own tool-call message (``gathered``) is
    # appended as returned.
    messages: list[Any] = [
        {"role": "system", "content": system_text},
        {"role": "user", "content": convo},
    ]
    rounds = 0
    while True:
        use_tools = rounds < _MAX_TOOL_ROUNDS
        gathered = None
        async for chunk in (model_tools if use_tools else model).astream(messages):
            if use_tools:
                try:
                    gathered = chunk if gathered is None else gathered + chunk
                except (
                    Exception
                ):  # noqa: BLE001 - chunk not addable; skip tool detection
                    gathered = None
            piece = _content_text(chunk)
            if piece:
                yield ("delta", piece)

        tool_calls = (
            list(getattr(gathered, "tool_calls", None) or [])
            if gathered is not None
            else []
        )
        if not tool_calls:
            return

        messages.append(gathered)
        for call in tool_calls:
            args = call.get("args", {}) or {}
            query = str(args.get("query", "")).strip()
            yield ("tool", query)
            result = _run_council_tool(call.get("name", ""), args)
            messages.append(
                {"role": "tool", "content": result, "tool_call_id": call.get("id", "")}
            )
        rounds += 1


async def run_council(
    topic: str,
    model: Any,
    personas: list[Persona] | None = None,
    history: list[dict[str, Any]] | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Run a council debate over *topic* and yield event dicts.

    *history* carries prior rounds of the same session so the advisors can build
    on an earlier discussion (follow-up questions).

    Event ``type``s, in order:
      ``council_start`` -> for each persona ``agent_start`` / ``agent_delta``* /
      ``agent_done`` -> ``vote_start`` -> for each persona ``vote`` ->
      ``verdict`` -> ``done``.
    """
    members = personas or PERSONAS
    name_to_id = {p.name: p.id for p in members}
    history_block = _format_history(history)

    yield {
        "type": "council_start",
        "topic": topic,
        "agents": [
            {"id": p.id, "name": p.name, "avatar": p.avatar, "color": p.color}
            for p in members
        ],
    }

    # --- Phase 1: sequential chatroom -------------------------------------
    transcript: list[tuple[str, str]] = []
    answers: dict[str, str] = {}
    for persona in members:
        yield {
            "type": "agent_start",
            "id": persona.id,
            "name": persona.name,
            "avatar": persona.avatar,
            "color": persona.color,
        }

        convo = ""
        if history_block:
            convo += history_block + "\n\n"
        convo += f"The topic before the council:\n\n{topic}\n\n"
        if transcript:
            convo += "What other advisors have said so far:\n\n"
            convo += "\n\n".join(f"{n}: {t}" for n, t in transcript)
            convo += "\n\n"
        convo += "Now give your perspective."

        full = ""
        async for event in _stream_persona_turn(persona, convo, model):
            if event[0] == "delta":
                full += event[1]
                yield {"type": "agent_delta", "id": persona.id, "text": event[1]}
            else:  # ("tool", query)
                yield {"type": "agent_tool", "id": persona.id, "query": event[1]}

        full = full.strip()
        transcript.append((persona.name, full))
        answers[persona.id] = full
        yield {"type": "agent_done", "id": persona.id, "text": full}

    # --- Phase 2: peer voting --------------------------------------------
    yield {"type": "vote_start"}
    totals: dict[str, int] = {p.id: 0 for p in members}

    for voter in members:
        others = [p for p in members if p.id != voter.id]
        valid_names = {p.name for p in others}

        ballot = (
            f"The topic was:\n\n{topic}\n\n"
            "Here are the other advisors' answers. Score each one.\n\n"
        )
        for p in others:
            ballot += f"=== {p.name} ===\n{answers.get(p.id, '')}\n\n"

        try:
            resp = await model.ainvoke(
                [("system", voter.system + _VOTE_GUIDE), ("human", ballot)]
            )
            scores = _parse_scores(_content_text(resp), valid_names)
        except Exception:  # noqa: BLE001 — a bad ballot must not kill the run
            scores = []

        detail: list[dict[str, Any]] = []
        for name, score, reason in scores:
            target_id = name_to_id[name]
            totals[target_id] += score
            detail.append(
                {
                    "target": target_id,
                    "target_name": name,
                    "score": score,
                    "reason": reason,
                }
            )

        yield {
            "type": "vote",
            "voter": voter.id,
            "voter_name": voter.name,
            "scores": detail,
        }

    # --- Phase 3: verdict -------------------------------------------------
    id_to_name = {p.id: p.name for p in members}
    winner_id = max(totals, key=lambda k: totals[k]) if totals else None
    yield {
        "type": "verdict",
        "winner_id": winner_id,
        "winner_name": id_to_name.get(winner_id, "") if winner_id else "",
        "totals": totals,
        "answer": answers.get(winner_id, "") if winner_id else "",
    }
    yield {"type": "done"}

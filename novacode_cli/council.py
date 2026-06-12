"""Council of agents — independent answers + democratic voting.

A *council* takes a single question and runs it past five distinct personas,
each backed by the session's configured model but given its own personality.
Every member answers **independently** (it cannot see the others' answers), then
each casts a **single democratic vote** for the best answer (never its own). The
**majority** answer is the verdict.

:func:`run_council` is a pure async generator yielding plain ``dict`` events, so
it can be unit-tested without HTTP and rendered by the ``/council`` web server as
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
    " You are one member of a council of advisors. Independently analyze the "
    "question and give your OWN best answer — you cannot see the other members' "
    "answers. Stay in character, speak in the first person, be technically "
    "substantive, and keep it focused (~160 words). If you need current or "
    "factual information, call the web search tool first, then answer."
)

_VOTE_GUIDE = (
    " The council has answered independently. You have read every answer "
    "(yours is among them, unlabeled). Vote for the SINGLE best answer on merit "
    "— you may NOT vote for your own. Respond with ONLY a JSON object of the "
    'form {"choice":"<exact advisor name>","reason":"<one short sentence>"} '
    "and nothing else."
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


def _parse_vote(raw: str, valid_names: set[str]) -> tuple[str | None, str]:
    """Parse a single-choice ballot: ``{"choice": name, "reason": ...}``.

    Returns ``(choice_name, reason)`` where ``choice_name`` is None if the model
    didn't pick a valid (non-self) advisor. Tolerant of code fences / prose.
    """
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return None, ""
    try:
        data = json.loads(match.group(0))
    except (json.JSONDecodeError, ValueError):
        return None, ""
    if not isinstance(data, dict):
        return None, ""
    choice = str(data.get("choice", "")).strip()
    reason = str(data.get("reason", "")).strip()
    if choice not in valid_names:
        return None, reason
    return choice, reason


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
                ):
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

    Flow: every member answers the topic **independently** (no peer context),
    then each casts a **single democratic vote** for the best answer (never its
    own); the **majority** answer is the verdict.

    Event ``type``s, in order:
      ``council_start`` -> for each persona ``agent_start`` / ``agent_delta``* /
      ``agent_done`` -> ``vote_start`` -> for each persona ``vote`` ->
      ``verdict`` -> ``done``.
    """
    members = personas or PERSONAS
    name_to_id = {p.name: p.id for p in members}
    id_to_name = {p.id: p.name for p in members}
    history_block = _format_history(history)

    yield {
        "type": "council_start",
        "topic": topic,
        "agents": [
            {"id": p.id, "name": p.name, "avatar": p.avatar, "color": p.color}
            for p in members
        ],
    }

    # --- Phase 1: independent answers ------------------------------------
    # Each member analyzes the topic on its own; it does NOT see the others'
    # answers (only prior-round history, for follow-ups).
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
        convo += f"The question before the council:\n\n{topic}\n\n"
        convo += "Give your own independent answer."

        full = ""
        async for event in _stream_persona_turn(persona, convo, model):
            if event[0] == "delta":
                full += event[1]
                yield {"type": "agent_delta", "id": persona.id, "text": event[1]}
            else:  # ("tool", query)
                yield {"type": "agent_tool", "id": persona.id, "query": event[1]}

        answers[persona.id] = full.strip()
        yield {"type": "agent_done", "id": persona.id, "text": answers[persona.id]}

    # --- Phase 2: democratic voting (one vote each) ----------------------
    yield {"type": "vote_start"}
    tally: dict[str, int] = {p.id: 0 for p in members}

    for voter in members:
        others = [p for p in members if p.id != voter.id]
        valid_names = {p.name for p in others}

        ballot = f"The question was:\n\n{topic}\n\nThe answers:\n\n"
        for p in others:
            ballot += f"=== {p.name} ===\n{answers.get(p.id, '')}\n\n"
        ballot += "Vote for the single best answer."

        try:
            resp = await model.ainvoke(
                [("system", voter.system + _VOTE_GUIDE), ("human", ballot)]
            )
            choice_name, reason = _parse_vote(_content_text(resp), valid_names)
        except Exception:  # noqa: BLE001 — a bad ballot must not kill the run
            choice_name, reason = None, ""

        choice_id = name_to_id.get(choice_name) if choice_name else None
        if choice_id is not None:
            tally[choice_id] += 1

        yield {
            "type": "vote",
            "voter": voter.id,
            "voter_name": voter.name,
            "choice": choice_id,
            "choice_name": choice_name or "",
            "reason": reason,
        }

    # --- Phase 3: majority verdict ---------------------------------------
    # Winner = most votes; ties broken by council order (first member wins).
    winner_id = (
        max(members, key=lambda p: (tally[p.id], -members.index(p))).id
        if any(tally.values())
        else (members[0].id if members else None)
    )
    yield {
        "type": "verdict",
        "winner_id": winner_id,
        "winner_name": id_to_name.get(winner_id, "") if winner_id else "",
        "tally": tally,
        "votes": sum(tally.values()),
        "answer": answers.get(winner_id, "") if winner_id else "",
    }
    yield {"type": "done"}

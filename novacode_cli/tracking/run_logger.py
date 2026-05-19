"""Structured run logger middleware (Meta-Harness F2).

Every nova session writes structured artifacts to .nova/runs/<id>/:
  meta.json        — model, mode, start time, system-prompt hash
  turns/NN/
    prompt.txt     — messages sent to LLM this turn
    response.json  — LLM response (text + tool calls)
    tools.jsonl    — one line per tool call executed
  summary.json     — totals written on session exit

Query runs with: nova log list | show | grep | diff | verdict | frontier

Enabled by default; disable with: NOVA_RUN_LOGS=false
"""

from __future__ import annotations

import atexit
import hashlib
import json
import os
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from langchain.agents.middleware.types import (
    AgentMiddleware,
    AgentState,
    ModelRequest,
    ModelResponse,
)
from langchain.tools.tool_node import ToolCallRequest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.runtime import Runtime
from langgraph.types import Command


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _slug() -> str:
    return uuid.uuid4().hex[:4]


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:12]


def _safe_json(obj: Any) -> str:
    try:
        return json.dumps(obj, default=str, ensure_ascii=False)
    except Exception:  # noqa: BLE001
        return json.dumps(str(obj))


def _format_messages(messages: list[BaseMessage]) -> str:
    """Render messages as human-readable text for prompt.txt."""
    lines: list[str] = []
    for msg in messages:
        role = type(msg).__name__.replace("Message", "").upper()
        content = msg.content if isinstance(msg.content, str) else str(msg.content)
        lines.append(f"[{role}]\n{content[:4000]}")
    return "\n\n".join(lines)


def _serialize_response(response: ModelResponse) -> dict:
    """Extract key fields from a ModelResponse for logging."""
    out: dict[str, Any] = {"at": _now_iso()}
    try:
        msgs = getattr(response, "messages", None) or []
        serialized: list[dict] = []
        for m in msgs:
            entry: dict[str, Any] = {"type": type(m).__name__}
            if isinstance(m, AIMessage):
                entry["content"] = m.content if isinstance(m.content, str) else str(m.content)
                if m.tool_calls:
                    entry["tool_calls"] = [
                        {"name": tc.get("name"), "id": tc.get("id")} for tc in m.tool_calls
                    ]
            serialized.append(entry)
        out["messages"] = serialized
    except Exception as exc:  # noqa: BLE001
        out["error"] = str(exc)
    return out


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------

class RunLoggerMiddleware(AgentMiddleware):
    """Write structured per-turn logs to .nova/runs/<id>/ every session.

    Args:
        workspace_root: Project directory (run logs go under .nova/runs/).
        model_name: LLM model identifier to record in meta.json.
        enabled: Override flag. Defaults to NOVA_RUN_LOGS env var (default: on).
    """

    def __init__(
        self,
        *,
        workspace_root: str,
        model_name: str = "unknown",
        enabled: bool | None = None,
    ) -> None:
        self._workspace_root = workspace_root
        self._model_name = model_name
        if enabled is None:
            val = os.environ.get("NOVA_RUN_LOGS", "true").lower()
            self._enabled = val not in {"false", "0", "no", "off"}
        else:
            self._enabled = enabled

        self._run_dir: Path | None = None
        self._turn_count: int = 0
        self._current_turn_dir: Path | None = None
        self._start_time: float = time.time()
        self._total_tool_calls: int = 0
        self._exit_status: str = "incomplete"

        if self._enabled:
            atexit.register(self._write_summary)

    # ------------------------------------------------------------------
    # Run directory
    # ------------------------------------------------------------------

    def _ensure_run_dir(self) -> Path:
        if self._run_dir is None:
            ts = datetime.now(UTC).strftime("%Y-%m-%dT%H-%M-%S")
            run_id = f"{ts}_{_slug()}"
            run_dir = Path(self._workspace_root) / ".nova" / "runs" / run_id
            run_dir.mkdir(parents=True, exist_ok=True)
            self._run_dir = run_dir
            self._write_meta()
        return self._run_dir

    def _write_meta(self) -> None:
        if self._run_dir is None:
            return
        meta = {
            "run_id": self._run_dir.name,
            "model": self._model_name,
            "started_at": _now_iso(),
            "workspace": self._workspace_root,
        }
        (self._run_dir / "meta.json").write_text(_safe_json(meta), encoding="utf-8")

    def _write_summary(self) -> None:
        if not self._enabled or self._run_dir is None:
            return
        try:
            summary = {
                "run_id": self._run_dir.name,
                "turns": self._turn_count,
                "tool_calls": self._total_tool_calls,
                "wall_seconds": round(time.time() - self._start_time, 2),
                "exit_status": self._exit_status,
                "ended_at": _now_iso(),
            }
            (self._run_dir / "summary.json").write_text(
                _safe_json(summary), encoding="utf-8"
            )
            self._exit_status = "complete"
        except Exception:  # noqa: BLE001
            pass  # never crash on shutdown

    # ------------------------------------------------------------------
    # Hooks
    # ------------------------------------------------------------------

    def before_agent(
        self, state: AgentState, runtime: Runtime, config: RunnableConfig
    ) -> None:
        if self._enabled:
            self._ensure_run_dir()
        return None

    async def abefore_agent(
        self, state: AgentState, runtime: Runtime, config: RunnableConfig
    ) -> None:
        return self.before_agent(state, runtime, config)

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        if not self._enabled:
            return handler(request)

        turn_num = self._turn_count
        self._turn_count += 1

        run_dir = self._ensure_run_dir()
        turn_dir = run_dir / "turns" / f"{turn_num:02d}"
        turn_dir.mkdir(parents=True, exist_ok=True)
        self._current_turn_dir = turn_dir

        # Log prompt (system prompt + conversation messages)
        try:
            messages: list[BaseMessage] = list(request.state.get("messages", []))
            prompt_text = ""
            if request.system_prompt:
                prompt_text = f"[SYSTEM]\n{request.system_prompt[:3000]}\n\n"
            prompt_text += _format_messages(messages[-20:])  # last 20 messages
            (turn_dir / "prompt.txt").write_text(prompt_text, encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass

        response = handler(request)

        # Log response
        try:
            resp_data = _serialize_response(response)
            (turn_dir / "response.json").write_text(_safe_json(resp_data), encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass

        return response

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        if not self._enabled:
            return await handler(request)

        turn_num = self._turn_count
        self._turn_count += 1

        run_dir = self._ensure_run_dir()
        turn_dir = run_dir / "turns" / f"{turn_num:02d}"
        turn_dir.mkdir(parents=True, exist_ok=True)
        self._current_turn_dir = turn_dir

        try:
            messages: list[BaseMessage] = list(request.state.get("messages", []))
            prompt_text = ""
            if request.system_prompt:
                prompt_text = f"[SYSTEM]\n{request.system_prompt[:3000]}\n\n"
            prompt_text += _format_messages(messages[-20:])
            (turn_dir / "prompt.txt").write_text(prompt_text, encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass

        response = await handler(request)

        try:
            resp_data = _serialize_response(response)
            (turn_dir / "response.json").write_text(_safe_json(resp_data), encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass

        return response

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        result = handler(request)
        if self._enabled:
            self._log_tool(request, result)
        return result

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        result = await handler(request)
        if self._enabled:
            self._log_tool(request, result)
        return result

    def _log_tool(self, request: ToolCallRequest, result: ToolMessage | Command) -> None:
        turn_dir = self._current_turn_dir
        if turn_dir is None:
            turn_dir = self._ensure_run_dir() / "turns" / "00"
            turn_dir.mkdir(parents=True, exist_ok=True)

        try:
            tool_call = request.tool_call
            output: str
            if isinstance(result, ToolMessage):
                raw = result.content
                output = raw if isinstance(raw, str) else str(raw)
            else:
                output = str(result)

            entry = {
                "at": _now_iso(),
                "name": tool_call.get("name", "unknown"),
                "args": tool_call.get("args", {}),
                "output": output[:1500],
                "status": getattr(result, "status", "unknown") if isinstance(result, ToolMessage) else "command",
            }
            tools_file = turn_dir / "tools.jsonl"
            with tools_file.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, default=str, ensure_ascii=False) + "\n")
            self._total_tool_calls += 1
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------
    # Public helpers for the CLI
    # ------------------------------------------------------------------

    @property
    def run_dir(self) -> Path | None:
        return self._run_dir

    def mark_success(self) -> None:
        self._exit_status = "success"

    def mark_error(self, reason: str = "") -> None:
        self._exit_status = f"error: {reason}" if reason else "error"

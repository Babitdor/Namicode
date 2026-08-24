"""Watch remote async-subagent runs and notify when they finish.

deepagents' async subagents are fire-and-forget: ``start_async_task`` returns a
``task_id`` and the main agent is told to stop, nothing pushes completion back.
This poller closes that gap. Given the tasks recorded in the agent state
(``async_tasks``), it polls each running task's remote status via the LangGraph
SDK and fires a notification (through the injected callback) when it reaches a
terminal state. Best-effort throughout: a poll failure never raises.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable

logger = logging.getLogger("nova.async_task_watcher")

# LangGraph Run.status values that mean "no longer running".
_TERMINAL = frozenset({"success", "error", "timeout", "interrupted", "cancelled"})
_POLL_INTERVAL = 6.0
_MAX_WATCH_SECONDS = 1800.0  # stop watching a task after 30 min


class AsyncTaskWatcher:
    """Polls launched async-subagent runs; notifies on completion. Idempotent."""

    def __init__(self, notify: Callable[[str, str, str], Any]) -> None:
        # notify(level, title, message) — surfaces a completed task to the user.
        self._notify = notify
        self._watched: set[str] = set()
        self._tasks: set[asyncio.Task] = set()
        self._specs: dict[str, dict] | None = None
        # Currently-running tasks, for the TUI indicator: task_id -> {agent_name, started}.
        self._running: dict[str, dict] = {}

    def _spec_for(self, agent_name: str) -> dict | None:
        """The async-subagent spec (url + headers) for a given agent name."""
        if self._specs is None:
            try:
                from novacode_cli.agents.default_subagents.async_subagents import (
                    retrieve_async_subagents,
                )

                self._specs = {s["name"]: s for s in retrieve_async_subagents()}
            except Exception:  # noqa: BLE001
                self._specs = {}
        return self._specs.get(agent_name)

    def sync_from_state(self, async_tasks: dict[str, Any] | None) -> None:
        """Start watching any running task in *async_tasks* not already watched."""
        for task_id, task in (async_tasks or {}).items():
            if not isinstance(task, dict) or task.get("status") != "running":
                continue
            if task_id in self._watched:
                continue
            self._watched.add(task_id)
            self._running[task_id] = {
                "agent_name": task.get("agent_name") or "async agent",
                "started": time.monotonic(),
            }
            t = asyncio.create_task(self._poll(dict(task)))
            self._tasks.add(t)
            t.add_done_callback(self._tasks.discard)

    def running_tasks(self) -> list[dict]:
        """Snapshot of currently-running async tasks (for the TUI indicator)."""
        now = time.monotonic()
        return [
            {"task_id": tid, "agent_name": v["agent_name"], "runtime": now - v["started"]}
            for tid, v in self._running.items()
        ]

    async def _poll(self, task: dict) -> None:
        task_id = str(task.get("task_id") or task.get("thread_id") or "?")
        agent_name = task.get("agent_name") or "async agent"
        try:
            spec = self._spec_for(agent_name)
            if spec is None:
                return
            try:
                from langgraph_sdk import get_client

                client = get_client(url=spec.get("url"), headers=spec.get("headers") or {})
            except Exception:  # noqa: BLE001
                return

            thread_id, run_id = task.get("thread_id"), task.get("run_id")
            loop = asyncio.get_event_loop()
            deadline = loop.time() + _MAX_WATCH_SECONDS
            while True:
                await asyncio.sleep(_POLL_INTERVAL)
                try:
                    run = await client.runs.get(thread_id, run_id)
                    status = (run or {}).get("status", "running")
                except Exception:  # noqa: BLE001 — transient; keep polling until deadline
                    status = "running"
                if status in _TERMINAL:
                    self._emit(agent_name, task_id, status)
                    return
                if loop.time() > deadline:
                    logger.debug("async task %s watch timed out", task_id)
                    return
        finally:
            # Drop from the running set on every exit path so the TUI indicator clears.
            self._running.pop(task_id, None)

    def _emit(self, agent_name: str, task_id: str, status: str) -> None:
        level = "success" if status == "success" else "warning"
        verb = "completed" if status == "success" else status
        title = f"Async agent {verb}"
        message = (
            f"{agent_name} ({task_id[:8]}) {verb}. "
            f"Ask me to check_async_task {task_id[:8]} for the result."
            # Full task_id is carried for consumers that auto-report the result
            # (the TUI parses it to drive a proactive turn); the human-readable
            # prefix above keeps the truncated form for display.
            f"\n[async_task_id={task_id}]"
        )
        try:
            self._notify(level, title, message)
        except Exception:  # noqa: BLE001 — a notification must never break the watcher
            pass

"""Long-lived child session: JSONL on stdio, real HITL forwarded to the parent.

This is the process a parallel session runs in. It is the interactive sibling of
:func:`novacode_cli.headless.runner.run_headless`: same canonical event stream
(:func:`~novacode_cli.core.agent_loop.iterate_agent_events`), but instead of
resolving one prompt and exiting, it stays up, accepts prompts on stdin, and
streams every event to the parent as JSONL.

The important difference from headless mode is approvals. Headless auto-resolves
interrupts because nobody is watching; here a human *is* watching — just in
another process — so interrupts are forwarded to the parent, which shows the
normal approval modal and sends the decision back. Every path resolves the
interrupt future in a ``finally``, so a dead or slow parent can never wedge the
agent graph: it fails closed to ``default_interrupt_response``.

One turn runs at a time. Prompts that arrive mid-turn are queued, not dropped.
"""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import logging
import os
import sys
import threading
from collections import deque
from typing import Any

from novacode_cli import ui_events as ev
from novacode_cli.core.agent_loop import default_interrupt_response, iterate_agent_events
from novacode_cli.sessions import protocol

logger = logging.getLogger(__name__)

EXIT_OK = 0
EXIT_ERROR = 1


class _Emitter:
    """Writes JSONL to the parent, one whole line at a time.

    Uses the fd dup'd before agent build when available: stdio MCP servers close
    the Python-level ``sys.stdout`` on shutdown, which would silently sever the
    parent connection. Writes are locked because the turn task and the shutdown
    path can both emit.
    """

    def __init__(self, fd: int | None) -> None:
        # The caller's dup can fail (it returns None), and falling back to
        # `sys.stdout` is not safe: a stdio MCP server closes that object during
        # agent build, after which every frame we write vanishes and the parent
        # sees a session that started but never spoke. Duplicate the ORIGINAL
        # stdout ourselves so we own a descriptor nothing else can close.
        if fd is None:
            # fd 1 IS stdout at the OS level, whatever Python object currently
            # wraps it — no `sys.stdout.fileno()` indirection to go wrong.
            for candidate in (lambda: os.dup(1), lambda: os.dup(sys.__stdout__.fileno())):
                try:
                    fd = candidate()
                    break
                except (OSError, ValueError, AttributeError):
                    continue
        self._fd = fd
        self._lock = threading.Lock()
        self.closed = False

    def __call__(self, msg: dict) -> None:
        if self.closed:
            return
        line = protocol.dumps(msg)
        try:
            with self._lock:
                if self._fd is not None:
                    os.write(self._fd, line.encode("utf-8", "replace"))
                else:
                    stream = sys.__stdout__ or sys.stdout
                    stream.write(line)
                    stream.flush()
        except (OSError, ValueError):
            # Parent went away mid-write; stop trying so shutdown stays quiet.
            self.closed = True


class SessionWorker:
    """Owns the child's stdin loop, the single active turn, and pending HITL."""

    def __init__(
        self,
        *,
        agent,
        assistant_id: str | None,
        session_state,
        backend=None,
        model_name: str | None = None,
        session_manager=None,
    ) -> None:
        self.agent = agent
        self.assistant_id = assistant_id
        self.session_state = session_state
        self.backend = backend
        self.model_name = model_name
        self.session_manager = session_manager

        self._emit = _Emitter(getattr(session_state, "headless_out_fd", None))
        self._pending: dict[str, asyncio.Future] = {}
        self._interrupt_ids = itertools.count(1)
        self._queued: deque[tuple[str, str]] = deque()
        self._turn: asyncio.Task | None = None
        self._turn_id: str | None = None
        self._seen: set[str] = set()
        self._stop = False
        # Parent messages land here. Constructed eagerly (safe since 3.10, where
        # Queue no longer binds a loop at construction) so tests can seed it
        # without standing up a stdin pipe.
        self.inbox: asyncio.Queue = asyncio.Queue()

    # ── stdin ────────────────────────────────────────────────────────────

    async def _stdin_pump(self) -> None:
        """Feed parsed parent messages onto :attr:`inbox`; ``None`` on EOF.

        ``sys.stdin.readline`` in a thread rather than ``connect_read_pipe``,
        which does not support pipes on Windows.
        """
        while not self._stop:
            try:
                line = await asyncio.to_thread(sys.stdin.readline)
            except (OSError, ValueError):
                line = ""
            if not line:  # EOF -> parent closed our stdin
                await self.inbox.put(None)
                return
            msg = protocol.loads(line)
            if msg is not None:
                await self.inbox.put(msg)

    # ── turns ────────────────────────────────────────────────────────────

    async def _forward_interrupt(self, event: ev.InterruptRequest) -> None:
        """Ask the parent to decide, and always resolve the agent's future."""
        iid = f"i{next(self._interrupt_ids)}"
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[iid] = fut

        self._emit(
            {
                "t": "interrupt",
                "id": iid,
                "kind": event.kind,
                "payload": protocol.jsonable(event.payload),
            }
        )

        result: Any = None
        try:
            result = await fut
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — a broken reply must not wedge the graph
            logger.debug("interrupt %s failed", iid, exc_info=True)
        finally:
            self._pending.pop(iid, None)
            if not event.future.done():
                # Fail closed: no answer means the benign default, never a
                # silent approval.
                event.future.set_result(
                    result if result is not None else default_interrupt_response(event.kind)
                )

    async def _run_turn(self, prompt_id: str, text: str) -> None:
        """Stream one prompt, emitting every event to the parent."""
        ok = True
        source = iterate_agent_events(
            text,
            self.agent,
            self.assistant_id,
            self.session_state,
            backend=self.backend,
            seen_message_ids=self._seen,
        )
        try:
            async for event in source:
                if isinstance(event, ev.InterruptRequest):
                    await self._forward_interrupt(event)
                    continue
                try:
                    self._emit({"t": "ev", **protocol.encode_event(event)})
                except ValueError:
                    logger.debug("unencodable event %s", type(event).__name__)
                if isinstance(event, ev.Error):
                    ok = False
        except asyncio.CancelledError:
            self._emit({"t": "ev", **protocol.encode_event(ev.Cancelled())})
            ok = False
            raise
        except Exception as exc:  # noqa: BLE001 — a turn must never kill the worker
            ok = False
            logger.debug("turn failed", exc_info=True)
            self._emit(
                {"t": "ev", **protocol.encode_event(
                    ev.Error(message=f"{type(exc).__name__}: {exc}")
                )}
            )
        finally:
            with contextlib.suppress(Exception):
                await source.aclose()
            self._emit({"t": "turn_done", "id": prompt_id, "ok": ok})

    def _start_turn(self, prompt_id: str, text: str) -> None:
        self._turn_id = prompt_id
        self._turn = asyncio.create_task(self._run_turn(prompt_id, text))

    def _turn_running(self) -> bool:
        return self._turn is not None and not self._turn.done()

    async def _cancel_turn(self) -> None:
        """Cancel the active turn, killing any foreground shell command first.

        Worker cancellation alone cannot reach a subprocess the shell middleware
        is blocked on, which is why the job registry gets asked to kill first.
        """
        if not self._turn_running():
            return
        with contextlib.suppress(Exception):
            from novacode_cli.shell import jobs

            jobs.request_kill()
        assert self._turn is not None
        self._turn.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await self._turn

    # ── main loop ────────────────────────────────────────────────────────

    async def run(self) -> int:
        """Serve the parent until shutdown or EOF. Returns an exit code."""
        self._emit(
            {
                "t": "ready",
                "session_id": getattr(self.session_state, "session_id", None),
                "thread_id": getattr(self.session_state, "thread_id", None),
                "cwd": os.getcwd(),
                "model": self.model_name,
                "assistant_id": self.assistant_id,
            }
        )

        pump = asyncio.create_task(self._stdin_pump())
        exit_code = EXIT_OK
        get_msg = asyncio.create_task(self.inbox.get())

        try:
            while True:
                # Wake on a parent message OR the active turn finishing. Waiting
                # on the inbox alone would starve a queued prompt whenever the
                # parent sends nothing further.
                waiters: set[asyncio.Task] = {get_msg}
                if self._turn is not None and not self._turn.done():
                    waiters.add(self._turn)
                done, _ = await asyncio.wait(waiters, return_when=asyncio.FIRST_COMPLETED)

                # A finished turn frees the slot for whatever was queued.
                if self._turn is not None and self._turn in done:
                    self._turn = None
                    self._turn_id = None
                    if self._queued and not self._stop:
                        pid, text = self._queued.popleft()
                        self._start_turn(pid, text)

                if get_msg not in done:
                    continue

                msg = get_msg.result()
                get_msg = asyncio.create_task(self.inbox.get())
                if msg is None:  # parent closed stdin
                    break

                kind = msg.get("t")
                if kind == "prompt":
                    text = str(msg.get("text") or "")
                    pid = str(msg.get("id") or "p")
                    if not text.strip():
                        self._emit({"t": "turn_done", "id": pid, "ok": True})
                    elif self._turn_running():
                        self._queued.append((pid, text))  # queued, never dropped
                    else:
                        self._start_turn(pid, text)

                elif kind == "interrupt_reply":
                    fut = self._pending.get(str(msg.get("id")))
                    if fut is not None and not fut.done():
                        fut.set_result(msg.get("result"))

                elif kind == "cancel":
                    self._queued.clear()
                    await self._cancel_turn()

                elif kind == "shutdown":
                    break
        except Exception as exc:  # noqa: BLE001 — report, don't crash silently
            exit_code = EXIT_ERROR
            self._emit({"t": "error", "message": f"{type(exc).__name__}: {exc}"})
            logger.debug("worker loop failed", exc_info=True)
        finally:
            self._stop = True
            get_msg.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await get_msg
            await self._cancel_turn()
            # Anything still waiting on the parent gets the safe default.
            for fut in list(self._pending.values()):
                if not fut.done():
                    fut.set_result(None)
            pump.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await pump
            await self._save()

        return exit_code

    async def _save(self) -> None:
        """Persist the conversation so the session is resumable like any other."""
        try:
            from novacode_cli.headless.runner import _autosave

            await _autosave(
                agent=self.agent,
                assistant_id=self.assistant_id,
                session_state=self.session_state,
                model_name=self.model_name,
                session_manager=self.session_manager,
                is_error=False,
            )
        except Exception:  # noqa: BLE001 — never fail shutdown on a save
            logger.debug("worker session save skipped", exc_info=True)


async def run_session_worker(
    *,
    agent,
    assistant_id: str | None,
    session_state,
    backend=None,
    model_name: str | None = None,
    session_manager=None,
) -> int:
    """Run one child session until the parent shuts it down."""
    worker = SessionWorker(
        agent=agent,
        assistant_id=assistant_id,
        session_state=session_state,
        backend=backend,
        model_name=model_name,
        session_manager=session_manager,
    )
    return await worker.run()

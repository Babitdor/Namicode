"""Persistent Python kernel tool — run Python with a namespace that survives calls.

The ``python_kernel`` tool gives the agent a long-lived Python interpreter. State
built up in one call (imports, variables, dataframes) is visible in the next, so
multi-step data work doesn't re-run everything each time. It also supports
dill-based snapshots: ``snapshot="save"`` checkpoints the namespace to a file, and
``snapshot="load:<path>"`` restores it — surviving kernel restarts and letting the
agent persist intermediate state.

The kernel runs as a child subprocess (``python -m novacode_cli.tools.python_kernel_loop``)
with the same privileges as the shell tool. A per-call timeout kills a hung kernel
and respawns it on the next call, so a runaway ``time.sleep(999)`` can't wedge the
agent.

This module must NEVER ``console.print`` — it runs inside the live agent loop / TUI.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

from langchain.tools import tool

logger = logging.getLogger("nova.tools.python_kernel")

#: Per-call timeout (seconds). A hung kernel is killed and respawned.
_DEFAULT_TIMEOUT = 30.0
#: Cap on captured output per call.
_MAX_OUTPUT = 100_000
#: Default snapshot filename (relative to the kernel's cwd).
_DEFAULT_SNAPSHOT = "kernel_snapshot.pkl"

_kernel: _KernelProcess | None = None
_kernel_lock = asyncio.Lock()


class _KernelProcess:
    """A managed kernel subprocess with a persistent namespace."""

    def __init__(self) -> None:
        self._proc: asyncio.subprocess.Process | None = None
        self._cwd = str(Path.cwd())

    async def _ensure(self) -> asyncio.subprocess.Process:
        if self._proc is not None and self._proc.returncode is None:
            return self._proc
        # Spawn the kernel loop. Use the same interpreter that's running us.
        python = sys.executable
        cmd = [python, "-u", "-m", "novacode_cli.tools.python_kernel_loop"]
        self._proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self._cwd,
            env=os.environ.copy(),
        )
        return self._proc

    async def _kill(self) -> None:
        if self._proc is None:
            return
        if self._proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                self._proc.kill()
        with contextlib.suppress(ProcessLookupError, ChildProcessError):
            await self._proc.wait()
        self._proc = None

    async def request(self, payload: dict[str, Any], timeout_secs: float) -> dict[str, Any]:
        """Send one request and await the response. Kills/respawns on timeout."""
        proc = await self._ensure()
        if proc.stdin is None or proc.stdout is None:
            return {"ok": False, "output": "", "error": "kernel pipes unavailable"}
        line = json.dumps(payload) + "\n"
        try:
            proc.stdin.write(line.encode("utf-8"))
            await proc.stdin.drain()
            raw = await asyncio.wait_for(proc.stdout.readline(), timeout=timeout_secs)
        except TimeoutError:
            logger.debug("python_kernel timed out; killing and respawning")
            await self._kill()
            return {
                "ok": False,
                "output": "",
                "error": f"kernel timed out after {timeout_secs:.0f}s (killed and respawned)",
            }
        if not raw:
            # EOF — the kernel died. Capture stderr for diagnostics.
            stderr = b""
            if proc.stderr is not None:
                try:
                    stderr = await asyncio.wait_for(proc.stderr.read(), timeout=2.0)
                except (TimeoutError, Exception):  # noqa: BLE001
                    stderr = b""
            await self._kill()
            return {
                "ok": False,
                "output": "",
                "error": f"kernel exited unexpectedly: {stderr.decode('utf-8', 'replace')[:500]}",
            }
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return {"ok": False, "output": "", "error": "kernel returned invalid JSON"}

    async def close(self) -> None:
        await self._kill()


async def _get_kernel() -> _KernelProcess:
    global _kernel  # noqa: PLW0603 — module-level singleton kernel process
    async with _kernel_lock:
        if _kernel is None:
            _kernel = _KernelProcess()
        return _kernel


@tool
async def python_kernel(
    code: str,
    snapshot: str = "",
    snapshot_path: str = "",
    timeout: float = _DEFAULT_TIMEOUT,  # noqa: ASYNC109 — agent-facing per-call timeout
) -> str:
    """Run Python code in a persistent kernel whose namespace survives across calls.

    Use this for multi-step data work: define variables/imports in one call and
    reference them in the next. The kernel keeps running between calls.

    Args:
        code: Python code to execute. State (imports, variables) persists.
        snapshot: Optional. "" (default) runs in the live namespace. "save"
            checkpoints the namespace to a dill file after running. "load:<path>"
            restores a previously saved namespace before running.
        snapshot_path: Filename for "save" (default "kernel_snapshot.pkl").
        timeout: Max seconds for this call (default 30). A hung kernel is killed
            and respawned on the next call.

    Returns:
        The captured stdout/stderr, or an error traceback. Use "reset" as the
        code to clear the namespace.
    """
    if code.strip() == "reset":
        payload: dict[str, Any] = {"op": "reset"}
    else:
        payload = {
            "op": "exec",
            "code": code,
            "snapshot": snapshot or None,
            "snapshot_path": snapshot_path or _DEFAULT_SNAPSHOT,
        }
    kernel = await _get_kernel()
    resp = await kernel.request(payload, timeout)
    output = str(resp.get("output") or "")
    if resp.get("ok"):
        if resp.get("snapshot_path"):
            return f"snapshot saved to {resp['snapshot_path']}\n{output}".rstrip()
        return output.rstrip() or "(no output)"
    error = str(resp.get("error") or "unknown error")
    return f"Error:\n{error}\n{output}".rstrip()

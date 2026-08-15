"""Environment bootstrap middleware (Meta-Harness F1).

Captures a live snapshot of the workspace before the first LLM turn and
injects it as an [Environment Snapshot] block in every system prompt.

This eliminates the 2-4 exploratory tool calls agents spend on cold-start
environment probing (python version? what files exist? git branch?).

Enabled by default; disable with: NOVA_BOOTSTRAP_SNAPSHOT=false
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Awaitable, Callable
from typing import Annotated, NotRequired, TypedDict

from langchain.messages import SystemMessage
from langchain.agents.middleware.types import (
    AgentMiddleware,
    AgentState,
    ModelRequest,
    ModelResponse,
    PrivateStateAttr,
)
from langchain_core.runnables import RunnableConfig
from langgraph.runtime import Runtime

# ---------------------------------------------------------------------------
# Snapshot commands per platform
# ---------------------------------------------------------------------------

_UNIX_SNAPSHOT_CMD = (
    "echo '=== cwd ===' && pwd && "
    "echo '=== files ===' && ls -1 2>/dev/null | head -25 && "
    "echo '=== git ===' && git status --short --branch 2>/dev/null || echo '(not a git repo)' && "
    "echo '=== languages ===' && "
    "(python --version 2>&1 || python3 --version 2>&1 || true) && "
    "(node --version 2>&1 || true) && "
    "(rustc --version 2>&1 || true) && "
    "(go version 2>&1 || true) && "
    "echo '=== package managers ===' && "
    "(pip --version 2>&1 | head -1 || true) && "
    "(npm --version 2>&1 || true) && "
    "(uv --version 2>&1 || true) && "
    "(cargo --version 2>&1 || true)"
)

_WIN_SNAPSHOT_CMD = (
    "Write-Output '=== cwd ===' ; Get-Location ; "
    "Write-Output '=== files ===' ; Get-ChildItem -Name | Select-Object -First 25 ; "
    "Write-Output '=== git ===' ; "
    "if (Get-Command git -ErrorAction SilentlyContinue) { git status --short --branch } "
    "else { Write-Output '(git not found)' } ; "
    "Write-Output '=== languages ===' ; "
    "if (Get-Command python -ErrorAction SilentlyContinue) { python --version } ; "
    "if (Get-Command node -ErrorAction SilentlyContinue) { node --version } ; "
    "if (Get-Command rustc -ErrorAction SilentlyContinue) { rustc --version } ; "
    "if (Get-Command go -ErrorAction SilentlyContinue) { go version } ; "
    "Write-Output '=== package managers ===' ; "
    "if (Get-Command pip -ErrorAction SilentlyContinue) { pip --version } ; "
    "if (Get-Command npm -ErrorAction SilentlyContinue) { npm --version } ; "
    "if (Get-Command uv -ErrorAction SilentlyContinue) { uv --version } ; "
    "if (Get-Command cargo -ErrorAction SilentlyContinue) { cargo --version }"
)

_SNAPSHOT_MAX_BYTES = 2_048  # keep prompt bloat minimal


def _run_snapshot(workspace_root: str, timeout: float) -> str:
    """Run the environment snapshot command and return its output."""
    try:
        if sys.platform == "win32":
            result = subprocess.run(  # noqa: S602
                ["powershell", "-NonInteractive", "-Command", _WIN_SNAPSHOT_CMD],
                capture_output=True,
                timeout=timeout,
                cwd=workspace_root,
            )
        else:
            result = subprocess.run(  # noqa: S602
                _UNIX_SNAPSHOT_CMD,
                shell=True,
                capture_output=True,
                timeout=timeout,
                cwd=workspace_root,
            )
        output = (result.stdout or b"").decode("utf-8", errors="replace").strip()
        if not output:
            return "(snapshot produced no output)"
        if len(output) > _SNAPSHOT_MAX_BYTES:
            output = output[:_SNAPSHOT_MAX_BYTES] + "\n... (truncated)"
        return output
    except subprocess.TimeoutExpired:
        return "(snapshot timed out)"
    except Exception as exc:  # noqa: BLE001
        return f"(snapshot unavailable: {exc})"


# ---------------------------------------------------------------------------
# State schema
# ---------------------------------------------------------------------------


class _BootstrapState(AgentState):
    """Private state for BootstrapMiddleware."""

    env_snapshot: NotRequired[Annotated[str, PrivateStateAttr]]


class _BootstrapStateUpdate(TypedDict):
    env_snapshot: str


# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------


class BootstrapMiddleware(AgentMiddleware):
    """Capture a live environment snapshot and inject it into every system prompt.

    The snapshot is captured exactly once per session (on the first agent turn)
    then reused for all subsequent LLM calls from the cached private state.

    Args:
        workspace_root: Directory to run the snapshot command in.
        timeout: Maximum seconds to wait for the snapshot command. Default 15.
        enabled: If False, this middleware is a no-op. Defaults to the value of
            the ``NOVA_BOOTSTRAP_SNAPSHOT`` env var (truthy unless set to "false"
            or "0").
    """

    state_schema = _BootstrapState

    def __init__(
        self,
        *,
        workspace_root: str,
        timeout: float = 15.0,
        enabled: bool | None = None,
    ) -> None:
        self._workspace_root = workspace_root
        self._timeout = timeout
        if enabled is None:
            val = os.environ.get("NOVA_BOOTSTRAP_SNAPSHOT", "true").lower()
            self._enabled = val not in {"false", "0", "no", "off"}
        else:
            self._enabled = enabled

        # Prewarm: the snapshot spawns PowerShell + ~8 sequential version
        # probes (~4s on Windows). Running it lazily on the first turn blocked
        # the event loop for that long. Kick it off in a daemon thread NOW
        # (agent build time) — it finishes while the user types their first
        # message, so before_agent just collects the result.
        self._snapshot_future: object | None = None
        if self._enabled:
            import concurrent.futures

            self._executor = concurrent.futures.ThreadPoolExecutor(
                max_workers=1, thread_name_prefix="env-snapshot"
            )
            self._snapshot_future = self._executor.submit(
                _run_snapshot, workspace_root, timeout
            )
            self._executor.shutdown(wait=False)  # thread finishes; no new work

    # ------------------------------------------------------------------
    # Capture
    # ------------------------------------------------------------------

    def _collect_snapshot(self) -> str:
        """Get the prewarmed snapshot, waiting if it's still running."""
        fut = self._snapshot_future
        if fut is None:  # prewarm never started (disabled at init, enabled later)
            return _run_snapshot(self._workspace_root, self._timeout)
        try:
            return fut.result(timeout=self._timeout)  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001 - timeout/crash → same fallback text as before
            return "(snapshot timed out)"

    def before_agent(  # type: ignore[override]
        self,
        state: _BootstrapState,
        runtime: Runtime,
        config: RunnableConfig,
    ) -> _BootstrapStateUpdate | None:
        """Collect the prewarmed snapshot on the very first turn, store in state."""
        if not self._enabled or "env_snapshot" in state:
            return None
        return _BootstrapStateUpdate(env_snapshot=self._collect_snapshot())

    async def abefore_agent(  # type: ignore[override]
        self,
        state: _BootstrapState,
        runtime: Runtime,
        config: RunnableConfig,
    ) -> _BootstrapStateUpdate | None:
        """Async version — collects off-thread so a still-running snapshot
        never blocks the event loop."""
        if not self._enabled or "env_snapshot" in state:
            return None
        import asyncio

        snapshot = await asyncio.to_thread(self._collect_snapshot)
        return _BootstrapStateUpdate(env_snapshot=snapshot)

    # ------------------------------------------------------------------
    # Injection
    # ------------------------------------------------------------------

    def _inject(self, request: ModelRequest) -> ModelRequest:
        """Prepend the snapshot block to the system prompt."""
        if not self._enabled:
            return request
        snapshot = request.state.get("env_snapshot", "")
        if not snapshot:
            return request
        block = f"[Environment Snapshot]\n{snapshot}\n[/Environment Snapshot]"
        if request.system_prompt:
            new_prompt = block + "\n\n" + request.system_prompt
        else:
            new_prompt = block
        return request.override(system_message=SystemMessage(new_prompt))

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        return handler(self._inject(request))

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        return await handler(self._inject(request))

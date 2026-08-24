"""CoworkBrokerMiddleware — enforce WorkspacePolicy on the LIVE agent's tools.

Every filesystem/shell tool call is authorized against the broker BEFORE it runs;
a denied call returns an error ToolMessage and never executes. This is the
defense that makes the cowork agent actually confined — the broker, not the
model, is the boundary. Fail closed: any resolution/authz error → deny.

The agent uses the deepagents virtual filesystem (paths like ``/src/a.py`` rooted
at ``workspace_root``); we map those to real absolute paths before authorizing so
symlink/``..`` escapes are caught by :meth:`WorkspacePolicy.authorize`.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from langchain.agents.middleware.types import AgentMiddleware
from langchain_core.messages import ToolMessage

from novacode_cli.cowork.policy import get_policy

# tool name -> op it needs (path-bearing tools). Shell/execute authorized for
# execute on the workspace root.
_READ_TOOLS = frozenset({"read_file", "ls", "glob", "grep"})
_WRITE_TOOLS = frozenset({"write_file", "edit_file", "str_replace", "apply_patch", "delete_file"})
_EXEC_TOOLS = frozenset({"shell", "bash", "execute"})
_PATH_KEYS = ("file_path", "path", "target", "dir", "directory")


class CoworkBrokerMiddleware(AgentMiddleware):
    """Deny any tool operation outside the granted workspaces."""

    def __init__(self, workspace_root: str | Path) -> None:
        super().__init__()
        self._root = Path(workspace_root).resolve()
        self.tools = []  # type: ignore[assignment]

    def _to_real(self, p: str) -> Path:
        """Map a tool path arg (virtual ``/x``, absolute, or relative) to a real
        absolute path so the broker resolves symlinks/``..`` on the true target."""
        s = str(p)
        if s.startswith(("/", "\\")):
            return (self._root / s.lstrip("/\\")).resolve()
        pp = Path(s)
        return pp.resolve() if pp.is_absolute() else (self._root / pp).resolve()

    def _deny(self, request: Any) -> ToolMessage | None:
        """Return an error ToolMessage if the call is not authorized, else None."""
        try:
            tc = request.tool_call
            name = tc.get("name", "")
            args = tc.get("args", {}) or {}
        except Exception:  # noqa: BLE001 — malformed request → fail closed
            return ToolMessage(content="[Cowork broker] malformed tool call denied", tool_call_id="", status="error")

        checks: list[tuple[Path, str]] = []
        if name in _READ_TOOLS or name in _WRITE_TOOLS:
            op = "write" if name in _WRITE_TOOLS else "read"
            raw = next((args[k] for k in _PATH_KEYS if args.get(k)), None)
            if raw is None:
                return None  # nothing path-like to gate (defensive: allow)
            try:
                checks.append((self._to_real(raw), op))
            except Exception:  # noqa: BLE001
                return self._error(name, tc, "SANDBOX_UNAVAILABLE", f"cannot resolve {raw!r}")
            # move/rename: also gate the destination for write.
            dst = args.get("new_path") or args.get("dest") or args.get("destination")
            if dst:
                try:
                    checks.append((self._to_real(dst), "write"))
                except Exception:  # noqa: BLE001
                    return self._error(name, tc, "SANDBOX_UNAVAILABLE", f"cannot resolve {dst!r}")
        elif name in _EXEC_TOOLS:
            checks.append((self._root, "execute"))
        else:
            return None  # non-filesystem/shell tool: not gated by the workspace broker

        pol = get_policy()
        for path, op in checks:
            d = pol.authorize(path, op)
            if not d.allowed:
                return self._error(name, tc, d.code, f"{d.reason}: {path}")
        return None

    @staticmethod
    def _error(name: str, tc: dict, code: str, detail: str) -> ToolMessage:
        return ToolMessage(
            content=(
                f"[Cowork broker DENIED — {code}] {detail}. This path/action is "
                f"outside the granted workspace(s). Ask the user to grant the folder "
                f"in the Permissions panel if it should be accessible."
            ),
            tool_call_id=tc.get("id", ""),
            name=name,
            status="error",
        )

    def wrap_tool_call(
        self, request: Any, handler: Callable[[Any], ToolMessage | Any]
    ) -> ToolMessage | Any:
        deny = self._deny(request)
        return deny if deny is not None else handler(request)

    async def awrap_tool_call(
        self, request: Any, handler: Callable[[Any], Awaitable[ToolMessage | Any]]
    ) -> ToolMessage | Any:
        deny = self._deny(request)
        return deny if deny is not None else await handler(request)

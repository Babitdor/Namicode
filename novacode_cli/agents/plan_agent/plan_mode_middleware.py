"""Middleware that enforces plan mode restrictions on tool calls.

Blocks write_file, edit_file, and execute tools during planning.
Only allows write_file/edit_file when the target is inside .nova/plans/.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Awaitable, Callable

from langchain_core.messages import ToolMessage
from langchain.agents.middleware.types import AgentMiddleware

_BLOCKED_TOOLS = frozenset(
    {"execute", "shell", "execute_bash", "start_dev_server", "run_tests", "write_todos"}
)
_RESTRICTED_WRITE_TOOLS = frozenset({"write_file", "edit_file"})


class PlanModeMiddleware(AgentMiddleware):
    """Blocks write/execute tool calls outside .nova/plans/ during plan mode.

    Allows write_file/edit_file only when the target path is inside .nova/plans/.
    All execute/shell tools are blocked entirely until exit_plan_mode is approved.
    """

    def __init__(self, workspace_root: Path | None = None) -> None:
        self._plan_dir = (
            (workspace_root / ".nova" / "plans").resolve() if workspace_root else None
        )

    async def awrap_tool_call(
        self,
        request: Any,
        handler: Callable[..., Awaitable[ToolMessage | Any]],
    ) -> ToolMessage | Any:
        tool_name: str = request.tool_call.get("name", "")

        if tool_name in _BLOCKED_TOOLS:
            return ToolMessage(
                content=(
                    f"[Plan Mode] `{tool_name}` is blocked during planning. "
                    "Call `exit_plan_mode` and receive user approval before running commands."
                ),
                tool_call_id=request.tool_call["id"],
                status="error",
            )

        if tool_name in _RESTRICTED_WRITE_TOOLS:
            args = request.tool_call.get("args", {})
            path = str(args.get("path") or args.get("file_path") or "")

            if not self._is_inside_plan_dir(path):
                return ToolMessage(
                    content=(
                        f"[Plan Mode] Cannot call `{tool_name}` on `{path or '(unknown path)'}`. "
                        "During planning, writes are only allowed to `.nova/plans/`. "
                        "Write your plan there, then call `exit_plan_mode` to request user approval."
                    ),
                    tool_call_id=request.tool_call["id"],
                    status="error",
                )

        return await handler(request)

    def _is_inside_plan_dir(self, path: str) -> bool:
        if not path:
            return False

        # Virtual paths (starting with /) come from the LLM when the backend
        # uses virtual_mode=True. The plan directory in virtual path space is
        # /.nova/plans/ — check if the path starts with this prefix.
        # This handles paths like /.nova/plans/plan.md correctly regardless
        # of the OS, since virtual paths always use forward slashes.
        VIRTUAL_PLAN_PREFIX = "/.nova/plans/"
        if path.startswith("/"):
            normalized = path.rstrip("/") + "/"
            return normalized.startswith(VIRTUAL_PLAN_PREFIX) or normalized == VIRTUAL_PLAN_PREFIX.rstrip("/")

        try:
            resolved = Path(path).resolve()
            if self._plan_dir is not None:
                return resolved.is_relative_to(self._plan_dir)
            # Fallback: check if any path component sequence matches .nova/plans
            normalized = resolved.as_posix()
            return ".nova/plans" in normalized
        except (ValueError, OSError):
            return False

"""Loop-guard middleware: break stuck, repeating tool calls.

Models sometimes get stuck firing the *exact same* tool call over and over —
e.g. ``grep("morphological|knowledge|...")`` returning "no matches" 18 times in
a row — without ever updating their plan. Each repeat makes no progress, burns
tokens and wall-clock time, and the agent never escapes on its own.

This middleware watches consecutive tool calls. When the same tool is invoked
with the same arguments and returns the same result ``threshold`` times back to
back, the next identical call is short-circuited with an error message that
tells the model to stop repeating and change approach.

The detection is deliberately conservative to avoid false positives:

- Only *consecutive* identical calls count. Any different tool call in between
  resets the streak — so the world may have changed and the call runs again.
- The *result* must also be identical. Re-running a test command that flips
  from failing to passing is NOT a loop; a search that always says "no matches"
  is. This keeps legitimate retries (transient errors, changed state) working.
"""

import hashlib
import json
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from langchain.agents.middleware.types import AgentMiddleware
from langchain.tools.tool_node import ToolCallRequest
from langchain_core.messages import ToolMessage
from langgraph.types import Command

if TYPE_CHECKING:
    from langchain.tools import BaseTool


def _canonical_args(tool_call: dict) -> str:
    """Stable string key for a tool call's name + arguments."""
    name = tool_call.get("name", "")
    args = tool_call.get("args", {})
    try:
        args_str = json.dumps(args, sort_keys=True, default=str)
    except (TypeError, ValueError):
        args_str = repr(args)
    return f"{name}\x00{args_str}"


def _result_text(result: ToolMessage | Command) -> str | None:
    """Extract comparable text from a tool result, or None if not guardable."""
    if not isinstance(result, ToolMessage):
        return None  # Command (state update) — leave it alone
    content = result.content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
            elif isinstance(block, str):
                parts.append(block)
        return "\n".join(parts)
    return str(content)


class LoopGuardMiddleware(AgentMiddleware):
    """Short-circuit a tool call that has stalled in an identical-repeat loop.

    Args:
        threshold: Number of consecutive identical (tool, args, result) calls to
            allow before blocking the next one. Default 3 — i.e. the 4th repeat
            is the first to be blocked.
    """

    def __init__(self, threshold: int = 3) -> None:
        """Initialise the guard with the consecutive-repeat ``threshold``."""
        super().__init__()
        self.threshold = threshold
        self.tools: list[BaseTool] = []  # no additional tools
        self._last_sig: str | None = None
        self._last_result_hash: str | None = None
        self._streak: int = 0

    def _is_blocked(self, sig: str) -> bool:
        """True if this signature has already repeated to the limit."""
        return sig == self._last_sig and self._streak >= self.threshold

    def _blocked_message(self, request: ToolCallRequest) -> ToolMessage:
        tool_call = request.tool_call
        name = tool_call.get("name", "this tool")
        return ToolMessage(
            content=(
                f"**LOOP STOPPED**: `{name}` was already called {self._streak} times "
                f"in a row with identical arguments and got the identical result "
                f"each time. Repeating it will not produce anything new.\n\n"
                f"Do NOT call it again with the same arguments. Instead:\n"
                f"- Change the approach — broaden/narrow the query, try a different "
                f"tool, or look in a different location.\n"
                f"- If you have enough information, stop searching and answer.\n"
                f"- If the thing genuinely does not exist, say so and move on."
            ),
            tool_call_id=tool_call.get("id", ""),
            status="error",
        )

    def _record(self, sig: str, result: ToolMessage | Command) -> None:
        """Update the consecutive-repeat streak from an executed result."""
        text = _result_text(result)
        if text is None:
            # Non-guardable result (Command) — reset so it can't anchor a streak.
            self._last_sig = None
            self._last_result_hash = None
            self._streak = 0
            return
        result_hash = hashlib.sha256(text.encode()).hexdigest()[:16]
        if sig == self._last_sig and result_hash == self._last_result_hash:
            self._streak += 1
        else:
            self._last_sig = sig
            self._last_result_hash = result_hash
            self._streak = 1

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        """Short-circuit the call if it has stalled in an identical-repeat loop."""
        sig = _canonical_args(request.tool_call)
        if self._is_blocked(sig):
            return self._blocked_message(request)
        result = handler(request)
        self._record(sig, result)
        return result

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        """(async) Short-circuit the call if it has stalled in a repeat loop."""
        sig = _canonical_args(request.tool_call)
        if self._is_blocked(sig):
            return self._blocked_message(request)
        result = await handler(request)
        self._record(sig, result)
        return result

"""Loop-guard middleware: break stuck, repeating tool calls.

Models sometimes get stuck firing the *exact same* tool call over and over —
e.g. ``grep("morphological|knowledge|...")`` returning "no matches" 18 times in
a row — without ever updating their plan. Each repeat makes no progress, burns
tokens and wall-clock time, and the agent never escapes on its own.

This middleware watches a sliding window of recent tool calls. When the same
tool is invoked with the same arguments and returns the same result
``threshold`` times within that window, the next identical call is
short-circuited with an error message that tells the model to stop repeating
and change approach.

The window — rather than only the immediately-previous call — is what lets the
guard catch the common loop shape ``grep → think → grep → think → grep …``,
where a harmless intervening call would otherwise reset a strict consecutive
streak forever and the loop never gets broken.

The detection stays conservative to avoid false positives:

- Intervening *different* calls are skipped, not counted — but they do not reset
  the count for the repeating signature. Heavy interleaving still ages old
  repeats out of the bounded window, so a non-tight loop is left alone.
- The *result* must also be identical. Re-running a test command that flips
  from failing to passing is NOT a loop; a search that always says "no matches"
  is. A changed result for the same args stops the count — progress, not a loop.
"""

import hashlib
import json
from collections import deque
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
        threshold: Number of identical (tool, args, result) calls — within the
            sliding window, intervening other calls ignored — to allow before
            blocking the next one. Default 3 — i.e. the 4th repeat is blocked.
        window: How many recent guardable results to retain when looking for
            repeats. Must comfortably exceed ``threshold`` so that a few
            interleaved calls between repeats don't age the streak out. Default
            12 (holds a ``grep``/``think`` alternation of 6 repeats).
    """

    def __init__(self, threshold: int = 3, window: int = 12) -> None:
        """Initialise the guard with the repeat ``threshold`` and ``window``."""
        super().__init__()
        self.threshold = threshold
        self.tools: list[BaseTool] = []  # no additional tools
        self._history: deque[tuple[str, str]] = deque(maxlen=window)

    def _repeat_count(self, sig: str) -> int:
        """Count identical (sig, result) repeats for ``sig`` within the window.

        Walks newest→oldest. Intervening calls with a *different* signature are
        skipped (so an interleaved think/read between identical greps does not
        reset the count). Counting stops as soon as ``sig`` is found to have
        produced a *different* result — a changed result means progress.
        """
        anchor_hash: str | None = None
        count = 0
        for past_sig, past_hash in reversed(self._history):
            if past_sig != sig:
                continue
            if anchor_hash is None:
                anchor_hash = past_hash
            if past_hash != anchor_hash:
                break
            count += 1
        return count

    def _blocked_message(self, request: ToolCallRequest, count: int) -> ToolMessage:
        tool_call = request.tool_call
        name = tool_call.get("name", "this tool")
        return ToolMessage(
            content=(
                f"**LOOP STOPPED**: `{name}` was already called {count} times "
                f"with identical arguments and got the identical result "
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
        """Append an executed result to the window, if it is guardable."""
        text = _result_text(result)
        if text is None:
            # Non-guardable result (Command) — don't record; it can't anchor a
            # loop and shouldn't occupy a window slot.
            return
        result_hash = hashlib.sha256(text.encode()).hexdigest()[:16]
        self._history.append((sig, result_hash))

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        """Short-circuit the call if it has stalled in an identical-repeat loop."""
        sig = _canonical_args(request.tool_call)
        count = self._repeat_count(sig)
        if count >= self.threshold:
            return self._blocked_message(request, count)
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
        count = self._repeat_count(sig)
        if count >= self.threshold:
            return self._blocked_message(request, count)
        result = await handler(request)
        self._record(sig, result)
        return result

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
from langgraph.graph import END
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

    Blocking the call is not enough on its own: a truly stuck model will keep
    re-emitting the *same* call and, if it always gets back the *same* block
    message, nothing in its context changes — so it loops on the guard itself
    (the "LOOP STOPPED … LOOP STOPPED …" wall). Two mechanisms break that:

    - **Escalation.** Each successive block of the same signature returns a
      *different*, stronger message. A changing tool result is the single most
      reliable way to perturb a degenerate loop, so varying the text gives the
      model a real chance to choose a different action.
    - **Hard stop.** If the model ignores ``escalate_after`` escalations anyway,
      the guard ends the turn (``Command(goto=END)``) with a final message
      rather than letting the wall scroll forever.

    Args:
        threshold: Number of identical (tool, args, result) calls — within the
            sliding window, intervening other calls ignored — to allow before
            blocking the next one. Default 3 — i.e. the 4th repeat is blocked.
        window: How many recent guardable results to retain when looking for
            repeats. Must comfortably exceed ``threshold`` so that a few
            interleaved calls between repeats don't age the streak out. Default
            12 (holds a ``grep``/``think`` alternation of 6 repeats).
        escalate_after: How many escalating blocks of the *same* signature to
            emit before hard-stopping the turn. Default 3 — i.e. the model gets
            three increasingly forceful warnings, then the 4th block ends the
            turn. A real call executing in between resets this.
    """

    def __init__(
        self, threshold: int = 3, window: int = 12, escalate_after: int = 3
    ) -> None:
        """Initialise the guard with the repeat ``threshold`` and ``window``."""
        super().__init__()
        self.threshold = threshold
        self.escalate_after = escalate_after
        self.tools: list[BaseTool] = []  # no additional tools
        self._history: deque[tuple[str, str]] = deque(maxlen=window)
        # Consecutive-block escalation state for the currently-stuck signature.
        self._blocked_sig: str | None = None
        self._block_streak: int = 0

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

    def _on_blocked(
        self, sig: str, request: ToolCallRequest, count: int
    ) -> ToolMessage | Command:
        """Handle a blocked call: escalate the message, then hard-stop the turn.

        Tracks how many times *this same signature* has been blocked in a row.
        Each block returns a stronger, *different* message (so the model's
        context actually changes); once ``escalate_after`` is exceeded the turn
        is ended outright.
        """
        if sig == self._blocked_sig:
            self._block_streak += 1
        else:
            self._blocked_sig = sig
            self._block_streak = 1

        if self._block_streak > self.escalate_after:
            return self._terminate(request, count)
        return self._blocked_message(request, count, self._block_streak)

    def _blocked_message(
        self, request: ToolCallRequest, count: int, streak: int
    ) -> ToolMessage:
        tool_call = request.tool_call
        name = tool_call.get("name", "this tool")
        if streak == 1:
            guidance = (
                "Do NOT call it again with the same arguments. Instead:\n"
                "- Change the approach — broaden/narrow the query, try a different "
                "tool, or look in a different location.\n"
                "- If you have enough information, stop searching and answer.\n"
                "- If the thing genuinely does not exist, say so and move on."
            )
        else:
            guidance = (
                f"You have repeated this identical call {streak} times AFTER being "
                f"told to stop — this is a hard loop. On your VERY NEXT step you "
                f"must do something different:\n"
                f"- call a DIFFERENT tool, or use DIFFERENT arguments (a different "
                f"pattern, path, or scope), OR\n"
                f"- stop calling tools and reply to the user with what you already "
                f"know — including that `{name}` found nothing.\n"
                f"Calling `{name}` with these same arguments again is forbidden and "
                f"will keep failing."
            )
        return ToolMessage(
            content=(
                f"**LOOP STOPPED** (repeat #{count + streak}): `{name}` was already "
                f"called {count} times with identical arguments and got the identical "
                f"result each time. Repeating it will not produce anything new.\n\n"
                f"{guidance}"
            ),
            tool_call_id=tool_call.get("id", ""),
            status="error",
        )

    def _terminate(self, request: ToolCallRequest, count: int) -> Command:
        """End the agent turn after the model ignored every escalation."""
        tool_call = request.tool_call
        name = tool_call.get("name", "this tool")
        msg = ToolMessage(
            content=(
                f"**LOOP HALTED**: `{name}` was called with identical arguments "
                f"{count} times and the loop continued through "
                f"{self.escalate_after} warnings. Ending this turn to stop the "
                f"runaway loop. Review the request and try a genuinely different "
                f"approach."
            ),
            tool_call_id=tool_call.get("id", ""),
            status="error",
        )
        # Reset so a later, legitimately-repeating signature starts fresh.
        self._reset_block_state()
        return Command(goto=END, update={"messages": [msg]})

    def _reset_block_state(self) -> None:
        """Clear consecutive-block escalation tracking (progress was made)."""
        self._blocked_sig = None
        self._block_streak = 0

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
            return self._on_blocked(sig, request, count)
        # A real call is running — the model made a different move; clear any
        # in-progress block escalation so it doesn't bleed into a future loop.
        self._reset_block_state()
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
            return self._on_blocked(sig, request, count)
        # A real call is running — clear any in-progress block escalation.
        self._reset_block_state()
        result = await handler(request)
        self._record(sig, result)
        return result


class TextRepetitionGuard:
    """Detect degenerate self-repetition in a model's streamed prose.

    The other failure shape: the model stops making tool calls and just
    re-emits the same paragraphs verbatim, forever ("Let me also check the X
    element. … Good." on a cycle). ``LoopGuardMiddleware`` never sees it — no
    tool ever runs — and the stream has no natural end, so the turn only stops
    when something dies.

    Detection is on *repeated blocks*, not repeated lines: a sliding window of
    ``window`` consecutive substantial lines is hashed, and the same window
    recurring ``threshold`` times means the model is cycling rather than
    writing. Requiring a multi-line block keeps legitimately repetitive output
    (boilerplate code, table rows, a wrapped list) from tripping it.

    Feed it every streamed text/reasoning delta; it buffers partial lines.
    """

    def __init__(
        self, *, threshold: int = 4, window: int = 3, min_line_chars: int = 40
    ) -> None:
        self.threshold = threshold
        self.window = window
        self.min_line_chars = min_line_chars
        self.tripped = False
        self._partial = ""
        self._recent: deque[int] = deque(maxlen=window)
        self._seen: dict[tuple[int, ...], int] = {}

    def feed(self, text: str) -> bool:
        """Add streamed text. Returns True once the output is a repetition loop."""
        if self.tripped or not text:
            return self.tripped
        self._partial += text
        *lines, self._partial = self._partial.split("\n")
        for line in lines:
            normalized = " ".join(line.split())
            if len(normalized) < self.min_line_chars:
                continue  # short lines ("Good.", "```") are noise, not a cycle
            self._recent.append(hash(normalized))
            if len(self._recent) < self.window:
                continue
            key = tuple(self._recent)
            count = self._seen.get(key, 0) + 1
            if count >= self.threshold:
                self.tripped = True
                return True
            # ponytail: plain dict, cleared wholesale. A response long enough to
            # blow this cap is itself the pathology we're watching for.
            if len(self._seen) > 50_000:
                self._seen.clear()
            self._seen[key] = count
        return False

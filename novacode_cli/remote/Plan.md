# Plan: Stream Agent Responses to Remote Bridges + Discord Reactions

## 1. Problem Statement

The remote bridges (Discord and Telegram) currently send **nothing to the chat** until the agent's entire turn completes. Only then do they send:

1. A condensed tool digest (`🔧 5 tool calls · read_file×2, grep, shell, write_file`)
2. The final answer text

This means users on Discord/Telegram stare at a "typing..." indicator for potentially minutes with **zero feedback** about what the agent is actually doing or saying.

### What We Want

1. **Stream agent responses in real-time** — text tokens should appear progressively in the Discord/Telegram chat, just like they do in the local TUI
2. **Keep tool calls condensed** — no individual `shell()` / `grep()` / `read_file()` messages flooding the chat; the existing condensed digest pattern is correct and should stay
3. **Allow the agent to react to user input in Discord** — e.g., 🤔 while thinking, ✅ when done, ❌ on error

---

## 2. Current Architecture (as-is)

### 2.1 Event Types (`novacode_cli/ui_events.py`)

| Event | Content | Used in TUI | Used in Bridge |
|-------|---------|-------------|----------------|
| `TextDelta` | Incremental token chunks | Live streaming buffer | **No** — ignored |
| `TextDiscard` | Drop the live preview | Yes | **No** |
| `AssistantMessage` | Committed markdown chunk | Finalization | **Indirectly** — `_extract_response()` gets it from state **after** the turn |
| `ToolCall` | Tool name + args | Renders panel/condensed | **Accumulated** into `_tool_names` list |
| `ToolResult` | Tool output preview | Renders result | **No** |
| `ReasoningDelta` | Thinking trace | Dimmed live stream | **No** |

### 2.2 Two Processing Pathways

#### Pathway A: Legacy Console (`remote/processor.py`)
```
remote_message_processor():
  1. dequeue RemoteMessage
  2. acquire lock, set auto_approve=True
  3. install _record_tool() callback → session_state._remote_tool_notify
  4. call execute_fn(text, ...) → runs entire agent turn, renders to rich console
     (ToolCall → _record_tool() accumulates names)
  5. _extract_response() → gets final answer from state
  6. format_tool_digest(_tool_names) → reply_fn(digest)
  7. reply_fn(response_text)
```
Key: `TextDelta` is explicitly `pass`-ed (line 181 of `execution.py`). Nothing is streamed.

#### Pathway B: TUI (`tui/app.py`)
```
_remote_consumer():
  1. dequeue RemoteMessage
  2. call _stream_prompt(text) → _do_stream(text) → run_agent_stream()
  3. for each event: _render(e)
     - TextDelta → _live_buf (local TUI transcript)
     - ToolCall → _remote_record(name) (accumulates for digest)
  4. After stream: _flush_remote_activity() → format_tool_digest() → reply_fn(digest)
  5. _extract_response() → reply_fn(response)
```
Key: `TextDelta` IS rendered locally, but NOT forwarded to `reply_fn`. The bridge only gets the post-hoc digest + final text.

### 2.3 Bridge reply_fn Closures

**Discord** (`discord_bridge.py` lines 180-189):
```python
async def reply_fn(response_text: str) -> None:
    chunks = chunk_message(response_text, RemotePlatform.DISCORD)
    for chunk in chunks:
        await message.channel.send(chunk)
```

**Telegram** (`telegram_bridge.py` lines 162-167):
```python
async def reply_fn(response_text: str, _chat_id: int = chat_id) -> None:
    await self._send_message(_chat_id, response_text)
```
Both send a whole string at once — no streaming.

---

## 3. Implementation Plan

### 3.1 Goal 1: Stream Agent Responses to Bridges

#### Approach: Periodic Text Flush from TextDelta Events

Instead of sending every individual `TextDelta` (which would be ~1 HTTP call per token/word), we batch text and flush on a timer or on specific events.

**Where to hook in:**

#### A) TUI Pathway (`tui/app.py` ~line 5514)

The `_render()` method already processes `TextDelta` events:
```python
elif isinstance(e, ev.TextDelta):
    self._live_buf += e.text
    self._schedule_stream_flush()
```

We add a flush to the bridge here:
```python
elif isinstance(e, ev.TextDelta):
    self._live_buf += e.text
    self._schedule_stream_flush()
    # NEW: send to remote bridge if active
    self._flush_remote_stream(e.text)
```

Where `_flush_remote_stream` accumulates text and flushes periodically (every ~500ms or every N characters). It calls `msg.reply_fn(chunk)` on the remote message.

#### B) Legacy Console Pathway (`processor.py` + `execution.py`)

The legacy processor calls `execute_fn` which is `execute_task()` from `execution.py`. That function currently ignores `TextDelta`. We need to:

1. Pass a `stream_callback` through the chain that receives text deltas
2. In the processor, accumulate and periodically send these to `reply_fn`

**Simpler approach**: Modify `execute_task()` (or add a new parameter) to call a callback on `TextDelta` events. The processor passes a callback that:
- Accumulates text into a buffer
- Flushes the buffer to `reply_fn` on a timer (e.g., every 500ms) or on `AssistantMessage`

#### Implementation Details

```python
# Interface
class TextStreamCallback(Protocol):
    async def __call__(self, text: str, *, is_final: bool = False) -> None: ...

# In processor.py, add to execute_fn call:
async def _stream_chunk(text: str, *, is_final: bool = False) -> None:
    _text_buffer += text
    now = time.monotonic()
    if is_final or now - _last_flush > 0.5 or len(_text_buffer) > 500:
        await remote_msg.reply_fn(_text_buffer)
        _text_buffer = ""
        _last_flush = now
```

##### Required code changes:

1. **`novacode_cli/ui_events.py`** — No changes needed; event types are sufficient.

2. **`novacode_cli/ui/execution.py`** — Add optional `text_stream_callback` parameter to `execute_task()`. Call it on each `TextDelta` event and on `AssistantMessage` (as final flush).

3. **`novacode_cli/remote/processor.py`** — In `remote_message_processor()`:
   - Create a text streaming buffer with timer-based flushing
   - Pass a `text_stream_callback` to `execute_fn`
   - After the stream ends, flush remaining text
   - Keep the existing condensed tool digest logic unchanged
   - Send tool digest → then remaining response text (avoid duplication)

4. **`novacode_cli/tui/app.py`** — In `_render()`:
   - On `TextDelta` event when `self._remote_msg` is active, call a new `_remote_stream_text(e.text)` method
   - That method accumulates text and flushes periodically
   - On `AssistantMessage`, flush any remaining buffer
   - Keep `_flush_remote_activity()` (tool digest) as-is after the turn

5. **`novacode_cli/remote/bridge.py`** — Add helper `stream_text_to_remote()` or similar utility if needed.

##### Interaction with reply_fn:

- `reply_fn` currently sends `chunk_message(text, platform)` — it already handles splitting long text.
- Streaming means multiple `reply_fn` calls per turn instead of one.
- For Discord, each chunk becomes a separate `channel.send()` call.
- For Telegram, each chunk becomes a separate `sendMessage` call.

**Important**: The existing final response text (`_extract_response`) should NOT be sent if we already streamed it — we need to ensure no duplication. Options:
- Track a "streamed" flag; if text was streamed, only send the tool digest (not the final answer)
- Or: only stream the *first* assistant message; `_extract_response` handles multi-message turns

**Recommended**: Stream from `TextDelta` events into a "live reply" message. The final `_extract_response` text should still be sent as a "finalized" version (better formatted, since it's the committed markdown from the agent state, not the incremental stream).

### 3.2 Goal 2: Keep Tool Calls Condensed

✅ **Already implemented.** No changes needed.

The existing architecture already:
- Accumulates tool names in `_tool_names` / `self._remote_activity` during the turn
- Calls `format_tool_digest()` once after the turn
- Sends one message like `🔧 5 tool calls · read_file×2, grep, shell, write_file`

The condensed digest should continue to be sent **after** the streamed response text. The order would become:

Before: `[thinking...] → [tool digest] → [final answer]`
After: `[thinking...] → [streaming text starts appearing] → [streaming continues] → [tool digest] → [final commit]`

### 3.3 Goal 3: Discord Reactions on User Messages

#### Feasibility

**Yes, this is feasible.** Discord.py's `Message.add_reaction(emoji)` method works on any message where the bot has permission.

The emoji can be:
- A Unicode string: `"🤔"`, `"✅"`, `"❌"`, `"👍"`
- A custom emoji: `discord.PartialEmoji(name="nova")` (requires the bot to have access to the emoji)

#### Implementation

1. **Extend `RemoteMessage`** (in `bridge.py`):
   ```python
   @dataclass
   class RemoteMessage:
       ...
       react_fn: Callable[[str], Awaitable[None]] | None = None
   ```

2. **In `DiscordBridge._on_message()`** (`discord_bridge.py`):
   Add a `react_fn` closure that captures the `message` object:
   ```python
   async def react_fn(emoji: str) -> None:
       """Add a reaction emoji to the user's message."""
       try:
           await message.add_reaction(emoji)
       except discord.HTTPException as e:
           logger.error(f"Discord reaction error: {e}")
   ```

3. **In `remote_message_processor()`** (`processor.py`) or TUI `_remote_consumer()`:
   Call `react_fn` at lifecycle points:
   - When dequeued: `react_fn("🤔")` — "thinking"
   - When stream starts: `react_fn("💬")` — "responding"
   - When done: `react_fn("✅")` — "completed"
   - On error: `react_fn("❌")` — "error"

4. **Telegram**: Telegram Bot API does **not** support message reactions. Use `sendChatAction("typing")` which is already implemented.

#### Emotion mapping (Discord only)

| Agent State | Emoji | When |
|-------------|-------|------|
| Thinking | 🤔 | Message dequeued, before agent turn |
| Processing tools | 🔧 | Tools running (keep condensed) |
| Responding | 💬 | First text delta received |
| Completed | ✅ | Turn finished normally |
| Error | ❌ | Exception in processing |

---

## 4. File-by-File Changes Summary

| File | Change | Complexity |
|------|--------|------------|
| `novacode_cli/remote/bridge.py` | Add `react_fn` field to `RemoteMessage`; add `stream_text_to_remote()` helper | Small |
| `novacode_cli/remote/discord_bridge.py` | Add `react_fn` closure in `_on_message()` | Small |
| `novacode_cli/remote/telegram_bridge.py` | No changes needed (no reactions in Telegram bot API) | None |
| `novacode_cli/remote/processor.py` | Add text streaming callback → `execute_fn`; add reaction lifecycle calls | Medium |
| `novacode_cli/ui/execution.py` | Add optional `text_stream_callback` param to `execute_task()` | Medium |
| `novacode_cli/ui/execution.py` | Call callback on `TextDelta` and `AssistantMessage` events | Small |
| `novacode_cli/tui/app.py` | Add `_remote_stream_text()` method; flush on timer in `_render()` | Medium |
| `novacode_cli/tui/app.py` | Call `react_fn` at lifecycle points when `_remote_msg` is active | Small |

Total: **~7 files modified**, ~200-300 lines of new code.

---

## 5. Edge Cases & Concerns

1. **Duplicate text**: Streamed text (from `TextDelta`) must not be re-sent as final `_extract_response`. Solution: maintain a `_text_was_streamed` flag; if True, only send the tool digest after the turn, not the full response. The streamed text **is** the response.

2. **Rapid flushing**: TextDelta fires per-token. We must **not** make an HTTP call per token. Use timer-based coalescing (every 500ms) AND character threshold (every 500 chars).

3. **Discord rate limits**: Discord allows 5 messages per 5 seconds per channel. Streaming text could trigger rate limits. Solutions:
   - Coalesce aggressively (min 1s between messages)
   - Use edit_message instead of send_message for live updates (edit existing message)
   
   **Recommended: Edit existing message approach** — Send one placeholder message, then edit it with accumulated text. This avoids rate limits entirely.

4. **Telegram rate limits**: Telegram has 20 messages/minute per chat with text, 30/minute without. Also use message editing for live streaming.

5. **`AssistantMessage` vs final response**: The final `_extract_response` may contain text from multiple AI messages (if tools triggered follow-up reasoning). Streaming only captures the first message. Options:
   - Stream the first message, send a final "summarized" version
   - Only stream, skip `_extract_response` entirely for the answer
   - Stream all text, but always send final committed markdown

6. **Edit approach vs send approach**:
   - **Send approach**: Send new chunks as separate messages. Simpler, but risks rate limits and floods the channel.
   - **Edit approach**: Send one message, edit it progressively (Discord: `message.edit()`, Telegram: `editMessageText`). More elegant, looks like GPT streaming. Requires tracking the message ID.
   - **Recommendation**: Use **edit approach** as primary, fall back to **send approach** if edit fails (e.g., the message was deleted).

---

## 6. Proposed Edit Approach (Preferred)

### Discord
```python
# In reply_fn, send placeholder, return edit capabilities
sent_msg = await message.channel.send("🤔 *Thinking...*")
reply_fn = sent_msg.edit  # or a wrapper
```

Then in the streaming callback:
```python
await sent_msg.edit(content=accumulated_text)
```

### Telegram
```python
sent = await self._api_call("sendMessage", {
    "chat_id": chat_id,
    "text": "🤔 *Thinking...*",
    "parse_mode": "Markdown",
})
message_id = sent["result"]["message_id"]
```

Then:
```python
await self._api_call("editMessageText", {
    "chat_id": chat_id,
    "message_id": message_id,
    "text": accumulated_text,
    "parse_mode": "Markdown",
})
```

This means `reply_fn` would change from "send a new message" to "edit the existing message". The condensed tool digest would then be sent as a **follow-up message** (not an edit), and the final message would be the final edited state.

### Revised message flow (edit approach)

```
1. [🤔 Thinking...]          ← sent as placeholder
2. [streaming text...]       ← progressively edits placeholder
3. [streaming text (done)]   ← final edit + tool digest sent as new message:
                               "🔧 5 tool calls · read_file×2, grep, shell"
```

This is clean, rate-limit-friendly, and looks professional.

---

## 7. Implementation Order

1. **Extend `RemoteMessage`**: Add `react_fn` field + optional `edit_fn` field (for edit-based streaming)
2. **Discord**: Add `react_fn` and `edit_fn` closures; initial message sends placeholder with `🤔`
3. **Telegram**: Add `edit_fn` closure; initial message sends placeholder with `🤔`
4. **`bridge.py`**: Add `stream_text_to_remote()` utility with timer coalescing
5. **`processor.py`**: Integrate streaming callback into `remote_message_processor()`
6. **`execution.py`**: Thread `text_stream_callback` through `execute_task()`
7. **`tui/app.py`**: Add `_remote_stream_text()` for TUI remote consumer
8. **Reactions**: Call `react_fn` at lifecycle points in both pathways
9. **Testing**: Manual testing with both Discord and Telegram bridges

---

## 8. Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Discord rate limit (5 msg/5s) | Use edit approach — only 1-2 messages per turn |
| Telegram rate limit (20 msg/min) | Use edit approach — only 1-2 messages per turn |
| Duplicate text (streamed + final) | Track `_text_was_streamed` flag; skip final answer if streamed |
| Message deleted before edit | Catch `HTTPException` and fall back to new messages |
| Unicode emoji rendering issues | Use standard emoji (🤔✅❌💬) — guaranteed on all platforms |
| Discord bot permissions (no reaction) | Catch `Forbidden`; `react_fn` is best-effort |
| TUI/console race conditions | Streaming runs inside the existing `_remote_message_lock` — already safe |
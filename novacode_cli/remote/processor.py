"""Remote message processor — reads from the shared queue and runs the agent.

This module provides the long-running background task that dequeues
``RemoteMessage`` objects produced by Discord/Telegram bridges and
feeds them through ``execute_task()`` just like a local prompt.

The processor serialises access with an ``asyncio.Lock`` so remote and
local messages do not interleave mid-stream.
"""

import asyncio
import logging
from typing import Any, Callable, Awaitable

logger = logging.getLogger(__name__)


async def remote_message_processor(
    queue: asyncio.Queue,
    agent: Any,
    assistant_id: str,
    session_state: Any,
    console: Any,
    token_tracker: Any,
    backend: Any,
    image_tracker: Any,
    seen_message_ids: Any,
    execute_fn: Any | None = None,
) -> None:
    """Process messages from the remote message queue."""
    from novacode_cli.config.config import COLORS

    lock = getattr(session_state, "_remote_message_lock", None)
    if lock is None:
        lock = asyncio.Lock()

    logger.info("Remote message processor started, queue=%s", id(queue))
    # Debug: write to file so we can confirm queue ID matches bridge
    import os as _os
    _dlog = _os.path.expanduser("~/.nova/remote_debug.log")
    _os.makedirs(_os.path.dirname(_dlog), exist_ok=True)
    with open(_dlog, "a") as _df:
        _df.write("PROCESSOR STARTED queue=" + str(id(queue)) + "\n")

    console.print("\n  [dim]\U0001f517 Remote message processor ready[/]\n")

    while True:
        try:
            # Wait for a remote message (blocks until one arrives)
            remote_msg = await queue.get()
            with open(_dlog, "a") as _df:
                _df.write("DEQUEUED from queue " + str(id(queue)) + ": " + remote_msg.text[:80] + "\n")

            logger.info(
                "Remote message from %s on %s",
                remote_msg.user_name, remote_msg.platform.value
            )

            # Notify the local CLI user
            console.print()
            console.print(
                f"  [{COLORS.get('primary', 'cyan')}]\U0001f4e1 Remote ({remote_msg.platform.value})[/"
                f" [{COLORS.get('user', 'green')}]{remote_msg.user_name}[/]: "
                f"{remote_msg.text[:120]}"
            )
            console.print()

            # Fire remote.message hook
            try:
                from novacode_cli.hooks import dispatch_hook_fire_and_forget, HookEvent
                dispatch_hook_fire_and_forget(HookEvent.REMOTE_MESSAGE, {
                    "platform": remote_msg.platform.value,
                    "user": remote_msg.user_name,
                    "text": remote_msg.text[:500],
                    "session_id": getattr(session_state, "session_id", ""),
                })
            except Exception:
                pass

            # Serialize with the lock so remote and local messages don't conflict
            async with lock:
                try:
                    # Show "typing" indicator on the remote platform while thinking
                    # Discord: channel.typing is an async context manager method
                    #   — calling it returns an object with __aenter__/__aexit__.
                    # Telegram: typing_fn is a regular async function
                    #   — calling it returns a coroutine that sends a chatAction.
                    #
                    # We probe which type it is by calling it ONCE, then:
                    #   - If the result has __aenter__, it's a context manager (Discord)
                    #   - Otherwise, close the probe coroutine and use the loop (Telegram)
                    _typing_cm = None
                    typing_task: asyncio.Task | None = None
                    typing_fn = getattr(remote_msg, "typing_fn", None)
                    if typing_fn is not None:
                        # Probe once to decide the type
                        _probe = typing_fn()
                        if hasattr(_probe, "__aenter__"):
                            # Discord-style async context manager
                            _typing_cm = _probe
                            try:
                                await _typing_cm.__aenter__()
                            except Exception:
                                _typing_cm = None
                        else:
                            # Telegram-style coroutine — close the probe to
                            # suppress RuntimeWarning, then loop the real calls
                            _probe.close()
                            async def _typing_loop():
                                try:
                                    while True:
                                        await typing_fn()
                                        await asyncio.sleep(8)
                                except asyncio.CancelledError:
                                    pass
                            typing_task = asyncio.create_task(_typing_loop())

                    # Notify local CLI that agent is thinking
                    console.print(
                        f"  [{COLORS.get('dim', 'dim')}]\U0001f914 Thinking...[/]"
                    )

                    # Auto-approve tool actions during remote processing so
                    # the agent doesn't block waiting for local CLI input.
                    # /remote start already set auto_approve=True persistently,
                    # but we still save/restore here as a safety net in case
                    # someone toggled it off mid-session.
                    _prev_auto_approve = getattr(session_state, "auto_approve", False)
                    session_state.auto_approve = True

                    # Set up tool notification callback so remote user sees
                    # tool usage in real-time as it happens
                    async def _notify_remote(name, info, *, is_result=False):
                        prefix = "⭐" if not is_result else "✅"
                        # Strip Rich markup for plain-text platforms
                        if "[" in info:
                            import re
                            info = re.sub(r"\[/?[^\]]+\]", "", info)
                        msg_text = prefix + " " + name + ": " + info[:200]
                        try:
                            await remote_msg.reply_fn(msg_text)
                        except Exception:
                            pass

                    def _notify_remote_sync(name, info, *, is_result=False):
                        # Called from sync context in execute_task();
                        # schedule the async notification on the running loop
                        try:
                            loop = asyncio.get_running_loop()
                            loop.create_task(_notify_remote(name, info, is_result=is_result))
                        except RuntimeError:
                            pass  # no running event loop

                    session_state._remote_tool_notify = _notify_remote_sync

                    try:
                        # Record the message count before execution
                        config = {
                            "configurable": {"thread_id": session_state.thread_id}
                        }
                        pre_state = await agent.aget_state(config)
                        pre_msg_count = len(
                            pre_state.values.get("messages", [])
                        ) if pre_state else 0

                        # Execute the task
                        if execute_fn is not None:
                            await execute_fn(
                                remote_msg.text,
                                agent,
                                assistant_id,
                                session_state,
                                token_tracker,
                                backend=backend,
                                is_subagent=False,
                                image_tracker=image_tracker,
                                seen_message_ids=seen_message_ids,
                                skip_file_mentions=True,
                            )

                        # Get the agent's response from the state
                        post_state = await agent.aget_state(config)
                        response_text = _extract_response(post_state, pre_msg_count)

                        if response_text:
                            await remote_msg.reply_fn(response_text)
                        else:
                            await remote_msg.reply_fn(
                                "\u2705 Task completed (no text response)."
                            )

                    finally:
                        # Restore settings
                        session_state.auto_approve = _prev_auto_approve
                        session_state._remote_tool_notify = None

                        # Stop the typing indicator
                        if typing_task is not None:
                            typing_task.cancel()
                            try:
                                await typing_task
                            except asyncio.CancelledError:
                                pass
                        if _typing_cm is not None:
                            try:
                                await _typing_cm.__aexit__(None, None, None)
                            except Exception:
                                pass

                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.error(f"Error processing remote message: {e}")
                    try:
                        await remote_msg.reply_fn(
                            f"\u274c Error: {str(e)[:200]}"
                        )
                    except Exception:
                        pass
                finally:
                    queue.task_done()

        except asyncio.CancelledError:
            logger.info("Remote message processor cancelled")
            break
        except Exception as e:
            logger.error(f"Remote message processor error: {e}")
            await asyncio.sleep(1)


def _extract_response(post_state: Any, pre_msg_count: int) -> str:
    """Extract the agent's text response from the state after execution."""
    if post_state is None:
        return ""

    from langchain_core.messages import AIMessage

    messages = post_state.values.get("messages", [])
    new_messages = messages[pre_msg_count:]

    parts: list[str] = []
    for msg in new_messages:
        if isinstance(msg, AIMessage):
            content = msg.content
            if isinstance(content, str) and content.strip():
                parts.append(content.strip())
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        text = part.get("text", "").strip()
                        if text:
                            parts.append(text)
                    elif isinstance(part, str) and part.strip():
                        parts.append(part.strip())

    return "\n\n".join(parts)
"""Telegram bridge — forwards messages between Telegram and the Nova-Code agent.

Uses the Telegram Bot HTTP API directly via ``aiohttp`` (already a
dependency), so no additional packages are needed.  Long-polling via
``getUpdates`` means we don't need webhooks or incoming ports.

Message Flow
------------
1. Background task calls ``getUpdates`` in a loop (long-polling with
   30-second timeout).
2. Incoming messages from the allowlisted chat are wrapped as
   ``RemoteMessage`` and put on the shared queue.
3. The CLI's main loop runs ``execute_task()`` with the message text.
4. The ``reply_fn`` uses ``sendMessage`` to return the response.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import aiohttp

from novacode_cli.remote.bridge import (
    BridgeConfig,
    RemoteMessage,
    RemotePlatform,
    chunk_message,
)

logger = logging.getLogger(__name__)

_TELEGRAM_API = "https://api.telegram.org"


_LONG_POLL_SERVER_TIMEOUT = 30  # seconds Telegram holds the connection open
_LONG_POLL_CLIENT_TIMEOUT = aiohttp.ClientTimeout(
    total=_LONG_POLL_SERVER_TIMEOUT + 5
)  # client-side deadline: give server 5 s extra, then treat as a network hang


class TelegramBridge:
    """Telegram bot bridge for Nova-Code.

    Connects to the Telegram Bot API via long-polling.  No additional
    dependencies beyond ``aiohttp`` (already installed).
    """

    def __init__(
        self,
        config: BridgeConfig,
        message_queue: asyncio.Queue[RemoteMessage],
    ) -> None:
        self._config = config
        self._queue = message_queue
        self._session: aiohttp.ClientSession | None = None
        self._offset: int = 0  # last update_id + 1 for long-polling
        self._running = False
        self._forum_thread_id: int | None = None  # set if chat is a forum supergroup

    def _ensure_session(self) -> aiohttp.ClientSession:
        """Return the current session, creating a fresh one if needed."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def _api_call(
        self,
        method: str,
        payload: dict[str, Any],
        *,
        req_timeout: aiohttp.ClientTimeout | None = None,
    ) -> dict[str, Any] | None:
        """Make a Telegram Bot API call.

        Args:
            method: API method name (e.g., "getUpdates", "sendMessage").
            payload: Request body as a dict.
            req_timeout: Optional per-request aiohttp timeout. Defaults to the
                session's default (300 s). Long-poll callers should pass
                ``_LONG_POLL_CLIENT_TIMEOUT`` so a network hang is detected
                within ~35 seconds instead of ~5 minutes.

        Returns:
            Parsed JSON response, or None on error.
        """
        session = self._ensure_session()
        url = f"{_TELEGRAM_API}/bot{self._config.token}/{method}"
        try:
            async with session.post(url, json=payload, timeout=req_timeout) as resp:
                data = await resp.json()
                if not data.get("ok"):
                    logger.error(f"Telegram API error: {data.get('description')}")
                    return None
                return data
        except aiohttp.ClientError as e:
            logger.error(f"Telegram HTTP error ({method}): {e}")
            # Close the stale session so the next call opens a fresh connection.
            try:
                await session.close()
            except Exception:  # noqa: BLE001
                pass
            self._session = None
            return None
        except TimeoutError:
            logger.debug(f"Telegram long-poll timeout on {method} — normal, retrying")
            try:
                await session.close()
            except Exception:  # noqa: BLE001
                pass
            self._session = None
            return None
        except Exception as e:  # noqa: BLE001
            logger.error(f"Telegram API call error ({method}): {e}")
            return None

    async def _get_updates(self) -> list[dict[str, Any]]:
        """Long-poll for updates from Telegram.

        The server holds the connection open for up to ``_LONG_POLL_SERVER_TIMEOUT``
        seconds while waiting for new messages, then responds with an empty list.
        We set a client-side deadline of server_timeout + 5 s so any network hang
        is detected quickly rather than waiting for aiohttp's 5-minute default.
        """
        result = await self._api_call(
            "getUpdates",
            {
                "offset": self._offset,
                "timeout": _LONG_POLL_SERVER_TIMEOUT,
                "allowed_updates": ["message"],
            },
            req_timeout=_LONG_POLL_CLIENT_TIMEOUT,
        )
        if result is None:
            return []

        updates = result.get("result", [])
        if updates:
            self._offset = updates[-1]["update_id"] + 1
        return updates

    async def create_forum_topic(self, chat_id: int, name: str) -> int | None:
        """Create a forum topic in a supergroup and return its message_thread_id.

        Returns None if the chat isn't a forum or the bot lacks permissions.
        """
        chat_info = await self._api_call("getChat", {"chat_id": chat_id})
        if chat_info is None:
            return None
        if not chat_info.get("result", {}).get("is_forum"):
            return None
        result = await self._api_call("createForumTopic", {"chat_id": chat_id, "name": name[:128]})
        if result is None:
            return None
        return result.get("result", {}).get("message_thread_id")

    def _thread_params(self, base: dict[str, Any]) -> dict[str, Any]:
        """Inject ``message_thread_id`` into an API payload when in a forum topic."""
        if self._forum_thread_id is not None:
            return {**base, "message_thread_id": self._forum_thread_id}
        return base

    async def _send_message(self, chat_id: int, text: str) -> None:
        """Send a message to a Telegram chat (chunked, forum-topic-aware)."""
        chunks = chunk_message(text, RemotePlatform.TELEGRAM)
        for chunk in chunks:
            await self._api_call(
                "sendMessage",
                self._thread_params({"chat_id": chat_id, "text": chunk, "parse_mode": "Markdown"}),
            )

    async def run(self) -> None:
        """Start the Telegram long-polling loop.

        This is intended to be run as an ``asyncio.Task``.
        """
        self._running = True

        # Get bot info to verify token
        me = await self._api_call("getMe", {})
        if me is None:
            logger.error("Telegram bot token is invalid or API is unreachable")
            self._running = False
            if self._session and not self._session.closed:
                await self._session.close()
            return

        bot_name = me.get("result", {}).get("username", "unknown")
        logger.info(f"Telegram bridge connected as @{bot_name}")

        _consecutive_errors = 0

        try:
            while self._running:
                updates = await self._get_updates()

                if not updates:
                    # No messages (normal) or a network error (also returns []).
                    # Back off briefly after repeated failures to avoid spinning.
                    if _consecutive_errors > 0:
                        await asyncio.sleep(min(2 ** _consecutive_errors, 30))
                    _consecutive_errors += 1
                else:
                    _consecutive_errors = 0

                for update in updates:
                    message = update.get("message")
                    if not message:
                        continue

                    chat = message.get("chat", {})
                    chat_id = chat.get("id")
                    from_user = message.get("from", {})
                    user_name = from_user.get("username") or from_user.get("first_name", "unknown")
                    text = (message.get("text") or "").strip()

                    if not text or chat_id is None:
                        continue

                    # Only process messages from the allowlisted chat.
                    # When in a forum topic, also accept messages from the topic thread.
                    if chat_id != self._config.chat_id and chat_id not in self._config.allowed_ids:
                        continue

                    # If we're scoped to a forum topic, only accept messages in that thread.
                    if self._forum_thread_id is not None:
                        msg_thread_id = message.get("message_thread_id")
                        if msg_thread_id != self._forum_thread_id:
                            continue

                    logger.info(
                        f"Telegram message from {user_name}: "
                        f"{text[:80]}{'...' if len(text) > 80 else ''}"
                    )

                    async def reply_fn(
                        response_text: str,
                        _chat_id: int = chat_id,
                    ) -> None:
                        await self._send_message(_chat_id, response_text)

                    async def typing_fn(
                        _chat_id: int = chat_id,
                    ) -> None:
                        await self._trigger_typing(_chat_id)

                    # Edit-in-place streaming state. `text` is the FULL accumulated
                    # answer; keep one live message and roll over past Telegram's
                    # 4096-char cap. Stream as PLAIN text (partial markdown like an
                    # unclosed code fence makes editMessageText reject the entity
                    # parse); apply Markdown only on the final edit, best-effort.
                    _live: dict = {"id": None, "base": 0, "last": None}
                    _EDIT_LIMIT = 3900

                    async def edit_fn(
                        body: str, final: bool = False, _chat_id: int = chat_id
                    ) -> None:
                        try:
                            while len(body) - _live["base"] > _EDIT_LIMIT:
                                block = body[_live["base"] : _live["base"] + _EDIT_LIMIT]
                                if _live["id"] is None:
                                    sent = await self._api_call(
                                        "sendMessage",
                                        self._thread_params({"chat_id": _chat_id, "text": block}),
                                    )
                                    _live["id"] = (
                                        (sent or {}).get("result", {}).get("message_id")
                                    )
                                elif block != _live["last"]:
                                    await self._api_call(
                                        "editMessageText",
                                        {
                                            "chat_id": _chat_id,
                                            "message_id": _live["id"],
                                            "text": block,
                                        },
                                    )
                                _live["base"] += _EDIT_LIMIT
                                _live["id"] = None
                                _live["last"] = None
                            remainder = body[_live["base"] :] or "…"
                            if _live["id"] is None:
                                params = self._thread_params({"chat_id": _chat_id, "text": remainder})
                                if final:
                                    params["parse_mode"] = "Markdown"
                                sent = await self._api_call("sendMessage", params)
                                if sent is None and final:
                                    sent = await self._api_call(
                                        "sendMessage",
                                        self._thread_params({"chat_id": _chat_id, "text": remainder}),
                                    )
                                _live["id"] = (
                                    (sent or {}).get("result", {}).get("message_id")
                                )
                                _live["last"] = remainder
                            elif remainder != _live["last"]:
                                params = {
                                    "chat_id": _chat_id,
                                    "message_id": _live["id"],
                                    "text": remainder,
                                }
                                if final:
                                    params["parse_mode"] = "Markdown"
                                res = await self._api_call("editMessageText", params)
                                if res is None and final:
                                    await self._api_call(
                                        "editMessageText",
                                        {
                                            "chat_id": _chat_id,
                                            "message_id": _live["id"],
                                            "text": remainder,
                                        },
                                    )
                                _live["last"] = remainder
                        except Exception as e:  # noqa: BLE001
                            logger.error(f"Telegram stream edit error: {e}")

                    tg_username = from_user.get("username")
                    user_mention = f"@{tg_username}" if tg_username else None

                    remote_msg = RemoteMessage(
                        platform=RemotePlatform.TELEGRAM,
                        chat_id=chat_id,
                        user_name=user_name,
                        text=text,
                        reply_fn=reply_fn,
                        typing_fn=typing_fn,
                        edit_fn=edit_fn,
                        user_mention=user_mention,
                    )

                    await self._queue.put(remote_msg)

        except asyncio.CancelledError:
            logger.info("Telegram bridge cancelled, shutting down")
        except Exception as e:  # noqa: BLE001
            logger.error(f"Telegram bridge error: {e}")
        finally:
            self._running = False
            if self._session and not self._session.closed:
                await self._session.close()
            logger.info("Telegram bridge stopped")

    async def _trigger_typing(self, chat_id: int) -> None:
        """Send a 'typing' chat action to Telegram."""
        await self._api_call(
            "sendChatAction",
            self._thread_params({"chat_id": chat_id, "action": "typing"}),
        )

    async def stop(self) -> None:
        """Gracefully stop the Telegram bridge."""
        self._running = False
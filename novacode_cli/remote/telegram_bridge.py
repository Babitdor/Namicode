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

    async def _api_call(self, method: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        """Make a Telegram Bot API call.

        Args:
            method: API method name (e.g., "getUpdates", "sendMessage").
            payload: Request body as a dict.

        Returns:
            Parsed JSON response, or None on error.
        """
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()

        url = f"{_TELEGRAM_API}/bot{self._config.token}/{method}"
        try:
            async with self._session.post(url, json=payload) as resp:
                data = await resp.json()
                if not data.get("ok"):
                    logger.error(f"Telegram API error: {data.get('description')}")
                    return None
                return data
        except aiohttp.ClientError as e:
            logger.error(f"Telegram HTTP error: {e}")
            return None
        except Exception as e:
            logger.error(f"Telegram API call error: {e}")
            return None

    async def _get_updates(self) -> list[dict[str, Any]]:
        """Long-poll for updates from Telegram.

        Uses a 30-second timeout so the bridge can check for cancellation
        every 30 seconds even when no messages arrive.
        """
        result = await self._api_call("getUpdates", {
            "offset": self._offset,
            "timeout": 30,
            "allowed_updates": ["message"],
        })
        if result is None:
            return []

        updates = result.get("result", [])
        if updates:
            self._offset = updates[-1]["update_id"] + 1
        return updates

    async def _send_message(self, chat_id: int, text: str) -> None:
        """Send a message to a Telegram chat.

        Handles chunking for messages that exceed the 4096-char limit.
        """
        chunks = chunk_message(text, RemotePlatform.TELEGRAM)
        for chunk in chunks:
            await self._api_call("sendMessage", {
                "chat_id": chat_id,
                "text": chunk,
                "parse_mode": "Markdown",
            })

    async def run(self) -> None:
        """Start the Telegram long-polling loop.

        This is intended to be run as an ``asyncio.Task``.
        """
        self._running = True
        self._session = aiohttp.ClientSession()

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

        try:
            while self._running:
                updates = await self._get_updates()

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

                    # Only process messages from the allowlisted chat
                    if chat_id != self._config.chat_id and chat_id not in self._config.allowed_ids:
                        continue

                    logger.info(
                        f"Telegram message from {user_name}: "
                        f"{text[:80]}{'...' if len(text) > 80 else ''}"
                    )

                    async def reply_fn(
                        response_text: str,
                        _chat_id: int = chat_id,
                    ) -> None:
                        """Send the agent's response back to the Telegram chat."""
                        await self._send_message(_chat_id, response_text)

                    async def typing_fn(
                        _chat_id: int = chat_id,
                    ) -> None:
                        """Trigger 'typing' indicator in the Telegram chat."""
                        await self._trigger_typing(_chat_id)

                    remote_msg = RemoteMessage(
                        platform=RemotePlatform.TELEGRAM,
                        chat_id=chat_id,
                        user_name=user_name,
                        text=text,
                        reply_fn=reply_fn,
                        typing_fn=typing_fn,
                    )

                    await self._queue.put(remote_msg)

        except asyncio.CancelledError:
            logger.info("Telegram bridge cancelled, shutting down")
        except Exception as e:
            logger.error(f"Telegram bridge error: {e}")
        finally:
            self._running = False
            if self._session and not self._session.closed:
                await self._session.close()
            logger.info("Telegram bridge stopped")

    async def _trigger_typing(self, chat_id: int) -> None:
        """Send a 'typing' chat action to Telegram."""
        if not self._session or self._session.closed:
            return
        try:
            url = f"https://api.telegram.org/bot{self._config.token}/sendChatAction"
            payload = {"chat_id": chat_id, "action": "typing"}
            async with self._session.post(url, json=payload) as resp:
                if resp.status != 200:
                    logger.debug(f"Telegram typing action failed: {resp.status}")
        except Exception as e:
            logger.debug(f"Telegram typing action error: {e}")

    async def stop(self) -> None:
        """Gracefully stop the Telegram bridge."""
        self._running = False
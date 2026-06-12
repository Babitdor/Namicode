"""Remote bridge package — Discord and Telegram integration for Nova-Code."""

from novacode_cli.remote.bridge import (
    BridgeConfig,
    RemoteBridgeManager,
    RemoteMessage,
    RemotePlatform,
    chunk_message,
)
from novacode_cli.remote.config import (
    async_get_discord_config,
    async_get_telegram_config,
    async_load_remote_config,
    async_save_discord_config,
    async_save_remote_config,
    async_save_telegram_config,
    get_discord_config,
    get_telegram_config,
    load_remote_config,
    save_discord_config,
    save_remote_config,
    save_telegram_config,
)

__all__ = [
    "BridgeConfig",
    "RemoteBridgeManager",
    "RemoteMessage",
    "RemotePlatform",
    "chunk_message",
    # Async variants (prefer these in async code paths)
    "async_load_remote_config",
    "async_save_remote_config",
    "async_get_discord_config",
    "async_get_telegram_config",
    "async_save_discord_config",
    "async_save_telegram_config",
    # Sync variants (internal / sync-context use only)
    "load_remote_config",
    "save_remote_config",
    "get_discord_config",
    "get_telegram_config",
    "save_discord_config",
    "save_telegram_config",
]
"""Remote bridge package — Discord and Telegram integration for Nova-Code."""

from novacode_cli.remote.bridge import (
    BridgeConfig,
    RemoteBridgeManager,
    RemoteMessage,
    RemotePlatform,
    chunk_message,
)
from novacode_cli.remote.config import (
    load_remote_config,
    save_remote_config,
    get_discord_config,
    get_telegram_config,
    save_discord_config,
    save_telegram_config,
)

__all__ = [
    "BridgeConfig",
    "RemoteBridgeManager",
    "RemoteMessage",
    "RemotePlatform",
    "chunk_message",
    "load_remote_config",
    "save_remote_config",
    "get_discord_config",
    "get_telegram_config",
    "save_discord_config",
    "save_telegram_config",
]
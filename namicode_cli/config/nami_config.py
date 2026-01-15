"""Configuration management for Nami CLI.

Manages persistent settings stored in ~/.nami/nami.config.json
"""

import json
from pathlib import Path
from typing import Any

from namicode_cli.config.config import Settings


class NamiConfig:
    """Manages persistent configuration for Nami CLI."""

    def __init__(self):
        """Initialize configuration manager."""
        settings = Settings.from_environment()
        self.config_dir = settings.user_deepagents_dir
        self.config_path = self.config_dir / "nami.config.json"
        self._config: dict[str, Any] = {}
        self._load()

    def _load(self) -> None:
        """Load configuration from disk."""
        if self.config_path.exists():
            try:
                with open(self.config_path, encoding="utf-8") as f:
                    self._config = json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                # If config is corrupted, start fresh
                print(f"Warning: Could not load config: {e}")
                self._config = {}
        else:
            self._config = {}

    def _save(self) -> None:
        """Save configuration to disk."""
        # Ensure config directory exists
        self.config_dir.mkdir(parents=True, exist_ok=True)

        # Write config file
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(self._config, f, indent=2)

    def get_model_config(self) -> dict[str, str] | None:
        """Get saved model provider configuration.

        Returns:
            Dict with 'provider' and 'model' keys, or None if not configured
        """
        return self._config.get("model")

    def set_model_config(self, provider: str, model: str) -> None:
        """Save model provider configuration.

        Args:
            provider: Provider ID (openai, anthropic, ollama, google)
            model: Model name
        """
        self._config["model"] = {
            "provider": provider,
            "model": model,
        }
        self._save()

    def clear_model_config(self) -> None:
        """Clear saved model configuration."""
        if "model" in self._config:
            del self._config["model"]
            self._save()

    def get(self, key: str, default: Any = None) -> Any:
        """Get a configuration value.

        Args:
            key: Configuration key
            default: Default value if key doesn't exist

        Returns:
            Configuration value or default
        """
        return self._config.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Set a configuration value.

        Args:
            key: Configuration key
            value: Value to set
        """
        self._config[key] = value
        self._save()

    def delete(self, key: str) -> None:
        """Delete a configuration value.

        Args:
            key: Configuration key to delete
        """
        if key in self._config:
            del self._config[key]
            self._save()

    def get_all(self) -> dict[str, Any]:
        """Get all configuration values.

        Returns:
            Copy of all configuration
        """
        return self._config.copy()

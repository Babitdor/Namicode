"""Configuration management for Nova CLI.

Manages persistent settings stored in ~/.nova/Nova.config.json
"""

import json
import os
from typing import Any

from novacode_cli.config.config import Settings, console


class NovaConfig:
    """Manages persistent configuration for Nova CLI."""

    def __init__(self):
        """Initialize configuration manager."""
        settings = Settings.from_environment()
        self.config_dir = settings.user_deepagents_dir
        self.config_path = self.config_dir / "Nova.config.json"
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
                console.print(f"[yellow]Warning: Could not load config: {e}[/yellow]")
                self._config = {}
        else:
            self._config = {}

    def _save(self) -> None:
        """Save configuration to disk atomically (temp file + rename)."""
        # Ensure config directory exists
        self.config_dir.mkdir(parents=True, exist_ok=True)

        # Write to temp file first, then atomically replace.
        # Use Path.replace (os.replace), not rename: on Windows rename raises
        # FileExistsError when the target exists, whereas replace overwrites
        # atomically on both Windows and POSIX.
        tmp_path = self.config_path.with_suffix(".tmp." + str(os.getpid()))
        try:
            tmp_path.write_text(json.dumps(self._config, indent=2), encoding="utf-8")
            tmp_path.replace(self.config_path)
        except Exception:
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:
                pass
            raise

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

    # ── Vision model config (for image routing) ─────────────────────────────

    VISION_MODEL_DEFAULT = "gemma4:31b-cloud"
    VISION_PROVIDER_DEFAULT = "ollama"

    def get_vision_model_config(self) -> dict[str, str]:
        """Get saved vision model provider configuration.

        Returns:
            Dict with 'provider' and 'model' keys. Defaults to ollama/gemma4:31b-cloud
            when not configured.
        """
        cfg = self._config.get("vision_model")
        if cfg and isinstance(cfg, dict) and "provider" in cfg and "model" in cfg:
            return {"provider": cfg["provider"], "model": cfg["model"]}
        return {"provider": self.VISION_PROVIDER_DEFAULT, "model": self.VISION_MODEL_DEFAULT}

    def set_vision_model_config(self, provider: str, model: str) -> None:
        """Save vision model provider configuration.

        Args:
            provider: Provider ID (openai, anthropic, ollama, google)
            model: Model name
        """
        self._config["vision_model"] = {
            "provider": provider,
            "model": model,
        }
        self._save()

    def clear_vision_model_config(self) -> None:
        """Clear saved vision model configuration (reverts to default)."""
        if "vision_model" in self._config:
            del self._config["vision_model"]
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

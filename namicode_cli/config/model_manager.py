"""Model provider management for Nami CLI.

Handles switching between different LLM providers (OpenAI, Anthropic, Ollama, Google)
during interactive sessions.
"""

import os
import subprocess
from typing import Any, Literal

from langchain_core.language_models import BaseChatModel

from namicode_cli.config.config import Settings, console
from namicode_cli.config.nami_config import NamiConfig

# Type for supported providers
ProviderType = Literal["openai", "anthropic", "ollama", "google"]


# Model provider presets
MODEL_PRESETS: dict[str, dict[str, Any]] = {
    "openai": {
        "name": "OpenAI",
        "description": "OpenAI GPT models (gpt-4, gpt-4-turbo, gpt-5-mini, etc.)",
        "default_model": "gpt-5-mini",
        "env_var": "OPENAI_MODEL",
        "api_key_var": "OPENAI_API_KEY",
        "requires_api_key": True,
        "models": [
            "gpt-5-mini",
            "gpt-4-turbo",
            "gpt-4",
            "gpt-4o",
            "gpt-4o-mini",
            "gpt-3.5-turbo",
        ],
    },
    "anthropic": {
        "name": "Anthropic",
        "description": "Claude models (claude-sonnet, claude-opus, etc.)",
        "default_model": "claude-sonnet-4-5-20250929",
        "env_var": "ANTHROPIC_MODEL",
        "api_key_var": "ANTHROPIC_API_KEY",
        "requires_api_key": True,
        "models": [
            "claude-sonnet-4-5-20250929",
            "claude-opus-4-5-20251101",
            "claude-3-5-sonnet-20241022",
            "claude-3-opus-20240229",
        ],
    },
    "ollama": {
        "name": "Ollama",
        "description": "Local Ollama models (qwen, llama, mistral, etc.)",
        "default_model": "qwen3-coder:480b-cloud",
        "env_var": "OLLAMA_MODEL",
        "api_key_var": None,
        "requires_api_key": False,
        "models": [
            "qwen3-coder:480b-cloud",
            "qwen2.5:72b",
            "llama3.3:70b",
            "deepseek-r1:70b",
            "mistral",
            "codestral",
        ],
    },
    "google": {
        "name": "Google",
        "description": "Google Gemini models",
        "default_model": "gemini-3-pro-preview",
        "env_var": "GOOGLE_MODEL",
        "api_key_var": "GOOGLE_API_KEY",
        "requires_api_key": True,
        "models": [
            "gemini-3-pro-preview",
            "gemini-2.0-flash-exp",
            "gemini-1.5-pro",
            "gemini-1.5-flash",
        ],
    },
}


def get_ollama_models() -> list[str]:
    """Get list of available Ollama models by running 'ollama list'.

    Returns:
        List of model names, or fallback list if command fails
    """
    try:
        result = subprocess.run(
            ["ollama", "list"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )

        if result.returncode == 0:
            lines = result.stdout.strip().split("\n")
            models = []

            # Skip header line and parse model names
            for line in lines[1:]:
                if line.strip():
                    # Model name is the first column
                    model_name = line.split()[0]
                    models.append(model_name)

            if models:
                return models

    except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
        # If ollama command fails, fall back to preset list
        pass

    # Fallback to preset models if command fails
    return MODEL_PRESETS["ollama"]["models"]


class ModelManager:
    """Manages model provider selection and switching."""

    def __init__(self):
        """Initialize model manager with current settings."""
        self.settings = Settings.from_environment()
        self.nami_config = NamiConfig()
        self.current_provider: ProviderType | None = None
        self.current_model: str | None = None

    def get_available_providers(self) -> list[tuple[str, dict[str, Any]]]:
        """Get list of available providers based on configured API keys.

        Returns:
            List of (provider_id, preset) tuples for available providers
        """
        available = []
        for provider_id, preset in MODEL_PRESETS.items():
            if not preset["requires_api_key"]:
                # Ollama is always available
                available.append((provider_id, preset))
            else:
                # Check if API key is configured
                api_key_var = preset["api_key_var"]
                if api_key_var and os.environ.get(api_key_var):
                    available.append((provider_id, preset))
        return available

    def get_current_provider(self) -> tuple[str, str] | None:
        """Get currently active provider and model.

        Checks saved config first, then falls back to environment variables.

        Returns:
            Tuple of (provider_name, model_name) or None
        """
        # Check saved configuration first
        saved_config = self.nami_config.get_model_config()
        if saved_config:
            provider_id = saved_config["provider"]
            model_name = saved_config["model"]
            preset = MODEL_PRESETS.get(provider_id)
            if preset:
                return (preset["name"], model_name)

        # Fall back to environment variables - check API keys in order
        if self.settings.has_openai:
            model = os.environ.get("OPENAI_MODEL", "gpt-5-mini")
            return ("OpenAI", model)
        elif self.settings.has_anthropic:
            model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5-20250929")
            return ("Anthropic", model)
        elif self.settings.has_google:
            model = os.environ.get("GOOGLE_MODEL", "gemini-3-pro-preview")
            return ("Google", model)
        else:
            # Default to Ollama (always available, no API key needed)
            model = os.environ.get("OLLAMA_MODEL", "qwen3-coder:480b-cloud")
            return ("Ollama", model)

    def create_model_for_provider(
        self, provider: ProviderType, model_name: str | None = None
    ) -> BaseChatModel:
        """Create a model instance for the specified provider.

        Args:
            provider: Provider identifier (openai, anthropic, ollama, google)
            model_name: Specific model name (optional, uses default if not provided)

        Returns:
            BaseChatModel instance

        Raises:
            ValueError: If provider is invalid or API key is missing
        """
        preset = MODEL_PRESETS.get(provider)
        if not preset:
            raise ValueError(f"Unknown provider: {provider}")

        # Use provided model name or default
        if model_name is None:
            model_name = preset["default_model"]

        # Check API key requirement
        if preset["requires_api_key"]:
            api_key_var = preset["api_key_var"]
            if not os.environ.get(api_key_var):
                raise ValueError(
                    f"{preset['name']} requires {api_key_var} environment variable"
                )

        # Create the appropriate model
        if provider == "openai":
            from langchain_openai import ChatOpenAI

            return ChatOpenAI(model=model_name)  # type: ignore

        elif provider == "anthropic":
            from langchain_anthropic import ChatAnthropic

            return ChatAnthropic(
                model_name=model_name,
                max_tokens=20_000,  # type: ignore[arg-type]
            )

        elif provider == "ollama":
            from langchain_ollama import ChatOllama

            return ChatOllama(
                model=model_name,  # type: ignore
                temperature=0,
                disable_streaming=True,
                keep_alive=600,
                num_ctx=200000,
            )

        elif provider == "google":
            from langchain_google_genai import ChatGoogleGenerativeAI

            return ChatGoogleGenerativeAI(
                model=model_name,
                temperature=0,
                max_tokens=None,
            )

        raise ValueError(f"Provider {provider} not implemented")

    def set_provider(
        self, provider: ProviderType, model_name: str | None = None
    ) -> None:
        """Set the current provider and model.

        Saves configuration to nami.config.json for persistence across sessions.

        Args:
            provider: Provider to use
            model_name: Model name (optional)
        """
        preset = MODEL_PRESETS.get(provider)
        if not preset:
            raise ValueError(f"Unknown provider: {provider}")

        # Use default model if not specified
        if model_name is None:
            model_name = preset["default_model"]

        # Save to persistent configuration
        self.nami_config.set_model_config(provider, model_name)

        # Also set environment variables for immediate effect in current session
        if preset["env_var"]:
            os.environ[preset["env_var"]] = model_name

        self.current_provider = provider
        self.current_model = model_name

        console.print(f"[dim]Switched to {preset['name']}: {self.current_model}[/dim]")

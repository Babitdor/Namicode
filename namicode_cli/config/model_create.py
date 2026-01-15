import os
import re
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

import dotenv
from langchain_core.language_models import BaseChatModel
from rich.console import Console
from namicode_cli.config.config import settings

if sys.platform == "win32":
    import io

    console = Console(
        highlight=False, file=io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    )
else:
    console = Console(highlight=False)


def create_model() -> BaseChatModel:
    """Create the appropriate model based on available API keys.

    Priority order:
    1. Saved configuration from nami.config.json (highest priority)
    2. Environment variables from .env file
    3. Default to Ollama (fallback)

    Returns:
        ChatModel instance (OpenAI, Anthropic, Google, or Ollama)
    """
    # Load saved configuration - this takes precedence over .env
    from namicode_cli.config.nami_config import NamiConfig

    nami_config = NamiConfig()
    saved_model_config = nami_config.get_model_config()

    # If we have a saved config, use it directly (bypasses .env settings)
    if saved_model_config:
        provider = saved_model_config["provider"]
        model_name = saved_model_config["model"]

        # console.print(f"[dim]Using saved configuration: {provider}/{model_name}[/dim]")

        # Create model directly based on saved config
        if provider == "ollama":
            from langchain_ollama import ChatOllama

            return ChatOllama(
                model=model_name,
                temperature=0,
                disable_streaming=True,
                keep_alive=600,
                num_ctx=200000,
            )

        elif provider == "openai":
            from langchain_openai import ChatOpenAI

            # Verify API key is available
            if not os.environ.get("OPENAI_API_KEY"):
                console.print(
                    "[yellow]Warning: OPENAI_API_KEY not set, falling back to Ollama[/yellow]"
                )
            else:
                return ChatOpenAI(model=model_name)

        elif provider == "anthropic":
            from langchain_anthropic import ChatAnthropic

            # Verify API key is available
            if not os.environ.get("ANTHROPIC_API_KEY"):
                console.print(
                    "[yellow]Warning: ANTHROPIC_API_KEY not set, falling back to Ollama[/yellow]"
                )
            else:
                return ChatAnthropic(
                    model_name=model_name,
                    max_tokens=20_000,  # type: ignore[arg-type]
                )

        elif provider == "google":
            from langchain_google_genai import ChatGoogleGenerativeAI

            # Verify API key is available
            if not os.environ.get("GOOGLE_API_KEY"):
                console.print(
                    "[yellow]Warning: GOOGLE_API_KEY not set, falling back to Ollama[/yellow]"
                )
            else:
                return ChatGoogleGenerativeAI(
                    model=model_name,
                    temperature=0,
                    max_tokens=None,
                )

    # No saved config - fall back to environment variables and .env file
    # Check available API keys in order of priority
    if settings.has_openai:
        from langchain_openai import ChatOpenAI

        model_name = os.environ.get("OPENAI_MODEL", "gpt-5-mini")
        console.print(f"[dim]Using OpenAI model: {model_name}[/dim]")
        return ChatOpenAI(
            model=model_name,
        )
    if settings.has_anthropic:
        from langchain_anthropic import ChatAnthropic

        model_name = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5-20250929")
        console.print(f"[dim]Using Anthropic model: {model_name}[/dim]")
        return ChatAnthropic(
            model_name=model_name,
            # The attribute exists, but it has a Pydantic alias which
            # causes issues in IDEs/type checkers.
            max_tokens=20_000,  # type: ignore[arg-type]
        )
    if settings.has_google:
        from langchain_google_genai import ChatGoogleGenerativeAI

        model_name = os.environ.get("GOOGLE_MODEL", "gemini-3-pro-preview")
        console.print(f"[dim]Using Google Gemini model: {model_name}[/dim]")
        return ChatGoogleGenerativeAI(
            model=model_name,
            temperature=0,
            max_tokens=None,
        )

    # Default to Ollama if no API keys are configured
    from langchain_ollama import ChatOllama

    model_name = os.environ.get("OLLAMA_MODEL", "qwen3-coder:480b-cloud")
    console.print(
        f"[dim]No API keys configured. Defaulting to Ollama model: {model_name}[/dim]"
    )
    return ChatOllama(
        model=model_name,
        temperature=0,
        disable_streaming=True,
        keep_alive=600,
        num_ctx=200000,
    )

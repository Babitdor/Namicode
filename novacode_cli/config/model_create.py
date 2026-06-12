import os
import sys

from langchain_core.language_models import BaseChatModel
from rich.console import Console

from novacode_cli.config.config import settings

if sys.platform == "win32":
    import io

    console = Console(highlight=False, file=io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8"))
else:
    console = Console(highlight=False)


def create_model_from_config(provider: str, model_name: str) -> BaseChatModel | None:
    """Create a model instance from a provider and model name (no fallback).

    Unlike :func:`create_model`, this function only tries the exact provider/model
    requested and returns ``None`` if the required API key is missing — it never
    falls back to another provider.  This is used for vision captioning (gemma).

    Args:
        provider: One of ``"ollama"``, ``"openai"``, ``"anthropic"``, ``"google"``, ``"openrouter"``.
        model_name: The model name/identifier.

    Returns:
        A ``BaseChatModel`` instance, or ``None`` if the provider cannot be used.
    """
    if provider == "ollama":
        from langchain_ollama import ChatOllama

        from novacode_cli.context._dynamic import get_ollama_num_ctx

        return ChatOllama(
            model=model_name,
            temperature=0,
            disable_streaming=True,
            keep_alive=600,
            num_ctx=get_ollama_num_ctx(),
        )

    if provider == "openai":
        if not os.environ.get("OPENAI_API_KEY"):
            return None
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(model=model_name, max_retries=5)

    if provider == "anthropic":
        if not os.environ.get("ANTHROPIC_API_KEY"):
            return None
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            model_name=model_name,
            max_tokens=20_000,  # type: ignore[arg-type]
            max_retries=5,
        )

    if provider == "google":
        if not os.environ.get("GOOGLE_API_KEY"):
            return None
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(
            model=model_name,
            temperature=0,
            max_tokens=None,
            max_retries=5,
        )

    if provider == "openrouter":
        if not os.environ.get("OPENROUTER_API_KEY"):
            return None
        from langchain_openai import ChatOpenAI

        from novacode_cli.config.model_manager import OPENROUTER_BASE_URL

        return ChatOpenAI(
            model=model_name,
            base_url=OPENROUTER_BASE_URL,
            api_key=os.environ.get("OPENROUTER_API_KEY"),  # type: ignore[arg-type]
            max_retries=5,
        )

    return None


def create_model() -> BaseChatModel:
    """Create the appropriate model based on available API keys.

    Priority order:
    1. Saved configuration from Nova.config.json (highest priority)
    2. Environment variables from .env file
    3. Default to Ollama (fallback)

    Returns:
        ChatModel instance (OpenAI, Anthropic, Google, OpenRouter, or Ollama)
    """
    # Load saved configuration - this takes precedence over .env
    from novacode_cli.config.nova_config import NovaConfig

    nova_config = NovaConfig()
    saved_model_config = nova_config.get_model_config()

    # If we have a saved config, use it directly (bypasses .env settings)
    if saved_model_config:
        provider = saved_model_config["provider"]
        model_name = saved_model_config["model"]

        # console.print(f"[dim]Using saved configuration: {provider}/{model_name}[/dim]")

        # Create model directly based on saved config
        if provider == "ollama":
            from langchain_ollama import ChatOllama

            from novacode_cli.context._dynamic import get_ollama_num_ctx

            return ChatOllama(
                model=model_name,
                temperature=0,
                disable_streaming=True,
                keep_alive=600,
                num_ctx=get_ollama_num_ctx(),
            )

        if provider == "openai":
            from langchain_openai import ChatOpenAI

            # Verify API key is available
            if not os.environ.get("OPENAI_API_KEY"):
                console.print(
                    "[yellow]Warning: OPENAI_API_KEY not set, falling back to Ollama[/yellow]"
                )
            else:
                return ChatOpenAI(model=model_name, max_retries=5)

        elif provider == "anthropic":
            from langchain_anthropic import ChatAnthropic

            # Verify API key is available
            if not os.environ.get("ANTHROPIC_API_KEY"):
                console.print(
                    "[yellow]Warning: ANTHROPIC_API_KEY not set, falling back to Ollama[/yellow]"
                )
            else:
                # Extended thinking support (Anthropic only)
                thinking_budget = nova_config.get("thinking_budget", 0)
                thinking_kwargs: dict = {}
                if thinking_budget and thinking_budget > 0:
                    thinking_kwargs["thinking"] = {
                        "type": "enabled",
                        "budget_tokens": int(thinking_budget),
                    }

                return ChatAnthropic(
                    model_name=model_name,
                    max_tokens=20_000,  # type: ignore[arg-type]
                    max_retries=5,
                    **thinking_kwargs,
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
                    max_retries=5,
                )

        elif provider == "openrouter":
            from langchain_openai import ChatOpenAI

            from novacode_cli.config.model_manager import OPENROUTER_BASE_URL

            # Verify API key is available
            if not os.environ.get("OPENROUTER_API_KEY"):
                console.print(
                    "[yellow]Warning: OPENROUTER_API_KEY not set, falling back to Ollama[/yellow]"
                )
            else:
                # OpenRouter is OpenAI-compatible: ChatOpenAI + custom base URL/key.
                return ChatOpenAI(
                    model=model_name,
                    base_url=OPENROUTER_BASE_URL,
                    api_key=os.environ.get("OPENROUTER_API_KEY"),  # type: ignore[arg-type]
                    max_retries=5,
                )

    # No saved config - fall back to environment variables and .env file
    # Check available API keys in order of priority
    if settings.has_openai:
        from langchain_openai import ChatOpenAI

        model_name = os.environ.get("OPENAI_MODEL", "gpt-5-mini")
        console.print(f"[dim]Using OpenAI model: {model_name}[/dim]")
        return ChatOpenAI(
            model=model_name,
            max_retries=5,
        )
    if settings.has_anthropic:
        from langchain_anthropic import ChatAnthropic

        model_name = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5-20250929")
        console.print(f"[dim]Using Anthropic model: {model_name}[/dim]")

        # Extended thinking support (Anthropic only)
        thinking_kwargs: dict = {}
        thinking_budget = int(os.environ.get("Nova_THINKING_BUDGET", "0"))
        if thinking_budget > 0:
            thinking_kwargs["thinking"] = {
                "type": "enabled",
                "budget_tokens": thinking_budget,
            }

        return ChatAnthropic(
            model_name=model_name,
            # The attribute exists, but it has a Pydantic alias which
            # causes issues in IDEs/type checkers.
            max_tokens=20_000,  # type: ignore[arg-type]
            max_retries=5,
            **thinking_kwargs,
        )
    if settings.has_google:
        from langchain_google_genai import ChatGoogleGenerativeAI

        model_name = os.environ.get("GOOGLE_MODEL", "gemini-3-pro-preview")
        console.print(f"[dim]Using Google Gemini model: {model_name}[/dim]")
        return ChatGoogleGenerativeAI(
            model=model_name,
            temperature=0,
            max_tokens=None,
            max_retries=5,
        )
    if settings.has_openrouter:
        from langchain_openai import ChatOpenAI

        from novacode_cli.config.model_manager import OPENROUTER_BASE_URL

        model_name = os.environ.get("OPENROUTER_MODEL", "anthropic/claude-3.5-sonnet")
        console.print(f"[dim]Using OpenRouter model: {model_name}[/dim]")
        return ChatOpenAI(
            model=model_name,
            base_url=OPENROUTER_BASE_URL,
            api_key=os.environ.get("OPENROUTER_API_KEY"),  # type: ignore[arg-type]
            max_retries=5,
        )

    # Default to Ollama if no API keys are configured
    from langchain_ollama import ChatOllama

    model_name = os.environ.get("OLLAMA_MODEL", "qwen3-coder:480b-cloud")
    console.print(f"[dim]No API keys configured. Defaulting to Ollama model: {model_name}[/dim]")

    from novacode_cli.context._dynamic import get_ollama_num_ctx

    return ChatOllama(
        model=model_name,
        temperature=0,
        disable_streaming=True,
        keep_alive=600,
        num_ctx=get_ollama_num_ctx(),
    )


# =============================================================================
# Vision Model Registry
# =============================================================================

# Models known to support vision/multimodal capabilities
VISION_CAPABLE_MODELS: dict[str, bool] = {
    # Anthropic - Claude 3+ models support vision
    "claude-sonnet-4-5-20250929": True,
    "claude-opus-4-5-20251001": True,
    "claude-3-5-sonnet-20241022": True,
    "claude-3-5-sonnet-20240620": True,
    "claude-3-5-haiku-20241022": True,
    "claude-3-opus-20240229": True,
    "claude-3-sonnet-20240229": True,
    "claude-3-haiku-20240307": True,
    # OpenAI - GPT-4 Vision models
    "gpt-4o": True,
    "gpt-4o-mini": True,
    "gpt-4-turbo": True,
    "gpt-4-vision-preview": True,
    "gpt-4-turbo-2024-04-09": True,
    # Google - Gemini 1.5+ models
    "gemini-1.5-pro": True,
    "gemini-1.5-flash": True,
    "gemini-2.0-flash-exp": True,
    "gemini-3-pro-preview": True,
    # Ollama vision models (common ones)
    "llava": True,
    "llava:7b": True,
    "llava:13b": True,
    "llava:34b": True,
    "bakllava": True,
    "moondream": True,
    "moondream2": True,
    "llava-llama3": True,
    "llava-phi3": True,
    "minicpm-v": True,
    # User's preferred model
    "qwen3-vl:235b-cloud": True,
    "qwen2-vl": True,
    "qwen2-vl:7b": True,
    "qwen2-vl:72b": True,
}

# Keywords that indicate vision capability in model names
VISION_KEYWORDS = [
    "vision",
    "multimodal",
    "mm",
    "llava",
    "bakllava",
    "moondream",
    "-vl",
    "-v",
    "minicpm-v",
    "qwen-vl",
    "qwen2-vl",
    "qwen3-vl",
]


def model_supports_vision(model_name: str) -> bool:
    """Check if a model supports vision/multimodal capabilities.

    Args:
        model_name: Name of the model

    Returns:
        True if model supports vision, False otherwise
    """
    # Normalize model name for comparison
    model_lower = model_name.lower()

    # Check registry first (exact match)
    if model_name in VISION_CAPABLE_MODELS:
        return VISION_CAPABLE_MODELS[model_name]

    # Check registry with lowercase
    if model_lower in VISION_CAPABLE_MODELS:
        return VISION_CAPABLE_MODELS[model_lower]

    # For unknown models, check if name contains vision keywords
    return any(keyword in model_lower for keyword in VISION_KEYWORDS)


def get_vision_model_suggestion(current_model: str) -> str | None:
    """Suggest a vision-capable model if current model doesn't support vision.

    Args:
        current_model: Current model name

    Returns:
        Suggested model name or None if current model supports vision
    """
    if model_supports_vision(current_model):
        return None  # Current model already supports vision

    # Suggest best available model based on configured providers
    if settings.has_anthropic:
        return "claude-sonnet-4-5-20250929"
    if settings.has_openai:
        return "gpt-4o"
    if settings.has_google:
        return "gemini-1.5-pro"
    # Default to Ollama vision model
    return "qwen3-vl:235b-cloud"


def get_current_model_name() -> str:
    """Get the name of the currently configured model.

    Returns:
        Model name string
    """
    from novacode_cli.config.nova_config import NovaConfig

    nova_config = NovaConfig()
    saved_config = nova_config.get_model_config()

    if saved_config:
        return saved_config["model"]

    # Check environment variables
    if settings.has_openai:
        return os.environ.get("OPENAI_MODEL", "gpt-5-mini")
    if settings.has_anthropic:
        return os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5-20250929")
    if settings.has_google:
        return os.environ.get("GOOGLE_MODEL", "gemini-3-pro-preview")
    return os.environ.get("OLLAMA_MODEL", "qwen3-coder:480b-cloud")

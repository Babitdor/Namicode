import os

from langchain_core.language_models import BaseChatModel

from novacode_cli.config.config import console, settings

# Env var that must be set before a provider is usable. Ollama needs no key.
PROVIDER_KEY_ENV: dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "google": "GOOGLE_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
}


def build_chat_model(provider: str, model_name: str) -> BaseChatModel:
    """THE model constructor — every ChatX(...) in Nova is built here.

    One deep module for provider construction: reasoning-effort / thinking
    budgets, retries, Ollama num_ctx + content-block patch, OpenRouter base
    URL. Key-presence *policy* stays with the callers (return None / warn and
    fall back / raise) — this function only constructs.

    Args:
        provider: "ollama" | "openai" | "anthropic" | "google" | "openrouter".
        model_name: The model identifier for that provider.

    Raises:
        ValueError: Unknown provider.
    """
    from novacode_cli.config.nova_config import NovaConfig

    nova_config = NovaConfig()
    effort = nova_config.get("reasoning_effort")

    if provider == "ollama":
        from langchain_ollama import ChatOllama

        from novacode_cli.context._dynamic import get_ollama_num_ctx
        from novacode_cli.utils.backend_patches import apply_ollama_content_block_patch

        apply_ollama_content_block_patch()

        ollama_kwargs = {}
        if effort:
            ollama_kwargs["reasoning"] = False if effort == "off" else effort

        return ChatOllama(
            model=model_name,
            temperature=0,
            disable_streaming=True,
            keep_alive=600,
            num_ctx=get_ollama_num_ctx(),
            **ollama_kwargs,
        )

    if provider in ("openai", "openrouter"):
        from langchain_openai import ChatOpenAI

        openai_kwargs: dict = {}
        if effort and effort != "off" and ("o1" in model_name or "o3" in model_name):
            openai_kwargs["reasoning_effort"] = effort
        if provider == "openrouter":
            # OpenRouter is OpenAI-compatible: same client, custom base URL + key.
            from novacode_cli.config.model_manager import OPENROUTER_BASE_URL

            openai_kwargs["base_url"] = OPENROUTER_BASE_URL
            openai_kwargs["api_key"] = os.environ.get("OPENROUTER_API_KEY")

        return ChatOpenAI(model=model_name, max_retries=5, **openai_kwargs)

    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        thinking_kwargs: dict = {}
        thinking_budget = nova_config.get("thinking_budget", 0) or int(
            os.environ.get("Nova_THINKING_BUDGET", "0")
        )
        if not thinking_budget and effort and effort != "off":
            budget_map = {"low": 2048, "medium": 4096, "high": 16384}
            thinking_budget = budget_map.get(effort, 4096)

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

    if provider == "google":
        from langchain_google_genai import ChatGoogleGenerativeAI

        google_kwargs: dict = {}
        if effort and effort != "off":
            if "gemini-2.5" in model_name or "gemini-2.0" in model_name:
                budget_map = {"low": 2048, "medium": 8192, "high": 32768}
                google_kwargs["thinking_budget"] = budget_map.get(effort, 8192)
            else:
                google_kwargs["thinking_level"] = effort
            google_kwargs["include_thoughts"] = True

        return ChatGoogleGenerativeAI(
            model=model_name,
            temperature=0,
            max_tokens=None,
            max_retries=5,
            **google_kwargs,
        )

    raise ValueError(f"Unknown provider: {provider}")


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
    key_var = PROVIDER_KEY_ENV.get(provider)
    if key_var and not os.environ.get(key_var):
        return None
    try:
        return build_chat_model(provider, model_name)
    except ValueError:
        return None  # unknown provider


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

    # If we have a saved config, use it directly (bypasses .env settings).
    # Missing key for the saved provider → warn and fall through to the
    # env-priority chain below (same as the pre-consolidation behavior).
    if saved_model_config:
        provider = saved_model_config["provider"]
        model_name = saved_model_config["model"]
        key_var = PROVIDER_KEY_ENV.get(provider)
        if key_var and not os.environ.get(key_var):
            console.print(f"[yellow]Warning: {key_var} not set, falling back to Ollama[/yellow]")
        else:
            return build_chat_model(provider, model_name)

    # No usable saved config — pick the first provider with a key configured.
    _ENV_PRIORITY = [
        (settings.has_openai, "openai", "OPENAI_MODEL", "gpt-5-mini", "OpenAI"),
        (
            settings.has_anthropic,
            "anthropic",
            "ANTHROPIC_MODEL",
            "claude-sonnet-4-5-20250929",
            "Anthropic",
        ),
        (settings.has_google, "google", "GOOGLE_MODEL", "gemini-3-pro-preview", "Google Gemini"),
        (
            settings.has_openrouter,
            "openrouter",
            "OPENROUTER_MODEL",
            "anthropic/claude-3.5-sonnet",
            "OpenRouter",
        ),
    ]
    for available, provider, model_env, default_model, label in _ENV_PRIORITY:
        if available:
            model_name = os.environ.get(model_env, default_model)
            console.print(f"[dim]Using {label} model: {model_name}[/dim]")
            return build_chat_model(provider, model_name)

    # Default to Ollama if no API keys are configured
    model_name = os.environ.get("OLLAMA_MODEL", "qwen3-coder:480b-cloud")
    console.print(f"[dim]No API keys configured. Defaulting to Ollama model: {model_name}[/dim]")
    return build_chat_model("ollama", model_name)


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

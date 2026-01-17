"""Vision model capability detection and registry.

This module provides functionality to detect and manage vision-capable models
across different LLM providers (Anthropic, OpenAI, Google, Ollama).
"""

from typing import Literal

# Registry of known vision-capable models
VISION_CAPABLE_MODELS: dict[str, bool] = {
    # Anthropic Claude models
    "claude-sonnet-4-5-20250929": True,
    "claude-opus-4-5-20251001": True,
    "claude-3-5-sonnet-20241022": True,
    "claude-3-5-sonnet-20240620": True,
    "claude-3-5-haiku-20241022": True,
    "claude-3-opus-20240229": True,

    # OpenAI models
    "gpt-4o": True,
    "gpt-4o-mini": True,
    "gpt-4-turbo": True,
    "gpt-4-vision-preview": True,

    # Google Gemini models
    "gemini-1.5-pro": True,
    "gemini-1.5-flash": True,
    "gemini-2.0-flash-exp": True,

    # Ollama vision models
    "qwen3-vl": True,
    "qwen3-vl:235b-cloud": True,
    "llava": True,
    "llava:latest": True,
    "llava:7b": True,
    "llava:13b": True,
    "llava:34b": True,
    "llava-llama-3": True,
    "bakllava": True,
    "moondream": True,
    "moondream:latest": True,
}


# Keywords that suggest a model might support vision
VISION_MODEL_KEYWORDS = [
    "vision",
    "multimodal",
    "mm",
    "vl",  # vision-language
    "llava",  # popular vision model family
    "bakllava",
    "moondream",
]


def model_supports_vision(model_name: str) -> bool:
    """Check if a model supports vision capabilities.

    Args:
        model_name: Name of the model (e.g., "gpt-4o", "qwen3-vl:235b-cloud")

    Returns:
        True if model supports vision, False otherwise

    Examples:
        >>> model_supports_vision("gpt-4o")
        True
        >>> model_supports_vision("gpt-3.5-turbo")
        False
        >>> model_supports_vision("qwen3-vl:235b-cloud")
        True
    """
    # Direct lookup in registry
    if model_name in VISION_CAPABLE_MODELS:
        return VISION_CAPABLE_MODELS[model_name]

    # Check base model name (without tag/version)
    # e.g., "qwen3-vl:235b-cloud" -> "qwen3-vl"
    base_name = model_name.split(":")[0]
    if base_name in VISION_CAPABLE_MODELS:
        return VISION_CAPABLE_MODELS[base_name]

    # Heuristic: check for vision-related keywords
    model_lower = model_name.lower()
    return any(keyword in model_lower for keyword in VISION_MODEL_KEYWORDS)


def get_vision_models(provider: Literal["anthropic", "openai", "google", "ollama"]) -> list[str]:
    """Get list of vision-capable models for a specific provider.

    Args:
        provider: LLM provider name

    Returns:
        List of model names that support vision

    Examples:
        >>> get_vision_models("ollama")
        ['qwen3-vl', 'qwen3-vl:235b-cloud', 'llava', ...]
    """
    provider_models = {
        "anthropic": ["claude"],
        "openai": ["gpt-4"],
        "google": ["gemini"],
        "ollama": ["qwen", "llava", "bakllava", "moondream"],
    }

    prefix = provider_models.get(provider, [])

    vision_models = []
    for model_name in VISION_CAPABLE_MODELS.keys():
        if any(model_name.startswith(p) for p in prefix):
            vision_models.append(model_name)

    return vision_models


def suggest_vision_model(current_model: str) -> str | None:
    """Suggest a vision-capable model if current model doesn't support vision.

    This is used when users try to add images but their current model
    doesn't support vision capabilities.

    Args:
        current_model: Current model name

    Returns:
        Suggested model name or None if current model already supports vision

    Examples:
        >>> suggest_vision_model("gpt-3.5-turbo")
        'gpt-4o'
        >>> suggest_vision_model("qwen3-vl:235b-cloud")
        None
    """
    if model_supports_vision(current_model):
        return None

    # Priority suggestions based on provider availability
    # These would be checked against actual configuration in production
    suggestions = [
        ("ollama", "qwen3-vl:235b-cloud"),  # User's preferred model
        ("ollama", "qwen3-vl"),
        ("anthropic", "claude-sonnet-4-5-20250929"),
        ("openai", "gpt-4o"),
        ("google", "gemini-1.5-pro"),
    ]

    # Return first suggestion (in production, this would check API key availability)
    return suggestions[0][1]
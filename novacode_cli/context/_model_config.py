"""Model-specific configuration for context optimization.

Private to the ``context`` package. Provides per-model tuning (context window,
safe budget, eviction/growth thresholds, token ratio, cost) via a hardcoded
table. Surfaced through ``ContextManager.model_config``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ModelConfig:
    """Configuration for a specific LLM model.

    Attributes:
        name: Model identifier
        context_window: Maximum context window size in tokens
        safe_budget: Safe context budget (leaving room for response)
        growth_threshold: Maximum growth per turn before warning
        eviction_threshold: Fraction of budget to trigger eviction
        token_ratio: Characters per token ratio
        supports_streaming: Whether model supports streaming
        cost_per_1k_tokens: Cost per 1000 tokens (input, output)
    """

    name: str
    context_window: int
    safe_budget: int
    growth_threshold: float
    eviction_threshold: float
    token_ratio: float
    supports_streaming: bool = True
    cost_per_1k_tokens: tuple[float, float] = (0.0, 0.0)  # (input, output)


# Model-specific configurations (based on actual Ollama model specs)
MODEL_CONFIGS = {
    # GLM Models
    "glm-5": ModelConfig(
        name="glm-5",
        context_window=202752,  # Actual: 202,752 tokens (~198K)
        safe_budget=160000,
        growth_threshold=2000.0,
        eviction_threshold=0.75,
        token_ratio=3.5,
        supports_streaming=True,
        cost_per_1k_tokens=(0.001, 0.001),
    ),
    "glm-4.7": ModelConfig(
        name="glm-4.7",
        context_window=128000,
        safe_budget=100000,
        growth_threshold=1000.0,
        eviction_threshold=0.75,
        token_ratio=3.5,
        supports_streaming=True,
        cost_per_1k_tokens=(0.001, 0.001),
    ),
    "glm-4.6": ModelConfig(
        name="glm-4.6",
        context_window=128000,
        safe_budget=100000,
        growth_threshold=1000.0,
        eviction_threshold=0.75,
        token_ratio=3.5,
        supports_streaming=True,
        cost_per_1k_tokens=(0.001, 0.001),
    ),
    "glm-ocr": ModelConfig(
        name="glm-ocr",
        context_window=32000,
        safe_budget=25000,
        growth_threshold=500.0,
        eviction_threshold=0.7,
        token_ratio=3.5,
        supports_streaming=True,
        cost_per_1k_tokens=(0.0, 0.0),
    ),
    # Qwen Models
    "qwen3.5": ModelConfig(
        name="qwen3.5",
        context_window=262144,  # Actual: 262,144 tokens (256K)
        safe_budget=200000,
        growth_threshold=2500.0,
        eviction_threshold=0.75,
        token_ratio=3.5,
        supports_streaming=True,
        cost_per_1k_tokens=(0.0, 0.0),
    ),
    "qwen3-coder": ModelConfig(
        name="qwen3-coder",
        context_window=128000,
        safe_budget=100000,
        growth_threshold=1000.0,
        eviction_threshold=0.75,
        token_ratio=4.0,
        supports_streaming=True,
        cost_per_1k_tokens=(0.0, 0.0),
    ),
    "qwen3": ModelConfig(
        name="qwen3",
        context_window=32000,
        safe_budget=25000,
        growth_threshold=500.0,
        eviction_threshold=0.7,
        token_ratio=3.5,
        supports_streaming=True,
        cost_per_1k_tokens=(0.0, 0.0),
    ),
    "qwen2.5-coder": ModelConfig(
        name="qwen2.5-coder",
        context_window=32000,
        safe_budget=25000,
        growth_threshold=500.0,
        eviction_threshold=0.7,
        token_ratio=4.0,
        supports_streaming=True,
        cost_per_1k_tokens=(0.0, 0.0),
    ),
    # Gemma Models
    "gemma4": ModelConfig(
        name="gemma4",
        context_window=128000,
        safe_budget=100000,
        growth_threshold=1000.0,
        eviction_threshold=0.75,
        token_ratio=3.5,
        supports_streaming=True,
        cost_per_1k_tokens=(0.0, 0.0),
    ),
    "functiongemma": ModelConfig(
        name="functiongemma",
        context_window=8000,
        safe_budget=6000,
        growth_threshold=200.0,
        eviction_threshold=0.7,
        token_ratio=4.0,
        supports_streaming=True,
        cost_per_1k_tokens=(0.0, 0.0),
    ),
    "embeddinggemma": ModelConfig(
        name="embeddinggemma",
        context_window=8000,
        safe_budget=6000,
        growth_threshold=200.0,
        eviction_threshold=0.7,
        token_ratio=4.0,
        supports_streaming=False,  # Embedding model
        cost_per_1k_tokens=(0.0, 0.0),
    ),
    # Llama Models
    "llama3.1": ModelConfig(
        name="llama3.1",
        context_window=131072,  # Actual: 131,072 tokens (128K)
        safe_budget=100000,
        growth_threshold=1000.0,
        eviction_threshold=0.75,
        token_ratio=4.0,
        supports_streaming=True,
        cost_per_1k_tokens=(0.0, 0.0),
    ),
    "llama3.2": ModelConfig(
        name="llama3.2",
        context_window=131072,
        safe_budget=100000,
        growth_threshold=1000.0,
        eviction_threshold=0.75,
        token_ratio=4.0,
        supports_streaming=True,
        cost_per_1k_tokens=(0.0, 0.0),
    ),
    # Mistral Models
    "mistral-large-3": ModelConfig(
        name="mistral-large-3",
        context_window=128000,
        safe_budget=100000,
        growth_threshold=1000.0,
        eviction_threshold=0.75,
        token_ratio=3.5,
        supports_streaming=True,
        cost_per_1k_tokens=(0.0, 0.0),
    ),
    "mistral": ModelConfig(
        name="mistral",
        context_window=32768,  # Actual: 32,768 tokens (32K)
        safe_budget=25000,
        growth_threshold=500.0,
        eviction_threshold=0.7,
        token_ratio=4.0,
        supports_streaming=True,
        cost_per_1k_tokens=(0.0, 0.0),
    ),
    # MiniMax Models
    "minimax-m2.7": ModelConfig(
        name="minimax-m2.7",
        context_window=128000,
        safe_budget=100000,
        growth_threshold=1000.0,
        eviction_threshold=0.75,
        token_ratio=3.5,
        supports_streaming=True,
        cost_per_1k_tokens=(0.0, 0.0),
    ),
    "minimax-m2.5": ModelConfig(
        name="minimax-m2.5",
        context_window=128000,
        safe_budget=100000,
        growth_threshold=1000.0,
        eviction_threshold=0.75,
        token_ratio=3.5,
        supports_streaming=True,
        cost_per_1k_tokens=(0.0, 0.0),
    ),
    # Kimi Models
    "kimi-k2.5": ModelConfig(
        name="kimi-k2.5",
        context_window=128000,
        safe_budget=100000,
        growth_threshold=1000.0,
        eviction_threshold=0.75,
        token_ratio=3.5,
        supports_streaming=True,
        cost_per_1k_tokens=(0.0, 0.0),
    ),
    # DeepSeek Models
    "deepseek-v3.1": ModelConfig(
        name="deepseek-v3.1",
        context_window=128000,
        safe_budget=100000,
        growth_threshold=1000.0,
        eviction_threshold=0.75,
        token_ratio=3.5,
        supports_streaming=True,
        cost_per_1k_tokens=(0.0, 0.0),
    ),
    # Gemini Models (Cloud - Massive 1M context!)
    "gemini-3-flash": ModelConfig(
        name="gemini-3-flash",
        context_window=1048576,  # Actual: 1,048,576 tokens (1M!)
        safe_budget=800000,
        growth_threshold=10000.0,
        eviction_threshold=0.8,
        token_ratio=4.0,
        supports_streaming=True,
        cost_per_1k_tokens=(0.0, 0.0),
    ),
    "gemini-3-pro": ModelConfig(
        name="gemini-3-pro",
        context_window=1048576,  # Actual: 1,048,576 tokens (1M!)
        safe_budget=800000,
        growth_threshold=10000.0,
        eviction_threshold=0.8,
        token_ratio=4.0,
        supports_streaming=True,
        cost_per_1k_tokens=(0.0, 0.0),
    ),
    # CodeLlama Models
    "codellama": ModelConfig(
        name="codellama",
        context_window=16000,
        safe_budget=12000,
        growth_threshold=300.0,
        eviction_threshold=0.7,
        token_ratio=4.0,
        supports_streaming=True,
        cost_per_1k_tokens=(0.0, 0.0),
    ),
    # GPT Models (for reference)
    "gpt-4": ModelConfig(
        name="gpt-4",
        context_window=128000,
        safe_budget=100000,
        growth_threshold=1000.0,
        eviction_threshold=0.75,
        token_ratio=4.0,
        supports_streaming=True,
        cost_per_1k_tokens=(0.03, 0.06),
    ),
    "gpt-4-turbo": ModelConfig(
        name="gpt-4-turbo",
        context_window=128000,
        safe_budget=100000,
        growth_threshold=1000.0,
        eviction_threshold=0.75,
        token_ratio=4.0,
        supports_streaming=True,
        cost_per_1k_tokens=(0.01, 0.03),
    ),
    "gpt-3.5-turbo": ModelConfig(
        name="gpt-3.5-turbo",
        context_window=16000,
        safe_budget=12000,
        growth_threshold=300.0,
        eviction_threshold=0.7,
        token_ratio=4.0,
        supports_streaming=True,
        cost_per_1k_tokens=(0.0005, 0.0015),
    ),
    # Claude Models (for reference)
    "claude-3-opus": ModelConfig(
        name="claude-3-opus",
        context_window=200000,
        safe_budget=150000,
        growth_threshold=1500.0,
        eviction_threshold=0.75,
        token_ratio=3.5,
        supports_streaming=True,
        cost_per_1k_tokens=(0.015, 0.075),
    ),
    "claude-3-sonnet": ModelConfig(
        name="claude-3-sonnet",
        context_window=200000,
        safe_budget=150000,
        growth_threshold=1500.0,
        eviction_threshold=0.75,
        token_ratio=3.5,
        supports_streaming=True,
        cost_per_1k_tokens=(0.003, 0.015),
    ),
    "claude-3-haiku": ModelConfig(
        name="claude-3-haiku",
        context_window=200000,
        safe_budget=150000,
        growth_threshold=1500.0,
        eviction_threshold=0.75,
        token_ratio=3.5,
        supports_streaming=True,
        cost_per_1k_tokens=(0.00025, 0.00125),
    ),
    # Default fallback
    "default": ModelConfig(
        name="default",
        context_window=50000,
        safe_budget=40000,
        growth_threshold=500.0,
        eviction_threshold=0.7,
        token_ratio=4.0,
        supports_streaming=True,
        cost_per_1k_tokens=(0.0, 0.0),
    ),
}


def get_model_config(model_name: str, use_dyNovac: bool = True) -> ModelConfig:
    """Get configuration for a specific model.

    Looks up ``model_name`` (normalized) in the hardcoded table, trying an exact
    match then a partial match, falling back to the ``default`` config.

    Args:
        model_name: Model identifier (e.g., "glm-5", "gpt-4", "claude-3").
        use_dyNovac: Accepted for backward compatibility; the table is the
            single source of truth (window sizes are detected separately by
            :func:`novacode_cli.context._analysis.get_context_window_size`).

    Returns:
        ModelConfig for the specified model.
    """
    normalized = model_name.lower().replace("_", "-").replace(" ", "-")

    # Exact match
    if normalized in MODEL_CONFIGS:
        return MODEL_CONFIGS[normalized]

    # Partial match
    for key, config in MODEL_CONFIGS.items():
        if key in normalized or normalized in key:
            logger.info(f"Using config for {config.name} (matched {model_name})")
            return config

    logger.warning(
        f"Unknown model '{model_name}', using default config. "
        f"Available models: {list(MODEL_CONFIGS.keys())}"
    )
    return MODEL_CONFIGS["default"]

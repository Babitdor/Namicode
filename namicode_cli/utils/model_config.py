"""Model-specific configuration for context optimization.

This module provides automatic configuration for different LLM models,
including GLM-5, GPT-4, Claude-3, and others. Uses dynamic detection from
Ollama when available, with fallback to hardcoded configurations.
"""

import logging
from dataclasses import dataclass
from typing import Optional
from functools import lru_cache

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
        cost_per_1k_tokens: Cost per 1000 tokens (input/output)
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
        safe_budget=160000,  # Use ~80% of context
        growth_threshold=2000.0,  # Allow more growth for large context
        eviction_threshold=0.75,
        token_ratio=3.5,
        supports_streaming=True,
        cost_per_1k_tokens=(0.001, 0.001),  # Cloud pricing
    ),
    
    "glm-4.7": ModelConfig(
        name="glm-4.7",
        context_window=128000,  # Estimated
        safe_budget=100000,
        growth_threshold=1000.0,
        eviction_threshold=0.75,
        token_ratio=3.5,
        supports_streaming=True,
        cost_per_1k_tokens=(0.001, 0.001),
    ),
    
    "glm-4.6": ModelConfig(
        name="glm-4.6",
        context_window=128000,  # Estimated
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
        cost_per_1k_tokens=(0.0, 0.0),  # Local model
    ),
    
    # Qwen Models
    "qwen3.5": ModelConfig(
        name="qwen3.5",
        context_window=262144,  # Actual: 262,144 tokens (256K)
        safe_budget=200000,  # Use ~76% of context
        growth_threshold=2500.0,  # Allow more growth for large context
        eviction_threshold=0.75,
        token_ratio=3.5,
        supports_streaming=True,
        cost_per_1k_tokens=(0.0, 0.0),  # Cloud pricing varies
    ),
    
    "qwen3-coder": ModelConfig(
        name="qwen3-coder",
        context_window=128000,  # Estimated
        safe_budget=100000,
        growth_threshold=1000.0,
        eviction_threshold=0.75,
        token_ratio=4.0,  # Code models use more tokens
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
        cost_per_1k_tokens=(0.0, 0.0),  # Local model
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
        safe_budget=100000,  # Use ~76% of context
        growth_threshold=1000.0,
        eviction_threshold=0.75,
        token_ratio=4.0,
        supports_streaming=True,
        cost_per_1k_tokens=(0.0, 0.0),  # Local model
    ),
    
    "llama3.2": ModelConfig(
        name="llama3.2",
        context_window=131072,  # Same as llama3.1
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
        context_window=128000,  # Estimated
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
        safe_budget=25000,  # Use ~76% of context
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
        safe_budget=800000,  # Use ~76% of context
        growth_threshold=10000.0,  # Allow massive growth for 1M context
        eviction_threshold=0.8,  # Later eviction for large context
        token_ratio=4.0,
        supports_streaming=True,
        cost_per_1k_tokens=(0.0, 0.0),  # Cloud pricing varies
    ),
    
    "gemini-3-pro": ModelConfig(
        name="gemini-3-pro",
        context_window=1048576,  # Actual: 1,048,576 tokens (1M!)
        safe_budget=800000,  # Use ~76% of context
        growth_threshold=10000.0,  # Allow massive growth for 1M context
        eviction_threshold=0.8,  # Later eviction for large context
        token_ratio=4.0,
        supports_streaming=True,
        cost_per_1k_tokens=(0.0, 0.0),  # Cloud pricing varies
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


def get_model_config(model_name: str, use_dynamic: bool = True) -> ModelConfig:
    """Get configuration for a specific model.
    
    Args:
        model_name: Model identifier (e.g., "glm-5", "gpt-4", "claude-3")
        use_dynamic: Whether to use dynamic detection from Ollama (default: True)
        
    Returns:
        ModelConfig for the specified model
        
    Example:
        >>> config = get_model_config("glm-5")
        >>> print(config.context_window)
        202752  # Dynamically detected from Ollama
        
        >>> config = get_model_config("glm-5", use_dynamic=False)
        >>> print(config.context_window)
        202752  # From hardcoded config
    """
    # Normalize model name
    normalized = model_name.lower().replace("_", "-").replace(" ", "-")
    
    # Try dynamic detection first (if enabled)
    if use_dynamic:
        try:
            from .dynamic_context import get_model_config_dynamic
            
            # Get dynamic configuration
            dynamic_config = get_model_config_dynamic(model_name)
            
            if dynamic_config.get("source") == "dynamic":
                # Create ModelConfig from dynamic data
                config = ModelConfig(
                    name=dynamic_config["name"],
                    context_window=dynamic_config["context_window"],
                    safe_budget=dynamic_config["safe_budget"],
                    growth_threshold=dynamic_config["growth_threshold"],
                    eviction_threshold=dynamic_config["eviction_threshold"],
                    token_ratio=dynamic_config["token_ratio"],
                    supports_streaming=True,
                    cost_per_1k_tokens=(0.0, 0.0),
                )
                logger.info(f"Using dynamic config for {model_name}: {config.context_window:,} tokens")
                return config
        except Exception as e:
            logger.debug(f"Dynamic detection failed for {model_name}: {e}, falling back to hardcoded")
    
    # Check for exact match in hardcoded configs
    if normalized in MODEL_CONFIGS:
        return MODEL_CONFIGS[normalized]
    
    # Check for partial match
    for key, config in MODEL_CONFIGS.items():
        if key in normalized or normalized in key:
            logger.info(f"Using config for {config.name} (matched {model_name})")
            return config
    
    # Return default
    logger.warning(
        f"Unknown model '{model_name}', using default config. "
        f"Available models: {list(MODEL_CONFIGS.keys())}"
    )
    return MODEL_CONFIGS["default"]


def detect_model_from_env() -> Optional[str]:
    """Detect model from environment variables.
    
    Checks common environment variables for model configuration.
    
    Returns:
        Model name if detected, None otherwise
    """
    import os
    
    # Check common environment variables
    env_vars = [
        "OPENAI_MODEL",
        "ANTHROPIC_MODEL",
        "MODEL_NAME",
        "LLM_MODEL",
        "MODEL",
    ]
    
    for var in env_vars:
        model = os.getenv(var)
        if model:
            logger.debug(f"Detected model from {var}: {model}")
            return model
    
    return None


def get_model_config_auto(model_name: Optional[str] = None, use_dynamic: bool = True) -> ModelConfig:
    """Get model configuration with automatic detection.
    
    Args:
        model_name: Optional model name. If None, attempts auto-detection.
        use_dynamic: Whether to use dynamic detection from Ollama (default: True)
        
    Returns:
        ModelConfig for the detected or specified model
        
    Example:
        >>> # Auto-detect from environment
        >>> config = get_model_config_auto()
        
        >>> # Or specify explicitly
        >>> config = get_model_config_auto("glm-5")
        
        >>> # Use hardcoded config only
        >>> config = get_model_config_auto("glm-5", use_dynamic=False)
    """
    if model_name:
        return get_model_config(model_name, use_dynamic=use_dynamic)
    
    # Try auto-detection
    detected = detect_model_from_env()
    if detected:
        return get_model_config(detected, use_dynamic=use_dynamic)
    
    # Return default
    logger.info("No model detected, using default configuration")
    return MODEL_CONFIGS["default"]


def list_available_models() -> list[str]:
    """List all available model configurations.
    
    Returns:
        List of model names
    """
    return list(MODEL_CONFIGS.keys())


def get_model_comparison() -> dict[str, dict[str, any]]:
    """Get comparison of all model configurations.
    
    Returns:
        Dictionary comparing all models
    """
    comparison = {}
    
    for name, config in MODEL_CONFIGS.items():
        if name == "default":
            continue
            
        comparison[name] = {
            "context_window": config.context_window,
            "safe_budget": config.safe_budget,
            "growth_threshold": config.growth_threshold,
            "eviction_threshold": config.eviction_threshold,
            "token_ratio": config.token_ratio,
            "cost_per_1k_input": config.cost_per_1k_tokens[0],
            "cost_per_1k_output": config.cost_per_1k_tokens[1],
        }
    
    return comparison


def print_model_comparison():
    """Print a formatted comparison of all models."""
    comparison = get_model_comparison()
    
    print("\n" + "=" * 100)
    print("Model Configuration Comparison")
    print("=" * 100)
    print()
    
    # Header
    print(f"{'Model':<20s} {'Context':>10s} {'Budget':>10s} {'Growth':>8s} {'Evict':>7s} {'Ratio':>6s} {'Cost':>15s}")
    print("-" * 100)
    
    # Models
    for name, config in comparison.items():
        cost = f"${config['cost_per_1k_input']:.4f}/${config['cost_per_1k_output']:.4f}"
        print(
            f"{name:<20s} "
            f"{config['context_window']:>10,d} "
            f"{config['safe_budget']:>10,d} "
            f"{config['growth_threshold']:>8.0f} "
            f"{config['eviction_threshold']:>7.0%} "
            f"{config['token_ratio']:>6.1f} "
            f"{cost:>15s}"
        )
    
    print("=" * 100)
    print()


__all__ = [
    "ModelConfig",
    "MODEL_CONFIGS",
    "get_model_config",
    "detect_model_from_env",
    "get_model_config_auto",
    "list_available_models",
    "get_model_comparison",
    "print_model_comparison",
]
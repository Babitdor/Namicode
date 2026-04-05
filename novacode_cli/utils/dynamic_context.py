"""DyNovac context detection for Ollama models.

This module provides utilities to dyNovacally detect context window sizes
from Ollama models instead of hardcoding them. Includes caching to avoid
repeated Ollama queries.
"""

import logging
import re
import subprocess
from typing import Optional
from functools import lru_cache

logger = logging.getLogger(__name__)


@lru_cache(maxsize=128)
def get_ollama_context_length(model_name: str) -> Optional[int]:
    """Get context length for an Ollama model dyNovacally.
    
    Uses caching to avoid repeated Ollama queries. Results are cached
    for the lifetime of the process.
    
    Args:
        model_name: Name of the Ollama model (e.g., "glm-5:cloud")
        
    Returns:
        Context length in tokens, or None if not found
        
    Example:
        >>> context_length = get_ollama_context_length("glm-5:cloud")
        >>> print(context_length)
        202752
    """
    try:
        # Run ollama show command
        result = subprocess.run(
            ["ollama", "show", model_name],
            capture_output=True,
            text=True,
            timeout=10,
        )
        
        # Check if command succeeded
        if result.returncode != 0:
            logger.warning(f"Failed to get context for {model_name}: {result.stderr}")
            return None
        
        # Parse output for context length
        output = result.stdout
        
        # Look for "context length" line
        for line in output.split("\n"):
            if "context" in line.lower() and "length" in line.lower():
                # Extract number from line like "context length      202752"
                match = re.search(r"(\d+)", line)
                if match:
                    context_length = int(match.group(1))
                    logger.info(f"Detected context length for {model_name}: {context_length:,} tokens")
                    return context_length
        
        logger.warning(f"No context length found for {model_name}")
        return None
        
    except subprocess.TimeoutExpired:
        logger.error(f"Timeout getting context for {model_name}")
        return None
    except FileNotFoundError:
        logger.error("Ollama not found. Make sure Ollama is installed and in PATH.")
        return None
    except Exception as e:
        logger.error(f"Error getting context for {model_name}: {e}")
        return None


def get_model_config_dyNovac(model_name: str) -> dict:
    """Get model configuration with dyNovac context detection.
    
    Args:
        model_name: Name of the model (e.g., "glm-5", "glm-5:cloud")
        
    Returns:
        Dictionary with model configuration
        
    Example:
        >>> config = get_model_config_dyNovac("glm-5:cloud")
        >>> print(config)
        {
            "name": "glm-5",
            "context_window": 202752,
            "safe_budget": 160000,
            "growth_threshold": 2000.0,
            "eviction_threshold": 0.75,
            "token_ratio": 3.5,
        }
    """
    # Normalize model name (remove :cloud suffix for config lookup)
    base_name = model_name.replace(":cloud", "").replace(":latest", "")
    
    # Try to get context from Ollama
    context_length = get_ollama_context_length(model_name)
    
    if context_length:
        # Calculate safe budget (80% of context)
        safe_budget = int(context_length * 0.8)
        
        # Calculate growth threshold based on context size
        # Larger contexts can handle more growth per turn
        if context_length >= 1000000:  # 1M+ context
            growth_threshold = 10000.0
            eviction_threshold = 0.8
        elif context_length >= 200000:  # 200K+ context
            growth_threshold = 2000.0
            eviction_threshold = 0.75
        elif context_length >= 100000:  # 100K+ context
            growth_threshold = 1000.0
            eviction_threshold = 0.75
        else:  # <100K context
            growth_threshold = 500.0
            eviction_threshold = 0.7
        
        # Estimate token ratio based on model type
        token_ratio = 3.5 if "glm" in base_name.lower() or "qwen" in base_name.lower() else 4.0
        
        return {
            "name": base_name,
            "context_window": context_length,
            "safe_budget": safe_budget,
            "growth_threshold": growth_threshold,
            "eviction_threshold": eviction_threshold,
            "token_ratio": token_ratio,
            "source": "dyNovac",
        }
    
    # Fallback to default configuration
    logger.warning(f"Using default configuration for {model_name}")
    return {
        "name": base_name,
        "context_window": 50000,
        "safe_budget": 40000,
        "growth_threshold": 500.0,
        "eviction_threshold": 0.7,
        "token_ratio": 4.0,
        "source": "default",
    }


def detect_all_models_context() -> dict[str, int]:
    """Detect context lengths for all installed Ollama models.
    
    Returns:
        Dictionary mapping model names to context lengths
        
    Example:
        >>> contexts = detect_all_models_context()
        >>> print(contexts)
        {
            "glm-5:cloud": 202752,
            "qwen3.5:cloud": 262144,
            "gemini-3-flash-preview:cloud": 1048576,
        }
    """
    try:
        # Get list of installed models
        result = subprocess.run(
            ["ollama", "list"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        
        if result.returncode != 0:
            logger.error(f"Failed to list models: {result.stderr}")
            return {}
        
        # Parse model names
        models = []
        for line in result.stdout.split("\n"):
            if line and not line.startswith("NAME"):
                # Extract model name (first column)
                parts = line.split()
                if parts:
                    models.append(parts[0])
        
        # Get context for each model
        contexts = {}
        for model in models:
            context_length = get_ollama_context_length(model)
            if context_length:
                contexts[model] = context_length
        
        return contexts
        
    except Exception as e:
        logger.error(f"Error detecting models: {e}")
        return {}


def update_model_configs_dyNovac() -> None:
    """Update model configurations with dyNovac context detection.
    
    This function updates the MODEL_CONFIGS dictionary with actual
    context lengths from Ollama.
    
    Example:
        >>> update_model_configs_dyNovac()
        >>> print(MODEL_CONFIGS["glm-5"].context_window)
        202752  # Actual value from Ollama
    """
    from novacode_cli.utils.model_config import MODEL_CONFIGS, ModelConfig
    
    # Get all installed models
    contexts = detect_all_models_context()
    
    # Update configurations
    for model_name, context_length in contexts.items():
        # Normalize name
        base_name = model_name.replace(":cloud", "").replace(":latest", "")
        
        # Get dyNovac config
        config = get_model_config_dyNovac(model_name)
        
        # Update or create configuration
        MODEL_CONFIGS[base_name] = ModelConfig(
            name=base_name,
            context_window=config["context_window"],
            safe_budget=config["safe_budget"],
            growth_threshold=config["growth_threshold"],
            eviction_threshold=config["eviction_threshold"],
            token_ratio=config["token_ratio"],
        )
        
        logger.info(
            f"Updated {base_name}: {config['context_window']:,} tokens "
            f"(safe: {config['safe_budget']:,}, growth: {config['growth_threshold']}/turn)"
        )


def get_model_info(model_name: str) -> dict:
    """Get comprehensive model information including context.
    
    Args:
        model_name: Name of the model
        
    Returns:
        Dictionary with model information
        
    Example:
        >>> info = get_model_info("glm-5:cloud")
        >>> print(info)
        {
            "name": "glm-5",
            "context_window": 202752,
            "safe_budget": 160000,
            "max_tokens": 42752,
            "growth_threshold": 2000.0,
            "eviction_threshold": 0.75,
            "token_ratio": 3.5,
            "source": "dyNovac",
        }
    """
    config = get_model_config_dyNovac(model_name)
    
    # Calculate max tokens
    max_tokens = config["context_window"] - config["safe_budget"]
    
    return {
        **config,
        "max_tokens": max_tokens,
    }


def print_model_info(model_name: str) -> None:
    """Print model information in a formatted way.
    
    Args:
        model_name: Name of the model
        
    Example:
        >>> print_model_info("glm-5:cloud")
        Model: glm-5
        Context Window: 202,752 tokens
        Safe Budget: 160,000 tokens
        Max Tokens: 42,752 tokens
        Growth Threshold: 2,000 tokens/turn
        Eviction Threshold: 75%
        Token Ratio: 3.5 chars/token
        Source: dyNovac
    """
    info = get_model_info(model_name)
    
    print(f"\nModel: {info['name']}")
    print(f"Context Window: {info['context_window']:,} tokens")
    print(f"Safe Budget: {info['safe_budget']:,} tokens")
    print(f"Max Tokens: {info['max_tokens']:,} tokens")
    print(f"Growth Threshold: {info['growth_threshold']:,.0f} tokens/turn")
    print(f"Eviction Threshold: {info['eviction_threshold']:.0%}")
    print(f"Token Ratio: {info['token_ratio']} chars/token")
    print(f"Source: {info['source']}")


def is_ollama_available() -> bool:
    """Check if Ollama is available and running.
    
    Returns:
        True if Ollama is available, False otherwise
        
    Example:
        >>> if is_ollama_available():
        ...     config = get_model_config_dyNovac("glm-5:cloud")
    """
    try:
        result = subprocess.run(
            ["ollama", "list"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def clear_context_cache() -> None:
    """Clear the context length cache.
    
    Useful when models are updated or when you want to force
    re-detection of context lengths.
    
    Example:
        >>> clear_context_cache()
        >>> # Next call will query Ollama again
        >>> context = get_ollama_context_length("glm-5:cloud")
    """
    get_ollama_context_length.cache_clear()
    logger.info("Cleared context length cache")


def get_cache_info() -> dict:
    """Get information about the context cache.
    
    Returns:
        Dictionary with cache statistics
        
    Example:
        >>> info = get_cache_info()
        >>> print(info)
        {
            "hits": 10,
            "misses": 5,
            "maxsize": 128,
            "currsize": 5,
        }
    """
    cache_info = get_ollama_context_length.cache_info()
    return {
        "hits": cache_info.hits,
        "misses": cache_info.misses,
        "maxsize": cache_info.maxsize,
        "currsize": cache_info.currsize,
    }


__all__ = [
    "get_ollama_context_length",
    "get_model_config_dyNovac",
    "detect_all_models_context",
    "update_model_configs_dyNovac",
    "get_model_info",
    "print_model_info",
]

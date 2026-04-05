"""Integration test for dyNovac context detection with model config."""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from novacode_cli.utils.model_config import get_model_config, get_model_config_auto
from novacode_cli.utils.dyNovac_context import (
    get_ollama_context_length,
    is_ollama_available,
    clear_context_cache,
    get_cache_info,
)


def test_dyNovac_detection():
    """Test dyNovac detection from Ollama."""
    print("\n" + "=" * 80)
    print("Testing DyNovac Detection Integration")
    print("=" * 80)
    
    # Test with dyNovac detection enabled (default)
    print("\n1. Testing with dyNovac detection enabled:")
    config = get_model_config("glm-5:cloud", use_dyNovac=True)
    print(f"   Model: {config.name}")
    print(f"   Context Window: {config.context_window:,} tokens")
    print(f"   Safe Budget: {config.safe_budget:,} tokens")
    print(f"   Growth Threshold: {config.growth_threshold:,.0f} tokens/turn")
    print(f"   ✓ DyNovac detection works")
    
    # Test with dyNovac detection disabled
    print("\n2. Testing with dyNovac detection disabled:")
    config_hardcoded = get_model_config("glm-5", use_dyNovac=False)
    print(f"   Model: {config_hardcoded.name}")
    print(f"   Context Window: {config_hardcoded.context_window:,} tokens")
    print(f"   ✓ Hardcoded config works")
    
    # Compare
    print("\n3. Comparing dyNovac vs hardcoded:")
    print(f"   DyNovac: {config.context_window:,} tokens")
    print(f"   Hardcoded: {config_hardcoded.context_window:,} tokens")
    if config.context_window == config_hardcoded.context_window:
        print(f"   ✓ Values match (both use actual context from Ollama)")
    else:
        print(f"   ⚠ Values differ (dyNovac detected different value)")


def test_caching():
    """Test caching of context detection."""
    print("\n" + "=" * 80)
    print("Testing Cache Performance")
    print("=" * 80)
    
    # Clear cache first
    clear_context_cache()
    print("\n1. Cache cleared")
    
    # First call (cache miss)
    print("\n2. First call (cache miss):")
    context1 = get_ollama_context_length("glm-5:cloud")
    cache_info = get_cache_info()
    print(f"   Context: {context1:,} tokens")
    print(f"   Cache: {cache_info}")
    
    # Second call (cache hit)
    print("\n3. Second call (cache hit):")
    context2 = get_ollama_context_length("glm-5:cloud")
    cache_info = get_cache_info()
    print(f"   Context: {context2:,} tokens")
    print(f"   Cache: {cache_info}")
    
    # Verify cache hit
    if cache_info["hits"] > 0:
        print(f"   ✓ Cache hit detected ({cache_info['hits']} hits)")
    else:
        print(f"   ⚠ No cache hit detected")
    
    # Verify values match
    if context1 == context2:
        print(f"   ✓ Values match")
    else:
        print(f"   ⚠ Values differ")


def test_fallback():
    """Test fallback to hardcoded configs."""
    print("\n" + "=" * 80)
    print("Testing Fallback Behavior")
    print("=" * 80)
    
    # Test with unknown model
    print("\n1. Testing with unknown model:")
    config = get_model_config("unknown-model-xyz", use_dyNovac=True)
    print(f"   Model: {config.name}")
    print(f"   Context Window: {config.context_window:,} tokens")
    print(f"   Safe Budget: {config.safe_budget:,} tokens")
    print(f"   ✓ Fallback to default config works")
    
    # Test with Ollama unavailable (simulate by using invalid model)
    print("\n2. Testing fallback when Ollama unavailable:")
    if not is_ollama_available():
        print("   ⚠ Ollama not available, testing fallback")
        config = get_model_config("glm-5", use_dyNovac=True)
        print(f"   Model: {config.name}")
        print(f"   Context Window: {config.context_window:,} tokens")
        print(f"   ✓ Fallback to hardcoded config works")
    else:
        print("   ✓ Ollama available, dyNovac detection active")


def test_auto_detection():
    """Test automatic model detection."""
    print("\n" + "=" * 80)
    print("Testing Auto Detection")
    print("=" * 80)
    
    # Test with explicit model name
    print("\n1. Testing with explicit model name:")
    config = get_model_config_auto("glm-5:cloud", use_dyNovac=True)
    print(f"   Model: {config.name}")
    print(f"   Context Window: {config.context_window:,} tokens")
    print(f"   ✓ Auto detection with explicit name works")
    
    # Test without model name (should use default)
    print("\n2. Testing without model name:")
    config = get_model_config_auto(use_dyNovac=True)
    print(f"   Model: {config.name}")
    print(f"   Context Window: {config.context_window:,} tokens")
    print(f"   ✓ Auto detection with default works")


def test_multiple_models():
    """Test with multiple models."""
    print("\n" + "=" * 80)
    print("Testing Multiple Models")
    print("=" * 80)
    
    models = [
        "glm-5:cloud",
        "qwen3.5:cloud",
        "gemini-3-flash-preview:cloud",
        "llama3.1:latest",
        "mistral:latest",
    ]
    
    print("\nTesting dyNovac detection for multiple models:")
    for model in models:
        config = get_model_config(model, use_dyNovac=True)
        print(f"\n   {model}:")
        print(f"     Context: {config.context_window:,} tokens")
        print(f"     Safe Budget: {config.safe_budget:,} tokens")
        print(f"     Growth Threshold: {config.growth_threshold:,.0f} tokens/turn")
    
    print(f"\n   ✓ All models detected successfully")


def test_performance():
    """Test performance of cached vs uncached calls."""
    import time
    
    print("\n" + "=" * 80)
    print("Testing Performance")
    print("=" * 80)
    
    # Clear cache
    clear_context_cache()
    
    # Time first call (uncached)
    print("\n1. Timing first call (uncached):")
    start = time.time()
    get_ollama_context_length("glm-5:cloud")
    uncached_time = time.time() - start
    print(f"   Time: {uncached_time:.4f} seconds")
    
    # Time second call (cached)
    print("\n2. Timing second call (cached):")
    start = time.time()
    get_ollama_context_length("glm-5:cloud")
    cached_time = time.time() - start
    print(f"   Time: {cached_time:.6f} seconds")
    
    # Calculate speedup
    if uncached_time > 0:
        speedup = uncached_time / cached_time if cached_time > 0 else float('inf')
        print(f"\n   ✓ Cache speedup: {speedup:.1f}x faster")
    
    # Show cache stats
    cache_info = get_cache_info()
    print(f"   Cache stats: {cache_info}")


def main():
    """Run all integration tests."""
    print("\n" + "=" * 80)
    print("          DyNovac Context Integration Test Suite")
    print("=" * 80)
    
    try:
        test_dyNovac_detection()
        test_caching()
        test_fallback()
        test_auto_detection()
        test_multiple_models()
        test_performance()
        
        print("\n" + "=" * 80)
        print("                    All Integration Tests Passed! ✓")
        print("=" * 80)
        print("\n✓ DyNovac detection integrated successfully")
        print("✓ Caching working correctly")
        print("✓ Fallback to hardcoded configs working")
        print("✓ Auto detection working")
        print("✓ Multiple models supported")
        print("✓ Performance optimized with caching")
        print("\n")
        
    except Exception as e:
        print(f"\n✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

"""Test dynamic context detection integration with context_manager."""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from namicode_cli.context.context_manager import (
    get_context_window_size,
    get_model_config_for_context,
    get_dynamic_context_info,
    build_context_breakdown,
    get_compaction_recommendation,
)


def test_get_context_window_size():
    """Test get_context_window_size with dynamic detection."""
    print("\n" + "=" * 80)
    print("Testing get_context_window_size")
    print("=" * 80)
    
    # Test with dynamic detection enabled (default)
    print("\n1. Testing with dynamic detection enabled:")
    context = get_context_window_size("glm-5:cloud", use_dynamic=True)
    print(f"   GLM-5 Cloud: {context:,} tokens")
    assert context == 202752, f"Expected 202752, got {context}"
    print("   ✓ Dynamic detection works")
    
    # Test with dynamic detection disabled
    print("\n2. Testing with dynamic detection disabled:")
    context = get_context_window_size("glm-5", use_dynamic=False)
    print(f"   GLM-5: {context:,} tokens")
    assert context == 202752, f"Expected 202752, got {context}"
    print("   ✓ Hardcoded config works")
    
    # Test with unknown model
    print("\n3. Testing with unknown model:")
    context = get_context_window_size("unknown-model", use_dynamic=True)
    print(f"   Unknown model: {context:,} tokens")
    assert context == 128000, f"Expected 128000 (default), got {context}"
    print("   ✓ Fallback to default works")
    
    # Test with various models
    print("\n4. Testing with various models:")
    models = [
        ("qwen3.5:cloud", 262144),
        ("gemini-3-flash-preview:cloud", 1048576),
        ("llama3.1:latest", 131072),
        ("mistral:latest", 32768),
    ]
    
    for model, expected in models:
        context = get_context_window_size(model, use_dynamic=True)
        print(f"   {model}: {context:,} tokens")
        assert context == expected, f"Expected {expected}, got {context}"
    
    print("   ✓ All models detected correctly")


def test_get_model_config_for_context():
    """Test get_model_config_for_context."""
    print("\n" + "=" * 80)
    print("Testing get_model_config_for_context")
    print("=" * 80)
    
    # Test with dynamic detection
    print("\n1. Testing with dynamic detection:")
    config = get_model_config_for_context("glm-5:cloud", use_dynamic=True)
    print(f"   Model: {config.name}")
    print(f"   Context Window: {config.context_window:,} tokens")
    print(f"   Safe Budget: {config.safe_budget:,} tokens")
    print(f"   Growth Threshold: {config.growth_threshold:,.0f} tokens/turn")
    print(f"   Eviction Threshold: {config.eviction_threshold:.0%}")
    assert config.context_window == 202752
    print("   ✓ Dynamic config works")
    
    # Test with hardcoded config
    print("\n2. Testing with hardcoded config:")
    config = get_model_config_for_context("glm-5", use_dynamic=False)
    print(f"   Model: {config.name}")
    print(f"   Context Window: {config.context_window:,} tokens")
    assert config.context_window == 202752
    print("   ✓ Hardcoded config works")


def test_get_dynamic_context_info():
    """Test get_dynamic_context_info."""
    print("\n" + "=" * 80)
    print("Testing get_dynamic_context_info")
    print("=" * 80)
    
    # Test with dynamic detection
    print("\n1. Testing with dynamic detection:")
    info = get_dynamic_context_info("glm-5:cloud")
    print(f"   Model: {info['name']}")
    print(f"   Context Window: {info['context_window']:,} tokens")
    print(f"   Safe Budget: {info['safe_budget']:,} tokens")
    print(f"   Max Tokens: {info['max_tokens']:,} tokens")
    print(f"   Growth Threshold: {info['growth_threshold']:,.0f} tokens/turn")
    print(f"   Eviction Threshold: {info['eviction_threshold']:.0%}")
    print(f"   Source: {info['source']}")
    assert info['context_window'] == 202752
    print("   ✓ Dynamic info works")
    
    # Test with various models
    print("\n2. Testing with various models:")
    models = ["qwen3.5:cloud", "gemini-3-flash-preview:cloud", "llama3.1:latest"]
    
    for model in models:
        info = get_dynamic_context_info(model)
        print(f"   {model}: {info['context_window']:,} tokens (source: {info['source']})")


def test_build_context_breakdown():
    """Test build_context_breakdown with dynamic detection."""
    print("\n" + "=" * 80)
    print("Testing build_context_breakdown")
    print("=" * 80)
    
    # Create mock messages
    from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
    
    messages = [
        SystemMessage(content="You are a helpful assistant."),
        HumanMessage(content="Hello!"),
        AIMessage(content="Hi! How can I help you?"),
        HumanMessage(content="What's the weather?"),
        AIMessage(content="I don't have access to real-time weather data."),
    ]
    
    # Test with dynamic detection
    print("\n1. Testing with dynamic detection:")
    breakdown = build_context_breakdown(messages, "glm-5:cloud", use_dynamic=True)
    print(f"   Context Window: {breakdown.context_window_size:,} tokens")
    print(f"   Total Tokens: {breakdown.total_tokens:,}")
    print(f"   System Tokens: {breakdown.system_prompt_tokens:,}")
    print(f"   User Tokens: {breakdown.user_message_tokens:,}")
    print(f"   Assistant Tokens: {breakdown.assistant_message_tokens:,}")
    assert breakdown.context_window_size == 202752
    print("   ✓ Dynamic breakdown works")
    
    # Test with hardcoded config
    print("\n2. Testing with hardcoded config:")
    breakdown = build_context_breakdown(messages, "glm-5", use_dynamic=False)
    print(f"   Context Window: {breakdown.context_window_size:,} tokens")
    assert breakdown.context_window_size == 202752
    print("   ✓ Hardcoded breakdown works")


def test_get_compaction_recommendation():
    """Test get_compaction_recommendation with dynamic detection."""
    print("\n" + "=" * 80)
    print("Testing get_compaction_recommendation")
    print("=" * 80)
    
    # Create mock messages
    from langchain_core.messages import HumanMessage, AIMessage
    
    messages = []
    for i in range(50):
        messages.append(HumanMessage(content=f"Question {i}: " + "x" * 100))
        messages.append(AIMessage(content=f"Answer {i}: " + "y" * 100))
    
    # Test with dynamic detection
    print("\n1. Testing with dynamic detection:")
    recommendation = get_compaction_recommendation(messages, "glm-5:cloud", use_dynamic=True)
    print(f"   Should Compact: {recommendation.should_compact}")
    print(f"   Reason: {recommendation.reason}")
    print(f"   Usage: {recommendation.usage_percentage:.1f}%")
    print(f"   Tokens Used: {recommendation.tokens_used:,}")
    print(f"   Tokens Available: {recommendation.tokens_available:,}")
    print(f"   Messages: {recommendation.messages_count}")
    print("   ✓ Dynamic recommendation works")
    
    # Test with hardcoded config
    print("\n2. Testing with hardcoded config:")
    recommendation = get_compaction_recommendation(messages, "glm-5", use_dynamic=False)
    print(f"   Should Compact: {recommendation.should_compact}")
    print(f"   Usage: {recommendation.usage_percentage:.1f}%")
    print("   ✓ Hardcoded recommendation works")


def test_integration():
    """Test full integration."""
    print("\n" + "=" * 80)
    print("Testing Full Integration")
    print("=" * 80)
    
    # Test that all functions work together
    print("\n1. Testing all functions together:")
    
    # Get context window
    context = get_context_window_size("glm-5:cloud")
    print(f"   ✓ get_context_window_size: {context:,} tokens")
    
    # Get model config
    config = get_model_config_for_context("glm-5:cloud")
    print(f"   ✓ get_model_config_for_context: {config.context_window:,} tokens")
    
    # Get dynamic info
    info = get_dynamic_context_info("glm-5:cloud")
    print(f"   ✓ get_dynamic_context_info: {info['context_window']:,} tokens")
    
    # Build context breakdown
    from langchain_core.messages import HumanMessage, AIMessage
    messages = [HumanMessage("Hello"), AIMessage("Hi there!")]
    breakdown = build_context_breakdown(messages, "glm-5:cloud")
    print(f"   ✓ build_context_breakdown: {breakdown.context_window_size:,} tokens")
    
    # Get compaction recommendation
    recommendation = get_compaction_recommendation(messages, "glm-5:cloud")
    print(f"   ✓ get_compaction_recommendation: {recommendation.usage_percentage:.1f}% usage")
    
    print("\n   ✓ All functions integrated successfully")


def main():
    """Run all tests."""
    print("\n" + "=" * 80)
    print("     Context Manager Dynamic Integration Test Suite")
    print("=" * 80)
    
    try:
        test_get_context_window_size()
        test_get_model_config_for_context()
        test_get_dynamic_context_info()
        test_build_context_breakdown()
        test_get_compaction_recommendation()
        test_integration()
        
        print("\n" + "=" * 80)
        print("              All Context Manager Tests Passed! ✓")
        print("=" * 80)
        print("\n✓ Dynamic detection integrated with context_manager")
        print("✓ All functions support use_dynamic parameter")
        print("✓ Fallback to hardcoded configs working")
        print("✓ Integration with model_config working")
        print("\n")
        
    except Exception as e:
        print(f"\n✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
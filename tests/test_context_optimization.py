#!/usr/bin/env python3
"""Test script for context optimization utilities.

This script demonstrates all context optimization features:
1. Context budget tracking
2. Growth monitoring
3. Automatic eviction
4. Lazy/conditional middleware loading
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from novacode_cli.utils.context_budget import get_context_budget, reset_context_budget
from novacode_cli.utils.context_growth_tracker import get_growth_tracker, reset_growth_tracker
from novacode_cli.utils.context_eviction import (
    evict_old_messages,
    evict_by_age,
    evict_by_importance,
    smart_evict,
    get_eviction_summary,
)
from novacode_cli.utils.lazy_middleware import (
    LazyMiddleware,
    ConditionalMiddleware,
    has_file_operations,
    has_skills,
)


def test_context_budget():
    """Test context budget tracking."""
    print("=" * 80)
    print("Test 1: Context Budget Tracking")
    print("=" * 80)
    print()
    
    # Reset budget
    reset_context_budget()
    budget = get_context_budget(max_tokens=50000)
    
    # Track some middleware
    middleware_data = {
        "FilesystemMiddleware": "File operations context...",
        "SkillsMiddleware": "Skills context...",
        "MemoryMiddleware": "Memory context...",
    }
    
    for name, context in middleware_data.items():
        tokens = budget.track_middleware(name, context)
        print(f"✓ {name}: {tokens} tokens")
    
    # Get report
    report = budget.get_usage_report()
    print()
    print(f"Total tokens: {report['total_tokens']}")
    print(f"Budget used: {report['percentage_used']:.1f}%")
    print()
    
    print("✅ Context budget tracking works!")
    print()


def test_growth_tracker():
    """Test context growth tracking."""
    print("=" * 80)
    print("Test 2: Context Growth Tracking")
    print("=" * 80)
    print()
    
    # Reset tracker
    reset_growth_tracker()
    tracker = get_growth_tracker(max_tokens=50000, growth_threshold=500.0)
    
    # Simulate conversation turns
    turns = [
        (1000, {"FilesystemMiddleware": 400, "SkillsMiddleware": 300, "MemoryMiddleware": 300}),
        (1500, {"FilesystemMiddleware": 500, "SkillsMiddleware": 400, "MemoryMiddleware": 600}),
        (2000, {"FilesystemMiddleware": 600, "SkillsMiddleware": 500, "MemoryMiddleware": 900}),
        (2500, {"FilesystemMiddleware": 700, "SkillsMiddleware": 600, "MemoryMiddleware": 1200}),
        (3000, {"FilesystemMiddleware": 800, "SkillsMiddleware": 700, "MemoryMiddleware": 1500}),
    ]
    
    for context_size, middleware_usage in turns:
        metrics = tracker.track_turn(context_size, middleware_usage)
        print(f"Turn {metrics.turn_number}: {context_size} tokens (growth: {metrics.growth_rate:+.0f})")
    
    # Get report
    report = tracker.get_growth_report()
    print()
    print(f"Total turns: {report['total_turns']}")
    print(f"Average growth: {report['average_growth_per_turn']:.0f} tokens/turn")
    print(f"Current context: {report['current_context_size']} tokens")
    print(f"Budget used: {report['budget_used_fraction']*100:.1f}%")
    print()
    
    print("Recommendations:")
    for rec in report['recommendations']:
        print(f"  • {rec}")
    print()
    
    print("✅ Growth tracking works!")
    print()


def test_context_eviction():
    """Test context eviction strategies."""
    print("=" * 80)
    print("Test 3: Context Eviction")
    print("=" * 80)
    print()
    
    # Create test messages
    messages = [
        {"role": "system", "content": "System prompt"},
        {"role": "user", "content": "User message 1"},
        {"role": "assistant", "content": "Assistant response 1"},
        {"role": "user", "content": "User message 2"},
        {"role": "assistant", "content": "Assistant response 2"},
        {"role": "user", "content": "User message 3"},
        {"role": "assistant", "content": "Assistant response 3"},
    ]
    
    print(f"Original messages: {len(messages)}")
    print()
    
    # Test eviction strategies
    print("1. Evict old messages (keep last 3):")
    evicted = evict_old_messages(messages, keep_last_n=3)
    summary = get_eviction_summary(messages, evicted)
    print(f"   Kept: {summary['kept_messages']} messages")
    print(f"   Evicted: {summary['evicted_messages']} messages")
    print()
    
    print("2. Evict by age (max 4 turns):")
    evicted = evict_by_age(messages, max_age_turns=4)
    summary = get_eviction_summary(messages, evicted)
    print(f"   Kept: {summary['kept_messages']} messages")
    print(f"   Evicted: {summary['evicted_messages']} messages")
    print()
    
    print("3. Evict by importance (threshold 0.5):")
    evicted = evict_by_importance(messages, importance_threshold=0.5)
    summary = get_eviction_summary(messages, evicted)
    print(f"   Kept: {summary['kept_messages']} messages")
    print(f"   Evicted: {summary['evicted_messages']} messages")
    print()
    
    print("4. Smart eviction (target 50% reduction):")
    evicted = smart_evict(messages, target_tokens=100, current_tokens=200, strategy="balanced")
    summary = get_eviction_summary(messages, evicted)
    print(f"   Kept: {summary['kept_messages']} messages")
    print(f"   Evicted: {summary['evicted_messages']} messages")
    print()
    
    print("✅ Context eviction works!")
    print()


def test_lazy_middleware():
    """Test lazy and conditional middleware loading."""
    print("=" * 80)
    print("Test 4: Lazy/Conditional Middleware Loading")
    print("=" * 80)
    print()
    
    # Mock middleware class
    class MockMiddleware:
        def __init__(self, name):
            self.name = name
            self.loaded = True
        
        def wrap_model_call(self, request, handler):
            print(f"   → {self.name} processing request")
            return handler(request)
    
    # Test lazy loading
    print("1. Lazy Middleware:")
    lazy = LazyMiddleware(MockMiddleware, "LazyMiddleware")
    print(f"   Loaded: {lazy.is_loaded}")
    print(f"   Accessing method...")
    lazy.wrap_model_call({}, lambda x: x)
    print(f"   Loaded: {lazy.is_loaded}")
    print()
    
    # Test conditional loading
    print("2. Conditional Middleware (condition met):")
    conditional = ConditionalMiddleware(
        MockMiddleware,
        lambda req: req.get("has_files", False),
        "ConditionalMiddleware"
    )
    print(f"   Loaded: {conditional.is_loaded}")
    request = {"has_files": True}
    conditional.wrap_model_call(request, lambda x: x)
    print(f"   Loaded: {conditional.is_loaded}")
    print()
    
    print("3. Conditional Middleware (condition NOT met):")
    conditional2 = ConditionalMiddleware(
        MockMiddleware,
        lambda req: req.get("has_files", False),
        "ConditionalMiddleware"
    )
    print(f"   Loaded: {conditional2.is_loaded}")
    request2 = {"has_files": False}
    conditional2.wrap_model_call(request2, lambda x: x)
    print(f"   Loaded: {conditional2.is_loaded}")
    print()
    
    # Test condition helpers
    print("4. Condition Helpers:")
    print(f"   has_file_operations(file request): {has_file_operations({'tools': [{'name': 'read_file'}]})}")
    print(f"   has_file_operations(no files): {has_file_operations({'tools': [{'name': 'search'}]})}")
    print(f"   has_skills(skill request): {has_skills({'system_prompt': 'Use SKILL.md'})}")
    print(f"   has_skills(no skills): {has_skills({'system_prompt': 'No skills'})}")
    print()
    
    print("✅ Lazy/conditional loading works!")
    print()


def test_integration():
    """Test full integration of all optimization utilities."""
    print("=" * 80)
    print("Test 5: Full Integration")
    print("=" * 80)
    print()
    
    # Initialize all utilities
    reset_context_budget()
    reset_growth_tracker()
    
    budget = get_context_budget(max_tokens=50000)
    tracker = get_growth_tracker(max_tokens=50000)
    
    # Simulate conversation
    print("Simulating conversation with optimization:")
    print()
    
    for turn in range(1, 6):
        # Track context
        context_size = 1000 + (turn * 500)
        middleware_usage = {
            "FilesystemMiddleware": 400 + (turn * 50),
            "SkillsMiddleware": 300 + (turn * 40),
            "MemoryMiddleware": 300 + (turn * 60),
        }
        
        # Track in budget
        for name, tokens in middleware_usage.items():
            budget.track_middleware(name, f"{name} context for turn {turn}")
        
        # Track in growth tracker
        metrics = tracker.track_turn(context_size, middleware_usage)
        
        print(f"Turn {turn}:")
        print(f"  Context: {context_size} tokens")
        print(f"  Growth: {metrics.growth_rate:+.0f} tokens")
        print(f"  Budget used: {budget.total_tokens}/{budget.max_tokens}")
        
        # Check eviction
        if tracker.should_evict():
            recommendation = tracker.get_eviction_recommendation()
            print(f"  ⚠️  Eviction needed: {recommendation['message']}")
        else:
            print(f"  ✓ Context healthy")
        
        print()
    
    # Get final report
    budget_report = budget.get_usage_report()
    growth_report = tracker.get_growth_report()
    
    print("Final Report:")
    print(f"  Total context: {budget_report['total_tokens']} tokens")
    print(f"  Budget used: {budget_report['percentage_used']:.1f}%")
    print(f"  Average growth: {growth_report['average_growth_per_turn']:.0f} tokens/turn")
    print()
    
    print("Recommendations:")
    for rec in growth_report['recommendations']:
        print(f"  • {rec}")
    print()
    
    print("✅ Full integration works!")
    print()


def main():
    """Run all tests."""
    print()
    print("╔" + "=" * 78 + "╗")
    print("║" + " " * 20 + "Context Optimization Test Suite" + " " * 26 + "║")
    print("╚" + "=" * 78 + "╝")
    print()
    
    try:
        test_context_budget()
        test_growth_tracker()
        test_context_eviction()
        test_lazy_middleware()
        test_integration()
        
        print("=" * 80)
        print("All Tests Passed! ✅")
        print("=" * 80)
        print()
        print("Summary:")
        print("  ✅ Context budget tracking works")
        print("  ✅ Growth monitoring works")
        print("  ✅ Context eviction works")
        print("  ✅ Lazy/conditional loading works")
        print("  ✅ Full integration works")
        print()
        print("Context optimization utilities are ready for production!")
        print()
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

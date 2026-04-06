"""Tests for context optimization utilities."""

from langchain_core.messages import HumanMessage
from nova_deepagents.utils.complexity import TaskComplexityAnalyzer
from nova_deepagents.utils.prompt_compression import PromptCompressor
from nova_deepagents.utils.dynamic_middleware import DynamicMiddlewareSelector, MiddlewareProfile


def test_complexity_analyzer():
    """Test task complexity analysis."""
    print("=" * 80)
    print("Testing TaskComplexityAnalyzer")
    print("=" * 80)
    
    # Test simple task
    simple_messages = [HumanMessage(content="What is the capital of France?")]
    analysis = TaskComplexityAnalyzer.analyze(simple_messages)
    print(f"\nSimple task: 'What is the capital of France?'")
    print(f"  Needs todo: {analysis['needs_todo']}")
    print(f"  Needs planning: {analysis['needs_planning']}")
    print(f"  Needs filesystem: {analysis['needs_filesystem']}")
    print(f"  Needs subagents: {analysis['needs_subagents']}")
    assert not analysis['needs_todo'], "Simple query should not need todo"
    assert not analysis['needs_planning'], "Simple query should not need planning"
    
    # Test complex task
    complex_messages = [HumanMessage(content="Implement a user authentication system with OAuth2, JWT tokens, and role-based access control. First, design the architecture, then implement the backend, and finally create the frontend integration.")]
    analysis = TaskComplexityAnalyzer.analyze(complex_messages)
    print(f"\nComplex task: 'Implement a user authentication system...'")
    print(f"  Needs todo: {analysis['needs_todo']}")
    print(f"  Needs planning: {analysis['needs_planning']}")
    print(f"  Needs filesystem: {analysis['needs_filesystem']}")
    print(f"  Needs subagents: {analysis['needs_subagents']}")
    assert analysis['needs_todo'], "Complex implementation should need todo"
    assert analysis['needs_planning'], "Complex implementation should need planning"
    
    # Test research task
    research_messages = [HumanMessage(content="Research the best practices for microservices architecture and compare different approaches.")]
    analysis = TaskComplexityAnalyzer.analyze(research_messages)
    print(f"\nResearch task: 'Research the best practices...'")
    print(f"  Needs todo: {analysis['needs_todo']}")
    print(f"  Needs planning: {analysis['needs_planning']}")
    print(f"  Needs filesystem: {analysis['needs_filesystem']}")
    print(f"  Needs subagents: {analysis['needs_subagents']}")
    assert analysis['needs_subagents'], "Research task should need subagents"
    
    print("\n✓ All complexity analyzer tests passed")


def test_prompt_compressor():
    """Test prompt compression."""
    print("\n" + "=" * 80)
    print("Testing PromptCompressor")
    print("=" * 80)
    
    # Test redundant phrase removal
    original = "Please note that it is important to remember that you should use this tool to read files from the filesystem."
    compressed = PromptCompressor.compress_prompt(original, compression_level='medium')
    print(f"\nOriginal: {original}")
    print(f"Compressed: {compressed}")
    savings = PromptCompressor.estimate_token_savings(original, compressed)
    print(f"Savings: {savings['savings']} tokens ({savings['savings_percentage']:.1f}%)")
    assert len(compressed) < len(original), "Compressed should be shorter"
    
    # Test simplification
    original = "In order to complete the task, you need to read the file."
    compressed = PromptCompressor.compress_prompt(original, compression_level='medium')
    print(f"\nOriginal: {original}")
    print(f"Compressed: {compressed}")
    assert "In order to" not in compressed, "Should simplify 'In order to'"
    
    # Test tool description compression
    tool_desc = "This tool allows you to read files from the filesystem. It is useful for examining code, configuration files, and documentation."
    compressed_desc = PromptCompressor.compress_tool_description(tool_desc, compression_level='medium')
    print(f"\nOriginal tool desc: {tool_desc}")
    print(f"Compressed tool desc: {compressed_desc}")
    assert len(compressed_desc) < len(tool_desc), "Tool description should be shorter"
    
    # Test aggressive compression
    original = "The information specification documentation for the application environment configuration."
    compressed = PromptCompressor.compress_prompt(original, compression_level='aggressive')
    print(f"\nOriginal (aggressive): {original}")
    print(f"Compressed (aggressive): {compressed}")
    # Should use abbreviations
    assert "info" in compressed.lower() or "spec" in compressed.lower() or "docs" in compressed.lower(), \
        "Should use abbreviations in aggressive mode"
    
    print("\n✓ All prompt compressor tests passed")


def test_dynamic_middleware_selector():
    """Test dynamic middleware selection."""
    print("\n" + "=" * 80)
    print("Testing DynamicMiddlewareSelector")
    print("=" * 80)
    
    # Mock middleware options
    middleware_options = {
        'todo': "TodoListMiddleware",
        'planning': "PlanModeMiddleware",
        'filesystem': "FilesystemMiddleware",
        'subagents': "SubAgentMiddleware",
    }
    
    selector = DynamicMiddlewareSelector(
        middleware_options=middleware_options,
        default_middleware=['filesystem'],
    )
    
    # Test simple task
    simple_messages = [HumanMessage(content="What is the capital of France?")]
    selected = selector.select_middleware(simple_messages)
    print(f"\nSimple task selected middleware: {selected}")
    assert 'FilesystemMiddleware' in selected, "Should include default filesystem middleware"
    assert 'TodoListMiddleware' not in selected, "Should not include todo for simple task"
    
    # Test complex task
    complex_messages = [HumanMessage(content="Implement a complex feature with multiple steps and planning required.")]
    selected = selector.select_middleware(complex_messages)
    print(f"\nComplex task selected middleware: {selected}")
    assert 'TodoListMiddleware' in selected, "Should include todo for complex task"
    
    # Test context savings estimation
    savings = selector.estimate_context_savings(complex_messages)
    print(f"\nContext savings for complex task:")
    print(f"  Total possible tokens: {savings['total_possible_tokens']}")
    print(f"  Selected tokens: {savings['selected_tokens']}")
    print(f"  Savings: {savings['savings_tokens']} tokens ({savings['savings_percentage']:.1f}%)")
    print(f"  Middleware selected: {savings['middleware_selected']}")
    
    print("\n✓ All dynamic middleware selector tests passed")


def test_middleware_profiles():
    """Test middleware profiles."""
    print("\n" + "=" * 80)
    print("Testing MiddlewareProfile")
    print("=" * 80)
    
    # List available profiles
    profiles = MiddlewareProfile.list_profiles()
    print(f"\nAvailable profiles: {profiles}")
    assert 'simple' in profiles, "Should have simple profile"
    assert 'research' in profiles, "Should have research profile"
    assert 'implementation' in profiles, "Should have implementation profile"
    
    # Get profile details
    simple_profile = MiddlewareProfile.get_profile('simple')
    print(f"\nSimple profile: {simple_profile}")
    assert not simple_profile['features']['needs_todo'], "Simple profile should not need todo"
    
    research_profile = MiddlewareProfile.get_profile('research')
    print(f"\nResearch profile: {research_profile}")
    assert research_profile['features']['needs_subagents'], "Research profile should need subagents"
    
    impl_profile = MiddlewareProfile.get_profile('implementation')
    print(f"\nImplementation profile: {impl_profile}")
    assert impl_profile['features']['needs_todo'], "Implementation profile should need todo"
    assert impl_profile['features']['needs_planning'], "Implementation profile should need planning"
    
    # Test getting middleware for profile
    middleware_options = {
        'todo': "TodoListMiddleware",
        'planning': "PlanModeMiddleware",
        'filesystem': "FilesystemMiddleware",
        'subagents': "SubAgentMiddleware",
    }
    
    impl_middleware = MiddlewareProfile.get_middleware_for_profile(
        'implementation',
        middleware_options
    )
    print(f"\nImplementation middleware: {impl_middleware}")
    assert len(impl_middleware) == 4, "Implementation profile should have 4 middleware"
    
    print("\n✓ All middleware profile tests passed")


if __name__ == "__main__":
    test_complexity_analyzer()
    test_prompt_compressor()
    test_dynamic_middleware_selector()
    test_middleware_profiles()
    
    print("\n" + "=" * 80)
    print("All tests passed!")
    print("=" * 80)
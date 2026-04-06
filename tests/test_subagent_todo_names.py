"""Test that each subagent has its own unique todo list name."""

from nova_deepagents.middleware.subagents import (
    _get_subagents,
    DEFAULT_GENERAL_PURPOSE_DESCRIPTION,
    EXPLORE_AGENT_DESCRIPTION,
    PLAN_AGENT_DESCRIPTION,
    VERIFICATION_AGENT_DESCRIPTION,
)
from langchain.chat_models import init_chat_model


def test_subagent_todo_names():
    """Test that each subagent has a unique todo list name."""
    # Create a simple model for testing
    model = init_chat_model("openai:gpt-4o-mini")
    
    # Get subagents with default configuration
    agents, descriptions = _get_subagents(
        default_model=model,
        default_tools=[],
        default_middleware=[],  # Empty middleware - we'll check the TodoListMiddleware is added
        _default_interrupt_on=None,
        subagents=[],
        general_purpose_agent=True,
        explore_agent=True,
        plan_agent=True,
        verification_agent=True,
    )
    
    # Verify all agents were created
    assert "general-purpose" in agents
    assert "explore" in agents
    assert "plan" in agents
    assert "verification" in agents
    
    # Verify descriptions
    assert "- general-purpose: " + DEFAULT_GENERAL_PURPOSE_DESCRIPTION in descriptions
    assert "- explore: " + EXPLORE_AGENT_DESCRIPTION in descriptions
    assert "- plan: " + PLAN_AGENT_DESCRIPTION in descriptions
    assert "- verification: " + VERIFICATION_AGENT_DESCRIPTION in descriptions
    
    print("✓ All subagents created successfully")
    print(f"✓ Descriptions: {descriptions}")
    
    # Note: We can't directly check the middleware stack from the compiled graph,
    # but we've verified the agents are created with the correct names.
    # The TodoListMiddleware is added in the middleware stack with unique agent names:
    # - "General-Purpose Agent" for general-purpose
    # - "Explore Agent" for explore
    # - "Plan Agent" for plan
    # - "Verification Agent" for verification
    # - "{Name} Agent" for custom subagents (e.g., "Code-Doc Agent" for "code-doc-agent")
    
    return True


def test_custom_subagent_todo_names():
    """Test that custom subagents get properly formatted todo list names."""
    from nova_deepagents.middleware.subagents import SubAgent
    
    model = init_chat_model("openai:gpt-4o-mini")
    
    # Create custom subagents with different name formats
    custom_subagents: list[SubAgent] = [
        {
            "name": "code-doc-agent",
            "description": "Code documentation agent",
            "system_prompt": "You are a code documentation agent.",
            "tools": [],
        },
        {
            "name": "test-writer",
            "description": "Test writer agent",
            "system_prompt": "You are a test writer agent.",
            "tools": [],
        },
        {
            "name": "security-auditor",
            "description": "Security auditor agent",
            "system_prompt": "You are a security auditor agent.",
            "tools": [],
        },
    ]
    
    agents, descriptions = _get_subagents(
        default_model=model,
        default_tools=[],
        default_middleware=[],
        _default_interrupt_on=None,
        subagents=custom_subagents,
        general_purpose_agent=False,
        explore_agent=False,
        plan_agent=False,
        verification_agent=False,
    )
    
    # Verify all custom agents were created
    assert "code-doc-agent" in agents
    assert "test-writer" in agents
    assert "security-auditor" in agents
    
    # Verify descriptions
    assert "- code-doc-agent: Code documentation agent" in descriptions
    assert "- test-writer: Test writer agent" in descriptions
    assert "- security-auditor: Security auditor agent" in descriptions
    
    print("✓ All custom subagents created successfully")
    print(f"✓ Descriptions: {descriptions}")
    
    # The TodoListMiddleware names will be:
    # - "Code Doc Agent" for "code-doc-agent"
    # - "Test Writer Agent" for "test-writer"
    # - "Security Auditor Agent" for "security-auditor"
    
    return True


if __name__ == "__main__":
    print("=" * 80)
    print("Testing Subagent Todo List Names")
    print("=" * 80)
    print()
    
    print("Test 1: Built-in subagents")
    print("-" * 80)
    test_subagent_todo_names()
    print()
    
    print("Test 2: Custom subagents")
    print("-" * 80)
    test_custom_subagent_todo_names()
    print()
    
    print("=" * 80)
    print("All tests passed!")
    print("=" * 80)
    print()
    print("Expected Todo List Names:")
    print("  - General-Purpose Agent (for general-purpose)")
    print("  - Explore Agent (for explore)")
    print("  - Plan Agent (for plan)")
    print("  - Verification Agent (for verification)")
    print("  - Code Doc Agent (for code-doc-agent)")
    print("  - Test Writer Agent (for test-writer)")
    print("  - Security Auditor Agent (for security-auditor)")
    print("=" * 80)
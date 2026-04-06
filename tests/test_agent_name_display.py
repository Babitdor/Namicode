"""Test that agent names are properly displayed in todo lists."""

from langchain_core.messages import HumanMessage
from nova_deepagents.middleware.todo import TodoListMiddleware, _format_todo_list, Todo


def test_agent_name_in_todo_list():
    """Test that agent name is displayed in todo list header."""
    print("=" * 80)
    print("Testing Agent Name Display in Todo Lists")
    print("=" * 80)
    
    # Test 1: Main agent with custom name
    print("\nTest 1: Main Agent with Custom Name")
    print("-" * 80)
    middleware = TodoListMiddleware(agent_name="Deep Agent")
    todos = [
        {"content": "Implement user authentication", "status": "in_progress"},
        {"content": "Write unit tests", "status": "pending"},
        {"content": "Update documentation", "status": "pending"},
    ]
    formatted = middleware.format_todos(todos)
    print(formatted)
    assert "Deep Agent" in formatted, "Agent name should be in formatted output"
    assert "Deep Agent's Task List" in formatted, "Header should contain agent name"
    print("✓ Agent name correctly displayed in header")
    
    # Test 2: Subagent with different name
    print("\nTest 2: Subagent with Different Name")
    print("-" * 80)
    subagent_middleware = TodoListMiddleware(agent_name="Explore Agent")
    explore_todos = [
        {"content": "Analyze project structure", "status": "completed"},
        {"content": "Map module dependencies", "status": "in_progress"},
        {"content": "Document architecture", "status": "pending"},
    ]
    formatted = subagent_middleware.format_todos(explore_todos)
    print(formatted)
    assert "Explore Agent" in formatted, "Subagent name should be in formatted output"
    assert "Explore Agent's Task List" in formatted, "Header should contain subagent name"
    print("✓ Subagent name correctly displayed in header")
    
    # Test 3: Multiple agents with different names
    print("\nTest 3: Multiple Agents with Different Names")
    print("-" * 80)
    
    agents = [
        ("Plan Agent", [
            {"content": "Analyze requirements", "status": "completed"},
            {"content": "Design architecture", "status": "in_progress"},
        ]),
        ("Verification Agent", [
            {"content": "Run unit tests", "status": "completed"},
            {"content": "Run integration tests", "status": "in_progress"},
        ]),
        ("Code Doc Agent", [
            {"content": "Generate API docs", "status": "in_progress"},
            {"content": "Create usage examples", "status": "pending"},
        ]),
    ]
    
    for agent_name, agent_todos in agents:
        middleware = TodoListMiddleware(agent_name=agent_name)
        formatted = middleware.format_todos(agent_todos)
        print(f"\n{agent_name}:")
        print(formatted)
        assert agent_name in formatted, f"{agent_name} should be in formatted output"
        assert f"{agent_name}'s Task List" in formatted, f"Header should contain {agent_name}"
    
    print("✓ All agent names correctly displayed")
    
    # Test 4: Default agent name (no name provided)
    print("\nTest 4: Default Agent Name (No Name Provided)")
    print("-" * 80)
    default_middleware = TodoListMiddleware()
    default_todos = [
        {"content": "Complete task", "status": "pending"},
    ]
    formatted = default_middleware.format_todos(default_todos)
    print(formatted)
    assert "Task List" in formatted, "Default header should contain 'Task List'"
    print("✓ Default name correctly displayed")
    
    # Test 5: Verify status symbols
    print("\nTest 5: Status Symbols")
    print("-" * 80)
    status_todos = [
        {"content": "Completed task", "status": "completed"},
        {"content": "In progress task", "status": "in_progress"},
        {"content": "Pending task", "status": "pending"},
    ]
    middleware = TodoListMiddleware(agent_name="Status Test")
    formatted = middleware.format_todos(status_todos)
    print(formatted)
    assert "✓" in formatted, "Completed symbol should be present"
    assert "►" in formatted, "In progress symbol should be present"
    assert "○" in formatted, "Pending symbol should be present"
    print("✓ All status symbols correctly displayed")
    
    print("\n" + "=" * 80)
    print("All tests passed! Agent names are correctly displayed in todo lists.")
    print("=" * 80)


if __name__ == "__main__":
    test_agent_name_in_todo_list()
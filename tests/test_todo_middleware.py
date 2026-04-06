"""Test the TodoListMiddleware with agent name display."""

from nova_deepagents.middleware.todo import (
    Todo,
    TodoListMiddleware,
    _format_todo_list,
)


def test_format_todo_list_with_agent_name():
    """Test that todo list formatting includes agent name in header."""
    todos: list[Todo] = [
        {"content": "Research IBM Quantum roadmaps and qubit milestones (2024-2025)", "status": "in_progress"},
        {"content": "Research Google Quantum AI publications and breakthroughs", "status": "pending"},
        {"content": "Research IonQ, Rigetti, Quantinuum developments", "status": "pending"},
        {"content": "Research error correction breakthroughs", "status": "pending"},
        {"content": "Research hardware platform comparisons", "status": "pending"},
        {"content": "Research coherence time improvements", "status": "pending"},
        {"content": "Compile and save findings to markdown file", "status": "pending"},
    ]

    formatted = _format_todo_list(todos, agent_name="General-Purpose Agent")
    print(formatted)
    print()

    # Verify the agent name is in the output
    assert "General-Purpose Agent's Task List" in formatted
    assert "► Research IBM Quantum roadmaps" in formatted
    assert "○ Research Google Quantum AI" in formatted


def test_format_todo_list_without_agent_name():
    """Test that todo list formatting works without agent name."""
    todos: list[Todo] = [
        {"content": "Task 1", "status": "in_progress"},
        {"content": "Task 2", "status": "pending"},
        {"content": "Task 3", "status": "completed"},
    ]

    formatted = _format_todo_list(todos, agent_name=None)
    print(formatted)
    print()

    # Verify default header is used
    assert "Task List" in formatted
    assert "► Task 1" in formatted
    assert "○ Task 2" in formatted
    assert "✓ Task 3" in formatted


def test_format_empty_todo_list():
    """Test that empty todo list is handled gracefully."""
    formatted = _format_todo_list([], agent_name="Test Agent")
    assert formatted == "No tasks in the list."


def test_middleware_initialization():
    """Test that TodoListMiddleware can be initialized with agent name."""
    middleware = TodoListMiddleware(agent_name="Research Agent")
    assert middleware.agent_name == "Research Agent"
    assert len(middleware.tools) == 1
    assert middleware.tools[0].name == "write_todos"


def test_middleware_without_agent_name():
    """Test that TodoListMiddleware works without agent name."""
    middleware = TodoListMiddleware()
    assert middleware.agent_name is None
    assert len(middleware.tools) == 1


if __name__ == "__main__":
    print("=" * 80)
    print("Testing TodoListMiddleware with agent name display")
    print("=" * 80)
    print()

    test_format_todo_list_with_agent_name()
    print("✓ test_format_todo_list_with_agent_name passed")
    print()

    test_format_todo_list_without_agent_name()
    print("✓ test_format_todo_list_without_agent_name passed")
    print()

    test_format_empty_todo_list()
    print("✓ test_format_empty_todo_list passed")
    print()

    test_middleware_initialization()
    print("✓ test_middleware_initialization passed")
    print()

    test_middleware_without_agent_name()
    print("✓ test_middleware_without_agent_name passed")
    print()

    print("=" * 80)
    print("All tests passed!")
    print("=" * 80)
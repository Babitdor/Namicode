"""Example usage of TodoListMiddleware with agent name display.

This example demonstrates how to use the TodoListMiddleware in your agents
to provide structured task tracking with agent-specific headers.
"""

from langchain.agents import create_agent
from langchain_core.messages import HumanMessage
from nova_deepagents.middleware import TodoListMiddleware


async def example_with_agent_name():
    """Example: Create an agent with a named todo list."""
    # Create an agent with a custom name for the todo list
    agent = create_agent(
        "openai:gpt-4o",
        middleware=[
            TodoListMiddleware(agent_name="Research Agent"),
        ]
    )

    # The agent will now display "Research Agent's Task List" in the todo header
    result = await agent.invoke({
        "messages": [
            HumanMessage("Research quantum computing advancements and create a summary")
        ]
    })

    # Access the todo list from state
    todos = result.get("todos", [])
    print(f"Agent completed {len([t for t in todos if t['status'] == 'completed'])} tasks")
    print(f"Agent has {len([t for t in todos if t['status'] == 'pending'])} pending tasks")

    return result


async def example_without_agent_name():
    """Example: Create an agent with a default todo list."""
    # Create an agent without specifying a name (uses default "Task List" header)
    agent = create_agent(
        "openai:gpt-4o",
        middleware=[
            TodoListMiddleware(),
        ]
    )

    result = await agent.invoke({
        "messages": [
            HumanMessage("Help me organize my project files")
        ]
    })

    return result


async def example_multiple_agents():
    """Example: Multiple agents with different todo lists."""
    # Create specialized agents with different names
    research_agent = create_agent(
        "openai:gpt-4o",
        middleware=[
            TodoListMiddleware(agent_name="Research Agent"),
        ]
    )

    code_agent = create_agent(
        "openai:gpt-4o",
        middleware=[
            TodoListMiddleware(agent_name="Code Agent"),
        ]
    )

    # Each agent maintains its own todo list with its name in the header
    research_result = await research_agent.invoke({
        "messages": [HumanMessage("Research Python best practices")]
    })

    code_result = await code_agent.invoke({
        "messages": [HumanMessage("Implement a sorting algorithm")]
    })

    return research_result, code_result


def format_todos_manually():
    """Example: Format todos manually for display."""
    from nova_deepagents.middleware.todo import _format_todo_list, Todo

    todos: list[Todo] = [
        {"content": "Research IBM Quantum roadmaps and qubit milestones (2024-2025)", "status": "in_progress"},
        {"content": "Research Google Quantum AI publications and breakthroughs", "status": "pending"},
        {"content": "Research IonQ, Rigetti, Quantinuum developments", "status": "pending"},
        {"content": "Research error correction breakthroughs", "status": "pending"},
        {"content": "Research hardware platform comparisons", "status": "pending"},
        {"content": "Research coherence time improvements", "status": "pending"},
        {"content": "Compile and save findings to markdown file", "status": "pending"},
    ]

    # Format with agent name
    formatted = _format_todo_list(todos, agent_name="General-Purpose Agent")
    print(formatted)

    # Format without agent name
    formatted_default = _format_todo_list(todos, agent_name=None)
    print(formatted_default)


if __name__ == "__main__":
    print("=" * 80)
    print("TodoListMiddleware Examples")
    print("=" * 80)
    print()

    print("Example 1: Manual formatting with agent name")
    print("-" * 80)
    format_todos_manually()
    print()

    print("=" * 80)
    print("To use with an agent, see the async examples above.")
    print("=" * 80)
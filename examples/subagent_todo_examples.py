"""Visual example of subagent todo lists with unique names.

This example demonstrates how each subagent will display its own unique
todo list header when managing tasks.
"""

from nova_deepagents.middleware.todo import _format_todo_list, Todo


def show_subagent_todo_examples():
    """Show examples of how different subagents display their todo lists."""
    
    # Example tasks for different subagent types
    explore_tasks: list[Todo] = [
        {"content": "Analyze project structure and dependencies", "status": "in_progress"},
        {"content": "Map out module relationships", "status": "pending"},
        {"content": "Identify key entry points", "status": "pending"},
        {"content": "Document architecture patterns", "status": "pending"},
    ]
    
    plan_tasks: list[Todo] = [
        {"content": "Analyze requirements and constraints", "status": "completed"},
        {"content": "Design solution architecture", "status": "in_progress"},
        {"content": "Create implementation timeline", "status": "pending"},
        {"content": "Identify potential risks", "status": "pending"},
    ]
    
    verification_tasks: list[Todo] = [
        {"content": "Run unit tests", "status": "completed"},
        {"content": "Run integration tests", "status": "completed"},
        {"content": "Check code coverage", "status": "in_progress"},
        {"content": "Verify performance benchmarks", "status": "pending"},
    ]
    
    code_doc_tasks: list[Todo] = [
        {"content": "Generate API documentation", "status": "in_progress"},
        {"content": "Create usage examples", "status": "pending"},
        {"content": "Document configuration options", "status": "pending"},
    ]
    
    print("=" * 80)
    print("SUBAGENT TODO LIST EXAMPLES")
    print("=" * 80)
    print()
    
    # Show Explore Agent's todo list
    print("1. EXPLORE AGENT - Read-only codebase exploration")
    print("-" * 80)
    print(_format_todo_list(explore_tasks, agent_name="Explore Agent"))
    print()
    
    # Show Plan Agent's todo list
    print("2. PLAN AGENT - Implementation planning")
    print("-" * 80)
    print(_format_todo_list(plan_tasks, agent_name="Plan Agent"))
    print()
    
    # Show Verification Agent's todo list
    print("3. VERIFICATION AGENT - Testing and verification")
    print("-" * 80)
    print(_format_todo_list(verification_tasks, agent_name="Verification Agent"))
    print()
    
    # Show Code Doc Agent's todo list
    print("4. CODE DOC AGENT - Documentation generation")
    print("-" * 80)
    print(_format_todo_list(code_doc_tasks, agent_name="Code Doc Agent"))
    print()
    
    # Show General-Purpose Agent's todo list
    general_tasks: list[Todo] = [
        {"content": "Research quantum computing algorithms", "status": "in_progress"},
        {"content": "Implement optimization techniques", "status": "pending"},
        {"content": "Test performance improvements", "status": "pending"},
        {"content": "Document findings", "status": "pending"},
    ]
    
    print("5. GENERAL-PURPOSE AGENT - Complex multi-step tasks")
    print("-" * 80)
    print(_format_todo_list(general_tasks, agent_name="General-Purpose Agent"))
    print()
    
    # Show custom subagent's todo list
    security_tasks: list[Todo] = [
        {"content": "Scan for SQL injection vulnerabilities", "status": "completed"},
        {"content": "Check authentication mechanisms", "status": "in_progress"},
        {"content": "Review access control policies", "status": "pending"},
        {"content": "Generate security report", "status": "pending"},
    ]
    
    print("6. SECURITY AUDITOR AGENT - Security analysis")
    print("-" * 80)
    print(_format_todo_list(security_tasks, agent_name="Security Auditor Agent"))
    print()
    
    print("=" * 80)
    print("KEY FEATURES:")
    print("=" * 80)
    print("✓ Each subagent has a unique, descriptive name in the header")
    print("✓ Status symbols: ► (in_progress), ○ (pending), ✓ (completed)")
    print("✓ Beautiful bordered display for easy visual identification")
    print("✓ Helps users track which subagent is working on what")
    print("=" * 80)


if __name__ == "__main__":
    show_subagent_todo_examples()
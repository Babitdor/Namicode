#!/usr/bin/env python3
"""Test script to analyze context tracking across middleware layers."""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from namicode_cli.utils.context_budget import get_context_budget, reset_context_budget


def test_middleware_context_usage():
    """Simulate middleware context usage and analyze results."""
    
    print("=" * 80)
    print("Context Tracking Analysis")
    print("=" * 80)
    print()
    
    # Reset budget for clean test
    reset_context_budget()
    budget = get_context_budget(max_tokens=50000)
    
    # Simulate middleware context additions
    # Based on typical middleware prompts
    
    # FilesystemMiddleware - Large prompts for file operations
    filesystem_context = """
You have access to filesystem tools for reading, writing, and editing files.

When using file operations:
- Always use absolute paths
- Check file existence before reading
- Create backups before editing
- Use appropriate encodings

Available tools:
- read_file: Read file contents with line ranges
- write_file: Create or overwrite files
- edit_file: Make precise edits to existing files
- list_directory: List directory contents
- search_files: Find files matching patterns
- grep_search: Search within files

Guidelines:
- Prefer read_file with line ranges over reading entire files
- Use edit_file for small changes, write_file for new files
- Always verify paths before operations
- Handle errors gracefully
"""
    
    # SkillsMiddleware - Skill descriptions and instructions
    skills_context = """
You have access to specialized skills that can be invoked on-demand.

Available skills:
- web-research: Conduct thorough web research on topics
- code-review: Perform comprehensive code reviews
- testing: Design and implement test strategies
- documentation: Write clear documentation

To use a skill:
1. Identify when the skill is relevant
2. Read the skill's SKILL.md file
3. Follow the skill's workflow
4. Apply the skill's guidelines

Skills are loaded from:
- ~/.nami/skills/ (user-level)
- ./.nami/skills/ (project-level)
"""
    
    # MemoryMiddleware - Project context and instructions
    memory_context = """
Project Context:
- This is a Python CLI application
- Uses LangChain for agent orchestration
- Implements MCP (Model Context Protocol) for tool integration
- Supports multiple backend configurations

Build commands:
- make install: Install dependencies
- make test: Run test suite
- make lint: Run linting checks

Code style:
- Use type hints for all functions
- Follow PEP 8 conventions
- Write docstrings for public APIs
- Keep functions focused and small
"""
    
    # SubAgentMiddleware - Subagent instructions
    subagent_context = """
You can delegate tasks to specialized subagents.

Available subagents:
- explore: Read-only codebase exploration
- plan: Create implementation plans
- verification: Test and verify implementations

To invoke a subagent:
1. Use the 'task' tool
2. Specify the subagent type
3. Provide clear instructions
4. Review the subagent's output

Subagents have isolated context and focused toolsets.
"""
    
    # MCPMiddleware - MCP server instructions
    mcp_context = """
You have access to MCP (Model Context Protocol) servers.

Active servers:
- spotify: Control Spotify playback
- filesystem: File system operations
- github: GitHub API integration

To use MCP tools:
1. Check server status with /mcp list
2. Tools are automatically available
3. Use tools according to their schemas
4. Handle connection errors gracefully

MCP servers maintain state across tool calls.
"""
    
    # SharedMemoryMiddleware - Cross-agent memory
    shared_memory_context = """
You have access to shared memory for cross-agent communication.

Memory operations:
- write_memory: Store information for other agents
- read_memory: Retrieve stored information
- list_memories: See all stored keys
- delete_memory: Remove stored information

Use shared memory to:
- Pass context to subagents
- Store intermediate results
- Share findings across conversations
"""
    
    # PlanModeMiddleware - Planning instructions
    planning_context = """
Plan mode is available for complex tasks.

When to use plan mode:
- Multi-step implementations
- Architecture decisions
- Breaking down large tasks

To activate:
1. Use the 'enter_plan_mode' tool
2. Create a detailed plan
3. Get user approval
4. Execute approved steps

Plans help ensure systematic progress.
"""
    
    # AskQuestionMiddleware - Question asking
    ask_question_context = """
You can ask the user questions when clarification is needed.

Question types:
- Multiple choice: Provide options
- Free text: Open-ended questions
- Confirmation: Yes/no questions

Use questions sparingly and only when necessary.
"""
    
    # Track each middleware
    print("Tracking middleware context usage...")
    print()
    
    middleware_data = [
        ("FilesystemMiddleware", filesystem_context),
        ("SkillsMiddleware", skills_context),
        ("MemoryMiddleware", memory_context),
        ("SubAgentMiddleware", subagent_context),
        ("MCPMiddleware", mcp_context),
        ("SharedMemoryMiddleware", shared_memory_context),
        ("PlanModeMiddleware", planning_context),
        ("AskQuestionMiddleware", ask_question_context),
    ]
    
    for name, context in middleware_data:
        tokens = budget.track_middleware(name, context)
        print(f"✓ {name:25s} {tokens:5d} tokens ({tokens/50000*100:5.1f}% of budget)")
    
    print()
    print("=" * 80)
    print("Context Usage Report")
    print("=" * 80)
    print()
    
    # Get usage report
    report = budget.get_usage_report()
    
    print(f"Total Tokens Used: {report['total_tokens']:,} / {report['max_tokens']:,}")
    print(f"Percentage Used: {report['percentage_used']:.1f}%")
    print()
    
    print("Middleware Breakdown (sorted by usage):")
    print("-" * 80)
    print(f"{'Middleware':<30s} {'Tokens':>10s} {'% of Total':>12s} {'% of Budget':>12s}")
    print("-" * 80)
    
    for name, tokens in report['middleware_breakdown'].items():
        pct_of_total = (tokens / report['total_tokens']) * 100
        pct_of_budget = (tokens / report['max_tokens']) * 100
        print(f"{name:<30s} {tokens:>10,d} {pct_of_total:>11.1f}% {pct_of_budget:>11.1f}%")
    
    print()
    print("Top 5 Context Consumers:")
    print("-" * 80)
    for i, consumer in enumerate(report['top_consumers'], 1):
        pct = (consumer['tokens'] / report['max_tokens']) * 100
        print(f"{i}. {consumer['middleware']:<25s} {consumer['tokens']:>6,d} tokens ({pct:>5.1f}% of budget)")
    
    print()
    print("=" * 80)
    print("Analysis Summary")
    print("=" * 80)
    print()
    
    # Analysis
    total = report['total_tokens']
    max_tokens = report['max_tokens']
    remaining = max_tokens - total
    
    print(f"✓ Context budget is {report['percentage_used']:.1f}% utilized")
    print(f"✓ {remaining:,} tokens remaining ({remaining/max_tokens*100:.1f}% of budget)")
    print()
    
    # Identify optimization targets
    top_consumer = report['top_consumers'][0]
    if top_consumer['tokens'] > max_tokens * 0.2:
        print(f"⚠ {top_consumer['middleware']} uses >20% of budget - consider optimization")
    
    if report['percentage_used'] > 50:
        print("⚠ Context usage >50% - consider compression strategies")
    elif report['percentage_used'] > 30:
        print("ℹ Context usage >30% - monitor for growth")
    else:
        print("✓ Context usage is healthy (<30%)")
    
    print()
    print("Recommendations:")
    print("-" * 80)
    
    # Generate recommendations based on data
    if total > max_tokens * 0.5:
        print("1. Implement context compression for high-usage middleware")
        print("2. Consider lazy loading for non-essential middleware")
        print("3. Use progressive disclosure for large contexts")
    
    if top_consumer['tokens'] > max_tokens * 0.15:
        print(f"4. Optimize {top_consumer['middleware']} - highest context consumer")
    
    print("5. Monitor context growth over conversation turns")
    print("6. Implement context eviction for long conversations")
    print()
    
    return report


if __name__ == "__main__":
    test_middleware_context_usage()
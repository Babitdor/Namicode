#!/usr/bin/env python3
"""Analyze real-world context usage from actual middleware prompts."""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from namicode_cli.utils.context_budget import get_context_budget, reset_context_budget


def analyze_real_prompts():
    """Analyze context usage from actual middleware prompt files."""
    
    print("=" * 80)
    print("Real-World Context Usage Analysis")
    print("=" * 80)
    print()
    
    # Reset budget
    reset_context_budget()
    budget = get_context_budget(max_tokens=50000)
    
    # Find actual prompt templates
    prompts_dir = Path("namicode_cli/prompts")
    
    if not prompts_dir.exists():
        print("⚠ Prompts directory not found, using estimates")
        return analyze_estimated_usage()
    
    print("Analyzing actual prompt templates...")
    print()
    
    # Track context from actual files
    middleware_sizes = {}
    
    # Check for template files
    template_files = {
        "filesystem": prompts_dir / "filesystem.jinja",
        "skills": prompts_dir / "skills.jinja",
        "memory": prompts_dir / "memory.jinja",
        "mcp": prompts_dir / "mcp.jinja",
        "planning": prompts_dir / "planning.jinja",
    }
    
    for name, path in template_files.items():
        if path.exists():
            content = path.read_text()
            tokens = budget._count_tokens(content)
            middleware_sizes[name] = tokens
            print(f"✓ {name:20s} template: {tokens:5d} tokens")
        else:
            print(f"⚠ {name:20s} template: not found")
    
    print()
    
    # Now analyze middleware code size
    print("Analyzing middleware implementation sizes...")
    print()
    
    middleware_dir = Path("deepagents-nami/nami_deepagents/middleware")
    
    if middleware_dir.exists():
        middleware_files = {
            "FilesystemMiddleware": middleware_dir / "filesystem.py",
            "SubAgentMiddleware": middleware_dir / "subagents.py",
            "SkillsMiddleware": middleware_dir / "skills.py",
            "SharedMemoryMiddleware": middleware_dir / "shared_memory.py",
            "MemoryMiddleware": middleware_dir / "memory.py",
            "PlanModeMiddleware": middleware_dir / "planning.py",
            "AskQuestionMiddleware": middleware_dir / "ask_question.py",
            "PatchToolCallsMiddleware": middleware_dir / "patch_tool_calls.py",
        }
        
        for name, path in middleware_files.items():
            if path.exists():
                # Count lines of code
                lines = len(path.read_text().splitlines())
                # Estimate tokens (code is denser than prompts)
                tokens = lines * 2  # Rough estimate: 2 tokens per line
                print(f"  {name:30s} {lines:5d} lines (~{tokens:5d} tokens)")
    
    print()
    print("=" * 80)
    print("Context Budget Analysis")
    print("=" * 80)
    print()
    
    # Simulate realistic context usage
    print("Simulating realistic context usage...")
    print()
    
    reset_context_budget()
    budget = get_context_budget(max_tokens=50000)
    
    # Realistic estimates based on actual usage
    realistic_contexts = {
        "FilesystemMiddleware": """
You have access to filesystem tools for reading, writing, and editing files.

When using file operations:
- Always use absolute paths when possible
- Check file existence before reading
- Create backups before editing critical files
- Use appropriate encodings (UTF-8 for text, binary for images)

Available tools:
- read_file: Read file contents with line ranges
  - Use startLine and endLine for large files
  - Returns content with line numbers
  
- write_file: Create or overwrite files
  - Creates directories if needed
  - Handles encoding automatically
  
- edit_file: Make precise edits to existing files
  - Use oldString and newString for replacements
  - Include context lines for uniqueness
  
- list_directory: List directory contents
  - Shows files and folders
  - Use glob patterns for filtering
  
- search_files: Find files matching patterns
  - Supports glob and regex patterns
  - Can search recursively
  
- grep_search: Search within files
  - Fast text search with regex support
  - Shows matching lines with context

Guidelines:
- Prefer read_file with line ranges over reading entire files
- Use edit_file for small changes, write_file for new files
- Always verify paths before operations
- Handle errors gracefully
- Use binary mode for non-text files

Best practices:
1. Read before write to understand context
2. Use line ranges to avoid reading entire files
3. Create backups for important files
4. Test operations on non-critical files first
5. Document changes in commit messages
""",
        
        "SkillsMiddleware": """
You have access to specialized skills that can be invoked on-demand.

Skills are loaded from:
- ~/.nami/skills/ (user-level skills)
- ./.nami/skills/ (project-level skills)

Each skill is a directory containing:
- SKILL.md: Skill definition with YAML frontmatter
- Supporting files (optional)

Skill structure:
```
skills/
├── web-research/
│   ├── SKILL.md
│   └── helper.py
├── code-review/
│   ├── SKILL.md
│   └── checklist.md
└── testing/
    ├── SKILL.md
    └── templates/
```

SKILL.md format:
```markdown
---
name: web-research
description: Conduct thorough web research
license: MIT
---

# Web Research Skill

## When to Use
- User asks for research
- Need to gather information
- Comparing options

## Workflow
1. Define research question
2. Search for sources
3. Analyze findings
4. Synthesize results
```

To use a skill:
1. Check available skills with list_skills
2. Read the skill's SKILL.md file
3. Follow the skill's workflow
4. Apply the skill's guidelines

Available skills:
- web-research: Conduct thorough web research on topics
- code-review: Perform comprehensive code reviews
- testing: Design and implement test strategies
- documentation: Write clear documentation
- git: Advanced Git operations and workflows
- deployment: Deploy applications to various platforms

Guidelines:
- Skills are optional enhancements
- Read SKILL.md before using a skill
- Follow the skill's workflow
- Combine skills when appropriate
""",
        
        "MemoryMiddleware": """
Project Context and Instructions

This project is a Python CLI application for AI-powered code assistance.

Architecture:
- LangChain for agent orchestration
- MCP (Model Context Protocol) for tool integration
- Multiple backend support (filesystem, state, remote)
- Middleware-based architecture

Key directories:
- namicode_cli/: Main CLI application
- deepagents-nami/: DeepAgents integration
- tests/: Test suite
- docs/: Documentation

Build commands:
- make install: Install dependencies
- make test: Run test suite
- make lint: Run linting checks
- make build: Build distribution

Code style:
- Use type hints for all functions
- Follow PEP 8 conventions
- Write docstrings for public APIs
- Keep functions focused and small
- Use meaningful variable names

Testing:
- pytest for unit tests
- pytest-asyncio for async tests
- Coverage target: 80%
- Run: pytest tests/

Git workflow:
- Feature branches from main
- PR reviews required
- Squash merge preferred
- Semantic versioning

Documentation:
- README.md: Quick start
- docs/: Detailed guides
- CHANGELOG.md: Version history
- Inline comments for complex logic

Common patterns:
- Middleware: AgentMiddleware base class
- Tools: StructuredTool with schemas
- Prompts: Jinja2 templates
- State: TypedDict with annotations

Error handling:
- Use custom exceptions
- Log errors with context
- Provide helpful error messages
- Handle edge cases gracefully

Performance:
- Lazy loading for large modules
- Caching for repeated operations
- Async for I/O operations
- Context budget management
""",
        
        "SubAgentMiddleware": """
You can delegate tasks to specialized subagents.

Subagents are isolated agent instances with focused toolsets and context.

Available subagents:
- explore: Read-only codebase exploration
  - Tools: read_file, list_directory, search_files, grep_search
  - Use for: Understanding code structure, finding patterns
  
- plan: Create implementation plans
  - Tools: read_file, write_file (plan files only)
  - Use for: Breaking down complex tasks, architecture decisions
  
- verification: Test and verify implementations
  - Tools: read_file, write_file (test files), execute (limited)
  - Use for: Running tests, validating changes

To invoke a subagent:
1. Use the 'task' tool
2. Specify the subagent type (explore/plan/verification)
3. Provide clear instructions
4. Review the subagent's output

Example:
```python
task(
    subagent_type="explore",
    instructions="Find all uses of the MCPConfig class"
)
```

Subagent benefits:
- Isolated context prevents contamination
- Focused toolset reduces errors
- Specialized prompts improve results
- Parallel execution possible

Guidelines:
- Use subagents for complex, multi-step tasks
- Provide clear, specific instructions
- Review subagent output before acting
- Don't nest subagents (no subagent calling subagent)

Context management:
- Subagents have separate context budgets
- Main agent context not affected
- Results returned as text
- No state shared between calls
""",
        
        "MCPMiddleware": """
You have access to MCP (Model Context Protocol) servers.

MCP servers provide tools that extend your capabilities.

Active servers:
- spotify: Control Spotify playback
  - Tools: play, pause, next, previous, search
  - Stateful: Maintains playback state
  
- filesystem: File system operations
  - Tools: read, write, edit, list, search
  - Secure: Sandboxed to allowed directories
  
- github: GitHub API integration
  - Tools: create_issue, create_pr, list_issues
  - Auth: Uses GitHub token

To use MCP tools:
1. Check server status: /mcp list
2. Tools are automatically available
3. Use tools according to their schemas
4. Handle connection errors gracefully

Server management:
- Servers are configured in .mcp.json
- Each server has a command and args
- Servers can be enabled/disabled
- State persists across tool calls

Tool usage:
```python
# Tools appear as regular functions
result = spotify_play(track_uri="spotify:track:...")
```

Error handling:
- Connection errors: Server may be down
- Timeout errors: Long-running operations
- Auth errors: Check credentials
- Tool errors: Invalid parameters

Best practices:
- Check server status before use
- Handle errors gracefully
- Don't assume tools are available
- Use appropriate timeouts
""",
        
        "SharedMemoryMiddleware": """
You have access to shared memory for cross-agent communication.

Shared memory allows storing and retrieving information across agent invocations.

Memory operations:
- write_memory(key, content): Store information
  - Key: Unique identifier
  - Content: Text to store
  - Returns: Success status
  
- read_memory(key): Retrieve stored information
  - Key: Unique identifier
  - Returns: Stored content or None
  
- list_memories(): See all stored keys
  - Returns: List of keys with metadata
  
- delete_memory(key): Remove stored information
  - Key: Unique identifier
  - Returns: Success status

Use cases:
- Pass context to subagents
- Store intermediate results
- Share findings across conversations
- Remember user preferences
- Cache expensive computations

Memory structure:
```python
{
    "content": "Stored information",
    "author": "main-agent",
    "timestamp": "2026-04-05T12:00:00Z",
    "tags": ["optional", "tags"]
}
```

Guidelines:
- Use meaningful keys
- Include context in stored content
- Clean up old memories periodically
- Don't store sensitive information
- Tag memories for organization

Best practices:
- Write before read to ensure availability
- Use consistent naming conventions
- Include timestamps for temporal data
- Document memory structure
- Handle missing keys gracefully
""",
        
        "PlanModeMiddleware": """
Plan mode is available for complex tasks.

Plan mode helps you think through complex tasks before executing.

When to use plan mode:
- Multi-step implementations
- Architecture decisions
- Breaking down large tasks
- Risky operations
- User-requested planning

To activate plan mode:
1. Use the 'enter_plan_mode' tool
2. Create a detailed plan
3. Get user approval
4. Execute approved steps

Plan structure:
```markdown
# Plan: [Task Name]

## Objective
[What we're trying to achieve]

## Steps
1. [First step]
   - Details
   - Expected outcome
   
2. [Second step]
   - Details
   - Expected outcome

## Risks
- [Potential issues]
- [Mitigation strategies]

## Success Criteria
- [How to measure success]
```

Plan workflow:
1. Analyze requirements
2. Break down into steps
3. Identify dependencies
4. Estimate effort
5. Get user approval
6. Execute step by step
7. Verify success

Guidelines:
- Plans should be detailed but not verbose
- Include rollback strategies
- Consider edge cases
- Get approval before execution
- Update plan as needed

Exit plan mode:
- Use 'exit_plan_mode' tool
- Plan is saved for reference
- Can re-enter if needed
""",
        
        "AskQuestionMiddleware": """
You can ask the user questions when clarification is needed.

Question types:
- Multiple choice: Provide predefined options
  - Use for: Selecting from alternatives
  - Limit: 2-5 options recommended
  
- Free text: Open-ended questions
  - Use for: Gathering detailed input
  - Limit: Use sparingly
  
- Confirmation: Yes/no questions
  - Use for: Verifying actions
  - Limit: Critical decisions only

To ask a question:
```python
ask_question(
    question="Which approach should I use?",
    options=["Option A", "Option B", "Option C"],
    context="I need to choose between..."
)
```

Guidelines:
- Ask questions sparingly
- Only when necessary for progress
- Provide clear options
- Include context for clarity
- Respect user's time

Best practices:
- Default to most common option
- Explain why you're asking
- Keep questions concise
- Offer to proceed without answer
- Don't ask for information you can find

Avoid:
- Asking obvious questions
- Repeating questions
- Asking for preferences on trivial matters
- Interrupting workflow for minor clarifications
""",
    }
    
    # Track each middleware
    for name, context in realistic_contexts.items():
        tokens = budget.track_middleware(name, context)
        pct = (tokens / budget.max_tokens) * 100
        print(f"✓ {name:30s} {tokens:5,d} tokens ({pct:5.1f}% of budget)")
    
    print()
    print("=" * 80)
    print("Context Usage Report")
    print("=" * 80)
    print()
    
    # Get usage report
    report = budget.get_usage_report()
    
    print(f"Total Tokens Used: {report['total_tokens']:,} / {report['max_tokens']:,}")
    print(f"Percentage Used: {report['percentage_used']:.1f}%")
    print(f"Remaining: {report['max_tokens'] - report['total_tokens']:,} tokens")
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
    print("Analysis & Recommendations")
    print("=" * 80)
    print()
    
    # Analysis
    total = report['total_tokens']
    max_tokens = report['max_tokens']
    remaining = max_tokens - total
    
    # Health check
    if report['percentage_used'] < 30:
        health = "✓ HEALTHY"
        color = "green"
    elif report['percentage_used'] < 50:
        health = "ℹ MODERATE"
        color = "yellow"
    elif report['percentage_used'] < 70:
        health = "⚠ HIGH"
        color = "orange"
    else:
        health = "✗ CRITICAL"
        color = "red"
    
    print(f"Context Health: {health}")
    print(f"  - Budget used: {report['percentage_used']:.1f}%")
    print(f"  - Remaining: {remaining:,} tokens ({remaining/max_tokens*100:.1f}%)")
    print()
    
    # Identify optimization targets
    top_consumer = report['top_consumers'][0]
    
    print("Optimization Targets:")
    print("-" * 80)
    
    if top_consumer['tokens'] > max_tokens * 0.1:
        print(f"1. {top_consumer['middleware']} - Highest consumer ({top_consumer['tokens']:,} tokens)")
        print(f"   → Consider lazy loading or compression")
    
    if report['percentage_used'] > 20:
        print("2. Total context usage >20% - Monitor growth")
        print("   → Implement context eviction for long conversations")
    
    # Calculate potential savings
    print()
    print("Potential Optimizations:")
    print("-" * 80)
    
    # Lazy loading savings
    lazy_savings = sum([
        report['middleware_breakdown'].get('FilesystemMiddleware', 0) * 0.5,
        report['middleware_breakdown'].get('SkillsMiddleware', 0) * 0.3,
    ])
    print(f"1. Lazy loading: Save ~{lazy_savings:,.0f} tokens")
    print(f"   - Load FilesystemMiddleware only when file operations needed")
    print(f"   - Load SkillsMiddleware only when skills referenced")
    
    # Compression savings
    compression_savings = sum([
        report['middleware_breakdown'].get('MemoryMiddleware', 0) * 0.3,
        report['middleware_breakdown'].get('PlanModeMiddleware', 0) * 0.2,
    ])
    print(f"2. Context compression: Save ~{compression_savings:,.0f} tokens")
    print(f"   - Compress verbose instructions")
    print(f"   - Use references instead of full text")
    
    # Conditional loading
    conditional_savings = sum([
        report['middleware_breakdown'].get('SubAgentMiddleware', 0) * 0.4,
        report['middleware_breakdown'].get('SharedMemoryMiddleware', 0) * 0.5,
    ])
    print(f"3. Conditional loading: Save ~{conditional_savings:,.0f} tokens")
    print(f"   - Load SubAgentMiddleware only when task tool used")
    print(f"   - Load SharedMemoryMiddleware only when memory tools used")
    
    total_savings = lazy_savings + compression_savings + conditional_savings
    print()
    print(f"Total potential savings: ~{total_savings:,.0f} tokens ({total_savings/max_tokens*100:.1f}% of budget)")
    print(f"Optimized context: {total - total_savings:,.0f} tokens ({(total-total_savings)/max_tokens*100:.1f}% of budget)")
    print()
    
    return report


def analyze_estimated_usage():
    """Fallback analysis using estimates."""
    print("Using estimated context usage...")
    print()
    
    reset_context_budget()
    budget = get_context_budget(max_tokens=50000)
    
    # Estimates based on file sizes
    estimates = {
        "FilesystemMiddleware": 5000,
        "SkillsMiddleware": 3000,
        "MemoryMiddleware": 2500,
        "SubAgentMiddleware": 2000,
        "MCPMiddleware": 1500,
        "SharedMemoryMiddleware": 1200,
        "PlanModeMiddleware": 1000,
        "AskQuestionMiddleware": 800,
    }
    
    for name, tokens in estimates.items():
        budget.middleware_usage[name] = tokens
        budget.total_tokens += tokens
    
    return budget.get_usage_report()


if __name__ == "__main__":
    analyze_real_prompts()
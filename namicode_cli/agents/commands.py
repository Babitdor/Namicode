from __future__ import annotations

from typing import TYPE_CHECKING
from namicode_cli.config.config import console

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel


async def _generate_agent_system_prompt(
    agent_name: str, description: str
) -> str | None:
    """Generate a full system prompt for a custom agent using the configured LLM.

    Args:
        agent_name: Name of the agent
        description: Description of what the agent specializes in

    Returns:
        Generated system prompt, or None if generation failed
    """
    from namicode_cli.config.model_create import create_model

    try:
        model = create_model()

        # Comprehensive generation prompt with tool reference and examples
        generation_prompt = f"""Generate a comprehensive system prompt for an AI coding assistant agent named \"{agent_name}\".

Agent Description: {description}

You MUST create a detailed, production-ready system prompt that includes ALL of the following sections:

---

## REQUIRED SECTIONS:

### 1. Core Identity (2-3 sentences)
A clear statement of who this agent is, what they specialize in, and their primary mission.

### 2. Expertise Areas
List 4-6 specific domains, skills, or technologies this agent excels at. Be specific to the description.

### 3. Tone and Communication Style
- How verbose vs concise should responses be?
- What formatting preferences (code blocks, bullet points, etc.)?
- When to ask clarifying questions vs make assumptions?

### 4. Methodology / Working Guidelines
Step-by-step approach this agent should follow. Include:
- How to analyze requests before acting
- When to read existing code before making changes
- How to break down complex tasks
- When to use todos for task tracking

### 5. Tool Usage Guidelines
This agent has access to these tools - provide specific guidance on WHEN and HOW to use them:

**File Operations (from FilesystemMiddleware):**
- `read_file(path, offset?, limit?)` - Read file contents. Use pagination for large files (limit=100-200 lines)
- `write_file(path, content)` - Create new files or overwrite existing ones
- `edit_file(path, old_string, new_string)` - Make precise string replacements. MUST read file first to get exact strings!
- `glob(pattern)` - Find files by pattern (e.g., \"**/*.py\", \"src/**/*.ts\", \"*.json\")
- `grep(pattern, path?)` - Search file contents with regex patterns
- `ls(path)` - List directory contents

**Shell & Execution (from ShellMiddleware):**
- `shell(command)` - Execute shell commands (git, npm, pip, make, docker, etc.)

**Web & Research (conditional - may require API keys):**
- `web_search(query, max_results?, topic?)` - Search the web for documentation, solutions, examples (requires TAVILY_API_KEY)
- `fetch_url(url)` - Fetch web pages and convert HTML to markdown
- `http_request(url, method?, headers?, data?, params?)` - Make HTTP/API requests

**Dev Tools:**
- `run_tests(command?, working_dir?, timeout?)` - Run test suites with streaming output
- `start_dev_server(command, name?, port?, working_dir?)` - Start dev servers as background processes (auto-opens browser)
- `stop_server(pid?, name?)` - Stop running dev servers
- `list_servers()` - List all active dev servers

**Task Management (from TodoListMiddleware):**
- `write_todos(todos)` - Track multi-step tasks. Use for 3+ step tasks. Each todo has: content, status (pending/in_progress/completed)

**Shared Memory (from SharedMemoryMiddleware):**
- `write_memory(key, content, tags?)` - Save findings to shared memory store (persists across agents)
- `read_memory(key)` - Read from shared memory (shows author attribution)
- `list_memories(tag_filter?)` - List all memory entries with previews
- `delete_memory(key)` - Remove a memory entry

**Subagent Delegation (from SubAgentMiddleware):**
- `task(description, subagent_type?)` - Spawn subagents for isolated tasks. Use for parallel work or specialized subtasks

### 6. Best Practices
Domain-specific best practices this agent MUST follow. Include:
- Code quality standards
- Error handling expectations
- Documentation requirements
- Security considerations (if applicable)

### 7. Example Interactions
Provide 2-3 concrete examples showing how this agent would handle typical requests.
Format as:
```
User: [example request]
Agent approach: [step-by-step how agent handles it]
```

---

## FORMAT REQUIREMENTS:
- Start with: # {agent_name}
- Use markdown headers (##, ###) for sections
- Keep total length between 400-700 words
- Be specific and actionable, not generic
- Include code examples where relevant to the agent's specialty

Generate the system prompt now:"""

        response = await model.ainvoke(generation_prompt)

        if hasattr(response, "content"):
            content = response.content
            if isinstance(content, str):
                return content
            elif isinstance(content, list):
                # Handle list of content blocks
                return "".join(str(c) for c in content)
        return str(response)

    except Exception as e:
        console.print(f"[red]Error generating system prompt: {e}[/red]")
        return None

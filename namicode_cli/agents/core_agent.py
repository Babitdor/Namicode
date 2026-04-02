"""Agent management and creation for the CLI.

This module handles the creation, configuration, and management of LangGraph
deep agents for the Nami-Code CLI. It provides:

- Agent creation with custom system prompts and tool configurations
- Management of agent profiles (global and project-specific)
- Integration with middleware components (memory, skills, MCP, shell)
- Support for multiple backends (local filesystem and sandboxes)
- Agent memory management and persistence

Key Components:
- create_agent_with_config(): Create a fully configured deep agent
- list_agents(): Display available agent profiles
- reset_agent(): Reset an agent to default configuration
- Agent profiles stored in ~/.nami/agents/<name>/agent.md

The agent is built using LangGraph's Pregel architecture with:
- Planning capability via write_todos tool
- Subagent delegation via task tool
- File system access via CompositeBackend
- Middleware for memory, skills, MCP, and shell execution
- Checkpointing for conversation state persistence
"""

import os
import shutil
from pathlib import Path

from langchain.agents.middleware import (
    InterruptOnConfig,
)
from langchain.agents.middleware.types import AgentState
from langchain.messages import ToolCall
from langchain.tools import BaseTool
from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.pregel import Pregel
from langgraph.runtime import Runtime
from langgraph.store.memory import InMemoryStore
from nami_deepagents import create_deep_agent
from nami_deepagents.backends import CompositeBackend
from nami_deepagents.backends.filesystem import FilesystemBackend
from nami_deepagents.backends.sandbox import SandboxBackendProtocol
from nami_deepagents.middleware import (
    AskQuestionMiddleware,
    PlanModeMiddleware,
    SkillsMiddleware,
)
from nami_deepagents.middleware.subagents import SubAgent

from namicode_cli.agents.default_subagents.subagents import retrieve_core_subagents
from namicode_cli.config.config import (
    COLORS,
    config,
    console,
    get_default_coding_instructions,
    parse_agent_color,
    set_agent_color,
    settings,
)
from namicode_cli.integrations.sandbox_factory import get_default_working_dir
from namicode_cli.mcp import get_shared_mcp_middleware
from namicode_cli.memory.agent_memory import AgentMemoryMiddleware
from namicode_cli.memory.shared_memory import (
    SharedMemoryMiddleware,
    reset_shared_memory_store,
)
from namicode_cli.shell import ShellMiddleware
from namicode_cli.tracking.file_tracker import (
    FileTrackerMiddleware,
    reset_session_tracker,
)
from namicode_cli.tracking.tracing import (
    get_tracing_config,
    is_tracing_enabled,
)

# Module-level shared store for agent/subagent memory sharing
_shared_store: InMemoryStore | None = None
_store_lock_initialized = False


def get_shared_store() -> InMemoryStore:
    """Get or create the shared InMemoryStore for agent/subagent communication.

    Returns:
        Shared InMemoryStore instance
    """
    global _shared_store, _store_lock_initialized
    if _shared_store is None:
        _shared_store = InMemoryStore()
        _store_lock_initialized = True
    return _shared_store


def reset_shared_store() -> None:
    """Reset the shared store, shared memory, and file tracker (useful for new sessions)."""
    global _shared_store, _store_lock_initialized
    _shared_store = None
    _store_lock_initialized = False
    # Also reset the shared memory store
    reset_shared_memory_store()
    # Also reset the file tracker for the new session
    reset_session_tracker()


def _extract_agent_description(agent_md_content: str) -> str:
    """Extract a description from agent.md content.

    Looks for the first substantial line of content (ignoring headers and blank lines).

    Args:
        agent_md_content: The content of the agent.md file

    Returns:
        A brief description extracted from the file, or a default message
    """
    lines = agent_md_content.strip().split("\n")

    for line in lines[:10]:  # Check first 10 lines
        line = line.strip()
        # Skip empty lines, headers, and very short lines
        if line and not line.startswith("#") and len(line) > 30:
            # Truncate if too long
            if len(line) > 150:
                return line[:147] + "..."
            return line

    # Fallback: return a generic description
    return "Agent with custom system prompt and tools"


def build_named_subagents(
    assistant_id: str,
    tools: list[BaseTool],
) -> list[SubAgent]:
    """Build SubAgent specifications from all available named agents.

    Reads all agents from both global (~/.nami/agents/) and project (.nami/agents/)
    directories, excluding the current main agent, and converts them into SubAgent
    specifications that can be passed to SubAgentMiddleware.

    Args:
        assistant_id: The name of the current main agent (to exclude from subagents)
        tools: The list of tools to provide to each subagent

    Returns:
        List of SubAgent specifications ready for SubAgentMiddleware
    """
    from namicode_cli.config.config import settings

    subagents: list[SubAgent] = []
    all_agents = settings.get_all_agents()

    for agent_name, agent_dir, scope in all_agents:
        # Skip the current main agent
        if agent_name == assistant_id:
            continue

        agent_md_path = agent_dir / "agent.md"

        # Skip if agent.md doesn't exist
        if not agent_md_path.exists():
            console.print(
                f"[dim yellow]Warning: Skipping agent '{agent_name}' - no agent.md file[/dim yellow]"
            )
            continue

        try:
            system_prompt = agent_md_path.read_text(encoding="utf-8")
        except Exception as e:
            console.print(
                f"[dim yellow]Warning: Could not read agent.md for '{agent_name}': {e}[/dim yellow]"
            )
            continue

        # Extract description from the agent.md content
        description = _extract_agent_description(system_prompt)

        # Parse and register agent color from YAML frontmatter
        agent_color = parse_agent_color(agent_md_path)
        if agent_color:
            set_agent_color(agent_name, agent_color)

        # Create SubAgent specification
        subagent: SubAgent = {
            "name": agent_name,
            "description": f"[{scope}] {description}",
            "system_prompt": system_prompt,
            "tools": tools,  # Same tools as main agent
            # model and middleware will use defaults from SubAgentMiddleware
        }

        # Add color to subagent if available
        if agent_color:
            subagent["color"] = agent_color  # type: ignore

        subagents.append(subagent)

    return subagents


def list_agents() -> None:
    """List all available agents with detailed information."""
    agents = settings.get_all_agents()

    if not agents:
        console.print(
            f"\n[bold {COLORS['primary']}]📋 Available Agents[/bold {COLORS['primary']}]\n"
        )
        console.print("[yellow]No agents found.[/yellow]")
        console.print(
            "[dim]Agents will be created in ~/.nami/agents/ when you first use them.[/dim]",
            style=COLORS["dim"],
        )
        return

    console.print(
        f"\n[bold {COLORS['primary']}]📋 Available Agents[/bold {COLORS['primary']}]\n"
    )

    for agent_name, agent_path, scope in sorted(agents, key=lambda x: (x[2], x[0])):
        # Display scope badge
        scope_badge = "🌐" if scope == "global" else "📁"
        scope_color = COLORS["accent"] if scope == "global" else COLORS["success"]

        # Agent name with icon and scope
        console.print(
            f"  {scope_badge} [bold {COLORS['primary']}]{agent_name}[/bold {COLORS['primary']}] "
            f"[dim]([{scope_color}]{scope}[/{scope_color}])[/dim]"
        )

        # Agent path
        relative_path = (
            agent_path.relative_to(Path.home())
            if agent_path.is_relative_to(Path.home())
            else agent_path
        )
        console.print(f"    [dim]Path: ~/{relative_path}[/dim]")

        # Check for agent.md existence and show summary
        agent_md = agent_path / "agent.md"
        if agent_md.exists():
            content = agent_md.read_text(encoding="utf-8")
            # Extract first line or first sentence as description
            lines = content.strip().split("\n")
            desc = ""
            for line in lines[:3]:  # Check first 3 lines
                line = line.strip()
                if line and not line.startswith("#") and len(line) > 20:
                    desc = line[:80] + "..." if len(line) > 80 else line
                    break
            if desc:
                console.print(f"    [dim]{desc}[/dim]")
        else:
            console.print("    [yellow]⚠️  (incomplete - no agent.md)[/yellow]")

        console.print()

    console.print(f"[dim]Total: {len(agents)} agent(s)[/dim]")
    console.print()


def reset_agent(agent_name: str, source_agent: str | None = None) -> None:
    """Reset an agent to default or copy from another agent."""
    agents_root = settings.get_agents_root_dir()
    agent_dir = agents_root / agent_name

    if source_agent:
        source_dir = agents_root / source_agent
        source_md = source_dir / "agent.md"

        if not source_md.exists():
            console.print(
                f"[bold red]Error:[/bold red] Source agent '{source_agent}' not found "
                "or has no agent.md"
            )
            return

        source_content = source_md.read_text(encoding="utf-8")
        action_desc = f"contents of agent '{source_agent}'"
    else:
        source_content = get_default_coding_instructions()
        action_desc = "default"

    if agent_dir.exists():
        shutil.rmtree(agent_dir)
        console.print(
            f"Removed existing agent directory: {agent_dir}", style=COLORS["tool"]
        )

    agent_dir.mkdir(parents=True, exist_ok=True)
    agent_md = agent_dir / "agent.md"
    agent_md.write_text(source_content, encoding="utf-8")

    console.print(
        f"✓ Agent '{agent_name}' reset to {action_desc}", style=COLORS["primary"]
    )
    console.print(f"Location: {agent_dir}\n", style=COLORS["dim"])


def get_system_prompt(assistant_id: str, sandbox_type: str | None = None) -> str:
    """Get the base system prompt for the agent.

    Args:
        assistant_id: The agent identifier for path references
        sandbox_type: Type of sandbox provider ("modal", "runloop", "daytona").
                     If None, agent is operating in local mode.

    Returns:
        The system prompt string (without NAMI.md content)
    """
    agent_dir_path = f"~/.nami/{assistant_id}"

    if sandbox_type:
        # Get provider-specific working directory

        working_dir = get_default_working_dir(sandbox_type)

        working_dir_section = f"""### Current Working Directory

You are operating in a **remote Linux sandbox** at `{working_dir}`.

All code execution and file operations happen in this sandbox environment.

**Important:**
- The CLI is running locally on the user's machine, but you execute code remotely
- Use `{working_dir}` as your working directory for all operations

"""
    else:
        cwd = Path.cwd()
        working_dir_section = f"""<env>
Working directory: {cwd}
</env>

### Current Working Directory

The filesystem backend is currently operating in: `{cwd}`

### File System and Paths

**IMPORTANT - Path Handling:**
- All file paths must be absolute paths (e.g., `{cwd}/file.txt`)
- Use the working directory from <env> to construct absolute paths
- Example: To create a file in your working directory, use `{cwd}/research_project/file.md`
- Never use relative paths - always construct full absolute paths

"""

    reasoning_section = """
## Reasoning Protocol

Follow this process **strictly** unless explicitly instructed otherwise:

**Understand → Context → Plan → Execute → Verify**

### Step-by-Step Enforcement

**CRITICAL**: Before ANY code change, explicitly think through:

1. **Understand**: What is the user asking? Are there ambiguities? What's the scope?
2. **Context**: What files/code are relevant? READ them first (with limit for large files).
3. **Plan**: What steps are needed? Use `write_todos` for 3+ steps. What could go wrong?
4. **Execute**: One step at a time. Verify after each change.
5. **Verify**: Did it work? Run lint/tests. Check for unintended changes.

### General Rules

* If the task is **ambiguous**, ask clarifying questions *before* acting.
* If the task requires **3 or more steps**, first create a plan using `write_todos`.
* If the task involves **new or unfamiliar concepts**, research before implementation.
* **Read before edit**: ALWAYS read a file before editing it (edit_file requires this).
* **One change at a time**: Don't make multiple unrelated changes in one edit.

### Code Change Protocol

For ANY code modification:

1. **Read** the file first (with `limit` for large files)
2. **Understand** existing code and conventions
3. **Plan** the minimal change needed
4. **Edit** with `edit_file` (provide unique `old_string`)
5. **Verify** with `lint_code` immediately
6. **Test** if functionality changed
7. **Commit** only if tests pass

### Security-First Mindset

When making any change:
- **Check for secrets**: Never commit API keys, tokens, passwords
- **Validate inputs**: User input should be sanitized
- **Check dependencies**: Vulnerable packages?
- **Review permissions**: Does this need auth/authorization?

---

## Tool Quick Reference

| Task                     | Tool              | Notes                                             |
| ------------------------ | ----------------- | ------------------------------------------------- |
| Find files by name       | `glob`            | Examples: `**/*.py`, `**/test_*.ts`               |
| Search code content      | `grep`            | Examples: `function.*auth`, `TODO`                |
| Read file                | `read_file`       | Use `limit=100` for large files                   |
| Create or overwrite file | `write_file`      | Use only when full replacement is intended        |
| Targeted edit            | `edit_file`       | Preferred for small changes; preserves formatting |
| List directory           | `ls`              | One directory at a time                           |
| Run shell command        | `shell`           | Use `interactive=True` for prompts                |
| Delegate subtask         | `task`            | Spawn subagent for isolated work                  |
| Run tests               | `run_tests`       | Auto-detects pytest, npm test, jest, etc.         |
| Lint code               | `lint_code`       | Use `fix=True` to auto-fix issues                 |
| Type check              | `check_types`     | mypy/pyright/tsc detection                        |
| Search web              | `web_search`      | Tavily (requires API key)                         |
| Free web search         | `duckduckgo_search` | No API key needed                               |
| Search docs             | `docs_search`     | Official docs only, filtered by topic             |
| Git status              | `git_status`      | Branch, staged, unstaged, untracked               |
| Git history             | `git_log`         | Structured commit log                             |
| Git diff                | `git_diff`        | Compare commits or working tree                   |
| Git blame               | `git_blame`       | Line-by-line attribution                          |

---

## Filesystem Tool Selection

ALWAYS prefer dedicated tools over shell commands for file operations:
- Use `grep` instead of `shell("grep ...")` — richer output, no shell escaping needed
- Use `glob` instead of `shell("find ...")` — cross-platform, faster
- Use `read_file` instead of `shell("cat ...")` — paginated, line-numbered output

### grep vs glob

| Goal                              | Tool   |
| --------------------------------- | ------ |
| Find files named `*.ts`           | `glob` |
| Find files containing `useState`  | `grep` |
| Find all test files               | `glob` (pattern: `**/*test*.py`) |
| Find where a function is called   | `grep` (pattern: `my_function\\(`) |

Rule: If you know what the file is **called**, use `glob`. If you know what it **contains**, use `grep`.

---

## Shell Command Usage

* **Interactive commands** (`interactive=True`):
  Use for commands that prompt for input (e.g., `npm init`, `npx create-next-app`, `git rebase -i`)

* **Command chaining**:
  Use `&&` (e.g., `cd app && npm install && npm test`)

* **Paths with spaces**:
  Always quote paths (e.g., `cd "path with spaces"`)

* **Development servers**:
  Automatically detected and run in the background
  Use `background=True` to force background execution

---

## Web Search Guidelines

* Use **specific, time-aware queries**
  Example: *"FastAPI JWT authentication 2025"* instead of *"auth"*
* **Synthesize** findings; do not expose raw JSON or search responses
* **Cite sources** when accuracy or recency matters

### Which web search tool to use

| Tool                | When to use                                                        |
| ------------------- | ------------------------------------------------------------------ |
| `docs_search`       | First choice for library APIs, framework docs, configuration       |
| `web_search`        | General queries with higher-quality results (requires Tavily key)  |
| `duckduckgo_search` | Fallback when `web_search` is unavailable (no API key required)    |

Decision rule: For technical library/API questions, try `docs_search` first.
For general knowledge, use `web_search`. Fall back to `duckduckgo_search` if unavailable.

---

## Sandbox Execution (E2B)

Use `execute_in_e2b` for **secure, isolated execution** when appropriate.

### Valid Use Cases

* Testing code **before** writing it to files
* Running **untrusted or user-provided code**
* Executing **skill reference scripts**
* Testing packages (`pip`, `npm`) without affecting the local system
* Making **network or API requests**

### Supported Languages

* Python
* Node.js / JavaScript
* Bash

Sandboxes are fully isolated and automatically cleaned up.
Package managers (`pip`, `npm`) work out of the box.

**Example**:

```python
execute_in_e2b(
  code="import requests\nprint(requests.__version__)",
  language="python"
)
```

---

## Security Rules for Shell

**BLOCKED** (cannot run):
- `rm -rf /` or any destructive operation on system directories
- `sudo` commands (require explicit approval)
- `chmod 777` or `chmod a+rwx`
- Commands with pipes from untrusted sources
- `eval`, `exec` on user-provided strings

**ALWAYS ASK** before:
- Deleting files or directories
- Force pushing to git
- Dropping databases
- Modifying system configuration

---

## Error Recovery Protocol

1. **Read the error carefully** — do not retry blindly
2. **Diagnose the cause**:

   * File not found → use `glob`
   * Permission denied → check with `ls -la`
   * Missing module → install the dependency
3. **Verify the fix**:

   * Rerun the command, tests, or script to confirm resolution

"""

    return (
        reasoning_section
        + working_dir_section
        + f"""### Skills Directory

Your skills are stored at: `{agent_dir_path}/skills/`
Skills may contain scripts or supporting files. When executing skill scripts with bash, use the real filesystem path:
Example: `bash python {agent_dir_path}/skills/web-research/script.py`

### Human-in-the-Loop Tool Approval

Some tool calls require user approval before execution. When a tool call is rejected by the user:
1. Accept their decision immediately - do NOT retry the same command
2. Explain that you understand they rejected the action
3. Suggest an alternative approach or ask for clarification
4. Never attempt the exact same rejected command again

Respect the user's decisions and work with them collaboratively.

### Web Search Tool Usage

When you use the web_search tool:
1. The tool will return search results with titles, URLs, and content excerpts
2. You MUST read and process these results, then respond naturally to the user
3. NEVER show raw JSON or tool results directly to the user
4. Synthesize the information from multiple sources into a coherent answer
5. Cite your sources by mentioning page titles or URLs when relevant
6. If the search doesn't find what you need, explain what you found and ask clarifying questions

The user only sees your text responses - not tool results. Always provide a complete, natural language answer after using web_search.

### Todo List Management

When using the write_todos tool:
1. Keep the todo list MINIMAL - aim for 3-6 items maximum
2. Only create todos for complex, multi-step tasks that truly need tracking
3. Break down work into clear, actionable items without over-fragmenting
4. For simple tasks (1-2 steps), just do them directly without creating todos
5. When first creating a todo list for a task, ALWAYS ask the user if the plan looks good before starting work
   - Create the todos, let them render, then ask: "Does this plan look good?" or similar
   - Wait for the user's response before marking the first todo as in_progress
   - If they want changes, adjust the plan accordingly
6. Update todo status promptly as you complete each item

The todo list is a planning tool - use it judiciously to avoid overwhelming the user with excessive task tracking.

### Documentation Search (RECOMMENDED)

When working with external libraries, APIs, or unfamiliar frameworks, use `docs_search` first to find authoritative documentation before implementing.

**Recommended for:**
- External library/API usage
- Configuration changes for third-party tools
- Version-specific behavior
- Security or authentication patterns

**You may skip `docs_search` when:**
- Refactoring internal code without changing external behavior
- Working with well-known standard library features
- The topic was already researched earlier in this session
- The task is purely conceptual (explaining concepts, answering questions)
- Simple bug fixes in existing code where the issue is clear

**Best practice**: When using `docs_search`, cite the documentation sources found before implementing.

Example workflow:
1. User asks to add JWT authentication
2. Call `docs_search("JWT authentication", topic="python")` or relevant topic
3. Review results and cite sources: "Based on PyJWT documentation at..."
4. Then proceed with implementation"""
    )


def _format_write_file_description(
    tool_call: ToolCall, _state: AgentState, _runtime: Runtime
) -> str:
    """Format write_file tool call for approval prompt."""
    args = tool_call["args"]
    file_path = args.get("file_path", "unknown")
    content = args.get("content", "")

    # Handle case where content might be a dict instead of string
    if isinstance(content, dict):
        # If content is structured, try to extract the actual content
        content_str = content.get("text", str(content))
    else:
        content_str = str(content) if content is not None else ""

    action = "Overwrite" if Path(file_path).exists() else "Create"
    line_count = len(content_str.splitlines())

    return f"File: {file_path}\nAction: {action} file\nLines: {line_count}"


def _format_edit_file_description(
    tool_call: ToolCall, _state: AgentState, _runtime: Runtime
) -> str:
    """Format edit_file tool call for approval prompt."""
    args = tool_call["args"]
    file_path = args.get("file_path", "unknown")
    replace_all = bool(args.get("replace_all", False))

    return (
        f"File: {file_path}\n"
        f"Action: Replace text ({'all occurrences' if replace_all else 'single occurrence'})"
    )


def _format_web_search_description(
    tool_call: ToolCall, _state: AgentState, _runtime: Runtime
) -> str:
    """Format web_search tool call for approval prompt."""
    args = tool_call["args"]
    query = args.get("query", "unknown")
    max_results = args.get("max_results", 5)

    return f"Query: {query}\nMax results: {max_results}\n\n⚠️  This will use Tavily API credits"


def _format_fetch_url_description(
    tool_call: ToolCall, _state: AgentState, _runtime: Runtime
) -> str:
    """Format fetch_url tool call for approval prompt."""
    args = tool_call["args"]
    url = args.get("url", "unknown")
    timeout = args.get("timeout", 30)

    return f"URL: {url}\nTimeout: {timeout}s\n\n⚠️  Will fetch and convert web content to markdown"


def _format_task_description(
    tool_call: ToolCall, _state: AgentState, _runtime: Runtime
) -> str:
    """Format task (subagent) tool call for approval prompt.

    The task tool signature is: task(description: str, subagent_type: str)
    The description contains all instructions that will be sent to the subagent.
    """
    args = tool_call["args"]
    description = args.get("description", "unknown")
    subagent_type = args.get("subagent_type", "unknown")

    # Truncate description if too long for display
    description_preview = description
    if len(description) > 500:
        description_preview = description[:500] + "..."

    return (
        f"Subagent Type: {subagent_type}\n\n"
        f"Task Instructions:\n"
        f"{'─' * 40}\n"
        f"{description_preview}\n"
        f"{'─' * 40}\n\n"
        f"⚠️  Subagent will have access to file operations and shell commands"
    )


def _format_shell_description(
    tool_call: ToolCall, _state: AgentState, _runtime: Runtime
) -> str:
    """Format shell tool call for approval prompt."""
    args = tool_call["args"]
    command = args.get("command", "N/A")
    return f"Shell Command: {command}\nWorking Directory: {Path.cwd()}"


def _format_execute_description(
    tool_call: ToolCall, _state: AgentState, _runtime: Runtime
) -> str:
    """Format execute tool call for approval prompt."""
    args = tool_call["args"]
    command = args.get("command", "N/A")
    return f"Execute Command: {command}\nLocation: Remote Sandbox"


def _format_run_tests_description(
    tool_call: ToolCall, _state: AgentState, _runtime: Runtime
) -> str:
    """Format run_tests tool call for approval prompt."""
    args = tool_call["args"]
    command = args.get("command", "")
    working_dir = args.get("working_dir", ".")
    timeout = args.get("timeout", 300)

    command_display = command if command else "(auto-detect framework)"
    return (
        f"Test Command: {command_display}\n"
        f"Working Directory: {working_dir}\n"
        f"Timeout: {timeout}s\n\n"
        "⚠️  Will execute tests and stream output in real-time"
    )


def _format_start_dev_server_description(
    tool_call: ToolCall, _state: AgentState, _runtime: Runtime
) -> str:
    """Format start_dev_server tool call for approval prompt."""
    args = tool_call["args"]
    command = args.get("command", "unknown")
    name = args.get("name", "dev-server")
    port = args.get("port", "auto")
    working_dir = args.get("working_dir", ".")
    auto_open_browser = args.get("auto_open_browser", True)

    return (
        f"Server Command: {command}\n"
        f"Name: {name}\n"
        f"Port: {port if port else 'auto-detect'}\n"
        f"Working Directory: {working_dir}\n"
        f"Auto-open browser: {'Yes' if auto_open_browser else 'No'}\n\n"
        "⚠️  Will start a background process (killed on CLI exit)"
    )


def _add_interrupt_on() -> dict[str, InterruptOnConfig]:
    """Configure human-in-the-loop interrupt_on settings for destructive tools."""
    shell_interrupt_config: InterruptOnConfig = {
        "allowed_decisions": ["approve", "reject"],
        "description": _format_shell_description,  # type: ignore
    }

    execute_interrupt_config: InterruptOnConfig = {
        "allowed_decisions": ["approve", "reject"],
        "description": _format_execute_description,  # type: ignore
    }

    write_file_interrupt_config: InterruptOnConfig = {
        "allowed_decisions": ["approve", "reject"],
        "description": _format_write_file_description,  # type: ignore
    }

    edit_file_interrupt_config: InterruptOnConfig = {
        "allowed_decisions": ["approve", "reject"],
        "description": _format_edit_file_description,  # type: ignore
    }

    web_search_interrupt_config: InterruptOnConfig = {
        "allowed_decisions": ["approve", "reject"],
        "description": _format_web_search_description,  # type: ignore
    }

    fetch_url_interrupt_config: InterruptOnConfig = {
        "allowed_decisions": ["approve", "reject"],
        "description": _format_fetch_url_description,  # type: ignore
    }

    # Subagent delegation (task tool) runs without HITL approval —
    # subagents are controlled, stateless agents, not destructive operations.

    run_tests_interrupt_config: InterruptOnConfig = {
        "allowed_decisions": ["approve", "reject"],
        "description": _format_run_tests_description,  # type: ignore
    }

    start_dev_server_interrupt_config: InterruptOnConfig = {
        "allowed_decisions": ["approve", "reject"],
        "description": _format_start_dev_server_description,  # type: ignore
    }

    return {
        "shell": shell_interrupt_config,
        "execute": execute_interrupt_config,
        "write_file": write_file_interrupt_config,
        "edit_file": edit_file_interrupt_config,
        "web_search": web_search_interrupt_config,
        "fetch_url": fetch_url_interrupt_config,
        "run_tests": run_tests_interrupt_config,
        "start_dev_server": start_dev_server_interrupt_config,
    }


def create_agent_with_config(
    model: str | BaseChatModel,
    assistant_id: str,
    tools: list[BaseTool],
    *,
    sandbox: SandboxBackendProtocol | None = None,
    sandbox_type: str | None = None,
    system_prompt: str | None = None,
    auto_approve: bool = False,
    store: InMemoryStore | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
    is_continuation: bool = False,
) -> tuple[Pregel, CompositeBackend]:
    """Create and configure an agent with the specified model and tools.

    Args:
        model: LLM model to use
        assistant_id: Agent identifier for memory storage
        tools: Additional tools to provide to agent
        sandbox: Optional sandbox backend for remote execution (e.g., ModalBackend).
                 If None, uses local filesystem + shell.
        sandbox_type: Type of sandbox provider ("modal", "runloop", "daytona")
        store: Optional InMemoryStore. If None and use_shared_store is True,
               uses a module-level shared store that subagents can also access.
        is_continuation: If True, skip project memory paths (NAMI.md/CLAUDE.md)
               from AgentMemoryMiddleware since they're already in the continuation prompt.

    Returns:
        2-tuple of (graph, backend)
    """
    tracing_enabled = False
    skill_sources = []
    Nami_SubAgent: list[SubAgent] = []

    if is_tracing_enabled():
        tracing_enabled = True
        tracing_config = get_tracing_config()
        # console.print(
        #     f"[dim]LangSmith tracing enabled: {tracing_config.project_name}[/dim]"
        # )
    else:
        # Try to auto-configure from environment
        from namicode_cli.tracking.tracing import auto_configure

        config_result = auto_configure()
        if config_result.is_configured():
            tracing_enabled = True
            # console.print(
            #     f"[dim]LangSmith tracing enabled: {config_result.project_name}[/dim]"
            # )

    # Wrap model for OpenAI tracing if enabled and model is a ChatOpenAI instance
    wrapped_model = model
    if tracing_enabled and hasattr(model, "_model"):  # Check if it's a LangChain model
        try:
            from langchain_openai import ChatOpenAI

            if isinstance(model, ChatOpenAI):
                from namicode_cli.tracking.tracing import (
                    wrap_openai_client as _wrap_openai,
                )

                wrapped_model = _wrap_openai(model)
        except ImportError:
            pass

    # Skills directory - global (shared across all agents at ~/.nami/skills/)
    skills_dir = settings.ensure_user_skills_dir()
    skill_sources.append(str(skills_dir))
    # Project-level skills directories (if in a project)
    # Supports both .claude/skills/ and .nami/skills/
    project_skills_dirs = settings.get_project_skills_dirs()
    skill_sources.append(str(project_skills_dirs))

    # Use shared MCP middleware (singleton pattern avoids reconnecting for subagents)
    mcp_middleware = get_shared_mcp_middleware()

    # CONDITIONAL SETUP: Local vs Remote Sandbox
    if sandbox is None:
        # ========== LOCAL MODE ==========
        # Backend: Local filesystem for code (no virtual routes)
        backend = FilesystemBackend()  # Current working directory

    else:
        # ========== REMOTE SANDBOX MODE ==========
        # Backend: Remote sandbox for code (no /memories/ route needed with filesystem-based memory)
        backend = sandbox
        # FileTrackerMiddleware MUST be first to track all file operations and enforce read-before-edit

    agent_middleware = [
        FileTrackerMiddleware(
            enforce_read_before_edit=True,
            truncate_results=True,
            include_system_prompt=True,
        ),
        mcp_middleware,
        SharedMemoryMiddleware(author_id="main-agent"),
        ShellMiddleware(
            workspace_root=str(Path.cwd()),
            env=dict(os.environ),
        ),
        AgentMemoryMiddleware(
            settings=settings,
            assistant_id=assistant_id,
            skip_project_memory=is_continuation,
        ),
    ]
    # Load pre-defined default and user defined subagents
    Nami_SubAgent.extend(retrieve_core_subagents(tools=tools))  # type: ignore
    Nami_SubAgent.extend(build_named_subagents(assistant_id=assistant_id, tools=tools))  # type: ignore

    # Get the system prompt (sandbox-aware and with skills)
    if system_prompt is None:
        system_prompt = get_system_prompt(
            assistant_id=assistant_id, sandbox_type=sandbox_type
        )

    if auto_approve:
        # No interrupts - all tools run automatically
        interrupt_on = {}
    else:
        # Full HITL for destructive operations
        interrupt_on = _add_interrupt_on()

    composite_backend = CompositeBackend(
        default=backend,
        routes={},
    )

    # Pass named_subagents directly to create_deep_agent
    # It will create the SubAgentMiddleware internally
    # Use provided checkpointer or fallback to InMemorySaver
    final_checkpointer = checkpointer if checkpointer is not None else InMemorySaver()
    agent = create_deep_agent(
        name=assistant_id,
        model=wrapped_model,
        skills=skill_sources,
        system_prompt=system_prompt,
        tools=tools,
        checkpointer=final_checkpointer,
        backend=composite_backend,  # type: ignore
        middleware=agent_middleware,
        store=store,
        interrupt_on=interrupt_on,  # type: ignore
        subagents=Nami_SubAgent,  # Pass named agents as subagents # type: ignore
    ).with_config(
        config  # type: ignore
    )

    return agent, composite_backend  # type: ignore


async def get_agent_plan_mode_state(agent: Pregel, thread_id: str) -> bool:
    """Get current plan mode state from agent.

    Args:
        agent: The agent instance.
        thread_id: Current thread ID.

    Returns:
        True if plan mode is enabled, False otherwise.
    """
    config = {"configurable": {"thread_id": thread_id}}
    state = await agent.aget_state(config)  # type: ignore
    return state.values.get("plan_mode_enabled", False)


async def set_agent_plan_mode_state(
    agent: Pregel, thread_id: str, enabled: bool
) -> None:
    """Set plan mode state in agent.

    Args:
        agent: The agent instance.
        thread_id: Current thread ID.
        enabled: Whether to enable plan mode.
    """
    config = {"configurable": {"thread_id": thread_id}}
    await agent.aupdate_state(
        config=config,  # type: ignore
        values={"plan_mode_enabled": enabled},
    )

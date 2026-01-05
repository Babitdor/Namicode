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

from nami_deepagents import create_deep_agent
from nami_deepagents.backends import CompositeBackend
from nami_deepagents.backends.filesystem import FilesystemBackend
from nami_deepagents.backends.sandbox import SandboxBackendProtocol
from langchain.agents.middleware import (
    InterruptOnConfig,
)
from langchain.agents.middleware.types import AgentState
from langchain.messages import ToolCall
from langchain.tools import BaseTool
from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.pregel import Pregel
from langgraph.runtime import Runtime

from namicode_cli.agent_memory import AgentMemoryMiddleware
from namicode_cli.config import (
    COLORS,
    config,
    console,
    get_default_coding_instructions,
    settings,
)
from namicode_cli.integrations.sandbox_factory import get_default_working_dir
from namicode_cli.shell import ShellMiddleware
from namicode_cli.skills import SkillsMiddleware
from namicode_cli.mcp import MCPMiddleware
from namicode_cli.tracing import (
    configure_tracing,
    is_tracing_enabled,
    get_tracing_config,
    wrap_openai_client,
)


def list_agents() -> None:
    """List all available agents."""
    agents_dir = settings.get_agents_root_dir()

    if not agents_dir.exists() or not any(agents_dir.iterdir()):
        console.print("[yellow]No agents found.[/yellow]")
        console.print(
            "[dim]Agents will be created in ~/.nami/agents/ when you first use them.[/dim]",
            style=COLORS["dim"],
        )
        return

    console.print("\n[bold]Available Agents:[/bold]\n", style=COLORS["primary"])

    for agent_path in sorted(agents_dir.iterdir()):
        if agent_path.is_dir():
            agent_name = agent_path.name
            agent_md = agent_path / "agent.md"

            if agent_md.exists():
                console.print(f"  • [bold]{agent_name}[/bold]", style=COLORS["primary"])
                console.print(f"    {agent_path}", style=COLORS["dim"])
            else:
                console.print(
                    f"  • [bold]{agent_name}[/bold] [dim](incomplete)[/dim]",
                    style=COLORS["tool"],
                )
                console.print(f"    {agent_path}", style=COLORS["dim"])

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

        source_content = source_md.read_text()
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
    agent_md.write_text(source_content)

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
        The system prompt string (without agent.md content)
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

**Understand → Context → Plan → Execute → Verify**

- Ambiguous? Ask first. Complex (3+ steps)? Use `write_todos`. New API? Research first.

## Tool Quick Reference

| Task | Tool | Notes |
|------|------|-------|
| Find files by name | `glob` | `**/*.py`, `**/test_*.ts` |
| Find code content | `grep` | `function.*auth`, `TODO` |
| Read file | `read_file` | Use `limit=100` for large files |
| New/rewrite file | `write_file` | |
| Targeted edit | `edit_file` | Faster, preserves formatting |
| List directory | `ls` | Single directory only |

### Shell Commands

- **Interactive mode** (`interactive=True`): Use for prompts (`npx create-next-app`, `npm init`, `git rebase -i`)
- **Chain commands**: `cd dir && npm install && npm test`
- **Quote paths**: `cd "path with spaces"`
- **Dev servers**: Auto-detected and run in background; use `background=True` to force

### Web Search

- Be specific: "FastAPI JWT auth 2025" not "auth"
- Synthesize results; never show raw JSON to user
- Cite sources when relevant

## Error Recovery

1. **Read error** - Don't blindly retry
2. **Diagnose**: File not found → `glob`. Permission denied → check with `ls -la`. Missing module → install it
3. **Verify fix**: Run tests or commands to confirm

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

The todo list is a planning tool - use it judiciously to avoid overwhelming the user with excessive task tracking."""
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

    task_interrupt_config: InterruptOnConfig = {
        "allowed_decisions": ["approve", "reject"],
        "description": _format_task_description,  # type: ignore
    }

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
        "task": task_interrupt_config,
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
) -> tuple[Pregel, CompositeBackend]:
    """Create and configure an agent with the specified model and tools.

    Args:
        model: LLM model to use
        assistant_id: Agent identifier for memory storage
        tools: Additional tools to provide to agent
        sandbox: Optional sandbox backend for remote execution (e.g., ModalBackend).
                 If None, uses local filesystem + shell.
        sandbox_type: Type of sandbox provider ("modal", "runloop", "daytona")

    Returns:
        2-tuple of (graph, backend)
    """
    # Setup tracing if LangSmith is configured
    tracing_enabled = False
    if is_tracing_enabled():
        tracing_enabled = True
        tracing_config = get_tracing_config()
        console.print(
            f"[dim]LangSmith tracing enabled: {tracing_config.project_name}[/dim]"
        )
    else:
        # Try to auto-configure from environment
        from namicode_cli.tracing import auto_configure

        config_result = auto_configure()
        if config_result.is_configured():
            tracing_enabled = True
            console.print(
                f"[dim]LangSmith tracing enabled: {config_result.project_name}[/dim]"
            )

    # Wrap model for OpenAI tracing if enabled and model is a ChatOpenAI instance
    wrapped_model = model
    if tracing_enabled and hasattr(model, "_model"):  # Check if it's a LangChain model
        try:
            from langchain_openai import ChatOpenAI

            if isinstance(model, ChatOpenAI):
                from namicode_cli.tracing import wrap_openai_client as _wrap_openai

                wrapped_model = _wrap_openai(model)
        except ImportError:
            pass

    # Setup agent directory for persistent memory (same for both local and remote modes)
    agent_dir = settings.ensure_agent_dir(assistant_id)
    agent_md = agent_dir / "agent.md"
    if not agent_md.exists():
        source_content = get_default_coding_instructions()
        agent_md.write_text(source_content)

    # Skills directory - global (shared across all agents at ~/.nami/skills/)
    skills_dir = settings.ensure_user_skills_dir()

    # Project-level skills directories (if in a project)
    # Supports both .claude/skills/ and .nami/skills/
    project_skills_dirs = settings.get_project_skills_dirs()

    # Create MCP middleware once (shared across modes for cleanup)
    mcp_middleware = MCPMiddleware()

    # CONDITIONAL SETUP: Local vs Remote Sandbox
    if sandbox is None:
        # ========== LOCAL MODE ==========
        # Backend: Local filesystem for code (no virtual routes)
        composite_backend = CompositeBackend(
            default=FilesystemBackend(),  # Current working directory
            routes={},  # No virtualization - use real paths
        )

        # Middleware: AgentMemoryMiddleware, SkillsMiddleware, MCPMiddleware, ShellToolMiddleware
        agent_middleware = [
            AgentMemoryMiddleware(settings=settings, assistant_id=assistant_id),
            SkillsMiddleware(
                skills_dir=skills_dir,
                assistant_id=assistant_id,
                project_skills_dirs=project_skills_dirs,
            ),
            mcp_middleware,
            ShellMiddleware(
                workspace_root=str(Path.cwd()),
                env=dict(os.environ),
            ),
        ]
    else:
        # ========== REMOTE SANDBOX MODE ==========
        # Backend: Remote sandbox for code (no /memories/ route needed with filesystem-based memory)
        composite_backend = CompositeBackend(
            default=sandbox,  # Remote sandbox (ModalBackend, etc.)
            routes={},  # No virtualization
        )

        # Middleware: AgentMemoryMiddleware, SkillsMiddleware, and MCPMiddleware
        # NOTE: File operations (ls, read, write, edit, glob, grep) and execute tool
        # are automatically provided by create_deep_agent when backend is a SandboxBackend.
        agent_middleware = [
            AgentMemoryMiddleware(settings=settings, assistant_id=assistant_id),
            SkillsMiddleware(
                skills_dir=skills_dir,
                assistant_id=assistant_id,
                project_skills_dirs=project_skills_dirs,
            ),
            mcp_middleware,
        ]

    # Get the system prompt (sandbox-aware and with skills)
    system_prompt = get_system_prompt(
        assistant_id=assistant_id, sandbox_type=sandbox_type
    )

    interrupt_on = _add_interrupt_on()

    agent = create_deep_agent(
        model=wrapped_model,
        system_prompt=system_prompt,
        tools=tools,
        checkpointer=InMemorySaver(),
        backend=composite_backend,  # type: ignore
        middleware=agent_middleware,
        interrupt_on=interrupt_on,  # type: ignore
    ).with_config(
        config  # type: ignore
    )

    return agent, composite_backend

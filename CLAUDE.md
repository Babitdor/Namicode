# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Nami-Code CLI** is a terminal-based AI coding assistant built on the `nami-deepagents` library (located in `deepagents-nami/`). It implements a "Deep Agent" architecture with planning, subagent delegation, and multi-backend file system support (local + remote sandboxes).

## Development Commands

### Setup
```bash
# Install dependencies (includes deepagents-nami from ./deepagents-nami)
uv sync --all-groups

# Run CLI in development mode
uv run nami

# Install from source
uv pip install -e .
```

### Testing
```bash
# Run all unit tests (network disabled)
make test

# Run specific test file
make test TEST_FILE=tests/unit_tests/test_specific.py

# Run integration tests (network enabled)
make test_integration

# Watch mode for tests
make test_watch
```

### Code Quality
```bash
# Format code with ruff
make format

# Lint code (check only)
make lint

# Format with unsafe fixes
make format_unsafe
```

### Running
```bash
# Standard run
nami

# With specific agent
nami --agent myagent

# Auto-approve tools (skip prompts)
nami --auto-approve

# With sandbox
nami --sandbox modal
```

## Architecture

### Core Components

1. **Deep Agent Architecture** (from `nami-deepagents`)
   - **Planning**: `write_todos` tool for task management
   - **Subagents**: `task` tool for parallel delegation via SubAgentMiddleware
   - **Backends**: Multi-layered file system abstraction (CompositeBackend)
   - **Middleware**: Plugin system for extending agent behavior

2. **Backend System** (`nami_deepagents/backends/`)
   - **CompositeBackend**: Routes operations between local and sandbox backends
   - **FilesystemBackend**: Local file operations
   - **SandboxBackend**: Remote execution (Modal, Runloop, Daytona, Docker)
   - **StateBackend**: Agent state persistence via LangGraph checkpoints
   - **StoreBackend**: Shared memory store for agent/subagent communication

3. **Middleware Stack** (in execution order)
   - **AgentMemoryMiddleware**: Loads agent.md memory files (user + project)
   - **SkillsMiddleware**: Progressive disclosure skills system
   - **MCPMiddleware**: Model Context Protocol server integration (singleton via `get_shared_mcp_middleware()`)
   - **SharedMemoryMiddleware**: Cross-agent memory sharing with attribution tracking
   - **ShellMiddleware**: Shell command execution with process management
   - **FilesystemMiddleware**: File operations (read, write, edit, glob, grep)
   - **SubAgentMiddleware**: Subagent delegation and compilation

4. **Module Structure** (`namicode_cli/`)
   - `main.py`: Entry point, CLI loop, session management, auto-save
   - `agent.py`: Agent creation, system prompt generation, middleware configuration
   - `subagent.py`: Custom agent creation for `@agent` invocations
   - `execution.py`: Task execution, streaming, tool approval (HITL)
   - `tools.py`: Custom tools (web_search, fetch_url, http_request)
   - `config.py`: Settings, environment variables, path resolution, agent colors
   - `input.py`: Prompt toolkit integration, keyboard shortcuts
   - `ui.py`: Rich-based rendering, token tracking, help display
   - `commands.py`: Slash commands (/help, /tokens, /save, /agents, etc.)
   - `session_persistence.py`: Session save/restore functionality
   - `agent_memory.py`: Agent memory loading and management
   - `shared_memory.py`: Cross-agent shared memory with attribution
   - `skills/`: Skills system (commands, discovery, middleware)
   - `mcp/`: MCP integration (client, presets, middleware, shared singleton)
   - `integrations/`: Sandbox backends (Modal, Runloop, Daytona, Docker)

### Key Design Patterns

**CompositeBackend Routing**: Operations are routed to the appropriate backend based on path patterns. Sandbox paths (e.g., `/tmp/workspace`) go to sandbox backend, local paths to FilesystemBackend.

**Middleware Chaining**: Each middleware wraps the agent's tool calls, allowing inspection, modification, and context injection. Middleware execute in a defined order and can share state via `AgentState`.

**Progressive Disclosure**: Skills are registered by name only; full instructions load on-demand when invoked. This keeps context windows manageable.

**Memory Hierarchy**: Agent loads two memory files at startup:
- Global: `~/.nami/agents/<name>/agent.md` (user preferences, coding style)
- Project: `.nami/agent.md` or `.claude/agent.md` (project-specific context)

**Session Persistence**: Sessions auto-save every 5 minutes or after 5 messages. State includes messages, todos, model name, and thread ID.

**Shared Memory**: Main agent and subagents share memory via `SharedMemoryMiddleware`. Memory entries include author attribution (`main-agent` or `subagent:<name>`), timestamps, and optional tags. Tools: `write_memory`, `read_memory`, `list_memories`, `delete_memory`.

**MCP Singleton**: MCP servers connect once via `get_shared_mcp_middleware()` and are shared across main agent and all subagents to avoid reconnection overhead.

## Configuration Files

### Agent Memory
- `~/.nami/agents/<name>/agent.md`: User-level agent memory with optional YAML frontmatter
- `.nami/agent.md`: Project-level agent memory (Claude Code compatible)
- `.claude/agent.md`: Alternative project-level format

### Agent Colors
Agents can have custom display colors defined in YAML frontmatter:
```markdown
---
color: #22c55e
---

# Agent Name
...
```
Colors are used for spinner, agent name, and output display. Use `/agents create` to create agents with color selection.

### Skills
- `~/.nami/skills/<name>/SKILL.md`: Global skills
- `.nami/skills/<name>/SKILL.md`: Project skills
- Format: YAML frontmatter + markdown instructions

### MCP Servers
- `~/.nami/mcp_config.json`: MCP server configurations
- Managed via `nami mcp` commands

### Path Approval
- `~/.nami/approved_paths.json`: Pre-approved file system paths
- Required for security (prevents arbitrary file access)

## Important Architectural Notes

1. **Dependency on deepagents-nami**: This project depends on the local `./deepagents-nami` package (path dependency in pyproject.toml). Changes to core agent logic often require modifying both packages.

2. **Sandbox vs Local Mode**: The CLI operates in two modes:
   - **Local**: File operations and shell commands execute on local machine
   - **Sandbox**: Code execution happens remotely; file operations may target sandbox or local depending on path

3. **Thread Safety**: The shared InMemoryStore (`_shared_store` in agent.py) enables agent/subagent communication. Reset between sessions via `reset_shared_store()`. Shared memory (`shared_memory.py`) and MCP middleware (`mcp/__init__.py`) also use module-level singletons.

4. **Token Tracking**: Baseline tokens calculated from system prompt + loaded files. Used to show incremental token usage during conversation.

5. **Auto-Approve Mode**: When enabled via `--auto-approve`, tools execute without user confirmation. Controlled by SessionState.auto_approve flag.

6. **Process Management**: Dev servers and background processes managed via ProcessManager singleton. Auto-cleanup on session exit.

## Testing Guidelines

- **Unit tests**: Must use `--disable-socket` (no network)
- **Integration tests**: Allow network access
- **Fixtures**: Use `tests/utils.py` for shared test utilities
- **Mocking**: Mock external services (Tavily, OpenAI, sandbox providers)

## Common Development Patterns

### Adding a New Tool
1. Define tool function in appropriate module (e.g., `tools.py`)
2. Add to tools list in `agent.py` `_run_agent_session()`
3. Optional: Add middleware if tool needs state access

### Adding a New Middleware
1. Create middleware class inheriting from base middleware pattern
2. Implement `before_tool_call()` and/or `after_tool_call()` methods
3. Register in `agent.py` `create_agent_with_config()`

### Adding a New Sandbox Backend
1. Implement `SandboxBackendProtocol` in `integrations/<name>.py`
2. Add factory function to `integrations/sandbox_factory.py`
3. Update CLI arg parser in `main.py`

### Adding a Custom Agent
1. Use `/agents create` command for interactive creation with color selection
2. Or manually create `~/.nami/agents/<name>/agent.md` with YAML frontmatter:
   ```markdown
   ---
   color: #3b82f6
   ---

   # Agent instructions...
   ```
3. Invoke with `@agent_name <query>` syntax

## Environment Variables

Required:
- `OPENAI_API_KEY` or `ANTHROPIC_API_KEY` (LLM provider)

Optional:
- `TAVILY_API_KEY` (web search)
- `LANGCHAIN_API_KEY` + `LANGCHAIN_TRACING_V2=true` (tracing)
- `GRPC_ENABLE_FORK_SUPPORT=0` (macOS gRPC fix)

## Special Considerations

- **Windows Support**: Uses MINGW64 environment; some shell commands may differ
- **Signal Handling**: SIGTERM/SIGHUP handlers save session before exit (Unix only)
- **Keyboard Shortcuts**: Platform-specific (⌥ Option on macOS, Alt on Windows/Linux)
- **Migration**: `nami migrate` command handles old directory structure upgrades

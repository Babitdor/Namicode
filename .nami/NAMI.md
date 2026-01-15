# NAMI.md

This file provides guidance to AI assistants when working with code in this repository.

## Project Overview

Nami-Code is an open-source terminal-based AI coding assistant similar to Claude Code. It's built on the `nami-deepagents` library (located in `deepagents-nami/`), which implements a "Deep Agent" architecture with planning tools, subagent delegation, file system access, and detailed prompts. The CLI supports multiple LLM providers (OpenAI, Anthropic, Google, Ollama), sandbox execution (Modal, Runloop, Daytona, Docker), MCP integration, and progressive disclosure skills.

## Technology Stack

| Layer | Technology | Purpose |
|-------|------------|---------|
| **Language** | Python 3.11+ (`>=3.11,<4.0`) | Core implementation |
| **Agent Framework** | LangGraph + LangChain | Agent orchestration, state management |
| **LLM Providers** | langchain-openai, langchain-ollama, langchain-google-genai, langchain-anthropic | Model access |
| **CLI UI** | Rich, prompt-toolkit | Terminal UI, syntax highlighting, interactive input |
| **Sandbox Execution** | Modal, Daytona, Runloop, Docker, E2B | Remote code execution |
| **Web Search** | Tavily API | Web research capability |
| **Protocols** | MCP (Model Context Protocol) | Tool server integration |
| **Observability** | LangSmith | Tracing and debugging |
| **Testing** | pytest, pytest-asyncio | Test framework |
| **Code Quality** | ruff (linting + formatting), mypy (type checking) | Code quality |
| **Package Management** | uv (recommended), pip | Fast Python package manager |

### Dependencies Breakdown

**Core AI/ML Frameworks:**
- `langchain>=1.0.7` - Core AI orchestration framework
- `langchain-openai>=0.1.0` - OpenAI integration
- `langchain-ollama>=1.0.0` - Local Ollama model integration
- `langchain-google-genai>=3.2.0` - Google AI integration

**CLI & UI Components:**
- `rich>=13.0.0` - Terminal UI rendering with colors
- `prompt-toolkit>=3.0.52` - Interactive command-line interface

**Sandbox Integrations:**
- `modal>=0.65.0` - Modal sandbox
- `daytona>=0.113.0` - Daytona workspace
- `runloop-api-client>=0.69.0` - Runloop sandbox
- `docker>=7.0.0` - Docker containers
- `e2b-code-interpreter>=1.0.0` - E2B cloud sandbox

**Protocol & Standards:**
- `mcp>=1.0.0` - Model Context Protocol support
- `langchain-mcp-adapters>=0.1.0` - MCP integration

**Development Tools:**
- `ruff` - Code linting and formatting
- `mypy` - Type checking
- `pytest` - Testing framework

## Project Structure

```
namicode-cli/
├── namicode_cli/              # Main CLI application
│   ├── main.py                # CLI entry point, argument parsing, REPL loop
│   ├── agent.py               # Agent creation with middleware stack, shared store management
│   ├── execution.py           # Task streaming, human-in-the-loop approval, tool rendering
│   ├── config.py              # Settings, API keys, model creation, colors, ASCII banner
│   ├── commands.py            # Slash commands (/help, /tokens, /clear, /quit)
│   ├── input.py               # Prompt session with prompt_toolkit, image handling
│   ├── shell.py               # Shell execution middleware for local mode
│   ├── tools.py               # HTTP tools (web_search, fetch_url, http_request)
│   ├── ui.py                  # Token tracking, diff rendering, help display
│   ├── file_ops.py            # File operation tracking and diff previews
│   ├── agent_memory.py        # Persistent agent memory (user + project level)
│   ├── shared_memory.py       # Cross-agent communication via InMemoryStore
│   ├── file_tracker.py        # Session-scoped file operation tracking
│   ├── session_persistence.py # Session save/restore, auto-save functionality
│   ├── context_manager.py     # Context management for long conversations
│   ├── compaction.py          # Message compaction for context optimization
│   ├── tracing.py             # LangSmith tracing configuration
│   ├── process_manager.py     # Background process management
│   ├── dev_server.py          # Dev server management tools
│   ├── test_runner.py         # Test execution tools
│   ├── token_utils.py         # Token calculation utilities
│   ├── path_approval.py       # Path approval for unapproved directories
│   ├── session_restore.py     # Session restoration logic
│   ├── migrate.py             # Migration utilities for config updates
│   ├── init_commands.py       # Project initialization commands
│   ├── image_utils.py         # Image handling utilities
│   ├── nami_config.py         # Nami-specific configuration
│   ├── model_manager.py       # Model provider management
│   ├── default_agent_prompt.md # Default agent system prompt
│   ├── skills/                # Progressive disclosure skill system
│   │   ├── middleware.py      # Skills middleware injection
│   │   ├── load.py            # Skill loading and metadata parsing
│   │   ├── commands.py        # Skill management CLI commands
│   │   └── registry.py        # Skill registry management
│   ├── mcp/                   # Model Context Protocol integration
│   │   ├── middleware.py      # MCP tools injection middleware
│   │   ├── client.py          # MultiServerMCPClient for connections
│   │   ├── presets.py         # Preset configurations
│   │   └── commands.py        # MCP management CLI commands
│   ├── integrations/          # Sandbox provider implementations
│   │   ├── sandbox_factory.py # Factory for creating sandbox instances
│   │   ├── modal.py           # Modal sandbox integration
│   │   ├── runloop.py         # Runloop sandbox integration
│   │   ├── daytona.py         # Daytona workspace integration
│   │   └── docker.py          # Docker container integration
│   └── errors/                # Error handling utilities
│       ├── handlers.py        # Exception handling decorators
│       └── taxonomy.py        # Error taxonomy and categorization
│
├── deepagents-nami/           # Core agent library (local dependency)
│   ├── nami_deepagents/
│   │   ├── __init__.py        # Exports: create_deep_agent, middleware
│   │   ├── graph.py           # create_deep_agent() factory with middleware stack
│   │   ├── backends/          # Storage backend implementations
│   │   │   ├── __init__.py    # Backend exports (BackendProtocol, etc.)
│   │   │   ├── protocol.py    # BackendProtocol interface definitions
│   │   │   ├── filesystem.py  # Local filesystem backend
│   │   │   ├── state.py       # LangGraph state wrapper (StateBackend)
│   │   │   ├── store.py       # LangGraph Store wrapper (StoreBackend)
│   │   │   ├── sandbox.py     # Sandbox base class
│   │   │   ├── composite.py   # Multi-backend router by path prefix
│   │   │   └── utils.py       # Backend utilities (formatting, truncation)
│   │   └── middleware/        # Agent middleware
│   │       ├── __init__.py    # Middleware exports
│   │       ├── filesystem.py  # File operation tools (ls, read, write, edit, glob, grep, execute)
│   │       ├── subagents.py   # Subagent spawning via task tool
│   │       └── patch_tool_calls.py # Dangling tool call handling
│   ├── pyproject.toml         # Core library config (v0.2.8)
│   └── tests/                 # Core library tests
│
├── tests/                     # Test suite
│   ├── unit_tests/            # Unit tests (socket disabled)
│   │   ├── test_*.py          # Various unit tests
│   │   ├── mcp/               # MCP-related tests
│   │   └── skills/            # Skills-related tests
│   ├── integration_tests/     # Integration tests (full I/O)
│   │   ├── benchmarks/        # Benchmark tests
│   │   ├── conftest.py        # LangSmith tracing fixture
│   │   └── test_*.py          # Integration tests
│   └── test_project_memory.py # Project memory tests
│
├── evaluation/                # Terminal-Bench Harbor evaluation framework
├── assets/                    # Project assets (banners, icons)
├── changelog/                 # Changelog files
├── pyproject.toml             # Main project config (v0.0.10)
├── Makefile                   # Development commands
├── CLAUDE.md                  # Claude Code guidance
└── README.md                  # Project documentation
```

## Development Setup

### Prerequisites

- Python 3.11 or higher
- [uv](https://docs.astral.sh/uv/) (recommended package manager)

### Installation

```bash
# Clone the repository
git clone https://github.com/Babitdor/namicode-cli.git
cd namicode-cli

# Create virtual environment and install dependencies
uv venv
uv sync --all-groups

# Install in editable mode (alternative)
uv pip install -e .
```

### Environment Configuration

Configure API keys in `.env` file (copy from `.env.template`):

```bash
# Required for LLM access
export OPENAI_API_KEY="your-openai-api-key"
# or
export ANTHROPIC_API_KEY="your-anthropic-api-key"

# Optional: Web search
export TAVILY_API_KEY="your-tavily-api-key"

# Optional: Sandbox providers
export DAYTONA_API_KEY="your-daytona-key"
export MODAL_TOKEN_ID="your-modal-token"
export MODAL_TOKEN_SECRET="your-modal-secret"
```

## Development Commands

### Running the CLI

```bash
# Run during development
uv run nami

# Run with reinstall
make run_reinstall
```

### Testing

```bash
# Run unit tests (socket disabled for isolation)
make test

# Run specific test file
make test TEST_FILE=tests/unit_tests/test_specific.py

# Run integration tests
make test_integration

# Run all tests
make test_all

# Run tests with coverage
make test_cov

# Run tests in watch mode
make test_watch
```

### Code Quality

```bash
# Format code (ruff format + ruff check --fix)
make format

# Check linting without fixing
make lint
```

### Cleanup

```bash
make clean  # Remove build artifacts, caches, egg-info
```

## Architecture

### Deep Agent Pattern

Nami-Code implements the "Deep Agent" architecture with four core components:

1. **Planning tool** (`write_todos`) - Task decomposition and tracking for complex multi-step work
2. **Subagents** (`task` tool) - Parallel delegation with context isolation for independent subtasks
3. **File system access** - Context offloading via CompositeBackend combining local filesystem and remote sandbox backends
4. **Detailed prompts** - Persistent memory via agent.md files loaded at session start

### Middleware Stack

Middleware is applied sequentially during agent creation (in `agent.py:create_agent_with_config()`):

**Nami-Code Custom Middleware:**
1. `AgentMemoryMiddleware` (`agent_memory.py`) - Loads persistent memory into system prompt
2. `SkillsMiddleware` (`skills/middleware.py`) - Progressive disclosure skill system
3. `ShellMiddleware` (`shell.py`) - Local shell command execution (local mode only)
4. `MCPMiddleware` (`mcp/middleware.py`) - Model Context Protocol tools
5. `SharedMemoryMiddleware` (`shared_memory.py`) - Cross-agent communication
6. `FileTrackerMiddleware` (`file_tracker.py`) - Track file operations

**DeepAgent Core Middleware** (applied by `create_deep_agent()` in `graph.py`):
7. `TodoListMiddleware` - Planning with `write_todos` tool
8. `FilesystemMiddleware` - File operations (ls, read, write, edit, glob, grep, execute)
9. `SubAgentMiddleware` - Subagent spawning via `task` tool
10. `SummarizationMiddleware` - Context summarization (triggers at 70% usage)
11. `AnthropicPromptCachingMiddleware` - Token optimization
12. `PatchToolCallsMiddleware` - Dangling tool call handling

**Optional:**
13. `HumanInTheLoopMiddleware` - Tool approval (if configured with `interrupt_on`)

### Backend Architecture

**BackendProtocol** defines the interface for all storage backends in `deepagents-nami/backends/protocol.py`:

| Method | Purpose |
|--------|---------|
| `ls_info(path)` | List directory contents with metadata |
| `read(path, offset, limit)` | Read file with line numbers (cat -n format) |
| `write(path, content)` | Create new file (WriteResult with state update) |
| `edit(path, old, new, replace_all)` | String replacement (EditResult) |
| `grep_raw(pattern, path, glob)` | Search files (literal string matching) |
| `glob_info(pattern, path)` | Find files by glob pattern |
| `upload_files(files)` | Upload batch of files |
| `download_files(paths)` | Download batch of files |

**SandboxBackendProtocol** extends BackendProtocol with:

| Method | Purpose |
|--------|---------|
| `execute(command)` | Run shell commands (returns output, exit_code, truncation flag) |
| `id` | Unique sandbox identifier |

**Available Backends:**

| Backend | Location | Storage Location | Persistence |
|---------|----------|------------------|-------------|
| `FilesystemBackend` | `filesystem.py` | Real filesystem | Permanent |
| `StateBackend` | `state.py` | LangGraph state | Ephemeral (per thread) |
| `StoreBackend` | `store.py` | LangGraph Store | Permanent (cross-thread) |
| `CompositeBackend` | `composite.py` | Routes to multiple backends by path prefix | Varies by backend |

**CompositeBackend Pattern** combines multiple backend types:
- Files routed by path prefix to appropriate backend
- Enables seamless local + sandbox operation
- Default: local filesystem for `/`, sandbox for `/workspace`

### Memory Systems

**Agent Memory** (`agent_memory.py`):
- Persistent memory via `agent.md` files
- Global: `~/.nami/agents/default/agent.md` - Agent personality and universal preferences
- Project: `.nami/NAMI.md` or `.claude/CLAUDE.md` - Project-specific context

**Shared Memory** (`shared_memory.py`):
- Cross-agent communication via LangGraph InMemoryStore
- Memory entries include attribution (author, timestamp, tags)
- Namespace: `("shared_memory",)`
- Accessible to main agent and all subagents

**File Tracker** (`file_tracker.py`):
- Tracks read/write operations during session
- Provides context-aware file operation suggestions
- Session-scoped (reset on new session)

### Skills System

**Location**: `namicode_cli/skills/`

Skills follow Anthropic's progressive disclosure pattern:
- Metadata (name + description) injected into system prompt
- Full instructions loaded from `SKILL.md` when skill is invoked
- Supports both global (`~/.nami/agents/{AGENT_NAME}/skills/`) and project-specific (`.nami/skills/`) skills

### Skill Management

```bash
# List all available skills
nami skills list

# Create a new skill
nami skills create my-skill

# Create project-specific skill
nami skills create my-skill --project

# View skill details
nami skills info web-research
```

### Skill Structure:
```
~/.nami/agents/default/skills/
├── web-research/
│   ├── SKILL.md        # YAML frontmatter + instructions
│   └── helper.py       # Optional supporting files
```

## MCP Integration

**Location**: `namicode_cli/mcp/`

Model Context Protocol servers extend agent capabilities:
- `client.py` - MultiServerMCPClient for managing multiple MCP connections
- `middleware.py` - Injects MCP tools into agent middleware chain
- `presets.py` - Preset configurations (filesystem, github, postgres, puppeteer)
- `commands.py` - CLI commands for MCP management (add, list, remove, info)

MCP tools are namespaced: `servername__toolname` (e.g., `github__search_repos`)

### MCP Management

**Preset Configurations:**
```bash
nami mcp add filesystem --preset filesystem
nami mcp add github --preset github
nami mcp add postgres --preset postgres
nami mcp add puppeteer --preset puppeteer
```

**Custom MCP Servers:**
```bash
# HTTP transport
nami mcp add custom-server --transport http --url https://example.com/mcp

# Stdio transport
nami mcp add my-server --transport stdio --command "python -m my_mcp_server"
```

**MCP Commands:**
```bash
nami mcp list          # List configured servers
nami mcp remove my-server  # Remove server
nami mcp info my-server     # View server details
```

### MCP Integration

**Location**: `namicode_cli/mcp/`

Model Context Protocol servers extend agent capabilities:
- `client.py` - MultiServerMCPClient for managing multiple MCP connections
- `middleware.py` - Injects MCP tools into agent middleware chain
- `presets.py` - Preset configurations (filesystem, github, postgres, puppeteer)
- `commands.py` - CLI commands for MCP management (add, list, remove, info)

MCP tools are namespaced: `servername__toolname` (e.g., `github__search_repos`)

### Built-in Tools

**From nami-deepagents**:
- File operations: `ls`, `read_file`, `write_file`, `edit_file`, `glob`, `grep`
- Planning: `write_todos`
- Delegation: `task` (spawns subagents)
- Execution: `execute_bash` (local), `execute` (sandbox)

**From namicode_cli**:
- `web_search` - Web search via Tavily API
- `fetch_url` - Fetch and convert web pages to markdown
- `dev_server.py` - Development server management
- `test_runner.py` - Test execution

## Important Files

| File | Purpose |
|------|---------|
| `pyproject.toml` | Project metadata, dependencies, ruff/mypy/pytest configuration |
| `Makefile` | Development commands (test, lint, format, run, clean) |
| `deepagents-nami/pyproject.toml` | Core agent library configuration |
| `deepagents-nami/nami_deepagents/agent.py` | create_deep_agent() implementation |
| `namicode_cli/main.py` | CLI entry point with REPL loop |
| `namicode_cli/agent.py` | Agent creation with middleware stack configuration |
| `namicode_cli/config.py` | Model provider and settings configuration |
| `namicode_cli/execution.py` | Task streaming and approval handling |
| `.env.template` | Environment variable template |
| `CLAUDE.md` | Claude-specific development guidance |

## Common Workflows

### Creating New Middleware

1. Inherit from `AgentMiddleware` base class
2. Define state schema extending `AgentState`
3. Implement `__call__` method to wrap model requests/responses
4. Add to middleware stack in `agent.py:create_agent_with_config()`
5. Order matters - middleware is applied sequentially

### Adding New Sandbox Provider

1. Create provider file in `namicode_cli/integrations/` (e.g., `new_provider.py`)
2. Implement `SandboxBackendProtocol` interface
3. Add provider factory case in `sandbox_factory.py`
4. Update documentation and CLI help text

### Creating New Skills

1. Create skill directory: `~/.nami/agents/default/skills/my-skill/`
2. Add `SKILL.md` with YAML frontmatter containing name and description
3. Add optional `helper.py` for supporting functions
4. Skill becomes available to agent (metadata loaded, full instructions on use)

## Testing

### Test Structure

- **Unit Tests**: `tests/unit_tests/` - Socket disabled (`--disable-socket --allow-unix-socket`) for isolation
- **Integration Tests**: `tests/integration_tests/` - Full I/O allowed, includes conftest.py fixtures
- **DeepAgents Tests**: `deepagents-nami/tests/` - Core library tests

### Testing Framework

- **pytest** with 10-second default timeout (configurable per-test)
- **pytest-asyncio** for async test support
- **pytest-cov** for coverage reporting
- **pytest-xdist** for parallel execution

### Running Tests

```bash
make test                           # Unit tests (default)
make test_integration              # Integration tests
make test_all                      # All tests
make test_cov                      # With coverage report
make test_watch                    # Watch mode
```

## Code Style and Conventions

### Linting and Formatting

**Primary Tool**: ruff (handles both linting and formatting)

Configuration in `pyproject.toml`:
- Line length: 100 characters
- Docstring convention: Google-style
- All rules enabled with specific ignores for practical development

**Ignored Rules** (per `pyproject.toml`):
```python
COM812      # Conflicts with formatter
ISC001      # Conflicts with formatter
PERF203     # Rarely useful
SLF001      # Private member access (needed for middleware patterns)
PLC0415     # Import position (dynamic loading required)
PLR0913     # Too many arguments
C901        # Function complexity
```

**Per-file ignores**:
- `namicode_cli/cli.py`: T201 (print statements allowed in CLI)
- `tests/*`: D1, S101, S311, ANN201, INP001, PLR2004

### Type Checking

**mypy** configured in strict mode with reduced strictness:
```toml
[tool.mypy]
strict = true
ignore_missing_imports = true
disallow_any_generics = false
warn_return_any = false
```

### Naming Conventions

| Element | Convention | Examples |
|---------|------------|----------|
| Modules | `snake_case.py` | `file_ops.py`, `test_runner.py` |
| Classes | `PascalCase` | `CompositeBackend`, `SandboxBackendProtocol` |
| Functions/Variables | `snake_case()` | `get_shared_store()`, `agent_memory` |
| Constants | `SCREAMING_SNAKE_CASE` | `MAX_TOKENS`, `DEFAULT_MODEL` |
| Private Methods | `_snake_case()` | `_format_write_file_description()` |
| Test Files | `test_*.py` | `test_agent.py`, `test_config.py` |
| Test Functions | `snake_case()` | `test_format_write_file_description_create_new_file()` |

### Docstrings

Google-style docstrings required:
```python
def get_shared_store() -> InMemoryStore:
    """Get or create the shared InMemoryStore for agent/subagent communication.

    Returns:
        Shared InMemoryStore instance
    """
```

## Working with deepagents-nami

The `deepagents-nami/` directory is a **local dependency** linked via:
```toml
[tool.uv.sources]
nami-deepagents = { path = "./deepagents-nami" }
```

**Development pattern:**
1. Make changes in `deepagents-nami/nami_deepagents/`
2. Changes are immediately available to `namicode_cli/` (no reinstall with `uv run`)
3. Run tests from both directories if applicable
4. Coordinate changes that span both codebases

## Memory File Locations

- **Global agent**: `~/.nami/agents/<name>/agent.md`
- **Project agent**: `.nami/NAMI.md` or `.claude/CLAUDE.md`
- **Skills**: `~/.nami/agents/<name>/skills/` (global), `.nami/skills/` (project)
- **MCP config**: `~/.nami/mcp-config.json`

## Error Handling

### Error Taxonomy (`namicode_cli/errors/taxonomy.py`)

Errors are classified for appropriate recovery strategies:

```python
class ErrorCategory(Enum):
    USER_ERROR = "user_error"
    FILE_NOT_FOUND = "file_not_found"
    PERMISSION_DENIED = "permission_denied"
    COMMAND_NOT_FOUND = "command_not_found"
    SYNTAX_ERROR = "syntax_error"
    NETWORK_ERROR = "network_error"
    CONTEXT_OVERFLOW = "context_overflow"
    TOOL_ERROR = "tool_error"
    SYSTEM_ERROR = "system_error"

@dataclass
class RecoverableError:
    category: ErrorCategory
    original_error: Exception
    context: dict
    recovery_suggestion: str
    user_message: str
    retry_allowed: bool = True
```

### Error Recovery (`namicode_cli/errors/handlers.py`)

| Strategy | Purpose |
|----------|---------|
| `FileNotFoundRecovery` | Handle missing files |
| `PermissionDeniedRecovery` | Handle permission issues |
| `ContextOverflowRecovery` | Handle context/window overflow |
| `NetworkErrorRecovery` | Handle network issues with exponential backoff (1s, 2s, 4s) |
| `CommandNotFoundRecovery` | Handle missing commands |

**Error Handler Features:**
- Automatic error classification
- Recovery suggestions for users
- Exponential backoff for network errors
- Graceful sandbox-specific error handling

## Key Deep Agent Components

### create_deep_agent() (`deepagents-nami/nami_deepagents/graph.py`)

The core factory function that creates LangGraph-based deep agents. Key parameters:

```python
def create_deep_agent(
    model: str | BaseChatModel | None = None,
    tools: Sequence[BaseTool | Callable | dict[str, Any]] | None = None,
    system_prompt: str | None = None,
    middleware: Sequence[AgentMiddleware] = (),
    subagents: list[SubAgent | CompiledSubAgent] | None = None,
    checkpointer: Checkpointer | None = None,
    store: BaseStore | None = None,
    backend: BackendProtocol | BackendFactory | None = None,
    interrupt_on: dict[str, bool | InterruptOnConfig] | None = None,
    debug: bool = False,
    name: str | None = None,
) -> CompiledStateGraph
```

**Default middleware applied by create_deep_agent():**
- TodoListMiddleware - Planning with write_todos
- FilesystemMiddleware(backend) - File operations (ls, read, write, edit, glob, grep, execute)
- SubAgentMiddleware - Task delegation via task tool
- SummarizationMiddleware - Context management (70% trigger, 15% keep)
- AnthropicPromptCachingMiddleware - Token optimization
- PatchToolCallsMiddleware - Tool call fixes

**Default Model:** Claude Sonnet 4 (`claude-sonnet-4-5-20250929`)

## Architectural Patterns

### Design Patterns Implemented in Nami-Code:

**Factory Pattern:**
- Agent Factory (`create_deep_agent()`)
- Sandbox Factory (`create_sandbox()`)
- Model Factory (`create_model()`)

**Middleware Pattern:**
- Chain of Responsibility with sequential middleware application
- Each middleware handles specific concern independently
- Plugin architecture for easy extension

**Command Pattern:**
- CLI commands implemented as discrete handlers
- Tools follow uniform interface
- Skill commands for management operations

**Observer Pattern:**
- Real-time token and session state monitoring
- Event-driven UI updates
- Background process management

**Strategy Pattern:**
- Multiple execution environments (local vs sandbox)
- Dynamic model provider selection
- Different tool implementations per environment

**Facade Pattern:**
- Simplified interfaces for complex external APIs
- Unified tool APIs across different backends
- Single point configuration management

### Key Architectural Decisions

1. **LangGraph-Based Architecture**: Leverages LangChain ecosystem while providing advanced agent capabilities with checkpointing and streaming support.

2. **Deep Agent Pattern**: Enables hierarchical task decomposition with human oversight and parallel execution.

3. **Skills-Based Extensibility**: Following Anthropic's progressive disclosure pattern for scalable knowledge management.

4. **Multi-Provider Strategy**: Sandbox flexibility with security isolation and unified interfaces.

5. **Human-in-the-Loop Design**: Safety-first approach with configurable approval workflows.

## Project Structure

### Core Package Layout

The project follows a modular architecture with clear separation of concerns:

```
namicode_cli/
├── main.py                    # CLI entry point, argument parsing, REPL loop
├── agent.py                  # Agent creation with middleware stack
├── execution.py              # Task execution and streaming
├── config.py                 # Settings and model provider configuration
├── ui.py                     # Rich-based UI rendering
├── commands.py               # Slash command handlers
├── input.py                  # Interactive input with prompt_toolkit
├── skills/                   # Progressive disclosure skill system
├── mcp/                      # Model Context Protocol integration
├── integrations/             # Sandbox provider implementations
├── default_subagents/        # Built-in specialized subagents
├── agent_memory.py           # Persistent agent memory
├── shared_memory.py          # Cross-agent communication
├── file_tracker.py           # File operation tracking
├── onboarding.py             # Interactive first-run setup
├── doctor.py                 # System diagnostics
└── evaluation/               # Terminal-Bench evaluation framework
```

### DeepAgents Core Library (`deepagents-nami/`)

Key directory structure for the core dependency:

```
deepagents-nami/
├── nami_deepagents/
│   ├── agent.py              # create_deep_agent() implementation
│   ├── graph.py              # LangGraph Pregel state management
│   ├── backends/             # Storage backend abstractions
│   │   ├── protocol.py       # BackendProtocol interface
│   │   ├── filesystem.py     # Local filesystem backend
│   │   ├── state.py          # LangGraph state wrapper
│   │   ├── store.py          # LangGraph Store wrapper
│   │   ├── sandbox.py        # Sandbox base class
│   │   ├── composite.py      # Multi-backend router
│   │   └── utils.py          # Backend utilities
│   ├── middleware/           # Agent middleware
│   │   ├── filesystem.py     # File operation tools
│   │   ├── subagents.py      # Subagent spawning
│   │   └── patch_tool_calls.py # Tool call handling
│   └── tests/                # Core library tests
```

## Important Files

| File | Purpose |
|------|---------|
| `pyproject.toml` | Main project configuration, dependencies, tooling |
| `deepagents-nami/pyproject.toml` | Core agent library configuration |
| `Makefile` | Development commands and automation |
| `README.md` | Comprehensive project documentation |
| `CLAUDE.md` | Claude Code-specific guidance |
| `.env.template` | Environment variable template |
| `namicode_cli/main.py` | CLI entry point and REPL loop |
| `namicode_cli/agent.py` | Agent creation with middleware configuration |
| `namicode_cli/config.py` | Settings and model provider management |
| `namicode_cli/execution.py` | Task execution and approval workflows |

## Common Workflows

### Development
```bash
# Setup environment
uv venv
uv sync --all-groups

# Run tests before committing
make lint
make test

# Format code
make format

# Run CLI locally
uv run nami
```

### Adding New Features
1. Implement functionality in `namicode_cli/` modules
2. If core agent capability needed, contribute to `deepagents-nami/`
3. Add unit tests in `tests/unit_tests/`
4. Update relevant documentation

### Testing Approach
- Unit tests isolated with socket disabled
- Integration tests for full I/O scenarios
- Use `pytest.raises()` for error handling tests
- Mock external dependencies for reliability

## Additional Notes

### Version Compatibility
- Requires Python 3.11+ for modern async/await patterns
- LangChain 1.0+ compatibility requirements
- Backward compatibility maintained within semantic versioning

### Security Considerations
- Environment variable management via OS keychain
- Sandbox isolation for untrusted code execution
- Automatic .gitignore enforcement
- Input validation for file operations

### Performance Optimization
- Context summarization at 70% token usage
- Progressive disclosure reduces prompt overhead
- Efficient file operation tracking
- Background process management

This NAMI.md provides comprehensive guidance for AI assistants working with the Nami-Code project, covering architecture, development practices, and key workflows.
class SubAgent(TypedDict):
    name: str                    # How main agent calls it
    description: str             # Shown to main agent for decisions
    system_prompt: str           # Subagent personality
    tools: Sequence[...]         # Available tools
    model: NotRequired[...]      # Override default model
    middleware: NotRequired[...] # Additional middleware
    interrupt_on: NotRequired[...] # HITL configuration

class CompiledSubAgent(TypedDict):
    name: str
    description: str
    runnable: Runnable           # Pre-built LangGraph graph
    color: NotRequired[str]      # Output color (hex)
```

## Entry Point Flow

```
cli_main() [main.py:entry point]
    │
    ▼
parse_args() [main.py]
    ├── Interactive mode → run_cli_session()
    ├── Commands (list, help, reset) → execute directly
    └── Skills/MCP → setup subparser → execute command
    │
    ▼
run_cli_session() [main.py]
    │
    ├─> create_model() [config.py] → Detect LLM provider
    ├─> create_sandbox() [sandbox_factory.py] → Remote execution (optional)
    ├─> create_agent_with_config() [agent.py]
    │   └─> create_deep_agent() [graph.py]
    │       └─> Builds LangGraph Pregel graph
    │           with middleware stack
    │
    └─> simple_cli() [main.py:interactive loop]
        └─> execute_task() [execution.py]
            └─> agent.astream()
                └─> Middleware chain → LLM → Tools
```

## Sandbox Integration

**Factory Pattern** (`integrations/sandbox_factory.py:49-314`):

```python
create_sandbox(provider: str, **kwargs) → SandboxBackendProtocol
```

| Provider | File | Features |
|----------|------|----------|
| `modal` | modal.py | Modal cloud execution |
| `daytona` | daytona.py | Daytona workspace |
| `runloop` | runloop.py | Runloop sandbox |
| `docker` | docker.py | Docker containers |
| `e2b` | e2b_executor.py | E2B cloud code interpreter |

**SandboxProvider Configuration** (`integrations/sandbox_factory.py`):

Each provider implements `SandboxBackendProtocol` with:
- `execute(command)` → ExecuteResponse (output, exit_code, truncation flag)
- `upload_files(files)` → List[FileUploadResponse]
- `download_files(paths)` → List[FileDownloadResponse]
- `id` property → Unique sandbox identifier

**Sandbox Selection:**
- Default: Local mode (no sandbox)
- Optional: `--sandbox <provider>` flag to enable remote execution
- Provider auto-detection based on available API keys

## Configuration File Locations

| Setting | Location |
|---------|----------|
| API Keys | OS keyring or `~/.nami/.env` or `.env` file |
| Global Agents | `~/.nami/agents/{agent_name}/agent.md` |
| MCP Configuration | `~/.nami/mcp.json` |
| Project Memory | `.nami/NAMI.md` or `.claude/CLAUDE.md` or `CLAUDE.md` |
| Skills | `~/.nami/{agent}/skills/` or `.nami/skills/` |
| Session State | `~/.nami/sessions/` |

## CLI Commands Reference

| Command | Purpose |
|---------|---------|
| `nami` | Interactive mode (default) |
| `nami init` | Initialize project/global config |
| `nami list` | List available agents |
| `nami reset --agent <name>` | Reset agent state |
| `nami skills list\|add\|remove` | Skills management |
| `nami mcp list\|add\|remove\|run` | MCP server management |
| `nami config show\|set\|get` | Configuration management |
| `nami secrets set\|list\|remove` | API key management |
| `nami doctor` | System diagnostics |
| `nami paths list\|allow\|deny` | Path approval management |
| `nami migrate` | Directory structure migration |
| `nami --sandbox <provider>` | Run in sandbox mode |

## Version Information

| Component | Version |
|-----------|---------|
| Package Name | `namicode-cli` |
| Current Version | 0.0.10 (pyproject.toml) |
| Core Library Version | 0.2.8 (deepagents-nami/pyproject.toml) |
| Python Range | `>=3.11,<4.0` |
| Entry Point | `nami = namicode_cli.main:cli_main` |

## Security Features

- **.gitignore enforcement**: Files in `.gitignore` are never accessed by the agent
- **Path validation**: FilesystemMiddleware validates paths to prevent directory traversal
- **Sandbox isolation**: Remote execution runs in isolated containers/VMs
- **Human-in-the-loop**: Potentially destructive operations require approval (unless `--auto-approve`)
- **Path approval system**: Unapproved directories require explicit user permission before access

## File Operations Best Practices

### Pattern for Codebase Exploration

1. **First scan**: `read_file(path, limit=100)` - See file structure and key sections
2. **Targeted read**: `read_file(path, offset=100, limit=200)` - read_file specific sections if needed
3. **Full read**: Only use `read_file(path)` without limit when necessary for editing

### When to Paginate

- Reading any file >500 lines
- Exploring unfamiliar codebases (always start with limit=100)
- Reading multiple files in sequence
- Any research or investigation task

### read_file-Before-edit Rule

You MUST read a file before editing it. The system tracks all file reads and will reject edit operations on files you haven't read in the session.

## Recommended Patterns for AI Assistants

### Working with Subagents

**When to delegate:**
- Domain expertise needed: Task matches a specialized agent's expertise
- Complex multi-step work: Research + analysis + synthesis
- Context isolation beneficial: Task would bloat the main context window

**When NOT to delegate:**
- Simple 1-2 step tasks
- Task doesn't match any specialized agent
- User explicitly asks YOU (the main agent) to do it

**Delegation pattern:**
1. Identify task requires specialization
2. Choose appropriate subagent based on domain
3. Prepare clear, complete instructions
4. Delegate: `task(description="...", subagent_type="agent-name")`
5. Receive synthesized result
6. Integrate into final response to user

### Using Skills

Skills follow a progressive disclosure pattern:

1. **Recognition**: User request matches skill's description
2. **Load**: read_file skill's full instructions from `SKILL.md`
3. **Execute**: Follow the skill's step-by-step workflow
4. **Access**: Use helper scripts with absolute paths if provided

### Code Quality Workflow

1. Before making changes: `make lint` to check issues
2. After changes: `make format` to auto-fix formatting
3. Run tests: `make test` to verify functionality
4. Type check: `uv run mypy .` for type safety

## Common Error Patterns

| Error Type | Location | Handling |
|------------|----------|----------|
| Path validation | `file_tracker.py` | Use approved paths only |
| Socket isolation | Unit tests | Tests use `--disable-socket` |
| Token limits | `token_utils.py` | Context compaction at 70% |
| Sandbox failures | `integrations/` | Auto-fallback to local mode |
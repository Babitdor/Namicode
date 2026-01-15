# NAMI.md

This file provides guidance to AI assistants when working with code in this repository.

## Project Overview

Nami-Code is an open-source terminal-based AI coding assistant built on the `deepagents` library. It implements a "Deep Agent" architecture with planning capabilities, subagent delegation, file system access, and persistent prompts. The CLI provides interactive AI assistance with specialized subagents for code exploration, documentation, and simplification.

**Key Features:**
- Built-in tools: file operations, shell execution, web search
- Customizable skills system with progressive disclosure
- Persistent memory across sessions
- Model Context Protocol (MCP) support for external tools
- Sandbox execution: Modal, Runloop, Daytona, Docker, E2B
- Dual UI: CLI REPL and Textual TUI
- 15+ specialized subagents for domain-specific tasks

## Technology Stack

**Core:**
- Python 3.11-3.13
- LangChain DeepAgents v0.2.8 (local dependency in `deepagents-nami/`)
- LangGraph with Pregel architecture for agent orchestration

**UI & Terminal:**
- Textual (TUI framework)
- prompt-toolkit (CLI REPL)
- Rich (formatted terminal output)

**LLM Providers:**
- Anthropic (Claude Sonnet 4.5, recommended)
- OpenAI
- Ollama
- Google GenAI
- Groq

**Key Dependencies:**
- langchain-anthropic, langchain-mcp-adapters
- daytona, modal, runloop-api-client, docker, e2b-code-interpreter
- tavily-python (web search)
- pytest, ruff, mypy (development)

## Project Structure

```
namicode_cli/                 # Main CLI application
├── main.py                   # CLI entry point, REPL loop
├── app.py                    # Textual TUI application
├── TUI_main_cli.py           # TUI-specific entry point
├── agents/                   # Agent creation and configuration
│   ├── core_agent.py         # Agent factory with middleware
│   ├── default_subagents/    # Pre-built subagents
│   │   └── subagents.py      # code-explorer, code-doc, code-simplifier
│   └── named_agents.py       # Agent profile management
├── config/                   # Configuration management
│   ├── config.py             # Settings, colors, UI constants
│   ├── model_create.py       # Model factory
│   └── model_manager.py      # Model configuration
├── commands/                 # CLI command handlers
├── integrations/             # Sandbox providers
│   ├── sandbox_factory.py    # Factory for sandbox backends
│   ├── modal.py
│   ├── runloop.py
│   ├── daytona.py
│   ├── docker.py
│   └── e2b_executor.py
├── mcp/                      # Model Context Protocol
│   ├── middleware.py         # MCP middleware
│   ├── client.py             # MultiServerMCPClient
│   └── presets.py            # Preset configurations
├── skills/                   # Skills system
│   ├── middleware.py         # Skills middleware
│   ├── load.py               # Skill loading
│   └── skill_creation.py     # LLM-powered skill creation
├── session/                  # Session persistence
│   ├── session_persistence.py
│   ├── session_restore.py
│   └── session_prompt_builder.py
├── ui/                       # Rich-based UI rendering
├── widgets/                  # 15+ Textual TUI widgets
├── memory/                   # Memory systems
│   ├── agent_memory.py       # Persistent agent memory
│   └── shared_memory.py      # Cross-agent communication
├── tracking/                 # Tracking systems
│   ├── file_tracker.py       # File operation tracking
│   ├── workspace_anchoring.py
│   └── tracing.py            # LangSmith integration
└── errors/                   # Error handling

deepagents-nami/              # Core agent library (local dependency)
├── nami_deepagents/
│   ├── agent.py              # create_deep_agent() implementation
│   ├── graph.py              # Main agent factory (LangGraph Pregel)
│   ├── backends/             # Backend abstraction layer
│   │   ├── protocol.py       # BackendProtocol interfaces
│   │   ├── composite.py      # CompositeBackend routing
│   │   ├── filesystem.py     # Local filesystem ops
│   │   ├── sandbox.py        # Remote sandbox execution
│   │   ├── state.py          # In-memory state backend
│   │   └── store.py          # Persistent storage backend
│   ├── middleware/           # Agent middleware
│   │   ├── subagents.py      # SubAgentMiddleware
│   │   ├── memory.py         # MemoryMiddleware
│   │   ├── filesystem.py     # FilesystemMiddleware
│   │   ├── skills.py         # SkillsMiddleware
│   │   └── planning.py       # PlanModeMiddleware
│   └── tools/                # Built-in tools

evaluation/                   # Terminal-Bench evaluation framework
acp/                          # Agent Client Protocol support (WIP)
tests/
├── unit_tests/               # Fast, isolated tests
└── integration_tests/        # Slower, cross-component tests
```

## Development Setup

### Prerequisites
- Python 3.11, 3.12, or 3.13
- uv (recommended) or pip

### Installation

```bash
# Clone repository
git clone https://github.com/Babitdor/namicode-cli.git
cd namicode-cli

# Create virtual environment and install dependencies
uv venv
uv sync --all-groups

# Install in editable mode
uv pip install -e .
```

### Environment Configuration

Copy `.env.template` to `.env` and configure API keys:

```bash
# Required (choose one or both)
OPENAI_API_KEY=your_key_here
ANTHROPIC_API_KEY=your_key_here

# Optional (for web search)
TAVILY_API_KEY=your_key_here

# Optional (for sandboxes)
E2B_API_KEY=your_key_here
```

API keys can also be stored in OS keychain (primary method) or `~/.nami/secrets.json` (fallback).

## Development Commands

### Running the CLI

```bash
# Run CLI (development mode)
make run
# or
uv run nami

# Run with specific agent
uv run nami --agent <agent_name>

# Continue previous session
uv run nami --continue

# Run with sandbox
uv run nami --sandbox <modal|daytona|docker|runloop>
```

### Testing

```bash
make test                  # Unit tests only
make test_integration      # Integration tests only
make test_all              # All tests
make test_cov              # With coverage report
make test_watch            # Watch mode (ptw)

# Run specific test file
make test TEST_FILE=tests/unit_tests/tools/test_file_ops.py
```

### Code Quality

```bash
make lint                  # Check format and linting
make format                # Format and fix issues

# Type checking
uv run mypy namicode_cli/

# Clean build artifacts
make clean
```

### Building Package

```bash
uv build                  # Build wheel and sdist
```

## Architecture

### Key Architectural Patterns

**1. LangGraph Pregel Architecture**
- CompiledStateGraph with checkpointing for conversation persistence
- State management through LangGraph StateGraph
- Message passing between nodes (agent, tools, human-in-the-loop)

**2. CompositeBackend Pattern**
- Routes file operations to different backends based on path prefixes
- Example: `/memories/` → memory backend, `/workspace/` → sandbox backend
- Implemented in `deepagents-nami/nami_deepagents/backends/composite.py`

**3. Middleware Pipeline**
Sequential middleware applied to agent execution:

**Main Agent Middleware Stack:**
1. TodoListMiddleware - Task management with `write_todos` tool
2. MemoryMiddleware - Persistent context from AGENTS.md files
3. SkillsMiddleware - Progressive disclosure skills system
4. MCPMiddleware - Model Context Protocol external tools
5. FilesystemMiddleware - File operations
6. SubAgentMiddleware - Subagent delegation via `task` tool
7. SummarizationMiddleware - Context management
8. AnthropicPromptCachingMiddleware - Performance optimization
9. PatchToolCallsMiddleware - Dangling tool call handling
10. HumanInTheLoopMiddleware - Interruption handling

**CLI Agent Middleware Stack** (in `core_agent.py:create_agent_with_config()`):
1. FileTrackerMiddleware - Read-before-edit enforcement
2. SkillsMiddleware - Agent skills
3. MCPMiddleware - External tools
4. SharedMemoryMiddleware - Cross-agent communication
5. ShellMiddleware - Shell execution
6. MemoryMiddleware - Persistent context

**4. Subagent Delegation**
- Main agent spawns specialized subagents via `task` tool
- Subagents have lighter middleware stack (no recursion)
- Ephemeral isolation with cross-agent communication via shared memory

**5. Backend Abstraction**
- Protocol-oriented design: `BackendProtocol` and `SandboxBackendProtocol`
- Pluggable backends: FilesystemBackend, StateBackend, StoreBackend, CompositeBackend
- Sandbox implementations: Modal, Runloop, Daytona, Docker, E2B

**6. Factory Pattern**
- `sandbox_factory.py` creates appropriate sandbox backend based on configuration
- Model factory in `config/model_create.py` for LLM provider instantiation

**7. Dual UI Architecture**
- CLI REPL (`main.py`) and Textual TUI (`app.py`)
- Share core execution logic via `textual_adapter.py`

### Main Modules

**Core Agent System:**
- `core_agent.py` - Agent creation with 6-10 middleware layers
- `graph.py` (deepagents) - create_deep_agent() using LangGraph Pregel
- `backends/` (deepagents) - Backend abstraction layer
- `middleware/` (deepagents) - Middleware implementations

**Sandbox Integration:**
- `sandbox_factory.py` - Unified sandbox interface
- Provider implementations: modal.py, runloop.py, daytona.py, docker.py, e2b_executor.py

**Extension Systems:**
- `skills/` - Progressive disclosure with 3-level pattern (metadata → path → content)
- `mcp/` - Model Context Protocol server management with tool namespacing

**Session Management:**
- `session_persistence.py` - Split storage (recent 8 messages + archive)
- `session_restore.py` - Workspace anchoring with drift detection
- `session_prompt_builder.py` - Context-aware continuation prompts

## Important Files

### Entry Points
- `namicode_cli/main.py:52-90` - CLI entry point, REPL loop, signal handling
- `namicode_cli/app.py:84-100` - Textual TUI application
- `namicode_cli/__main__.py` - Module execution entry point

### Configuration
- `pyproject.toml` - Project metadata, dependencies, tool configuration
- `Makefile` - Development commands (test, lint, format, run)
- `.env.template` - Environment variable template

### Core Agent
- `namicode_cli/agents/core_agent.py` - Agent factory, middleware stack
- `deepagents-nami/nami_deepagents/graph.py` - create_deep_agent() implementation
- `deepagents-nami/nami_deepagents/backends/protocol.py` - Backend protocols
- `deepagents-nami/nami_deepagents/backends/composite.py` - Multi-backend routing

### Key Components
- `namicode_cli/integrations/sandbox_factory.py` - Sandbox factory
- `namicode_cli/skills/middleware.py` - Skills middleware
- `namicode_cli/mcp/client.py` - MultiServerMCPClient
- `namicode_cli/tracking/file_tracker.py` - File operation tracking
- `namicode_cli/session/session_persistence.py` - Session persistence

### CLI/UI
- `namicode_cli/ui/execution.py` - Task execution and streaming
- `namicode_cli/widgets/` - 15+ Textual TUI components

## Common Workflows

### Adding a New Middleware

1. Inherit from `AgentMiddleware` in `deepagents-nami/nami_deepagents/middleware/base.py`
2. Define state schema extending `AgentState`
3. Implement `__call__` to wrap model requests/responses
4. Add to middleware stack in `core_agent.py:create_agent_with_config()`
5. Order matters - middleware applied sequentially

### Adding a New Sandbox Provider

1. Implement `SandboxBackendProtocol` from `backends/protocol.py`
2. Extend `BaseSandbox` from `backends/sandbox.py` for shell operations
3. Add to `sandbox_factory.py` factory
4. Test with both unit and integration tests

### Creating a New Agent Profile

1. Create directory: `~/.nami/agents/<agent_name>/`
2. Create `agent.md` with YAML frontmatter for color
3. Write system prompt in markdown
4. Reference in @agent mentions: `@agent_name`

### Modifying deepagents-nami

1. Edit files in `deepagents-nami/nami_deepagents/`
2. Changes immediately available with `uv run` (no reinstall needed)
3. Run tests in both directories if applicable

## Testing

### Framework and Structure
- **Framework:** pytest with pytest-cov, pytest-watch
- **Timeout:** Default 10 seconds per test
- **Structure:**
  - `tests/unit_tests/` - Fast, isolated tests (socket disabled via `--disable-socket`)
  - `tests/integration_tests/` - Slower, cross-component tests (with sandboxes, LangSmith)

### Running Tests

```bash
# Unit tests (fast, isolated)
make test

# Integration tests (with sandboxes)
make test_integration

# All tests
make test_all

# Coverage report
make test_cov

# Watch mode
make test_watch

# Specific test file
make test TEST_FILE=tests/unit_tests/tools/test_file_ops.py
```

### Test Conventions

- **Test files:** `test_*.py` naming convention
- **Test classes:** `TestClassName` (PascalCase)
- **Test functions:** `test_descriptive_name` (snake_case)
- **Fixtures:** Use `tmp_path: Path` for file operations
- **Assertions:** Plain `assert` statements allowed
- **Session fixtures:** LangSmith client flushes after each test (integration_tests/conftest.py)

### Testing Philosophy

- Unit tests should be fast and isolated (no external dependencies)
- Integration tests cover cross-component interactions and sandbox operations
- Use mocks for dependencies in unit tests
- Test both success and failure paths
- Timeout enforcement prevents hanging tests

## Code Style and Conventions

### Formatting
- **Tool:** ruff (formatting + linting)
- **Line length:** 100 characters
- **Rules:** ALL rules enabled by default
- **Docstrings:** Google-style convention

### Commands

```bash
make lint      # Check format and linting (ruff format --check + ruff check)
make format    # Format and fix (ruff format + ruff check --fix)
uv run mypy namicode_cli/  # Type checking
```

### Type Hints
- mypy strict mode enabled
- Use `from __future__ import annotations` for forward references
- `collections.abc` for type aliases (Generator, Mapping, etc.)
- `Literal` types for constrained values

### Naming Conventions

- **Variables/Functions:** snake_case (`_find_project_root`, `get_context_window_size`)
- **Classes:** PascalCase (`FileOpTracker`, `ApprovalPreview`)
- **Constants:** UPPER_SNAKE_CASE (`COLORS`, `HOME_DIR`, `MODEL_CONTEXT_WINDOWS`)
- **Private members:** `_underscore_prefix` (`_format_write_file_description`)

### Ruff Configuration Highlights

- Google-style docstrings
- Formatter conflicts: COM812, ISC001 ignored
- Private member access: SLF001 allowed
- Function arguments: PLR0913 flexible
- Test-specific: D1 (doc rules), S101 (asserts), S311 (random), INP001 (implicit namespace) ignored

### Common Patterns

- Use `dataclass` decorators for data models with `field()` for defaults
- Rich console for CLI output with color schemes defined in constants
- Context managers for resource management
- Explicit error handling with rich formatting

## Additional Notes

### Local Dependency

The `deepagents-nami/` directory is a local dependency linked via:
```toml
[tool.uv.sources]
nami-deepagents = { path = "./deepagents-nami" }
```

When modifying deepagents functionality:
1. Make changes in `deepagents-nami/nami_deepagents/`
2. Changes immediately available to `namicode_cli/` with `uv run`
3. Run tests in both directories

### Memory File Locations

- Global agent: `~/.nami/agents/default/agent.md`
- Project agent: `.nami/NAMI.md` or `.claude/CLAUDE.md`
- Skills: `~/.nami/skills/` (global), `.nami/skills/` (project, higher priority)
- MCP config: `~/.nami/mcp.json`
- Path approval: `~/.nami/approved_paths.json`
- Sessions: `~/.nami/sessions/<session_id>/`
- Secrets: OS keychain (primary) or `~/.nami/secrets.json` (fallback)

### CLI Commands Reference

**Slash Commands:**
- `/help` - Show available commands
- `/tokens` - Show token usage
- `/context` - Display context window usage
- `/clear` - Clear conversation
- `/exit`, `/quit` - Exit session
- `/init` - Initialize new session
- `/skills` - Manage skills
- `/mcp` - Manage MCP servers
- `/list` - List available agents
- `/continue` - Continue previous session
- `/model` - Change LLM model
- `/paths` - Manage approved paths
- `/server` - Manage development servers

**Bash Commands:**
- `!command` - Execute shell commands directly

**Subagent Invocation:**
- `@agent_name` - Invoke named subagent

### Path Approval System

The path approval system provides security for file operations:
- Tracks approved and denied paths per session
- Requires approval for operations outside approved paths
- Configuration stored in `~/.nami/approved_paths.json`
- Recursive directory approval support
- Audit trail of all approval decisions

### Troubleshooting

**Sandbox connection failures:**
- Check API keys in environment variables or keychain
- Verify network connectivity
- Run `/doctor` for diagnostic checks

**File operation errors:**
- Check `/paths` for approval status
- Verify file permissions
- Check for symlink attacks (virtual mode protection)

**Token limit exceeded:**
- Check `/context` for usage
- Consider summarization
- Use pagination for large files

**Agent not responding:**
- Check LLM provider connection
- Verify API key validity
- Run `/doctor` for diagnostics

### File Operation Rules (Enforced)

**Critical: Read-Before-Edit Rule**
You MUST read a file before editing it. The system tracks all file reads and will REJECT edit operations on files you haven't read in this session.

**Why this matters:**
- Prevents editing the wrong file or wrong location
- Ensures you have current file content before making changes
- Catches stale edits if the file changed since you last saw it

**File Operation Best Practices:**
1. **Always read first:** Before any edit_file or write_file (to existing file), use read_file
2. **Use pagination for large files:** `read_file(path, limit=100)` for initial scan
3. **Verify before edit:** Check the content you want to replace actually exists
4. **Track your changes:** The system logs all file operations for the session

### Changelog Maintenance

After implementing any feature, bug fix, refactor, or significant change:

1. Create/update changelog file in `changelog/` directory
2. Use versioning format: `changelog_v{version}.md` (e.g., `changelog_v0.1.md`)
3. Include for each entry:
   - Date of change (YYYY-MM-DD)
   - Type: **Feature**, **Bug Fix**, **Refactor**, **Documentation**, **Breaking Change**
   - Description of what changed
   - Related issue/PR number (if applicable)

### Evaluation Framework

DeepAgents Harbor (`evaluation/`) provides comprehensive benchmarking:

- **DeepAgentsWrapper** - SDK-based agent with minimal config
- **NamiCodeWrapper** - Full CLI agent with complete middleware
- **HarborSandbox** - Backend implementation for Harbor environments
- **Terminal Bench 2.0** - 90+ tasks across domains (coding, security, DevOps, AI/ML, science, gaming)
- **LangSmith Integration** - Automatic trace capture and experiment management

See `evaluation/` directory for detailed evaluation commands and workflows.
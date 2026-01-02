# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository Overview

This is a monorepo containing **Nami-Code CLI**, an open-source terminal-based AI coding assistant (similar to Claude Code), built on top of the **nami-deepagents** library.

- `Namicode-CodeAssistant-CLI/` - Main CLI application
- `Namicode-CodeAssistant-CLI/deepagents-nami/` - Core deepagents library (local dependency)

## Development Commands

### CLI (from `Namicode-CodeAssistant-CLI/`)

```bash
# Install dependencies
uv sync --all-groups

# Run the CLI (development mode)
uv run nami

# Run tests
make test                                              # All unit tests (with socket disabled)
make test TEST_FILE=tests/unit_tests/test_agent.py    # Specific test file
make test_integration                                  # Integration tests

# Code quality
make format                     # Format with Ruff
make lint                       # Check linting (Ruff + MyPy commented out)
make format_unsafe              # Format with unsafe auto-fixes
```

### Deepagents Library (from `Namicode-CodeAssistant-CLI/deepagents-nami/`)

```bash
uv pip install -e .             # Install in dev mode
make test                       # Unit tests with coverage
make integration_test           # Integration tests
make format                     # Format code
make lint                       # Lint with Ruff and MyPy
```

## Architecture

The CLI implements a "Deep Agent" pattern with four key components:

1. **Planning tool** (`write_todos`) - Task management and decomposition
2. **Sub-agents** (`task` tool) - Parallel delegation with context isolation
3. **File system access** - Multiple backends (local, sandbox)
4. **Detailed prompts** - Memory and skills systems

### CLI Module Structure (`namicode_cli/`)

| Module | Purpose |
|--------|---------|
| `main.py` | Entry point, CLI loop, argument parsing |
| `agent.py` | Agent creation via `create_agent_with_config()` |
| `config.py` | Environment, project detection, model creation |
| `execution.py` | Task execution, streaming, tool approval |
| `tools.py` | Built-in tools (http_request, fetch_url, web_search) |
| `file_ops.py` | File operations (ls, read, write, edit, glob, grep) |
| `skills/` | Progressive disclosure skill system |
| `mcp/` | Model Context Protocol integration |
| `integrations/` | Sandbox backends (Modal, Runloop, Daytona, Docker) |

### Deepagents Library (`deepagents-nami/nami_deepagents/`)

| Module | Purpose |
|--------|---------|
| `graph.py` | Main `create_deep_agent()` factory |
| `middleware/` | TodoListMiddleware, FilesystemMiddleware, SubAgentMiddleware |
| `backends/` | Storage backends (filesystem, state, store, sandbox, composite) |

## Key Patterns

### Middleware System
The agent uses composable middleware (from `langchain.agents.middleware`):
- **AgentMemoryMiddleware** (`namicode_cli/agent_memory.py`) - Loads/updates agent.md files from global and project locations
- **SkillsMiddleware** (`namicode_cli/skills/middleware.py`) - Progressive disclosure skill loading (name + description only, full content loaded on demand)
- **MCPMiddleware** (`namicode_cli/mcp/middleware.py`) - MCP tool integration for external servers
- **ShellMiddleware** (`namicode_cli/shell.py`) - Command execution with approval system
- **TodoListMiddleware** (from deepagents) - Task planning and decomposition via `write_todos` tool
- **FilesystemMiddleware** (from deepagents) - File operations (ls, read, write, edit, glob, grep)
- **SubAgentMiddleware** (from deepagents) - Spawning specialized subagents via `task` tool

### Memory Files
Agent memory is hierarchical and loaded at startup:

**Global (User-level)**:
- `~/.nami/agents/{agent_name}/agent.md` - Personal preferences across all projects
- `~/.nami/skills/` - Global skills shared across agents

**Project-level** (all existing files are merged):
- `.claude/CLAUDE.md` (Claude Code primary, highest priority)
- `CLAUDE.md` (Claude Code fallback)
- `.nami/NAMI.md` (Nami primary)
- `NAMI.md` (Nami fallback, created by `/init` command)
- `.nami/skills/` - Project-specific skills

### Backend System
The agent uses pluggable backends (implementing `BackendProtocol` from `deepagents-nami/nami_deepagents/backends/protocol.py`):

- **FilesystemBackend** - Local file operations on disk
- **SandboxBackend** - Remote execution in isolated environments (Modal, Runloop, Daytona, Docker)
- **CompositeBackend** - Combines multiple backends (e.g., sandbox for execution + local for memory)

All backends provide: `ls_info`, `read`, `write`, `edit`, `glob_info`, `grep_raw`
Sandbox backends additionally provide: `execute` (for shell commands)

### Configuration Detection
Project roots are detected by checking for these markers (in order):
1. `.git/` directory
2. `.nami/` directory
3. `.claude/` directory

## Code Style

**Line length**:
- CLI: 100 characters
- Deepagents library: 150 characters

**Linting**: Ruff with ALL rules enabled, specific ignores in `pyproject.toml`:
- `COM812`, `ISC001` - Conflicts with formatter
- `PERF203` - Rarely useful
- `SLF001` - Private member access (allowed)
- `PLC0415` - Imports at top (not always required)
- `PLR0913` - Too many arguments (allowed)
- `PLC0414` - Re-export pattern for type checkers
- `C901` - Complexity checks (disabled)

**Type checking**: MyPy strict mode
- `strict = true`
- `ignore_missing_imports = true`
- `disallow_any_generics = false`
- `warn_return_any = false`

**Other conventions**:
- Docstrings: Google-style
- Python: 3.11+, use `T | None` not `Optional[T]`
- Tests: Allow `D1` (docs), `S101` (asserts), `S311` (random), `ANN201`, `INP001`, `PLR2004`
- CLI files: Allow `T201` (print statements)

## Testing Notes

**Unit tests**:
- Default timeout: 10 seconds (configurable per-test with pytest timeout)
- Network disabled by default: `--disable-socket --allow-unix-socket`
- Use `make test` to run all unit tests
- Use `make test TEST_FILE=path/to/test.py` for specific tests

**Integration tests**:
- Network enabled (may make external calls)
- Use `make test_integration` or `make integration_test` (deepagents)

## Important Implementation Details

### Agent Creation Flow
1. `main.py` - Entry point, parses CLI args, creates prompt session
2. `config.py` - Detects project root, loads settings, creates model
3. `agent.py::create_agent_with_config()` - Assembles agent with all middleware
4. `execution.py::execute_task()` - Handles task execution, streaming, tool approval

### Tool Approval System
Potentially destructive operations require user approval via `PathApprovalManager`:
- File writes/edits outside project root
- Shell commands (unless `--auto-approve` flag)
- Configured via interrupt_on in agent creation

### Skills System (Progressive Disclosure)
Skills are defined in `SKILL.md` files with YAML frontmatter:
```yaml
---
name: skill-name
description: Brief description shown to agent
---
# Full instructions (loaded on-demand when agent reads file)
```

Agent sees only name+description at startup, reads full content when relevant.

### Deepagents Factory (`create_deep_agent`)
The `create_deep_agent()` factory in `deepagents-nami/nami_deepagents/graph.py`:
- Automatically attaches TodoList, Filesystem, and SubAgent middleware
- Accepts custom middleware, tools, subagents
- Returns a compiled LangGraph `CompiledStateGraph`
- Default model: `claude-sonnet-4-5-20250929`

### Local Dependency
The CLI depends on `nami-deepagents` as a local path dependency:
```toml
[tool.uv.sources]
nami-deepagents = { path = "./deepagents-nami" }
```

When making changes to deepagents, they're immediately available to the CLI (no reinstall needed in dev mode).

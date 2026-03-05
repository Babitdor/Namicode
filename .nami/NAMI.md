# NAMI.md

This file provides guidance to AI assistants when working with code in this repository.

## Project Overview

**Nami-Code CLI** is a terminal-based AI coding assistant built on LangGraph with a "Deep Agent" architecture. It provides:
- Agentic coding with planning tools (`write_todos`) and subagent delegation (`task` tool)
- Multiple sandbox backends for safe code execution (Modal, Daytona, Docker, E2B, Runloop)
- Persistent agent memory via `agent.md` files
- Progressive skill disclosure system
- Model Context Protocol (MCP) integration for extended capabilities
- Rich terminal UI with multiline input support

## Technology Stack

| Category | Technologies |
|----------|-------------|
| **Language** | Python 3.11+ (3.11, 3.12, 3.13 supported) |
| **Agent Framework** | LangChain, LangGraph |
| **LLM Providers** | Anthropic (default), OpenAI, Google Gemini, Ollama |
| **Terminal UI** | Rich, prompt-toolkit |
| **Sandbox Backends** | Modal, Daytona, Docker, E2B, Runloop |
| **Protocol Support** | MCP (Model Context Protocol) |
| **Testing** | pytest, pytest-asyncio, pytest-cov |
| **Linting/Formatting** | Ruff (primary), Black, MyPy (strict mode) |
| **Package Manager** | uv (recommended), pip |

## Project Structure

```
namicode-cli/
├── namicode_cli/              # Main CLI package
│   ├── main.py                # Entry point (cli_main)
│   ├── __main__.py            # Module entry (python -m namicode_cli)
│   ├── agents/                # Agent creation and management
│   │   ├── core_agent.py      # Agent creation with LangGraph
│   │   ├── named_agents.py    # Named agent configurations
│   │   ├── commands.py        # Agent commands
│   │   └── default_subagents/ # Default subagent definitions
│   ├── config/                # Configuration and settings
│   │   ├── config.py          # Main configuration
│   │   ├── model_create.py    # Model creation utilities
│   │   ├── model_manager.py   # Model management
│   │   └── default_agent_prompt.md # Default system prompt
│   ├── integrations/          # Sandbox backend integrations
│   │   ├── sandbox_factory.py # Factory for creating backends
│   │   ├── modal.py           # Modal cloud sandbox
│   │   ├── daytona.py         # Daytona sandbox
│   │   ├── runloop.py        # Runloop sandbox
│   │   ├── docker.py          # Docker sandbox
│   │   └── e2b_executor.py    # E2B code execution
│   ├── mcp/                   # Model Context Protocol
│   │   ├── client.py          # MCP client
│   │   ├── middleware.py      # MCP middleware
│   │   ├── commands.py        # MCP commands
│   │   └── presets.py         # MCP server presets
│   ├── skills/                 # Skill system
│   │   ├── load.py            # Skill loading
│   │   ├── middleware.py      # Skill middleware
│   │   └── skill_creation.py  # Skill creation utilities
│   ├── memory/                # Memory management
│   │   ├── agent_memory.py    # Agent memory persistence
│   │   └── shared_memory.py   # Shared memory system
│   ├── session/               # Session management
│   │   ├── session_persistence.py # Session save/restore
│   │   ├── session_restore.py  # Session restoration
│   │   └── session_summarization.py # Session summarization
│   ├── ui/                    # Terminal UI
│   │   ├── ui_elements.py     # UI components
│   │   ├── execution.py       # Execution display
│   │   └── question_prompt.py # Question prompts
│   ├── tools.py               # Core tools (file, web, code)
│   ├── browser_tools.py       # Playwright browser automation
│   ├── git_tools.py           # Git operations
│   ├── file_ops.py            # File operation tools
│   ├── semantic_search.py     # Code semantic search
│   └── shell.py               # Shell command execution
├── deepagents-nami/           # Core agent library
│   └── nami_deepagents/
│       ├── graph.py           # LangGraph agent definition
│       ├── backends/          # Backend protocols
│       │   ├── protocol.py    # Backend protocol definitions
│       │   ├── filesystem.py  # Local filesystem backend
│       │   ├── sandbox.py     # Sandbox backend base
│       │   └── composite.py   # Multi-backend composition
│       └── middleware/        # Agent middleware
│           ├── filesystem.py  # File operations middleware
│           ├── memory.py      # Memory middleware
│           ├── skills.py      # Skills middleware
│           ├── subagents.py   # Subagent middleware
│           └── patch_tool_calls.py # Tool call patching
├── tests/                     # Test suite
│   ├── unit_tests/            # Unit tests
│   ├── integration_tests/     # Integration tests
│   └── security/              # Security tests
├── evaluation/                # Terminal-Bench evaluation
│   └── terminal-bench-2/      # Benchmark environments
├── acp/                       # Agent Communication Protocol
├── nami-scripts/              # Utility scripts
├── docs/                      # Documentation
└── pyproject.toml             # Project configuration
```

## Development Setup

### Prerequisites
- Python 3.11+ (supports 3.11, 3.12, 3.13)
- uv package manager (recommended) or pip

### Installation

```bash
# Clone and setup
git clone https://github.com/Babitdor/namicode-cli.git
cd namicode-cli

# Create virtual environment and install
uv venv
uv sync --all-groups

# Configure environment
cp .env.template .env
# Edit .env with your API keys
```

### Environment Variables

**Required:**
- `ANTHROPIC_API_KEY` - Claude models (default provider)
- `OPENAI_API_KEY` - GPT models
- `GOOGLE_API_KEY` - Gemini models

**Optional:**
- `OLLAMA_HOST` - Local Ollama server (default: http://localhost:11434)
- `TAVILY_API_KEY` - Web search
- `RUNLOOP_API_KEY` - Runloop sandbox
- `DAYTONA_API_KEY` - Daytona sandbox
- `E2B_API_KEY` - E2B sandbox
- `LANGSMITH_API_KEY` - LangSmith tracing

## Development Commands

### Running the CLI
```bash
uv run nami                           # Standard run
uv run nami --agent mybot             # Specific agent
uv run nami --auto-approve            # Skip prompts
uv run nami --sandbox modal           # Modal sandbox
uv run nami --sandbox e2b             # E2B sandbox
uv run nami --sandbox docker          # Docker sandbox
uv run nami doctor                    # System diagnostics
```

### Testing
```bash
make test                    # Unit tests
make test_integration        # Integration tests
make test_all               # All tests
make test_cov               # Tests with coverage
make test_watch             # Watch mode
```

### Code Quality
```bash
make format                 # Format with ruff
make lint                   # Check formatting and linting
make clean                  # Remove build artifacts
```

### Makefile Targets
| Target | Description |
|--------|-------------|
| `run` | Run Nami CLI |
| `run_reinstall` | Reinstall and run |
| `test` | Run unit tests (pytest tests/unit_tests) |
| `test_integration` | Run integration tests |
| `test_all` | Run all tests |
| `test_cov` | Run tests with coverage |
| `lint` | Check formatting + linter |
| `format` | Format code with ruff |
| `clean` | Remove build artifacts |

## Architecture

### Core Pattern: Modular Monorepo with Plugin Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     CLI Layer (main.py)                         │
│  - Argument parsing, Interactive REPL, Session management      │
└─────────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────────┐
│                 Agent Layer (agents/)                           │
│  - Core agent creation, Subagent delegation, Memory management │
└─────────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────────┐
│              Middleware Layer (nami_deepagents/middleware/)    │
│  - FilesystemMiddleware, MemoryMiddleware, SkillsMiddleware    │
│  - SubAgentMiddleware, ShellMiddleware, MCPMiddleware          │
└─────────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────────┐
│               Backend Layer (backends/)                         │
│  - FilesystemBackend (local), SandboxBackend (cloud/container)  │
│  - CompositeBackend (multi-backend)                             │
└─────────────────────────────────────────────────────────────────┘
```

### Key Architectural Patterns

1. **LangGraph State Machine**: Core agent uses `CompiledStateGraph` for conversation state and tool execution
2. **Middleware Pattern**: Pluggable middleware for extending agent capabilities
3. **Backend Protocol Pattern**: Abstract backend interface with multiple implementations
4. **Factory Pattern**: `sandbox_factory.py` creates appropriate sandbox backends
5. **Repository Pattern**: Session persistence via SQLite backend

### Sandbox Backends

| Provider | Working Dir | API Key | Use Case |
|----------|------------|---------|----------|
| Local | Project root | None | Default development |
| Modal | `/workspace` | Modal SDK | Cloud sandbox |
| Runloop | `/home/user` | `RUNLOOP_API_KEY` | Cloud sandbox |
| Daytona | `/home/daytona` | `DAYTONA_API_KEY` | Dev environments |
| Docker | `/workspace` | None | Container isolation |
| E2B | - | `E2B_API_KEY` | Code execution |

## Important Files

| File | Purpose |
|------|---------|
| `namicode_cli/main.py` | CLI entry point, argument parsing, main loop |
| `namicode_cli/agents/core_agent.py` | Agent creation with LangGraph |
| `namicode_cli/config/config.py` | Configuration management |
| `namicode_cli/integrations/sandbox_factory.py` | Sandbox backend factory |
| `namicode_cli/tools.py` | Core tools (file, web, code operations) |
| `namicode_cli/browser_tools.py` | Playwright browser automation |
| `namicode_cli/mcp/client.py` | MCP client implementation |
| `namicode_cli/skills/load.py` | Skill loading system |
| `deepagents-nami/nami_deepagents/graph.py` | Deep agent graph definition |
| `deepagents-nami/nami_deepagents/backends/protocol.py` | Backend protocol definitions |
| `pyproject.toml` | Project configuration, dependencies |
| `Makefile` | Build/test commands |

## Common Workflows

### Adding a New Tool
1. Define tool function in appropriate module (`tools.py`, `browser_tools.py`, etc.)
2. Add tool to agent's tool list in `agents/core_agent.py`
3. Add tests in `tests/unit_tests/`

### Adding a New Sandbox Backend
1. Create new integration in `namicode_cli/integrations/`
2. Implement `SandboxBackendProtocol` from `backends/protocol.py`
3. Register in `sandbox_factory.py`
4. Add configuration in `config/config.py`

### Adding a New Skill
1. Create skill directory in user's `.nami/skills/` or project's `skills/`
2. Add `SKILL.md` with instructions
3. Optionally add helper scripts
4. Skill is auto-loaded on startup

### Running Tests
```bash
# Unit tests
make test

# Specific test file
uv run pytest tests/unit_tests/test_specific.py -v

# Integration tests
make test_integration

# With coverage
make test_cov
```

## Testing

### Test Structure
```
tests/
├── unit_tests/           # Fast, isolated tests
│   ├── mcp/              # MCP client tests
│   ├── skills/           # Skills system tests
│   └── tools/            # Tool tests
├── integration_tests/    # Integration tests
│   └── benchmarks/       # Benchmark tests
└── security/            # Security tests
```

### Test Configuration
- **Framework**: pytest with pytest-asyncio
- **Timeout**: 10 seconds default
- **Async Mode**: Auto (pytest-asyncio)
- **Coverage**: pytest-cov

### Running Tests
```bash
make test                    # Unit tests only
make test_integration        # Integration tests
make test_all               # All tests
uv run pytest tests/unit_tests/test_file.py -v  # Specific file
```

## Code Style and Conventions

### Linting/Formatting
- **Primary Tool**: Ruff (ALL rules enabled)
- **Line Length**: 100 characters (150 in deepagents-nami)
- **Docstring Style**: Google-style
- **Type Checking**: MyPy strict mode

### Ruff Configuration
```toml
[tool.ruff]
line-length = 100
select = ["ALL"]  # Enable all rules

# Ignored rules:
# COM812, ISC001 - Formatter conflicts
# PERF203 - Rarely useful
# SLF001 - Private member access
# PLC0415 - Imports at top
# PLR0913 - Too many arguments
# C901 - Too complex
```

### MyPy Configuration
```toml
[tool.mypy]
strict = true
ignore_missing_imports = true
```

### Naming Conventions
- Test files: `test_*.py`
- Test classes: `Test*` prefix
- Test functions: `test_*` prefix
- Fixtures: `conftest.py`

### Import Organization
Standard library → Third-party → Local imports

## Key Dependencies

### Core Dependencies
| Package | Purpose |
|---------|---------|
| `langchain` | LLM framework core |
| `langchain-anthropic` | Claude model integration |
| `langchain-openai` | GPT model integration |
| `langchain-ollama` | Local Ollama integration |
| `langchain-google-genai` | Gemini integration |
| `langgraph` | State machine for agents |
| `rich` | Terminal UI |
| `prompt-toolkit` | Interactive input |
| `mcp` | Model Context Protocol |
| `aiosqlite` | Async SQLite for sessions |

### Sandbox Dependencies
| Package | Purpose |
|---------|---------|
| `modal` | Modal cloud sandbox |
| `daytona` | Daytona dev environments |
| `runloop-api-client` | Runloop sandbox |
| `docker` | Docker containers |
| `e2b-code-interpreter` | E2B code execution |

### Development Dependencies
| Package | Purpose |
|---------|---------|
| `pytest` | Testing framework |
| `pytest-asyncio` | Async test support |
| `pytest-cov` | Coverage reporting |
| `ruff` | Linting/formatting |
| `mypy` | Type checking |

## Entry Points

| Entry Point | Command | File |
|-------------|---------|------|
| CLI | `nami` | `namicode_cli.main:cli_main` |
| Module | `python -m namicode_cli` | `namicode_cli/__main__.py` |

## Version Information

- **Package**: namicode-cli
- **Version**: 0.0.14
- **Core Library**: nami-deepagents v0.2.8

## Additional Notes

### Skills System
Skills use progressive disclosure - only name and description are shown initially. Full instructions are loaded on demand from `SKILL.md` files.

### Memory System
- **Agent Memory**: Stored in `agent.md` files in project root
- **Shared Memory**: Persists across agents using key-value store

### Session Persistence
Sessions are saved to SQLite database and can be restored. Use `--session` flag to restore a previous session.

### MCP Integration
MCP servers are configured in `~/.nami/mcp.json`. Presets available for common integrations (filesystem, github, etc.).

### Browser Automation
Playwright-based browser tools available for web automation. Requires browser installation: `playwright install`.

### Semantic Search
Code semantic search using sentence-transformers and FAISS for finding similar code patterns.

### Evaluation Framework
Terminal-Bench evaluation in `evaluation/` directory for benchmark testing with Docker environments.
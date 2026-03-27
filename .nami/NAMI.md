# NAMI.md

This file provides guidance to AI assistants when working with code in this repository.

## Project Overview

**Nami-Code CLI** (`namicode-cli`) is an open-source terminal-based AI coding assistant similar to Claude Code. It's built on top of a custom `deepagents` framework using LangGraph for agentic workflows with planning, subagent delegation, and multi-backend file system access.

## Technology Stack

| Category | Technology |
|----------|------------|
| **Language** | Python 3.11+ |
| **Package Manager** | uv (modern Python package manager) |
| **Agent Framework** | LangGraph 1.1.3+, LangChain 1.2.13+ |
| **LLM Providers** | Anthropic Claude, OpenAI, Google GenAI, Ollama |
| **Sandbox Providers** | Docker, E2B, Modal, Runloop, Daytona |
| **UI Framework** | Rich, prompt-toolkit |
| **Testing** | pytest, pytest-asyncio, pytest-timeout |
| **Linting/Formatting** | Ruff, mypy (strict mode) |

## Project Structure

```
Namicode-CodeAssistant-CLI/
├── namicode_cli/                    # Main CLI package
│   ├── main.py                      # Entry point & CLI loop
│   ├── __main__.py                  # Module entry (python -m)
│   ├── agents/                      # Agent management
│   │   ├── core_agent.py            # Agent creation/config
│   │   ├── default_subagents/       # Built-in subagents
│   │   └── named_agents.py          # Named agent profiles
│   ├── browser_tools.py             # Browser automation tools
│   ├── commands/                    # CLI commands
│   ├── config/                      # Configuration management
│   ├── doctor.py                    # System diagnostics
│   ├── file_ops.py                  # File operations
│   ├── git_tools.py                 # Git integration tools
│   ├── image_utils.py               # Image handling
│   ├── input.py                     # User input handling
│   ├── integrations/                # Sandbox providers
│   │   ├── daytona.py               # Daytona sandbox
│   │   ├── docker.py                # Docker sandbox
│   │   ├── e2b_executor.py          # E2B sandbox
│   │   ├── modal.py                 # Modal sandbox
│   │   ├── runloop.py               # Runloop sandbox
│   │   └── sandbox_factory.py       # Sandbox factory
│   ├── mcp/                         # Model Context Protocol
│   │   ├── client.py                # MCP client
│   │   ├── commands.py              # MCP CLI commands
│   │   ├── config.py                # MCP configuration
│   │   ├── middleware.py            # MCP middleware
│   │   └── presets.py               # MCP presets
│   ├── memory/                      # Memory management
│   ├── onboarding.py                # First-run setup
│   ├── semantic_search.py           # Code semantic search
│   ├── server_runner/               # Dev server management
│   ├── session/                     # Session persistence
│   ├── shell.py                     # Shell execution
│   ├── skills/                      # Skills system
│   ├── states/                      # Session state
│   ├── tools.py                     # Custom tools (HTTP, web search, etc.)
│   ├── tracking/                    # Tracing/tracking
│   └── ui/                          # Rich UI components
├── deepagents-nami/                  # Core agent framework
│   └── nami_deepagents/
│       ├── graph.py                 # Deep agent creation
│       ├── backends/                 # Backend protocols
│       │   ├── composite.py          # Composite backend
│       │   ├── filesystem.py        # Local filesystem
│       │   ├── protocol.py          # Backend protocol
│       │   └── sandbox.py            # Sandbox backend
│       └── middleware/              # Agent middleware
├── evaluation/                       # Harbor evaluation framework
│   ├── deepagents_harbor/           # Evaluation harness
│   └── terminal-bench-2/            # Benchmark tasks
├── tests/                           # Test suite
│   ├── unit_tests/
│   └── integration_tests/
└── assets/                          # Static assets
```

## Development Setup

### Prerequisites
- Python 3.11+
- uv package manager (`pip install uv`)

### Installation

```bash
# Clone the repository
git clone https://github.com/Babitdor/namicode-cli.git
cd namicode-cli

# Create virtual environment and install
uv venv
uv pip install -e .

# Or for development with all groups:
uv sync --all-groups
```

### Environment Variables

Copy `.env.template` to `.env` and configure:

```bash
# Required API Keys
ANTHROPIC_API_KEY=          # Claude models
OPENAI_API_KEY=             # GPT models
GOOGLE_API_KEY=             # Gemini models

# Optional Services
TAVILY_API_KEY=             # Web search
RUNLOOP_API_KEY=            # Cloud sandbox
DAYTONA_API_KEY=            # Daytona sandbox
E2B_API_KEY=                # E2B cloud sandbox

# LangSmith Tracing (optional)
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=
LANGSMITH_PROJECT=Nami-Code

# Model Overrides
OLLAMA_HOST=http://localhost:11434
OLLAMA_MODEL=qwen3-coder:480b-cloud
```

## Development Commands

### Running the CLI

```bash
# Run directly
uv run nami

# Or after install
nami
```

### Makefile Commands

| Command | Description |
|---------|-------------|
| `make run` | Run Nami CLI |
| `make run_reinstall` | Reinstall and run CLI |
| `make test` | Run unit tests (excludes subprocess-heavy tests) |
| `make test TEST_FILE=<path>` | Run specific test file |
| `make test_integration` | Run integration tests |
| `make test_all` | Run all tests |
| `make test_watch` | Run tests in watch mode |
| `make test_cov` | Run tests with coverage |
| `make format` | Format code (ruff format + fix) |
| `make lint` | Run linters (ruff format check + ruff check) |
| `make clean` | Remove build artifacts and caches |

### DeepAgents Subpackage Commands

```bash
cd deepagents-nami
make lint          # Run ruff format check + ruff check + mypy
make format        # Run ruff format + ruff check --fix
make test          # Run unit tests with coverage
make integration_test  # Run integration tests
```

### Evaluation Framework Commands

```bash
cd evaluation
make run-hello-world           # Run hello-world task
make run-terminal-bench-docker # Run 1 task with Docker
make run-namicode-docker       # Run Nami Code with Docker
make run-compare               # Compare DeepAgents vs Nami Code
```

## Architecture

### Deep Agent Architecture

Built on LangGraph with:
- **Planning Tool** (`write_todos`) for task management
- **Sub-agents** (`task` tool) for parallel delegation
- **File System Access** via multiple backends (local, sandbox)
- **Middleware Stack** (memory, skills, MCP, shell)

### Backend System

Supports multiple execution environments:
- **Local filesystem** - Direct file operations
- **Docker** - Containerized execution
- **E2B** - Cloud sandbox
- **Modal** - Serverless execution
- **Runloop** - Cloud sandbox
- **Daytona** - Development environment

### Skills System

Progressive disclosure pattern for domain-specific capabilities. Skills are loaded from:
- `C:\users\babit-pc\.nami\skills` (user skills)
- Project-level skills directories

### MCP Integration

Model Context Protocol for extending agent capabilities through:
- `mcp/client.py` - MCP client
- `mcp/commands.py` - CLI commands
- `mcp/config.py` - Configuration
- `mcp/middleware.py` - Middleware integration
- `mcp/presets.py` - Preset configurations

## Important Files

| File | Purpose |
|------|---------|
| `namicode_cli/main.py` | Main CLI entry point and REPL loop |
| `namicode_cli/agents/core_agent.py` | Agent creation and configuration |
| `namicode_cli/config/__init__.py` | Configuration management |
| `namicode_cli/tools.py` | Custom tools (HTTP, web search, etc.) |
| `deepagents-nami/nami_deepagents/graph.py` | Core deep agent creation |
| `deepagents-nami/nami_deepagents/backends/protocol.py` | Backend protocol definition |
| `pyproject.toml` | Main project configuration |
| `Makefile` | Build/test/lint commands |
| `.env.template` | Environment variable template |

## Common Workflows

### Adding a New Tool

1. Define tool in `namicode_cli/tools.py` or appropriate module
2. Use `@tool` decorator from LangChain
3. Add to agent's tool list in `agents/core_agent.py`

### Adding a New Subagent

1. Create subagent definition in `agents/default_subagents/`
2. Register in `agents/named_agents.py`
3. Define subagent type in appropriate enum

### Adding a New Sandbox Provider

1. Create integration file in `integrations/`
2. Implement backend protocol from `deepagents-nami/nami_deepagents/backends/protocol.py`
3. Register in `integrations/sandbox_factory.py`

### Adding a New Skill

1. Create skill directory in `~/.nami/skills/<skill-name>/`
2. Add `SKILL.md` with skill instructions
3. Optionally add `scripts/` for helper scripts

## Testing

### Test Structure

```
tests/
├── unit_tests/         # Unit tests
│   ├── test_config.py
│   ├── test_agent.py
│   └── test_imports.py
├── integration_tests/  # Integration tests
│   ├── conftest.py     # Shared fixtures
│   ├── test_sandbox_factory.py
│   └── test_sandbox_operations.py
└── security/           # Security tests
    └── test_path_security.py
```

### Test Naming Conventions

- **Files:** `test_*.py` (pytest standard)
- **Classes:** `Test<Feature>` (PascalCase with Test prefix)
- **Functions:** `test_<action>_<condition>` (snake_case)

### Running Tests

```bash
# Unit tests
make test

# Specific test file
make test TEST_FILE=tests/unit_tests/test_config.py

# Integration tests
make test_integration

# With coverage
make test_cov

# Watch mode
make test_watch
```

### Test Fixtures

- `conftest.py` in `tests/integration_tests/` provides shared fixtures
- LangSmith client fixture for tracing tests
- Mock tools available in `deepagents-nami/tests/utils.py`

## Code Style and Conventions

### Linting & Formatting

**Primary Tool:** Ruff (replaces Black, isort, flake8, etc.)

| Setting | Main Project | deepagents-nami |
|---------|--------------|-----------------|
| Line length | 100 | 150 |
| Rule selection | ALL | ALL |
| Docstring convention | Google | Google |

### Key Ruff Rules (from pyproject.toml)

```toml
[tool.ruff.lint]
select = ["ALL"]  # Enable all rules
ignore = [
    "COM812",   # Messes with formatter
    "ISC001",   # Messes with formatter
    "PERF203",  # Rarely useful
    "SLF001",   # Private member access
    "PLC0415",  # Imports at top
    "PLR0913",  # Too many arguments
    "PLC0414",  # Re-exports
    "C901",     # Too complex
]
```

### Type Checking

**Tool:** mypy (strict mode)

```toml
[tool.mypy]
strict = true
ignore_missing_imports = true
enable_error_code = ["deprecated"]
disallow_any_generics = false
warn_return_any = false
```

### Naming Conventions

| Element | Convention | Example |
|---------|------------|---------|
| Classes | PascalCase | `TestProjectRootDetection` |
| Functions | snake_case | `test_find_project_root_with_git` |
| Constants | UPPER_SNAKE_CASE | `HOME_DIR`, `COLORS` |
| Module docstrings | Triple-quoted with description | See `main.py` |
| Function docstrings | Google-style with Args/Returns | See `config.py` |

### Import Organization

```python
# Standard library
import argparse
import asyncio

# Third-party
from langgraph.checkpoint.memory import InMemorySaver

# Local imports
from namicode_cli.agents.core_agent import create_agent_with_config
```

### Type Annotations

Use modern Python type hints with `|` union syntax:

```python
def create_deep_agent(
    model: str | BaseChatModel | None = None,
    tools: Sequence[BaseTool | Callable | dict[str, Any]] | None = None,
) -> CompiledStateGraph:
```

## Additional Notes

### Entry Points

| Entry Point | Location | Usage |
|-------------|----------|-------|
| CLI Entry | `namicode_cli/main.py:cli_main()` | `nami` command |
| Module Entry | `namicode_cli/__main__.py` | `python -m namicode_cli` |
| Deep Agent Factory | `deepagents-nami/nami_deepagents/graph.py:create_deep_agent()` | Agent creation |

### Key Dependencies

**LangChain Ecosystem:**
- `langchain>=1.2.13`, `langchain-core>=1.2.22`
- `langgraph>=1.1.3`
- `langchain-anthropic>=1.4.0`, `langchain-ollama>=1.0.1`, `langchain-google-genai>=4.2.1`

**Sandbox Providers:**
- `modal>=0.65.0`, `daytona>=0.113.0`, `runloop-api-client>=0.69.0`
- `docker>=7.0.0`, `e2b-code-interpreter>=1.0.0`

**Tools & Utilities:**
- `rich>=13.0.0`, `prompt-toolkit>=3.0.52`
- `tavily-python`, `ddgs>=7.0.0` (web search)
- `replicate>=0.25.0` (image generation)

### Per-File Ignores

```toml
[tool.ruff.lint.per-file-ignores]
"namicode_cli/cli.py" = ["T201"]  # Allow print in CLI
"tests/*" = ["D1", "S101", "S311", "ANN201", "INP001", "PLR2004"]
```

### Sandbox Provider Configuration

| Provider | Dependency | Environment Variable |
|----------|------------|---------------------|
| Docker | `docker>=7.0.0` | Built-in |
| E2B | `e2b-code-interpreter>=1.0.0` | `E2B_API_KEY` |
| Modal | `modal>=0.65.0` | Modal auth |
| Runloop | `runloop-api-client>=0.69.0` | `RUNLOOP_API_KEY` |
| Daytona | `daytona>=0.113.0` | `DAYTONA_API_KEY` |

### Quick Reference

```bash
# Install
uv sync --all-groups

# Run CLI
uv run nami

# Development workflow
make format && make lint && make test

# Run specific test
uv run pytest tests/unit_tests/test_file.py

# System diagnostics
nami doctor
```
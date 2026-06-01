
![Nova CLI Banner](assets/Nova.png)

# NOVA : Agentic Coding Tool

[![Version](https://img.shields.io/badge/version-0.0.19-blue)](https://github.com/Babitdor/NovaCode)

An open-source terminal-based AI coding assistant that runs in your terminal, similar to Claude Code. Built on top of the `deepagents` library which provides the core agent architecture.

## Features

- **Built-in Tools**: 35+ tools including file operations, shell commands, web search, git, LSP, browser automation, and subagent delegation
- **Customizable Skills**: Add domain-specific capabilities through a progressive disclosure skill system (50+ built-in skills)
- **Persistent Memory**: Agent remembers your preferences, coding style, and project context across sessions
- **Project-Aware**: Automatically detects project roots and loads project-specific configurations
- **Project Graph**: Visualize and query your codebase architecture with community detection and dependency analysis
- **MCP Support**: Extend capabilities with Model Context Protocol servers (12+ presets available)
- **Sandbox Execution**: Run code safely in remote sandboxes (Modal, Runloop, Daytona, Docker, E2B)
- **Plan Mode**: Structured planning phase before implementation with plan approval workflow
- **Prompt Decomposition**: Automatically splits complex multi-intent prompts into sequential sub-prompts
- **Voice Agent**: Hands-free coding with wake-word detection, STT/TTS providers, and voice-driven file operations
- **Graphify Integration**: Generate interactive visualizations and knowledge graphs from codebases
- **LSP Integration**: Language Server Protocol support for go-to-definition, find references, rename, diagnostics, and more
- **Semantic Code Search**: Find code by description or meaning, not just exact text matches
- **Async Subagents**: Background task execution on remote LangGraph servers
- **Remote Bridges**: Discord and Telegram integration for remote agent interaction
- **Onboarding System**: Interactive first-run setup with API key management and model selection
- **Doctor Command**: System diagnostics to verify your environment
- **Default Subagents**: Built-in specialized agents for code exploration, documentation, and simplification
- **Security-First**: Automatic .gitignore enforcement, command injection detection, and input validation
- **File Recovery**: Automatic snapshots before destructive operations — restore deleted or overwritten files via `/restore` or agent tools

## Installation

### Prerequisites

- **Python 3.11 or higher** (Python 3.12 recommended)
- **Git** for cloning the repository
- **[uv](https://docs.astral.sh/uv/)** (recommended) or pip for package management

### Step-by-Step Installation

#### Option 1: Install with uv (Recommended)

```bash
# 1. Clone the repository
git clone https://github.com/Babitdor/NovaCode.git
cd NovaCode

# 2. Create a virtual environment with Python 3.11+
uv venv --python 3.11

# 3. Activate the virtual environment
# On Windows (PowerShell):
.venv\Scripts\Activate.ps1
# On Windows (Command Prompt):
.venv\Scripts\activate.bat
# On macOS/Linux:
source .venv/bin/activate

# 4. Install dependencies
uv sync

# 5. Install the package in editable mode
uv pip install -e .
```

#### Option 2: Install with pip

```bash
# 1. Clone the repository
git clone https://github.com/Babitdor/NovaCode.git
cd NovaCode

# 2. Create a virtual environment
python -m venv .venv

# 3. Activate the virtual environment
# On Windows (PowerShell):
.venv\Scripts\Activate.ps1
# On Windows (Command Prompt):
.venv\Scripts\activate.bat
# On macOS/Linux:
source .venv/bin/activate

# 4. Upgrade pip
pip install --upgrade pip

# 5. Install dependencies
pip install -e .
```

### Verify Installation

```bash
# Check if nova is installed
nova --version

# Run system diagnostics
nova doctor

# Start the CLI
nova
```

### API Keys Setup

Configure your preferred LLM provider by setting environment variables:

#### Option 1: Environment Variables (Recommended)

```bash
# OpenAI (default)
export OPENAI_API_KEY="your-openai-api-key"

# Or Anthropic
export ANTHROPIC_API_KEY="your-anthropic-api-key"

# Optional: Web search (Tavily)
export TAVILY_API_KEY="your-tavily-api-key"
```

#### Option 2: .env File

Create a `.env` file in your project root or home directory:

```bash
# .env file
OPENAI_API_KEY=your-openai-api-key
ANTHROPIC_API_KEY=your-anthropic-api-key
TAVILY_API_KEY=your-tavily-api-key
```

#### Option 3: Configuration File

Create `~/.nova/config.json`:

```json
{
  "api_keys": {
    "openai": "your-openai-api-key",
    "anthropic": "your-anthropic-api-key",
    "tavily": "your-tavily-api-key"
  }
}
```

### Troubleshooting

#### Common Issues

**1. Python version mismatch**
```bash
# Check Python version
python --version

# If you have multiple Python versions, specify the version
uv venv --python 3.11
```

**2. Virtual environment not activating**
```bash
# On Windows, you may need to enable script execution
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser

# Then activate
.venv\Scripts\Activate.ps1
```

**3. Package installation fails**
```bash
# Clear uv cache and reinstall
uv cache clean
uv sync --reinstall
```

**4. Missing dependencies**
```bash
# Install all dependencies including dev dependencies
uv sync --all-extras
```

**5. Import errors**
```bash
# Reinstall in editable mode
uv pip install -e . --force-reinstall
```

### Development Setup

For development work:

```bash
# Install development dependencies
uv sync --all-extras

# Run tests
pytest tests/

# Format and lint code
make format
make lint

# Type checking
make lint  # ruff includes type-aware checks
# or manually:
mypy novacode_cli/
```

## Quick Start

```bash
# Start the CLI
nova

# Use a specific agent configuration
nova --agent mybot

# Auto-approve tool usage (skip approval prompts)
nova --auto-approve

# Execute in a remote sandbox
nova --sandbox modal
nova --sandbox daytona
nova --sandbox runloop
nova --sandbox docker

# Execute code in E2B cloud sandbox (via tool)
# The agent can use execute_in_e2b() when E2B_API_KEY is set

# Run system diagnostics
nova doctor
```

## Built-in Tools

| Tool | Description |
|------|-------------|
| `ls` | List files and directories |
| `read_file` | Read contents of a file |
| `write_file` | Create or overwrite a file |
| `edit_file` | Make targeted edits to existing files |
| `glob` | Find files matching a pattern (e.g., `**/*.py`) |
| `grep` | Search for text patterns across files |
| `shell` | Execute shell commands (local mode) |
| `execute` | Execute commands in remote sandbox (sandbox mode) |
| `web_search` | Search the web using Tavily API |
| `fetch_url` | Fetch and convert web pages to markdown |
| `browser_automate` | AI-powered browser automation for web tasks |
| `capture_browser_console` | Capture browser console errors and logs from web apps |
| `task` | Delegate work to subagents for parallel execution |
| `write_todos` | Create and manage task lists for complex work |
| `think` | Structured reasoning and reflection before acting |
| `duckduckgo_search` | Web search using DuckDuckGo (no API key required) |
| `docs_search` | Search official documentation (LangGraph, LangChain, etc.) |
| `convert_format` | Convert between JSON, YAML, and TOML formats |
| `format_code_file` | Auto-format code files (Ruff, Prettier) |
| `lint_code` | Run linting on code files (Ruff) |
| `check_types` | Run type checking (mypy, pyright) |
| `http_request` | Make HTTP GET/POST/PUT/DELETE requests |
| `package_info` | Get package version and dependency info |
| `get_current_time` | Get current time in various formats and timezones |
| `git_status` / `git_log` / `git_diff` / `git_blame` | Git repository introspection tools |
| `create_memory_structure` | Initialize persistent memory storage |
| `read_memory` / `write_memory` | Read and write agent memories |
| `execute_in_e2b` | Run code in E2B cloud sandbox |
| `start_dev_server` / `stop_server` / `list_servers` | Manage local development servers |
| `run_tests` | Execute test suites |
| `list_trash` | List file snapshots available for recovery |
| `restore_file` | Restore a deleted or overwritten file from snapshots |
| `query_project_graph` | Query the project graph for architectural information |
| `code_search` | Semantic code search by description or symbol name |
| `find_related_code` | Find code semantically similar to a known location |
| `lsp_goto_definition` | Navigate to symbol definition via LSP |
| `lsp_find_references` | Find all usages of a symbol via LSP |
| `lsp_hover` | Get documentation and type info for a symbol |
| `lsp_document_symbols` | List classes, functions, and variables in a file |
| `lsp_workspace_symbols` | Find symbols across the entire workspace |
| `lsp_diagnostics` | Get syntax errors and linting issues via LSP |
| `lsp_rename` | Rename a symbol across all files |
| `lsp_signature_help` | Get parameter info for function calls |
| `start_async_task` | Start a background task on a remote LangGraph server |
| `check_async_task` | Check status and result of a background task |
| `update_async_task` | Send updated instructions to a running background task |
| `cancel_async_task` | Cancel a running background task |
| `list_async_tasks` | List all tracked background tasks |

> **Note**: Potentially destructive operations require user approval. Use `--auto-approve` to skip prompts.

## Browser Automation

NOVA includes AI-powered browser automation capabilities for web-based tasks:

### Direct Command

```bash
# Run browser automation task
/browser-use <task> [--model M] [--no-vision]

# Examples:
/browser-use Go to github.com and find trending Python repos
/browser-use Fill out the contact form on example.com --model llama3.2
/browser-use Search for Python tutorials --no-vision
```

### Agent Tool

The agent can also use browser automation directly:

```python
# Browser automation tool
browser_automate(
    task="Go to news.ycombinator.com and get the top 5 stories",
    model="llama3.1:8b",
    use_vision=True
)
```

## Browser Console Capture

NOVA can capture browser console errors and logs from running web applications:

### Use Cases

- Debug JavaScript errors in development
- Monitor console warnings during testing
- Capture console output from web applications
- Identify runtime errors in production

### Agent Tool

```python
# Capture console errors from local development server
capture_browser_console(
    url="http://localhost:3000",
    duration=60,
    capture_errors=True,
    capture_warnings=True,
    capture_logs=False
)

# Quick error check (5 seconds)
capture_browser_console("http://localhost:8080", duration=5)

# Capture all console messages from production site
capture_browser_console("https://example.com", duration=30)
```

### Output

Returns a dictionary with:
- `messages`: List of captured console messages with type, content, timestamp, and location
- `summary`: Statistics including error count, warning count, and log count
- `success`: Whether the capture succeeded

### Requirements

```bash
pip install playwright
playwright install chromium
```

### Specialized Subagent

NOVA includes a specialized browser-automation-agent for complex web tasks:

- **Web Scraping**: Extract data from websites
- **Form Filling**: Automate form submissions
- **Data Collection**: Gather information from multiple pages
- **Multi-step Interactions**: Perform complex web workflows

### Browser-Use Features

- **Vision Support**: Optional vision capabilities for visual understanding
- **Model Selection**: Choose different Ollama models (default: llama3.1:8b)
- **Result Integration**: Results automatically sent to Nova for analysis
- **Conversation History**: Browser results become part of the conversation context

### Requirements

```bash
# Install browser-use
pip install browser-use

# Or with uv
uv pip install browser-use

# Ensure Ollama is running with the model installed
ollama pull llama3.1:8b
```

## Trello Task Board

NOVA includes a browser-based task board for managing and processing tasks visually. Start it with the `/trello` slash command — it opens a self-contained HTML page served from a local HTTP server.

### Usage

```
/trello              Start the task board server and open browser
/trello stop         Stop the task board server
/trello status       Show current task board state
```

### How It Works

1. Run `/trello` — a local HTTP server starts and opens the task board in your browser
2. Add tasks via the web UI (description, priority, etc.)
3. Tasks are automatically picked up and processed by the agent one at a time
4. Completed tasks are marked "Done" in the board

### Task Lifecycle

| Status | Description |
|--------|-------------|
| **Loaded** | Task has been added to the board, waiting to be processed |
| **Processing** | Agent is currently working on the task |
| **Done** | Task has been completed by the agent |

Tasks move through the lifecycle automatically — no manual intervention needed. You can also click **"Start"** in the web UI to explicitly move a task to processing.

### Example

```bash
# Start the task board
/trello

# Check status
/trello status

# Stop the server
/trello stop
```

## Configuration

### Directory Structure

**Global Configuration** (`~/.nova/`):
```
~/.nova/
├── agents/           # Agent configurations
│   └── default/
│       └── agent.md
├── skills/           # Global skills (shared across all agents)
│   └── web-research/
│       └── SKILL.md
└── trash/            # File recovery snapshots (auto-created)
    └── <session-id>/
        ├── manifest.json
        └── <snapshots>
```

**Project Configuration** (in your project root):
```
my-project/
├── .nova/
│   ├── agent.md     # Project-specific instructions
│   └── skills/      # Project-specific skills
└── .claude/         # Also supported (Claude Code compatible)
```

### Agent Memory

The `agent.md` file provides persistent memory loaded at every session start:

- **Global** (`~/.nova/agents/default/agent.md`): Your personality, style, and universal preferences
- **Project** (`.nova/NOVA.md`): Project-specific context, conventions, and architecture

The agent automatically updates these files when you describe preferences or give feedback.

### Skills

Skills provide specialized workflows and domain knowledge. Manage skills with:

```bash
# List all skills
nova skills list

# Create a new skill
nova skills create my-skill

# Create a project-specific skill
nova skills create my-skill --project

# View skill details
nova skills info web-research
```

Skills follow [Anthropic's progressive disclosure pattern](https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills) - the agent knows skills exist but only loads full instructions when needed.

#### Installing Skills from GitHub

You can install skills directly from any public GitHub repository using `nova skills add`:

```bash
# Install a skill from a GitHub repo
nova skills add https://github.com/owner/repo

# Install a specific named skill from a multi-skill repo
nova skills add https://github.com/livekit/agent-skills --skill livekit-agents

# Install from a specific branch
nova skills add https://github.com/owner/repo/tree/main/my-skill

# Install as a project-scoped skill (only available in this project)
nova skills add https://github.com/owner/repo --project

# Overwrite an existing skill
nova skills add https://github.com/owner/repo --skill my-skill --force
```

**What gets installed:**

Nova fetches the `SKILL.md` file and all supporting files in recognized subdirectories alongside it:

| Directory | Contents |
|-----------|----------|
| `scripts/` | Shell scripts, automation helpers |
| `examples/` | Usage examples and sample code |
| `assets/` | Templates, config files, static resources |
| `references/` | Docs, cheat sheets, reference material |
| `prompts/` | Prompt templates |
| `templates/` | Code or file templates |
| `data/` | Data files used by the skill |

If the repository has no `SKILL.md`, Nova auto-generates one from the repo's README using the LLM.

**Example — Install the LiveKit Agents skill:**

```bash
nova skills add https://github.com/livekit/agent-skills --skill livekit-agents
```

This installs the `livekit-agents` skill along with its scripts, examples, and any other supporting files — giving Nova full context to help you build LiveKit voice and video agents.

### Default Subagents

NOVA includes built-in specialized subagents for common tasks:

| Subagent | Description |
|----------|-------------|
| `code-explorer-agent` | Deep code research and exploration |
| `code-doc-agent` | Documentation generation from code |
| `code-simplifier-agent` | Code simplification and refactoring |

These subagents are automatically available and can be invoked via the `task` tool for parallel, focused work on specific aspects of your codebase.

### Hooks System

NOVA provides a powerful hooks system for customizing agent behavior at key lifecycle points:

**Hook Types:**

| Hook | When It Fires | Use Case |
|------|---------------|----------|
| `pre_tool_call` | Before a tool is executed | Validate inputs, log actions, modify parameters |
| `post_tool_call` | After a tool completes | Process results, log outcomes, trigger notifications |
| `on_message` | When a message is received | Filter content, add context, track conversations |
| `on_error` | When an error occurs | Custom error handling, logging, recovery actions |

**Managing Hooks:**

```bash
# List all hooks
/hooks list

# Add a hook
/hooks add pre_tool_call my_hook --command "echo 'Tool called'"

# Add a hook from a file
/hooks add post_tool_call logger --file hooks/logger.py

# Enable/disable hooks
/hooks enable my_hook
/hooks disable my_hook

# View hook details
/hooks info my_hook

# Remove a hook
/hooks remove my_hook
```

**Hook Configuration:**

Hooks are stored in `~/.nova/hooks/` and can be:
- **Python scripts**: Full access to NOVA's internals
- **Shell commands**: Quick one-liners for simple tasks
- **Executable files**: Any executable for custom logic

**Example Hook (Python):**

```python
# ~/.nova/hooks/pre_tool_call.py
def hook(tool_name: str, args: dict) -> dict:
    """Log tool calls before execution."""
    print(f"[HOOK] Tool called: {tool_name}")
    print(f"[HOOK] Arguments: {args}")
    
    # Modify arguments if needed
    if tool_name == "write_file":
        args["content"] = args["content"].rstrip() + "\n"
    
    return args
```

**Example Hook (Shell):**

```bash
# ~/.nova/hooks/post_tool_call.sh
#!/bin/bash
echo "Tool completed: $TOOL_NAME"
echo "Result: $RESULT"
```

**Hook Use Cases:**

- **Logging**: Track all tool calls for debugging
- **Validation**: Ensure file paths are within project boundaries
- **Notifications**: Send alerts when tasks complete
- **Custom Behavior**: Add project-specific logic
- **Security**: Prevent certain operations
- **Integration**: Connect to external services

**Hook Priority:**

Hooks execute in priority order (lower number = higher priority):
1. System hooks (priority 0-99)
2. User hooks (priority 100-199)
3. Project hooks (priority 200-299)

### MCP Integration

Extend the agent with Model Context Protocol servers for specialized capabilities:

**Available Presets:**

```bash
# Add Brave Search MCP server (preset)
nova mcp add brave-search --preset brave-search

# Add PostgreSQL MCP server (preset)
nova mcp add postgres --preset postgres

# Add Playwright MCP server (preset)
nova mcp add playwright --preset playwright

# Add Google Drive MCP server (preset)
nova mcp add google-drive --preset google-drive
```

**Available Presets:** `brave-search`, `memory`, `postgres`, `google-drive`, `playwright`, `fetch`, `time`, `sqlite`, `stripe`, `everything`, `serena`, `context7`

**Custom MCP Servers:**

```bash
# HTTP transport
nova mcp add custom-server --transport http --url https://example.com/mcp

# Stdio transport (local process)
nova mcp add my-server --transport stdio --command "python -m my_mcp_server"

# Stdio with arguments
nova mcp add fetch-server --transport stdio --command "npx" --args "-y", "@modelcontextprotocol/server-fetch"
```

**MCP Management:**

```bash
# List all configured MCP servers
nova mcp list

# Remove an MCP server
nova mcp remove my-server

# View MCP server details
nova mcp info my-server
```

**Environment Variables for MCP:**

```bash
# Some MCP servers require additional configuration
export GITHUB_API_KEY="your-github-token"
export DATABASE_URL="postgresql://user:pass@localhost:5432/db"
```

### E2B Cloud Sandbox

E2B provides secure cloud sandbox execution via the `execute_in_e2b` tool:

```python
# Run code in E2B cloud sandbox
execute_in_e2b(
    code="print('Hello from E2B!')",
    language="python"
)
```

**Setup:**
```bash
# Get your E2B API key from https://e2b.dev/
export E2B_API_KEY="your-e2b-api-key"
```

E2B sandboxes are ideal for:
- Running untrusted code safely
- Testing code in clean, isolated environments
- Executing code that requires specific dependencies

### File Recovery

NOVA automatically snapshots files before any destructive operation, so you can always recover from mistakes.

**What gets snapshotted:**
- Files targeted by `rm` shell commands — captured before deletion
- Files overwritten by `write_file` — previous content saved
- Files modified by `edit_file` — pre-edit content saved

**Restoring files (human):**
```bash
# Show all recent snapshots interactively
/restore

# Restore by index
/restore 1

# Restore by path
/restore src/utils.py
```

**Restoring files (agent):**

The agent can also self-recover autonomously using its built-in tools:
- `list_trash()` — see what snapshots are available
- `restore_file("src/utils.py")` — restore the most recent snapshot for that path

Snapshots are stored in `~/.nova/trash/<session-id>/` and are available across session restarts. Files larger than 10 MB are skipped.

### Doctor Command

Run system diagnostics to verify your environment:

```bash
nova doctor
```

The `doctor` command checks:
- Python version and environment
- Required dependencies
- API key configurations
- Sandbox connectivity
- Project configuration

### Onboarding System

On first run, NOVA guides you through an interactive setup:

```bash
# First run - launches onboarding wizard
nova
```

The onboarding process includes:
- **API Key Setup**: Securely store your LLM provider API keys
- **Model Selection**: Choose your preferred model and provider
- **Environment Verification**: System checks for dependencies
- **Secret Management**: Keys stored securely via OS keychain

**Manual Configuration:**
You can also set API keys manually via environment variables or the `.env` file:

```bash
# OpenAI (default)
export OPENAI_API_KEY="your-openai-api-key"

# Anthropic
export ANTHROPIC_API_KEY="your-anthropic-api-key"

# E2B (for cloud sandbox)
export E2B_API_KEY="your-e2b-api-key"
```

### Testing

Run the test suite with:

```bash
# Run unit tests
make test

# Run all tests (including integration)
make test_all

# Run with coverage
make test_cov

# Run specific test file
make test TEST_FILE=tests/unit_tests/test_specific.py
```

## Development

### Setup Development Environment

```bash
# Clone the repository
git clone https://github.com/Babitdor/NovaCode.git
cd NovaCode

# Install dependencies
uv sync --all-groups

# Run during development
uv run nova
```

### Running Tests

```bash
# Run unit tests
make test

# Run specific test file
make test TEST_FILE=tests/unit_tests/test_specific.py

# Run integration tests
make test_integration
```

### Code Quality

```bash
# Format code
make format

# Check linting
make lint
```

## Architecture

The CLI implements a "Deep Agent" architecture with four key components:

1. **Planning tool** (`write_todos`) for task management
2. **Sub-agents** (`task` tool) for parallel delegation
3. **File system access** via multiple backends (local, sandbox)
4. **Detailed prompts** with memory and skills systems

### Module Structure

**Core:**
- `main.py` - Entry point, CLI loop, and argument parsing
- `cli_session.py` - Session management, auto-save, and display helpers
- `input.py` - prompt_toolkit input handling, completers, image paste, keybindings

**Agent:**
- `agents/core_agent.py` - Agent creation, configuration, and middleware wiring
- `agents/default_subagents/` - Built-in specialized subagents (code explorer, docs, simplifier)
- `agents/plan_agent/` - Plan mode agent with planning middleware

**Commands:**
- `commands/` - 17 CLI command handlers (`/model`, `/mcp`, `/skills`, `/plan`, `/browser`, etc.)

**Configuration:**
- `config/config.py` - Settings, color scheme, model factory, project root detection
- `config/nova_config.py` - Persistent JSON configuration management
- `config/model_create.py` - Model instantiation for all providers
- `config/model_manager.py` - Model provider management

**Context & Memory:**
- `context/` - Context budget tracking, eviction, optimization, and growth monitoring
- `memory/` - Persistent agent memory system
- `prompts/` - Jinja2 template rendering

**UI:**
- `ui/ui_elements.py` - Token tracking, help display, diff rendering, todo lists
- `ui/execution.py` - Tool execution orchestration and approval flow
- `ui/streaming.py` - Real-time output streaming
- `ui/tool_processing.py` - Tool call formatting and display
- `ui/hitl_approval.py` - Human-in-the-loop approval UI
- `ui/subagent_tracking.py` - Subagent progress visualization

**Tools (20 modules):**
- `tools/` - HTTP, web search, fetch, code execution, git, LSP, browser, format, lint, typecheck, memory, time, reflection, package, graph, code search, and plan mode tools

**Integrations:**
- `integrations/` - Sandbox providers (Modal, Runloop, Daytona, Docker, E2B)
- `mcp/` - Model Context Protocol client, config, middleware, and presets
- `remote/` - Discord and Telegram bridge support

**Infrastructure:**
- `session/` - Session persistence, restore, summarization, and prompt building
- `states/Session.py` - SessionState dataclass with plan mode, steering, and remote support
- `server_runner/` - Development server and test runner lifecycle management
- `process_manager.py` - Subprocess lifecycle, health checks, and cleanup
- `tracking/` - File tracking, run logging, LangSmith tracing, workspace anchoring

**Safety & Recovery:**
- `errors/` - Error taxonomy (14 categories) and recovery handlers
- `security/` - Unicode security and input validation
- `git_safety.py` - Dangerous command detection and injection prevention
- `file_ops.py` - File operation tracking, diff computation, and approval previews
- `recovery.py` - File recovery snapshots
- `path_approval.py` - Path-based operation approval

**Specialized:**
- `bootstrap/` - Environment snapshots, project graph context, steering instructions
- `init/` - Project initialization (detect, extract, generate, graph)
- `skills/` - Skill loading, creation, locking, and system prompt generation
- `hitl/` - Human-in-the-loop interrupt configuration
- `vision/` - Vision model support
- `vixie/` - Desktop companion server (notifications, system tray)
- `hooks.py` - Lifecycle hook system
- `compaction.py` - Conversation summarization via LLM
- `plans.py` - Plan management and persistence
- `prompt_decomposer.py` - Multi-intent prompt splitting
- `onboarding.py` - Interactive first-run setup with SecretManager
- `doctor.py` - System diagnostics and environment validation
- `migrate.py` - Configuration migration utilities

## Vixie Integration

NOVA includes **Vixie**, a lightweight desktop companion server:

### Features

- **Desktop Notifications**: Task completion and status alerts
- **System Tray Integration**: Quick access to Nova status
- **Server Module**: `novacode_cli/vixie/server.py`

Vixie runs as a background service alongside the Nova CLI and provides desktop-level integrations for a smoother workflow.

## Dependencies

This package depends on the `deepagents` library for core agent functionality, which is automatically installed as a dependency.

## License

MIT License - see LICENSE file for details.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

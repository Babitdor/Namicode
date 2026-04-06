
![Nova CLI Banner](assets/Nova.png)

# NOVA : Agentic Coding Tool

An open-source terminal-based AI coding assistant that runs in your terminal, similar to Claude Code. Built on top of the `deepagents` library which provides the core agent architecture.

## Features

- **Built-in Tools**: File operations (read, write, edit, glob, grep), shell commands, web search, and subagent delegation
- **Customizable Skills**: Add domain-specific capabilities through a progressive disclosure skill system
- **Persistent Memory**: Agent remembers your preferences, coding style, and project context across sessions
- **Project-Aware**: Automatically detects project roots and loads project-specific configurations
- **MCP Support**: Extend capabilities with Model Context Protocol servers
- **Sandbox Execution**: Run code safely in remote sandboxes (Modal, Runloop, Daytona, Docker, E2B)
- **Onboarding System**: Interactive first-run setup with API key management and model selection
- **Doctor Command**: System diagnostics to verify your environment
- **Default Subagents**: Built-in specialized agents for code exploration, documentation, and simplification
- **Terminal-Bench Evaluation**: Built-in Harbor evaluation framework for benchmark testing
- **Security-First**: Automatic .gitignore enforcement to protect sensitive files
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

#### Option 3: Install deepagents-nova separately (for development)

If you want to work on the deepagents-nova package separately:

```bash
# 1. Clone the repository
git clone https://github.com/Babitdor/NovaCode.git
cd NovaCode

# 2. Create and activate virtual environment
uv venv --python 3.11
source .venv/bin/activate  # or .venv\Scripts\Activate.ps1 on Windows

# 3. Install the main package
uv pip install -e .

# 4. Install deepagents-nova in editable mode
cd deepagents-nova
uv pip install -e .
cd ..
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

Create `~/.Nova/config.json`:

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

# Format code
black .
isort .

# Type checking
mypy novacode_cli/
```

### Docker Installation (Alternative)

```bash
# Build the Docker image
docker build -t nova-cli .

# Run in container
docker run -it -v $(pwd):/workspace nova-cli
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

# Execute code in E2B cloud sandbox
nova --sandbox e2b

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
| `task` | Delegate work to subagents for parallel execution |
| `write_todos` | Create and manage task lists for complex work |
| `list_trash` | List file snapshots available for recovery |
| `restore_file` | Restore a deleted or overwritten file from snapshots |

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
# Add filesystem MCP server (preset)
nova mcp add filesystem --preset filesystem

# Add GitHub MCP server (preset)
nova mcp add github --preset github

# Add PostgreSQL MCP server (preset)
nova mcp add postgres --preset postgres

# Add Puppeteer MCP server (preset)
nova mcp add puppeteer --preset puppeteer
```

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

E2B provides secure cloud sandbox execution for running code with full isolation:

```bash
# Execute in E2B cloud sandbox
nova --sandbox e2b

# Run Python scripts securely
nova --sandbox e2b <<< "print('Hello from E2B!')"
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

Snapshots are stored in `~/.Nova/trash/<session-id>/` and are available across session restarts. Files larger than 10 MB are skipped.

### Doctor Command

Run system diagnostics to verify your environment:

```bash
Nova doctor
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

### Terminal-Bench Evaluation

The CLI includes a built-in Harbor evaluation framework for benchmarking agent performance on standardized coding tasks.

**Setup:**

```bash
# Navigate to evaluation directory
cd evaluation

# Install evaluation dependencies
make setup

# Configure your API keys
export OPENAI_API_KEY="your-api-key"
# or
export ANTHROPIC_API_KEY="your-api-key"
```

**Running Evaluations:**

```bash
# Run all Terminal-Bench tasks
make evaluate

# Run specific subset of tasks
make evaluate TASK_FILTER="python-*.py"

# Run with custom model
make evaluate MODEL="gpt-4o" PROVIDER="openai"

# Run headless (no browser automation)
make evaluate HEADLESS=1
```

**Analyzing Results:**

```bash
# Generate performance report
make analyze

# Compare against baseline
make compare BASELINE="path/to/baseline/results.json"

# Export results to JSON
make export FORMAT=json
```

**Result Interpretation:**

Results are stored in `evaluation/results/` with:
- `config.json` - Task configuration and parameters
- `result.json` - Pass/fail status, execution time, and scores
- `exception.txt` - Error details (if failed)

**Evaluation Categories:**

| Category | Description | Example Tasks |
|----------|-------------|---------------|
| Code Generation | Write code from specifications | "Write a Python function to sort a list" |
| Bug Fix | Identify and fix bugs | "Fix the off-by-one error in this function" |
| Refactoring | Improve code structure | "Extract this logic into a helper function" |
| Documentation | Add docstrings and comments | "Document this class with docstrings" |
| Testing | Write unit tests | "Add tests for edge cases" |

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

- `main.py` - Entry point and CLI loop
- `agent.py` - Agent creation and configuration
- `execution.py` - Task execution and streaming
- `config.py` - Settings and environment configuration
- `tools.py` - Custom tool implementations
- `ui.py` - Rich-based UI rendering

## Vixie Integration

NOVA includes **Vixie**, an Electron-based desktop application for Nami integration:

### Features

- **Desktop UI**: Native desktop application for Nami interactions
- **Nami Client**: Built-in client for Nami blockchain integration
- **Gravity Simulation**: Interactive gravity simulation demo
- **Settings Management**: Configurable settings for customization

### Vixie Components

| File | Description |
|------|-------------|
| `main.js` | Electron main process |
| `preload.js` | IPC bridge between main and renderer |
| `index.html` | Main application window |
| `settings.html` | Settings configuration page |
| `nami-client.js` | Nami blockchain client integration |
| `gravity.js` | Gravity simulation module |

### Running Vixie

```bash
# Navigate to Vixie directory
cd Vixie

# Install dependencies
npm install

# Run in development mode
npm start

# Build for production
npm run make
```

### Vixie Architecture

Vixie uses Electron Forge for cross-platform desktop deployment:

- **Main Process**: Handles app lifecycle and native APIs
- **Renderer Process**: UI rendering and user interactions
- **Preload Script**: Secure bridge for IPC communication
- **Nami Client**: Integration with Nami blockchain wallet

### Integration with NOVA

Vixie provides a graphical interface for NOVA's capabilities:

- Visual browser automation controls
- Real-time task progress monitoring
- Interactive settings configuration
- Desktop notifications for task completion
- `recovery.py` - File recovery system (snapshots + restore)
- `skills/` - Skills system implementation
- `mcp/` - Model Context Protocol integration
- `integrations/` - Sandbox providers (Modal, Runloop, Daytona, Docker, E2B)
- `onboarding.py` - Interactive first-run setup and secret management
- `doctor.py` - System diagnostics and environment checks
- `default_subagents/` - Built-in specialized subagents
- `evaluation/` - Harbor evaluation framework for Terminal-Bench benchmarking
- `shared_memory.py` - Cross-agent memory sharing with attribution

## Dependencies

This package depends on the custom `deepagents` for windows library for core agent functionality. The `deepagents-Nova` library is automatically installed as a dependency.

## License

MIT License - see LICENSE file for details.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

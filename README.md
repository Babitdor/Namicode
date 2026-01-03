# Nami-Code CLI

An open-source terminal-based AI coding assistant that runs in your terminal, similar to Claude Code. Built on top of the `deepagents` library which provides the core agent architecture.

<img src="assets/cli-banner.png" alt="Nami CLI Banner" width="100%"/>

## Features

- **Built-in Tools**: File operations (read, write, edit, glob, grep), shell commands, web search, and subagent delegation
- **Customizable Skills**: Add domain-specific capabilities through a progressive disclosure skill system
- **Persistent Memory**: Agent remembers your preferences, coding style, and project context across sessions
- **Project-Aware**: Automatically detects project roots and loads project-specific configurations
- **MCP Support**: Extend capabilities with Model Context Protocol servers
- **Sandbox Execution**: Run code safely in remote sandboxes (Modal, Runloop, Daytona, Docker)

## Installation

### Prerequisites

- Python 3.11 or higher
- [uv](https://docs.astral.sh/uv/) (recommended) or pip

### Install from Source

```bash
# Clone the repository
git clone https://github.com/Babitdor/namicode-cli.git
cd namicode-cli

# Create virtual environment and install
uv venv
uv pip install -e .
```

### API Keys Setup

Configure your preferred LLM provider by setting environment variables:

```bash
# OpenAI (default)
export OPENAI_API_KEY="your-openai-api-key"

# Or Anthropic
export ANTHROPIC_API_KEY="your-anthropic-api-key"

# Optional: Web search (Tavily)
export TAVILY_API_KEY="your-tavily-api-key"
```

You can also create a `.env` file in your project root or home directory.

## Quick Start

```bash
# Start the CLI
nami

# Use a specific agent configuration
nami --agent mybot

# Auto-approve tool usage (skip approval prompts)
nami --auto-approve

# Execute in a remote sandbox
nami --sandbox modal
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
| `task` | Delegate work to subagents for parallel execution |
| `write_todos` | Create and manage task lists for complex work |

> **Note**: Potentially destructive operations require user approval. Use `--auto-approve` to skip prompts.

## Configuration

### Directory Structure

**Global Configuration** (`~/.nami/`):
```
~/.nami/
├── agents/           # Agent configurations
│   └── default/
│       └── agent.md
└── skills/           # Global skills (shared across all agents)
    └── web-research/
        └── SKILL.md
```

**Project Configuration** (in your project root):
```
my-project/
├── .nami/
│   ├── agent.md     # Project-specific instructions
│   └── skills/      # Project-specific skills
└── .claude/         # Also supported (Claude Code compatible)
```

### Agent Memory

The `agent.md` file provides persistent memory loaded at every session start:

- **Global** (`~/.nami/agents/default/agent.md`): Your personality, style, and universal preferences
- **Project** (`.nami/NAMI.md`): Project-specific context, conventions, and architecture

The agent automatically updates these files when you describe preferences or give feedback.

### Skills

Skills provide specialized workflows and domain knowledge. Manage skills with:

```bash
# List all skills
nami skills list

# Create a new skill
nami skills create my-skill

# Create a project-specific skill
nami skills create my-skill --project

# View skill details
nami skills info web-research
```

Skills follow [Anthropic's progressive disclosure pattern](https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills) - the agent knows skills exist but only loads full instructions when needed.

### MCP Integration

Extend the agent with Model Context Protocol servers:

```bash
# Add an HTTP MCP server
nami mcp add docs-server --transport http --url https://example.com/mcp

# Add a stdio MCP server
nami mcp add filesystem --transport stdio --command "python -m mcp_server"

# List configured servers
nami mcp list
```

See [MCP_GUIDE.md](MCP_GUIDE.md) for detailed configuration.

## Development

### Setup Development Environment

```bash
# Clone the repository
git clone https://github.com/Babitdor/namicode-cli.git
cd namicode-cli

# Install dependencies
uv sync --all-groups

# Run during development
uv run nami
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
- `skills/` - Skills system implementation
- `mcp/` - Model Context Protocol integration
- `integrations/` - Sandbox providers (Modal, Runloop, Daytona, Docker)

## Dependencies

This package depends on the custom `deepagents` for windows library for core agent functionality. The `deepagents-nami` library is automatically installed as a dependency.

## License

MIT License - see LICENSE file for details.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## Special
~ Project dedicated to my Bee 💕

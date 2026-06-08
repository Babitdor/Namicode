
![Nova CLI Banner](assets/Nova.png)

# NOVA : Agentic Coding Tool

[![Version](https://img.shields.io/badge/version-0.0.19-blue)](https://github.com/Babitdor/NovaCode)

An open-source terminal-based AI coding assistant that runs in your terminal, similar to Claude Code. Built on top of the `deepagents` library which provides the core agent architecture.

## Features

- **Autonomous Learning System (Hermes)**: Periodically reviews tool usage patterns, extracts lessons, and autonomously creates reusable skills — the agent improves itself over time without user intervention
- **Built-in Tools**: 25+ tools including file operations, shell commands, web search, subagent delegation, semantic code search, and web scraping (GitHub trending, Hacker News, LinkedIn, Reddit)
- **Customizable Skills**: Add domain-specific capabilities through a progressive disclosure skill system (50+ built-in skills)
- **Durable Memory**: Two-tier memory system — persistent markdown files (`USER.md`/`MEMORY.md`) auto-maintained by the learning system, plus a LangGraph key/value store (`remember`/`recall`) for cross-session facts
- **Project-Aware**: Automatically detects project roots and loads project-specific configurations
- **Project Graph**: Visualize and query your codebase architecture with community detection and dependency analysis
- **MCP Support**: Extend capabilities with Model Context Protocol servers (12+ presets available) — tools are eagerly discovered before graph build with server-prefixed names to avoid collisions
- **Sandbox Execution**: Run code safely in remote sandboxes (Modal, Runloop, Daytona, Docker, E2B)
- **Plan Mode**: Structured planning phase before implementation with plan approval workflow
- **Web Chat UI**: Launch a local browser-based chat interface via `/chat` — dark-themed, Claude-inspired, with Markdown rendering and code highlighting
- **Voice Agent**: Hands-free coding with wake-word detection, STT/TTS providers, and voice-driven file operations
- **Graphify Integration**: Generate interactive visualizations and knowledge graphs from codebases
- **LSP Integration**: Language Server Protocol support for go-to-definition, find references, rename, diagnostics, and more
- **Semantic Code Search**: Find code by description or meaning, not just exact text matches
- **Web Scraping**: Built-in tools for GitHub trending repos, Hacker News headlines, LinkedIn jobs, Reddit posts, and Twitter/X trends — no external API keys required
- **Async Subagents**: Background task execution on remote LangGraph servers. Includes specialized agents like the **Documentation Update Agent** which automatically synchronizes project docs and changelogs with git commits.
- **Remote Bridges**: Discord and Telegram integration for remote agent interaction
- **Onboarding System**: Interactive first-run setup with API key management and model selection
- **Doctor Command**: System diagnostics to verify your environment
- **Default Subagents**: 20+ built-in specialized agents with skill-aware prompts — each subagent auto-loads relevant skills for its domain
- **Security-First**: Automatic .gitignore enforcement, command injection detection, and input validation
- **File Recovery**: Automatic snapshots before destructive operations — restore deleted or overwritten files via `/restore` or agent tools
- **Condensed Tool UI**: Consecutive tool calls are grouped into collapsible sections — full diffs shown for code edits; reads, searches, and other calls stay compact
- **Modal Animations**: Entrance animations (fade/slide) for all modal dialogs, pulsing borders, and a shimmer status bar

## Installation

### Prerequisites

- **Python 3.11 or higher** (Python 3.12 recommended)
- **Git** for cloning the repository
- **[uv](https://docs.astral.sh/uv/)** (required for dependency management) or pip for package management

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
| `task` | Delegate work to subagents for parallel execution |
| `write_todos` | Create and manage task lists for complex work |
| `think` | Structured reasoning and reflection before acting |
| `web_search` | Search the web using Tavily API |
| `duckduckgo_search` | Web search using DuckDuckGo (no API key required) |
| `docs_search` | Search official documentation sites |
| `fetch_url` | Fetch and convert web pages to markdown (covers all HTTP methods) |
| `github_trending` | Scrape GitHub trending repositories by language/time range |
| `hacker_news` | Scrape Hacker News front page headlines |
| `linkedin_jobs` | Search LinkedIn job listings (Playwright-based, no login) |
| `reddit_posts` | Scrape Reddit posts by subreddit, user, or search query |
| `package_info` | Get package version and dependency info (PyPI / npm) |
| `read_memory` / `write_memory` | Read and write persistent markdown agent memories |
| `remember` / `recall` | Store and fetch durable cross-session facts by key |
| `list_memories` / `forget` | List and delete stored durable memory facts |
| `list_trash` | List file snapshots available for recovery |
| `restore_file` | Restore a deleted or overwritten file from snapshots |
| `query_project_graph` | Query the project graph for architectural information |
| `code_search` | Semantic code search by description or symbol name |
| `find_related_code` | Find code semantically similar to a known location |
| `start_async_task` | Start a background task on a remote LangGraph server |
| `check_async_task` | Check status and result of a background task |
| `update_async_task` | Send updated instructions to a running background task |
| `cancel_async_task` | Cancel a running background task |
| `list_async_tasks` | List all tracked background tasks |

> **Note**: Potentially destructive operations require user approval. Use `--auto-approve` to skip prompts.

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

## Web Chat UI

NOVA includes a `/chat` command that launches a local browser-based chat interface:

```
/chat              Start the chat server and open browser
/chat stop         Stop the chat server
/chat status       Show chat server status
```

### Features

- **Dark-themed UI**: Claude-inspired design with red accent colors
- **Markdown Rendering**: Messages rendered with full Markdown support and code syntax highlighting (via `marked` + `highlight.js`)
- **Typing Indicator**: Animated bouncing dots while the agent responds
- **Same Agent**: Connects to the same LangGraph agent from your CLI session — no separate configuration needed
- **Auto-open**: Browser opens automatically on launch

### How It Works

The `/chat` command starts a `ThreadingHTTPServer` in a background thread. The server communicates with the main agent loop via `asyncio.run_coroutine_threadsafe`, sharing the same session state and agent configuration.

## Web Scraping Tools

NOVA includes built-in web scraping tools that work with public data — no API keys required:

| Tool | Data Source | No API Key? |
|------|-------------|-------------|
| `github_trending` | GitHub trending repositories (filter by language/time) | ✅ |
| `hacker_news` | Hacker News front page headlines | ✅ |
| `linkedin_jobs` | LinkedIn job listings (Playwright-based) | ✅ |
| `reddit_posts` | Reddit posts by subreddit, user, or search | ✅ |

These tools use `requests` + `BeautifulSoup` (or `playwright` for LinkedIn) to scrape publicly available data and return structured results.

### Standalone CLI Scripts

The scraping logic is also available as standalone scripts in `scripts/scraper/`:

```
scripts/scraper/
├── gh_trending.py          # GitHub trending scraper
├── hn_scraper.py           # Hacker News scraper
├── linkedin_job_scraper.py # LinkedIn job scraper (Playwright)
├── reddit_scraper.py       # Reddit scraper
└── inline_json.py          # JSON extraction utility
```

## Autonomous Learning System (Hermes)

NOVA includes **Hermes**, an autonomous learning system that runs in the background:

- **Self-Review**: Every ~10 tool calls, Hermes reviews tool usage patterns and extracts lessons
- **Self-Improving Memory**: Automatically maintains two memory tiers:
  - `USER.md` — User model: communication style, preferences, workflows, recurring frustrations
  - `MEMORY.md` — Cross-session memory: architecture decisions, reusable patterns, key facts
- **Skill Creation**: Analyzes repeated successful tool sequences and autonomously creates reusable skills with deterministic naming and refinement
- **No Interruption**: Reviews run out-of-band in the background — no pause in agent operation
- **Live Indicator**: A visible indicator in the TUI status line shows when Hermes is reviewing

The system is always active and designed to require zero user configuration. Lessons are compacted automatically as they grow.

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

NOVA includes 20+ built-in specialized subagents, each loaded with domain-relevant skills via `SkillsMiddleware`:

#### Code Quality Agents

| Subagent | Description | Auto-loaded Skills |
|----------|-------------|-------------------|
| `code-explorer` | Navigate, understand, and query large codebases efficiently | `codebase-explorer/`, `graphify/` |
| `code-doc-Agent` | Generate README, API docs, and docstrings from structured inputs | `code-documentation/` |
| `code-simplifier-agent` | Simplify and refine code for clarity and maintainability | `code-review-expert/` |
| `reviewer-agent` | Code review for correctness, security, performance, and SOLID violations | `code-review-expert/` |
| `security-auditor-agent` | OWASP Top 10 audit, secrets detection, dependency vuln scanning | `web-research/` |
| `refactoring-specialist-agent` | Identify code smells, prioritize technical debt, apply design patterns | `improve-codebase-architecture/` |
| `bug-fix-agent` | Systematic bug reproduction, root-cause analysis, minimal fix + regression tests | `systematic-debugging/` |

#### Test Agents

| Subagent | Description | Auto-loaded Skills |
|----------|-------------|-------------------|
| `test-writer-agent` | Create comprehensive tests (happy-path, edge-case, error-case) | `test-driven-development/` |
| `testing-agent` | Execute tests in isolated sandboxes, detect frameworks, report failures | `testing-skills/`, `webapp-testing/` |

#### Browser Automation Agent

| Subagent | Description | Auto-loaded Skills |
|----------|-------------|-------------------|
| `browser-automation-agent` | Web testing, form filling, screenshots, data extraction, console capture | `agent-browser/`, `browser-use/` |

#### Domain-Specific Engineering Agents

| Subagent | Description | Auto-loaded Skills |
|----------|-------------|-------------------|
| `frontend-agent` | React, HTML/CSS, design systems, animations, production-grade UI | `frontend-design/`, `expert-css-skills/` |
| `backend-agent` | API design, databases, auth, async patterns, server-side systems | `backend-dev-guidelines/`, `async-python-patterns/` |
| `docker-agent` | Containerization, optimized Dockerfiles, multi-service Compose stacks | `docker-deploy/` |

#### Research Swarm Agents

| Subagent | Description | Auto-loaded Skills |
|----------|-------------|-------------------|
| `web-researcher` | General web research — search, fetch, synthesize | `web-research/`, `arxiv-search/` |
| `fact-checker` | Verify critical claims using web search snippets | `web-research/` |
| `research-synthesizer` | Synthesize findings + QA report into final coherent report | — (inline only) |
| `literature-reviewer` | Academic search (arXiv, Google Scholar, Semantic Scholar, PubMed) | `arxiv-search/`, `web-research/` |
| `market-analyst` | Market sizing, growth rates, competitive landscape research | `web-research/` |
| `financial-analyst` | Financial statements, earnings data, SEC filings, risk analysis | `web-research/`, `xlsx/` |
| `technical-researcher` | Official docs, GitHub repos, RFCs, version-accurate technical research | `web-research/`, `codebase-explorer/` |

Subagents are invoked via the `task` tool for parallel, focused work. Skills are loaded on-demand when the subagent is instantiated — agents without skill assignments skip `SkillsMiddleware` overhead entirely.

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

**Test suite includes:**

| Directory | What it tests |
|-----------|---------------|
| `tests/test_hermes/` | Hermes learning system — middleware, memory tiers, skill discovery |
| `tests/test_tui_app.py` | Textual TUI — animations, chat messages, modals, tool groups |
| `tests/test_workdir_grep.py` | Sandbox-backed grep tool with path-rebased execution |
| `tests/test_notifications.py` | Notification system integration |
| `tests/test_context_breakdown_tokens.py` | Token budget and context optimization |

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
- `agents/default_subagents/` - 20+ built-in specialized subagents with skill-aware prompts (code explorer, docs, simplifier, reviewer, security, refactoring, bug fix, test writer, testing, browser automation, frontend, backend, docker, research swarm, changelogger)
- `agents/plan_agent/` - Plan mode agent with planning middleware

**Commands:**
- `commands/` - 18+ CLI command handlers (`/model`, `/mcp`, `/skills`, `/plan`, `/browser`, `/chat`, etc.)
- `commands/chat_handler.py` - `/chat` command — launches a local web chat UI with a background HTTP server that connects to the same LangGraph agent

**Configuration:**
- `config/config.py` - Settings, color scheme, model factory, project root detection
- `config/nova_config.py` - Persistent JSON configuration management
- `config/model_create.py` - Model instantiation for all providers
- `config/model_manager.py` - Model provider management

**Context & Memory:**
- `context/` - Context budget tracking, eviction, optimization, and growth monitoring
- `memory/store.py` - Durable LangGraph key/value store (`remember`/`recall`) using sync SqliteStore with async wrappers; includes a stdlib-fallback BaseStore (works without `langgraph-checkpoint-sqlite`)
- `prompts/` - Jinja2 template rendering

**Learning System (Hermes):**
- `hermes/middleware.py` - NovaLearningMiddleware — reviews tool usage every ~10 calls, writes lessons to `USER.md`/`MEMORY.md`, and triggers autonomous skill creation
- `hermes/memory_tiers.py` - Manages the two memory tiers (user model in `USER.md`, session decisions in `MEMORY.md`)
- `hermes/skill_discovery.py` - Analyzes repeated successful tool sequences and autonomously creates reusable skills with deterministic naming

**UI:**
- `ui/ui_elements.py` - Token tracking, help display, diff rendering, todo lists
- `ui/execution.py` - Tool execution orchestration and approval flow
- `ui/streaming.py` - Real-time output streaming
- `ui/tool_processing.py` - Tool call formatting and display
- `ui/hitl_approval.py` - Human-in-the-loop approval UI
- `ui/subagent_tracking.py` - Subagent progress visualization

**TUI (Textual):**
- `tui/app.py` - NovaApp — the full Textual terminal UI with chat messages, modals, keyboard shortcuts, condensed tool groups, click-to-copy, and history management
- `tui/animations.py` - Entrance animations (fade/slide) for modals, pulsing borders, shimmer effects, and thinking dots

**Tools (21 modules):**
- `tools/` - HTTP fetch, web search, DuckDuckGo search, docs search, web scraping (GitHub trending, HN, LinkedIn, Reddit, Twitter/X), package info, git, LSP, browser, memory, reflection, project graph, code search, and plan mode tools

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
n a Pull Request
ature/amazing-feature`)
5. Open a Pull Request
n a Pull Request

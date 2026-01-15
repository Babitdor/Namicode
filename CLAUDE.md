# CLAUDE.md

## Project Overview

Nami-Code is an open-source terminal-based AI coding assistant built on `nami-deepagents`. Implements "Deep Agent" architecture with planning, subagent delegation, file system access, and persistent prompts.

## Development Commands

```bash
# Running
uv run nami                              # Development mode
uv run nami --agent <name>               # Specific agent
uv run nami --continue                   # Continue session
uv run nami --sandbox <modal|daytona|docker|runloop>  # With sandbox

# Testing
make test                                # Unit tests
make test_integration                    # Integration tests
make test_all                            # All tests
make test_cov                            # With coverage

# Code Quality
make format                              # Format code
make lint                                # Check linting
make clean                               # Remove artifacts
```

## Architecture

### Deep Agent Pattern
1. **Planning** (`write_todos`) - Task decomposition and tracking
2. **Subagents** (`task` tool) - Parallel delegation with context isolation
3. **File system** - CompositeBackend (local + sandbox)
4. **Persistent prompts** - agent.md files

### Middleware Stacks

**Main Agent** (10 layers):
`TodoList → Memory → Skills → MCP → Filesystem → SubAgent → Summarization → PromptCaching → PatchToolCalls → HumanInTheLoop`

**CLI Agent** (6 layers):
`FileTracker → Skills → MCP → SharedMemory → Shell → Memory`

**Subagent** (6 layers, lighter):
`TodoList → Skills → Filesystem → Summarization → PromptCaching → PatchToolCalls`

**Key Parameters**: `model`, `tools`, `subagents`, `skills`, `memory`, `mcp_config`, `backend`, `checkpointer`, `store`

### Backend System

**Protocol Operations**:
- File: `ls_info`, `read`, `write`, `edit`, `grep_raw`, `glob_info`, `upload_files`, `download_files`
- Sandbox: `execute(command)`, `id` property

**Backend Implementations**:
- **FilesystemBackend**: Direct filesystem access, symlink protection, ripgrep + Python fallback
- **StateBackend**: Ephemeral storage in LangGraph agent state
- **StoreBackend**: Persistent storage in LangGraph BaseStore
- **BaseSandbox**: Abstract base for sandboxed execution
- **CompositeBackend**: Multi-backend routing by path prefix

### Key Modules

- **`main.py`**: CLI entry point, REPL loop, auto-save (5 min or 5 messages), signal handling
- **`core_agent.py`**: Agent factory, 6 middleware layers, subagent management, agent profiles (global `~/.nami/agents/` + project `.nami/agents/`)
- **`execution.py`**: Task orchestration, streaming, tool approval UI, diff previews
- **`config/`**: Settings (OS keychain → env → .env), colors, model factory (OpenAI/Anthropic/Google/Ollama)
- **`input.py`**: prompt_toolkit session, context-aware completion, key bindings
- **`commands/`**: Slash commands (`/help`, `/init`, `/mcp`, `/skills`, etc.), `!bash`, `@agent`
- **`session/`**: Persistence (`~/.nami/sessions/`), auto-save, restoration, compatibility validation

### Middleware Stack (CLI Order)

1. **FileTrackerMiddleware** (`tracking/file_tracker.py`)
   - Enforces read-before-edit (hard rejection)
   - Tracks file operations with SHA-256 hashing
   - Smart tool result truncation (per-tool limits)

2. **SkillsMiddleware** (`deepagents-nami/nami_deepagents/middleware/skills.py`)
   - Progressive disclosure (3-level: metadata → path → content)
   - Global: `~/.nami/skills/`, Project: `.nami/skills/` (higher priority)

3. **MCPMiddleware** (`deepagents-nami/nami_deepagents/middleware/mcp.py`)
   - Model Context Protocol for external tools
   - Config: `~/.nami/mcp.json`, Tool namespacing: `servername__toolname`
   - 16 built-in presets (filesystem, github, brave-search, etc.)

4. **SharedMemoryMiddleware** (`memory/shared_memory.py`)
   - Cross-agent communication via InMemoryStore singleton
   - Tools: write_memory, read_memory, list_memories, delete_memory

5. **ShellMiddleware** (`shell.py`)
   - Shell execution via `execute_bash`, blocked patterns (sudo, rm), allow-list for tests

6. **MemoryMiddleware** (`memory/agent_memory.py`)
   - Loads AGENTS.md files (global `~/.nami/{agent}/agent.md` + project NAMI.md)

### Memory Systems

- **Agent Memory** (`memory/agent_memory.py`): Persistent AGENTS.md files (global + project), loaded once at session start
- **Shared Memory** (`memory/shared_memory.py`): Cross-agent communication via InMemoryStore, shared between main/subagents
- **File Tracker** (`tracking/file_tracker.py`): Session-scoped file operation tracking, read-before-edit enforcement

### Sandbox Integrations

**Providers**:
- **Modal**: Cloud sandboxes, `/workspace`, file API in alpha
- **Runloop**: Cloud sandboxes, `/home/user`, per-file operations
- **Daytona**: Cloud sandboxes, `/workspace`, strong batch operations
- **Docker**: Local containers, `python:3.11-slim`, container reuse
- **E2B**: Python/Node.js/Bash execution, per-execution sandbox, 50k char truncation

**Factory** (`integrations/sandbox_factory.py`): Unified interface, context managers, setup scripts, auto-cleanup

### Skills System

- **Locations**: Global `~/.nami/skills/` + Project `.nami/skills/` (higher priority)
- **Progressive Disclosure**: 3-level (metadata → path → content)
- **Commands**: `/skills list`, `/skills create`, `/skills info`

### MCP Integration

- **Location**: `namicode_cli/mcp/`
- **Config**: `~/.nami/mcp.json`
- **Transport**: stdio (npx, docker, python, uvx), http/SSE
- **Tool Namespacing**: `servername__toolname` (e.g., `github__search_repos`)
- **Commands**: `/mcp list`, `/mcp add`, `/mcp remove`, `/mcp install`
- **Presets**: 16 built-in (filesystem, github, brave-search, etc.)

### Tool System

**Built-in** (`nami-deepagents`): File ops (`ls`, `read_file`, `write_file`, `edit_file`, `glob`, `grep`), planning (`write_todos`), delegation (`task`), web (`web_search`, `fetch_url`), execution (`execute_bash`/`execute`)

**Additional**:
- **Server Management**: `start_dev_server_tool`, `stop_server_tool`, `list_servers_tool`
- **Test Execution**: `run_tests_tool` (pytest, npm test, go test, cargo test, jest, vitest)
- **Memory**: `write_memory`, `read_memory`, `list_memories`, `delete_memory`
- **Utility**: `http_request`, `execute_in_e2b`, `web_search`

**Browser Automation** (Playwright): Navigation, interaction, visual, waiting, debugging, advanced (`browser_evaluate`, `browser_run_code`), management

### Subagent Specializations

**15 specialized subagents**: general-purpose, code-reviewer, nodejs-expert, project-structure-agent, Playwright, code-explorer-agent, code-doc-Agent, code-simplifier-agent, Changelog-agent, pypi-python-builder, Serena, sysmlv2-agent, ultra-mode-agent

**Architecture**: Two-tier middleware (lighter stack), ephemeral isolation, cross-agent communication via shared memory

- Tracks token usage with visual progress bars
- Detailed breakdown: baseline (system + tools), conversation, total, remaining
- Color-coded thresholds: Green (<60%), Orange (60-90%), Red (>90%)
- `/context` command displays current usage

**Streaming Output**

- Buffered output for process streaming
- Line limit with truncation warning
- Rich markup escaping to prevent formatting issues

**Tool Display**

- Smart formatting for different tool types
- Path abbreviation for long paths
- Emoji icons for visual identification

**Process Manager** (`process_manager.py`)

- Singleton pattern for process tracking
- Async subprocess management
- Health monitoring with HTTP checks
- Graceful termination with fallback to kill
- Automatic cleanup on exit (atexit, SIGINT, SIGTERM)

**UI Widgets** (`widgets/`)

- Textual-based TUI framework
- 15+ widgets: Approval menus, autocomplete, chat input, confirmation dialogs, diff display, loading indicators
- Standard Textual patterns (BINDINGS, compose(), can_focus_children)
- Quick keys: j/k navigation, y/n/a quick approval

### Testing Framework

**Unit Tests** (`tests/unit_tests/`)

- Framework: pytest with fixtures and mocks
- Coverage: 25+ test files covering agents, config, file ops, tools, MCP, skills
- Key patterns:
  - Descriptive naming: `test_<function>_<scenario>`
  - Mock objects for dependencies
  - `tmp_path` fixture for file operations
  - Extensive edge case testing (unicode, special chars, large files)

**Integration Tests** (`tests/integration_tests/`)

- Framework: pytest with class-scoped fixtures
- LangSmith tracing integration (automated trace collection)
- Sandbox reuse optimization (`REUSE_SANDBOX=1`)
- Base class pattern for testing multiple backends (RunLoop, Daytona, Modal)
- 35+ sandbox operation tests

**Test Conventions:**

- Socket disabled via `--disable-socket` for unit test isolation
- Per-file ignores configured in `pyproject.toml` (e.g., allow print in CLI files)
- Timeout enforcement (default 10s per test)

### Evaluation Framework

**DeepAgents Harbor** (`evaluation/`)

Comprehensive benchmarking and evaluation framework for testing Nami-Code DeepAgents on real-world tasks.

**Components:**

- **`DeepAgentsWrapper`** (`deepagents_wrapper.py`):
  - Uses `create_deep_agent()` from SDK with minimal configuration
  - Dual mode: CLI agent (full middleware) vs SDK agent (minimal)
  - Model management with provider/model inference
  - Context-aware system prompts with directory listings

- **`NamiCodeWrapper`** (`namicode_wrapper.py`):
  - Full-featured Nami Code CLI agent integration
  - Complete middleware stack: FileTracker, SharedMemory, Shell, AgentMemory
  - Additional tools: http_request, fetch_url, run_tests, server management
  - Session tracking with unique assistant IDs

- **`HarborSandbox`** (`backend.py`):
  - Implements `SandboxBackendProtocol` for Harbor environments
  - Async-only shell command execution
  - Base64 encoding for file content safety
  - Shell-based file operations (read, write, edit, ls, grep, glob)

**Benchmarking:**

- **Terminal Bench 2.0**: 90+ tasks across domains:
  - Software engineering: `build-cython-ext`, `compile-compcert`, `fix-code-vulnerability`
  - Security: `crack-7z-hash`, `feal-linear-cryptanalysis`, `password-recovery`
  - AI/ML: `caffe-cifar-10`, `hf-model-inference`, `llm-inference-batching-scheduler`
  - DevOps: `configure-git-webserver`, `git-multibranch`, `nginx-request-logging`
  - Science: `mcmc-sampling-stan`, `protein-assembly`
  - Gaming: `chess-best-move`, `make-doom-for-mips`

- **Multi-Environment Support**:
  - **Docker**: Local containers (fast, good for testing)
  - **Daytona**: Cloud sandboxes (scalable, batch operations)
  - **Modal**: Cloud compute (parallel execution)
  - **Runloop**: Cloud sandboxes (sequential operations)

**LangSmith Integration:**

- Automatic trace capture for all agent runs
- Dataset creation from Harbor tasks
- Experiment management for side-by-side comparison
- Reward score feedback (0.0-1.0 based on test pass rate)
- Deterministic example ID linking
- Analysis workflow: Harbor → LangSmith → Analyze → Improve

**Testing Commands:**

```bash
cd evaluation
# Run DeepAgents wrapper
make run-terminal-bench-docker    # 1 task on Docker
make run-terminal-bench-daytona   # 40 tasks on Daytona
make run-terminal-bench-modal     # 4 tasks on Modal

# Run Nami Code wrapper
make run-namicode-docker          # 1 task on Docker
make run-namicode-daytona         # 10 tasks on Daytona
make run-namicode-task TASK=path-tracing  # Specific task

# Compare both wrappers
make run-compare
```

**Analysis Patterns:**

Common failure patterns identified in LangSmith:
- Poor Planning: Agent jumps into coding without reading requirements
- Incorrect Tool Usage: Uses `bash cat` instead of `read_file`
- No Incremental Testing: Writes 200 lines, then tests once
- Hallucinated Paths: Reads files before checking existence
- Wrong Model: Model fails on complex reasoning

### ACP (Agent Client Protocol) Support

**Status**: Work in Progress - Core functionality implemented, optional operations stubbed

**Implementation** (`acp/deepagents_acp/server.py`):

The `DeepagentsACP` class implements the ACP Agent protocol for DeepAgents, enabling integration with ACP-compliant clients via stdio streams.

**Core Capabilities:**

1. **Session Management**:
   - `initialize()` - Returns agent capabilities and version info
   - `newSession()` - Creates isolated sessions with UUID tracking
   - Stores agent graph and thread ID per session

2. **Message Streaming**:
   - `prompt()` - Handles user prompts with streaming responses
   - Manages interrupt loops for human-in-the-loop
   - Returns when agent completes or session ends

3. **Real-time Updates**:
   - **Text Streaming**: Streams text content chunks as `AgentMessageChunk`
   - **Reasoning Content**: Sends thought chunks as `AgentThoughtChunk`
   - **Tool Call Progress**: Tracks pending/running/completed/failed states
   - **Plan Updates**: Converts todo lists to ACP `PlanEntry` format

4. **Human-in-the-Loop**:
   - Extracts action requests from LangGraph interrupts
   - Creates ACP permission options (allow-once, reject-once)
   - Maps decisions back to LangGraph Command format
   - Future: Edit functionality support (TODO)

5. **Optional Operations** (not implemented):
   - `authenticate`, `extMethod`, `extNotification` - Stubbed
   - `cancel` - Session cancellation (stubbed)
   - `loadSession`, `setSessionMode`, `setSessionModel` - Not implemented

**Testing Infrastructure** (`acp/tests/`):

- `FakeAgentSideConnection`: Mocks ACP connection for testing
- `GenericFakeChatModel`: Configurable fake model with streaming support
  - Stream delimiters: None (single chunk), string, or regex pattern
  - Tool call simulation
  - Additional kwargs handling
- `deepagents_acp_test_context`: Context manager for test setup

**Test Coverage:**
- Initialization and streaming message chunks
- Tool call detection and execution with status updates
- Todo list plan update notifications
- Permission request generation and approval/denial workflows
- Fake model streaming modes with chunk delimiters

**Communication Pattern:**
- Uses stdio streams (`acp.stdio_streams()`) for bidirectional communication
- Compatible with CLI-based ACP clients
- Supports multiple stream types: AgentMessageChunk, AgentThoughtChunk, ToolCallProgress, AgentPlanUpdate

**Key Implementation Details:**
- Session isolation with UUID tracking
- Tool call ID matching for result tracking
- Todo tool calls handled separately from plan updates
- Status mapping: pending, in_progress, completed (default priority: medium)

### Diagnostic Tools

**Doctor Command** (`namicode_cli/doctor.py`)
6 comprehensive checks:

1. Configuration file existence and validity
2. API keys setup (all providers)
3. LLM provider connection (tests actual API calls)
4. Tavily web search connection
5. E2B sandbox test execution
6. Secrets file permissions

Output: Rich table with ✓/✗ status and actionable suggestions

### Error Handling

**Error Taxonomy** (`namicode_cli/errors/taxonomy.py`)
9 error categories:

- User error
- File not found
- Permission denied
- Command not found
- Syntax error
- Network error
- Context overflow
- Tool error
- System error

**Recovery Strategies** (`namicode_cli/errors/handlers.py`)

- FileNotFound: Suggest glob search for similar files
- ContextOverflow: Recommend summarization and pagination
- NetworkError: Exponential backoff retry (3 attempts: 1s, 2s, 4s)
- PermissionDenied: chmod/chown/ls -la suggestions
- CommandNotFound: pip/npm/apt/brew installation guidance

**Central ErrorHandler:**

- Pattern-based error classification
- Automatic recovery strategy selection
- User-friendly error messages with suggestions

### Migration & Onboarding

**Migration Utilities** (`namicode_cli/migrate.py`)

- Purpose: Transition from old to new directory structure
- Migration: `~/.nami/{agent}/` → `~/.nami/agents/{agent}/`
- Per-agent skills → Global `~/.nami/skills/`
- Safety features: Detection before migration, user confirmation, conflict handling

**Onboarding** (`namicode_cli/onboarding.py`)

- Primary storage: OS keyring via `keyring` library
- Fallback: JSON file with 600 permissions (owner read/write only)
- Supported providers: Tavily, OpenAI, Anthropic, Google, Groq, E2B
- Warning if keyring unavailable, permission validation

### Utility Modules

**File Operations** (`namicode_cli/file_ops.py`)

- `FileOpTracker`: Tracks operations across sessions
- `ApprovalPreview`: Data for HITL previews
- `compute_unified_diff`: 3-line context diffs with truncation
- Metrics: Lines read/written/added/removed, line ranges

**Clipboard** (`namicode_cli/clipboard.py`)

- Cross-platform: OSC 52, Textual, pyperclip methods
- Features: Selected text copying, preview shortening, notification

**Path Approval** (`namicode_cli/path_approval.py`)

- Security: Approved paths management in `~/.nami/approved_paths.json`
- Features: Recursive directory approval, path resolution, audit trail

**Context Manager** (`context/context_manager.py`)

- Context window sizes for 30+ models (128K to 2M tokens)
- Detailed breakdown: baseline vs conversation tokens
- Thresholds: 75% warning, 90% critical
- Smart model matching with fallback strategies

**Workspace Anchoring** (`tracking/workspace_anchoring.py`)

- Git status scanning (branch, HEAD, modified/untracked files)
- Drift detection with warnings
- Re-anchoring ensures agent works with current filesystem reality

## Important Development Patterns

### Working with deepagents-nami

The `deepagents-nami/` directory is a **local dependency** linked via:

```toml
[tool.uv.sources]
nami-deepagents = { path = "./deepagents-nami" }
```

When modifying deepagents functionality:

1. Make changes in `deepagents-nami/nami_deepagents/`
2. Changes are immediately available to `namicode_cli/` (no reinstall needed with `uv run`)
3. Run tests from both directories if applicable

### Middleware Development

When creating new middleware:

1. Inherit from `AgentMiddleware` (in `deepagents-nami/nami_deepagents/middleware/base.py`)
2. Define state schema extending `AgentState`
3. Implement `__call__` to wrap model requests/responses
4. Add to middleware stack in `namicode_cli/agents/core_agent.py:create_agent_with_config()`
5. Order matters - middleware is applied sequentially

### Protocol-Oriented Backend Design

When implementing new backends:

1. Implement `BackendProtocol` for file operations
2. Implement `SandboxBackendProtocol` if adding execution capability
3. Use standardized error codes (file_not_found, permission_denied, etc.)
4. Support async versions of all methods
5. Handle partial success for batch operations

### Testing Conventions

- Unit tests: `tests/unit_tests/` (socket disabled via `--disable-socket`)
- Integration tests: `tests/integration_tests/` (with sandbox and LangSmith)
- Use `pytest` with timeout (default 10s per test)
- Descriptive test names: `test_<function>_<scenario>`
- Use `tmp_path` fixture for file operations
- Use `Mock` from `unittest.mock` for dependencies

### Code Style

- Ruff with ALL rules enabled, specific ignores in `pyproject.toml`
- Google-style docstrings
- Type hints required (mypy strict mode with reduced strictness on generics)
- Line length: 100 characters

### Error Handling

- Use rich formatting for user-facing errors
- Provide actionable error messages
- Handle sandbox-specific errors gracefully
- Use centralized ErrorHandler for pattern-based recovery

## Project Structure

```
namicode_cli/
├── main.py              # CLI entry point and REPL loop
├── agents/              # Agent creation and configuration
│   ├── core_agent.py    # Core agent factory
│   ├── commands.py      # Agent creation commands
│   ├── named_agents.py  # Named subagent management
│   ├── default_subagents/  # Core subagent definitions
│   │   ├── subagents.py
│   │   └── prompt.py
│   └── default_agent_prompt.md  # Default system prompt
├── config/              # Configuration management
│   ├── config.py        # Settings, colors, UI constants
│   ├── model_create.py  # Model factory
│   ├── model_manager.py  # Model configuration management
│   └── nami_config.py   # Nami-specific configuration
├── ui/                  # UI components and rendering
│   ├── execution.py     # Task execution and streaming
│   ├── session_display.py  # Session restoration display
│   ├── ui_elements.py   # UI widgets and elements
│   ├── rich_ui.py       # Rich-based rendering
│   └── textual_adapter.py  # Textual TUI integration
├── commands/            # CLI command handlers
│   └── commands.py      # Command parsing and execution
├── input.py             # User input handling with prompt_toolkit
├── tools.py             # Custom tool implementations
├── skills/              # Progressive disclosure skill system
│   ├── middleware.py    # Skills middleware
│   ├── load.py          # Skill loading and metadata parsing
│   ├── skill_creation.py # Skill creation utilities
│   ├── skill_system_prompt.py  # Skills documentation
│   └── commands.py      # Skill management commands
├── mcp/                 # Model Context Protocol integration
│   ├── middleware.py    # MCP middleware
│   ├── client.py        # MultiServerMCPClient
│   ├── config.py        # MCP configuration
│   ├── presets.py       # Preset configurations
│   └── commands.py      # MCP management commands
├── integrations/        # Sandbox provider implementations
│   ├── sandbox_factory.py
│   ├── modal.py
│   ├── runloop.py
│   ├── daytona.py
│   ├── docker.py
│   └── e2b_executor.py  # E2B sandbox execution
├── memory/              # Memory systems
│   ├── agent_memory.py  # Persistent agent memory
│   └── shared_memory.py # Cross-agent communication
├── tracking/            # Tracking systems
│   ├── file_tracker.py  # File operation tracking
│   ├── workspace_anchoring.py # Workspace drift detection
│   └── tracing.py       # LangSmith integration
├── states/              # State management
│   └── Session.py       # Session state
├── session/             # Session management
│   ├── session_persistence.py  # Session save/restore
│   ├── session_restore.py  # Session restoration
│   ├── session_prompt_builder.py  # Continuation prompts
│   └── session_summarization.py  # Memory summarization
├── server_runner/       # Server management tools
│   ├── dev_server.py    # Development server tools
│   └── test_runner.py   # Test execution tools
├── shell.py             # Shell execution middleware
├── process_manager.py   # Process lifecycle management
├── path_approval.py     # Path approval system
├── file_ops.py          # File operations
├── clipboard.py         # Clipboard utilities
├── image_utils.py       # Image handling for multimodal input
├── token_utils.py       # Token counting and context management
├── compaction.py        # Context compaction
├── doctor.py            # Diagnostics and troubleshooting
├── migrate.py           # Migration utilities
├── onboarding.py        # New user onboarding
├── widgets/             # UI widgets
│   ├── screens.py       # Modal screens
│   ├── messages.py      # Message display
│   ├── tool_renderers.py  # Tool call visualization
│   ├── dialogs.py       # Dialog boxes
│   ├── approval.py      # Tool approval UI
│   ├── confirmation.py  # Confirmation dialogs
│   ├── diff.py          # Diff display
│   ├── history.py       # Chat history
│   ├── loading.py       # Loading indicators
│   ├── status.py        # Status displays
│   └── welcome.py       # Welcome screen
├── context/             # Context management
└── errors/              # Error handling utilities
    ├── handlers.py      # Error handlers
    └── taxonomy.py      # Error classification

deepagents-nami/         # Core agent library (local dependency)
├── nami_deepagents/
│   ├── agent.py         # create_deep_agent() implementation
│   ├── graph.py         # Main agent factory
│   ├── backends/        # Backend abstractions
│   │   ├── protocol.py  # Backend protocols
│   │   ├── filesystem.py # FilesystemBackend
│   │   ├── state.py     # StateBackend
│   │   ├── store.py     # StoreBackend
│   │   ├── sandbox.py   # BaseSandbox
│   │   └── composite.py # CompositeBackend
│   ├── middleware/      # Middleware implementations
│   │   ├── base.py      # Base middleware
│   │   ├── mcp.py       # MCP middleware
│   │   ├── skills.py    # Skills middleware
│   │   ├── memory.py    # Memory middleware
│   │   ├── subagents.py # Subagent middleware
│   │   └── filesystem.py # Filesystem middleware
│   └── tools/           # Built-in tools

evaluation/              # Terminal-Bench evaluation framework
├── deepagents_harbor/   # DeepAgents Harbor integration
└── terminal-bench-2/    # 90+ benchmark tasks (git repo)

tests/                   # Test suites
├── unit_tests/          # Unit tests
└── integration_tests/   # Integration tests

acp/                     # Agent Client Protocol support (WIP)
├── deepagents_acp/      # ACP server implementation
│   ├── __init__.py
│   └── server.py        # Full ACP server (~655 lines)
├── tests/               # ACP tests
│   ├── test_server.py
│   └── chat_model.py    # Fake chat model for testing
└── pyproject.toml       # Package config
```

## Memory File Locations

- **Global agent**: `~/.nami/agents/default/agent.md`
- **Project agent**: `.nami/NAMI.md` or `.claude/CLAUDE.md`
- **Skills**: `~/.nami/skills/` (global), `.nami/skills/` (project)
- **MCP config**: `~/.nami/mcp.json`
- **Path approval**: `~/.nami/approved_paths.json`
- **Sessions**: `~/.nami/sessions/<session_id>/`
- **Secrets**: OS keychain (primary) or `~/.nami/secrets.json` (fallback)

## Key Architectural Decisions

- **Two-Tier Middleware**: Subagents get lighter stack (no recursion), main agent gets full capabilities
- **Backend Abstraction**: Protocol-oriented design, pluggable backends, composite routing
- **Progressive Disclosure**: 3-level pattern for skills, MCP metadata in prompts
- **Ephemeral Subagents**: Short-lived, isolated context, shared memory communication
- **Session Persistence**: Split storage (recent 8 + archive), compatibility validation, workspace anchoring
- `/agents` - Manage agent profiles (list, switch, reset)
- `/server` - Manage development servers (start, stop, list)
- `/model` - Change the LLM model
- `/paths` - Manage approved file system paths

**Bash Commands:**

- `!command` - Execute shell commands directly
- `@agent` - Invoke named subagents

## Path Approval System

The path approval system (`path_approval.py`) provides security for file operations:

- Tracks approved and denied paths per session
- Requires approval for operations outside approved paths
- Managed by `PathApprovalManager`
- Configuration stored in `~/.nami/approved_paths.json`
- Recursive directory approval support
- Audit trail of all approval decisions

## Memory File Locations

- Global agent: `~/.nami/agents/default/agent.md`
- Project agent: `.nami/NAMI.md` or `.claude/CLAUDE.md`
- Skills: `~/.nami/skills/` (global), `.nami/skills/` (project)
- MCP config: `~/.nami/mcp-config.json`
- Path approval: `~/.nami/approved_paths.json`
- Sessions: `~/.nami/sessions/<session_id>/`
- Secret storage: OS keychain (primary) or `~/.nami/secrets.json` (fallback)

## Key Architectural Decisions

### Two-Tier Middleware Architecture

- Subagents get lighter middleware stack to prevent recursion
- Main agent gets full capabilities including memory, MCP, and subagent delegation
- Enables subagent isolation while maintaining full agent functionality

### Backend Abstraction

- Protocol-oriented design allows pluggable backends
- Composite backend supports multi-backend routing by path prefix
- FilesystemBackend, StateBackend, and StoreBackend provide different persistence levels

### Progressive Disclosure

- Skills use 3-level pattern for scalability
- MCP tools show metadata in every prompt
- Reduces context window usage while maintaining discoverability

### Ephemeral Subagents

- Subagents are short-lived with isolated context
- Cross-agent communication via shared memory
- Enables parallel delegation and context isolation

### Session Persistence

- Split storage: recent messages (8) + full history archive
- Compatibility validation with drift detection
- Workspace anchoring ensures agent works with current filesystem

## Development Workflow

1. **Making changes to deepagents-nami:**

   - Edit files in `deepagents-nami/nami_deepagents/`
   - Changes immediately available with `uv run`
   - Run tests in both directories

2. **Creating new middleware:**

   - Inherit from `AgentMiddleware`
   - Add to middleware stack in `create_agent_with_config()`
   - Consider order - middleware applied sequentially

3. **Adding new sandbox provider:**

   - Implement `SandboxBackendProtocol`
   - Extend `BaseSandbox` for shell operations
   - Add to `sandbox_factory.py`

4. **Creating new agent profile:**

   - Create `~/.nami/agents/<name>/agent.md`
   - Add YAML frontmatter for color
   - Reference in @agent mentions

5. **Testing changes:**
   - Unit tests: `make test`
   - Integration tests: `make test_integration`
   - All tests: `make test_all`
   - Coverage: `make test_cov`

## Troubleshooting

### Common Issues

**Sandbox connection failures:**

- Check API keys in environment variables or keychain
- Verify network connectivity
- Run `/doctor` for diagnostic checks

**File operation errors:**

- Check path approval status: `/paths`
- Verify file permissions
- Check for symlink attacks (virtual mode protection)

**Token limit exceeded:**

- Check context usage: `/context`
- Consider summarization
- Use pagination for large files

**Agent not responding:**

- Check LLM provider connection
- Verify API key validity
- Run `/doctor` for diagnostics

## Development Workflow

1. **Modify deepagents-nami**: Edit in `deepagents-nami/nami_deepagents/`, changes immediately available with `uv run`, run tests in both directories
2. **Create middleware**: Inherit from `AgentMiddleware`, add to `create_agent_with_config()`, consider order
3. **Add sandbox provider**: Implement `SandboxBackendProtocol`, extend `BaseSandbox`, add to `sandbox_factory.py`
4. **Create agent profile**: Create `~/.nami/agents/<name>/agent.md`, add YAML frontmatter for color
5. **Test**: `make test` (unit), `make test_integration` (integration), `make test_all` (all), `make test_cov` (coverage)

**Testing Conventions**: `tests/unit_tests/` (socket disabled), `tests/integration_tests/` (sandbox + LangSmith), pytest timeout 10s, `test_<function>_<scenario>` naming, `tmp_path` fixture, `Mock` from unittest.mock

**Code Style**: Ruff (ALL rules), Google docstrings, type hints (mypy strict), 100 char line length

**Error Handling**: Rich formatting, actionable messages, centralized ErrorHandler

## Troubleshooting

- **Sandbox failures**: Check API keys (env/keychain), verify network, run `/doctor`
- **File operations**: Check `/paths` for approval, verify permissions, check symlink attacks
- **Token limit**: Check `/context`, consider summarization, use pagination
- **Agent not responding**: Check LLM provider connection, verify API key, run `/doctor`

## CLI Commands

**Slash**: `/help`, `/tokens`, `/context`, `/clear`, `/exit`, `/quit`, `/init`, `/skills`, `/mcp`, `/list`, `/continue`, `/model`, `/paths`, `/server`

**Bash**: `!command`

**Subagent**: `@agent`

## Configuration Files

- `pyproject.toml` - Project metadata, dependencies, tools (ruff, pytest, mypy)
- `Makefile` - Development commands
- `.env` - API keys (not in git)
- `.env.template` - Environment setup template

## Project Structure

```
namicode_cli/
├── main.py              # CLI entry point, REPL loop
├── agents/              # Agent creation, config, subagents
├── config/              # Settings, colors, model management
├── ui/                  # UI components, execution, display
├── commands/            # CLI command handlers
├── skills/              # Progressive disclosure skill system
├── mcp/                 # Model Context Protocol integration
├── integrations/        # Sandbox providers (modal, runloop, daytona, docker, e2b)
├── memory/              # Agent memory, shared memory
├── tracking/            # File tracker, workspace anchoring, tracing
├── session/             # Session persistence, restoration, prompts
├── server_runner/       # Dev server, test execution tools
├── widgets/             # 15+ Textual TUI widgets
├── context/             # Context window management
└── errors/              # Error handling, taxonomy

deepagents-nami/         # Core agent library (local dependency)
├── nami_deepagents/
│   ├── agent.py         # create_deep_agent() implementation
│   ├── graph.py         # Main agent factory
│   ├── backends/        # Backend abstractions (protocol, filesystem, state, store, sandbox, composite)
│   ├── middleware/      # Middleware implementations (base, mcp, skills, memory, subagents, filesystem)
│   └── tools/           # Built-in tools

evaluation/              # Terminal-Bench evaluation framework
├── deepagents_harbor/   # DeepAgents Harbor integration
└── terminal-bench-2/    # 90+ benchmark tasks

tests/
├── unit_tests/          # Unit tests
└── integration_tests/   # Integration tests

acp/                     # Agent Client Protocol support (WIP)
├── deepagents_acp/      # ACP server implementation
├── tests/               # ACP tests
└── pyproject.toml
```

## Changelog

Documented in `changelog/` with versioned markdown files (e.g., `changelog/glob_info_fix.md`)

**Recent Fixes**: Fixed `NotImplementedError` in `FilesystemBackend.glob_info()` - Now supports `**/*.py` patterns using `wcmatch` library

## Recent Architecture Updates (v0.0.13)

**Refactoring**: Reorganized flat structure (25+ files) into 15+ subdirectories (agents/, config/, ui/, commands/, skills/, mcp/, integrations/, memory/, tracking/, session/, server_runner/, widgets/, context/, errors/)

**New Components**:
- `model_manager.py` - Centralized model config, provider presets, Ollama discovery
- `tracing.py` - LangSmith integration, automatic tracing, `@traceable` decorator
- `workspace_anchoring.py` - Git status scanning, drift detection, re-anchoring
- `session_*.py` - Comprehensive session management (persistence, restoration, prompts, summarization)
- `widgets/` - 15+ Textual TUI widgets (screens, dialogs, approvals, diffs)
- `evaluation/` - Benchmarking system (DeepAgents Harbor, Terminal Bench 2.0, LangSmith)
- `acp/` - Agent Client Protocol support (streaming, HITL, testing)

**Enhancements**:
- Unified sync/async API
- Enhanced security (O_NOFOLLOW, path traversal prevention)
- Windows support (path normalization)
- Backend system (unified protocols, composite routing)
- MCP integration (middleware, preset-based config)
- Skills support (progressive disclosure pattern)
4. MCPMiddleware - External tool integration
5. FilesystemMiddleware - File operations
6. SubAgentMiddleware - Subagent delegation
7. SummarizationMiddleware - Context management
8. AnthropicPromptCachingMiddleware - Performance optimization
9. PatchToolCallsMiddleware - Dangling tool call handling
10. HumanInTheLoopMiddleware - Interruption handling

**CLI Agent Middleware Stack** (6 layers, in `create_agent_with_config`):
1. FileTrackerMiddleware - Read-before-edit enforcement
2. SkillsMiddleware - Progressive disclosure skills
3. MCPMiddleware - External tools
4. SharedMemoryMiddleware - Cross-agent communication
5. ShellMiddleware - Shell execution
6. MemoryMiddleware - Persistent context

**Subagent Middleware Stack** (lighter, 6 layers):
1. TodoListMiddleware - Task management
2. SkillsMiddleware - Agent skills
3. FilesystemMiddleware - File operations
4. SummarizationMiddleware - Context management
5. AnthropicPromptCachingMiddleware - Performance
6. PatchToolCallsMiddleware - Dangling tool calls

## v0.0.14 - 2025-01-11

### Features

#### Onboarding System (e19f4b6)
- New interactive onboarding wizard for first-time setup
- `namicode_cli/onboarding.py` (456 lines) - Complete onboarding workflow
- `namicode_cli/doctor.py` (178 lines) - System health checks and diagnostics
- New `SecretManager` class for secure API key storage via keyring
- Interactive model selection with provider detection
- ModelManager integration for intelligent provider selection

#### E2B Sandbox Integration (3a5d2aa)
- New `namicode_cli/integrations/e2b_executor.py` (241 lines)
- E2B cloud sandbox for secure code execution
- `test_e2b.py` (186 lines) - Comprehensive test suite
- Added `e2b_api_key` to supported API providers

#### Default Subagent System (3a5d2aa)
- New `namicode_cli/default_subagents/` module
- `subagents.py` (36 lines) - Subagent factory functions
- `prompt.py` (138 lines) - Pre-configured system prompts for:
  - `code-explorer-agent` - Deep code research and exploration
  - `code-doc-agent` - Documentation generation from code
  - `code-simplifier-agent` - Code simplification and refactoring

#### Enhanced Agent Tools (3a5d2aa)
- `namicode_cli/tools.py` (138 lines) - Extended tool implementations
- New `get_default_subagents()` tool for retrieving pre-configured subagents
- Improved tool registration and discovery

#### Agent Management UI (60b4cc4)
- Enhanced `commands.py` with agent management commands
- Improved agent listing and status display
- Better error handling for agent operations

### Configuration Updates

#### Deployment Preparation (c8e7e0f)
- Updated `pyproject.toml` with enhanced metadata and dependencies
- Improved `setup.py` for better distribution
- Added additional package classifiers

#### Model Configuration (e19f4b6, d0384ab)
- Enhanced model selection and configuration
- `config.py` updated with 101 lines of improvements
- Better error messages and validation

### Bug Fixes

#### Session and Message History Fixes (2399a25)
- Fixed message history persistence across sessions
- Improved session state management
- Better handling of long-running sessions

### Documentation

#### README Updates (c8e7e0f)
- Cleaned up README content
- Removed outdated installation instructions
- Improved clarity and structure

### Files Changed Summary

| Commit | Files Changed | Lines Added/Removed | Description |
|--------|---------------|---------------------|-------------|
| 3a5d2aa | 16 files | +900/-609 | E2B sandbox, default subagents, tools |
| c8e7e0f | 3 files | +46/-9 | pyproject, setup.py, README updates |
| 60b4cc4 | 1 file | +54/-17 | Agent management UI |
| e19f4b6 | 10 files | +1751/-8 | Onboarding system, doctor, model selection |
| d0384ab | 1 file | +2/-4 | Config bug fixes |
| 7c78368 | 2 files | +31/-1 | Agent memory fixes |

---

## v0.0.13 - 2025-01-10

### Features

#### Session Management System (2399a25)
- Added `session_display.py` (243 lines) for enhanced session visualization
- Added `session_persistence.py` (200 lines) for saving/restoring session state
- Added `session_prompt_builder.py` (175 lines) for building contextual prompts
- Added `session_summarization.py` (192 lines) for conversation summarization
- Added `workspace_anchoring.py` (220 lines) for workspace context management

#### Configuration Updates (2399a25)
- Enhanced `config.py` with improved model settings handling
- Updated `main.py` with session management integration (+141 lines)
- Added `.claude/settings.local.json` for local settings
- Updated `.gitignore` to exclude local settings

#### MCP Middleware Improvements (2399a25)
- Enhanced `mcp/middleware.py` with session-aware MCP management

### Bug Fixes

#### Agent Memory Fix (Pending)
- Fixed `agent_memory.py` - Added list conversion for project memory paths to handle single path returns properly

---

## v0.0.12 - 2025-01-10

### Features

#### Subagent Delegation System Overhaul (0f64635)
- Complete refactor of the subagent delegation system in `agent.py`
- Added comprehensive subagent prompt documentation in `AGENT_PROMPT_ENHANCEMENT.md`
- Enhanced `default_agent_prompt.md` with detailed delegation instructions
- Added subagent observability documentation in `SUBAGENT_OBSERVABILITY.md`
- Implemented subagent color tracking via `set_subagent_color()`, `get_subagent_color()`, `get_all_subagent_colors()`, `clear_subagent_colors()` functions
- Added subagent output formatting with agent type labels (e.g., `🤖 [general-purpose]`)
- Added `get_shared_store()` singleton pattern for agent/subagent memory sharing
- Enhanced `create_agent_with_config()` with shared InMemoryStore integration

#### Agent and Subagent System Prompt Improvements (028396a)
- Comprehensive `.nami/NAMI.md` file (592 lines) for AI assistant guidance
- Removed redundant documentation files (`AGENT_PROMPT_ENHANCEMENT.md`, `IMPLEMENTATION_SUMMARY.md`, `SUBAGENT_OBSERVABILITY.md`, `Task.md`, `UNICODE_FIX.md`)
- Updated `default_agent_prompt.md` with improved delegation instructions
- Added subagent task tool documentation with example usage patterns
- Added subagent color customization support (hex codes like `#ef4444`)

#### Execution Improvements (0f64635)
- Added `execute_bash_command()` for command execution in `commands.py`
- Enhanced `execute_task()` with better error handling
- Added tool call tracking and visibility improvements
- Added `TokenTracker` improvements in `ui.py`
- Enhanced `token_utils.py` for better token calculation

### Bug Fixes

#### Subagent Delegation Fixes (0f64635)
- Fixed subagent delegation system prompt issues
- Resolved context isolation between main agent and subagents
- Fixed shared memory communication between agents
- Added proper subagent color inheritance

#### Memory System Fixes (0f64635)
- Fixed `AgentMemoryMiddleware` initialization
- Added proper memory persistence for subagents
- Fixed memory store reset on session boundaries

### Documentation

#### Comprehensive Documentation Update (028396a)
- Added `.nami/NAMI.md` (592 lines) - comprehensive AI assistant guidance
- Added `CLAUDE.md` (281 lines) - Claude Code specific guidance
- Removed fragmented documentation files
- Consolidated project memory into single authoritative source

#### README Updates (07d8d5f, f44bf0f, 52f9890, 12ba225)
- Updated project documentation
- Added new features and improvements
- Fixed outdated information

### Files Changed Summary

| Commit | Files Changed | Description |
|--------|---------------|-------------|
| 028396a | 8 files | +673/-904 | NAMI.md creation, documentation consolidation, prompt enhancement |
| 0f64635 | 13 files | +1480/-18 | Subagent delegation fixes, memory system, observability |
| 07d8d5f | 1 file | +2/-2 | README update |
| f44bf0f | 1 file | +1/-1 | README update |
| 52f9890 | 1 file | +1/-1 | README update |
| 12ba225 | 1 file | +1/-1 | README update |

---

## v0.0.11 - 2025-01-08

### Features

#### Harbor Evaluation Wrapper Improvements (4a10323)
- Added Windows asyncio ProactorEventLoop policy to fix subprocess issues
- Updated NamiCodeWrapper to use ModelManager for provider detection
- Added "harbor" sandbox type for Terminal-Bench evaluations
- Fixed create_agent_with_config call to match current API

#### Memory System Enhancement - .gitignore Rule (28f8928)
- Added critical `.gitignore` rule to project memory (NAMI.md)
- Added universal `.gitignore` rule to user agent memory for all projects
- Files in `.gitignore` are now never accessed for security/privacy
- Enforced across all AI assistants working with the codebase

#### Image Loading Support (2d1a8cd)
- New `namicode_cli/image_utils.py` module (209 lines)
- Supports loading and displaying images in terminal
- Added dependencies for image processing
- Used for banner display and visual enhancements

#### Session File Tracking & /files Command (037644f)
- New `/files` command shows session file summary
- Tracks all read_file operations with timestamps, content hashes, line/character counts
- Maintains write history per file with operation types
- Provides `SessionFileTracker` dataclass for session-level tracking
- Supports file operation statistics and content previews

#### FileTrackerMiddleware - read_file-Before-edit Enforcement (037644f)
- **Hard read-before-edit enforcement**: Rejects edit operations on files that haven't been read in the current session
- **File content caching**: Stores file hashes and content for edit verification
- **Security enhancement**: Prevents accidental edits to files outside project scope
- Added `namicode_cli/file_tracker.py` with 572 lines of middleware implementation

#### Lower Context Summarization Thresholds (037644f)
- Triggers context summarization at 70% instead of previous threshold
- Reduces token usage before context overflow
- Improves long-running session performance

#### Agent Colors via YAML Frontmatter (477f392)
- Custom agents can define colors in `agent.md` YAML frontmatter:
  ```markdown
  ---
  color: #22c55e
  ---
  ```
- Added `parse_agent_color()`, `get_agent_color()`, `set_agent_color()` functions
- Color applies to spinner, agent name, and output display
- Stored in `_agent_colors` registry in `config.py`

#### Shared Memory System (477f392)
- Cross-agent memory sharing with attribution tracking
- New `namicode_cli/shared_memory.py` module (405 lines)
- Supports `write_memory`, `read_memory`, `list_memories`, `delete_memory` tools
- Memory entries include author attribution (`main-agent` or `subagent:<name>`)
- Timestamps and optional tags for each memory
- Module-level singleton via `get_shared_memory_middleware()`

#### Agent Memory Middleware (fdcd958, 477f392)
- Loads agent.md memory files at session start
- Supports both global (`~/.nami/agents/<name>/agent.md`) and project-level memory
- Automatic memory updates based on user feedback
- YAML frontmatter parsing for configuration

### UI/UX Improvements

#### Branded ASCII Art Update (2d1a8cd)
- Renamed `DEEP_AGENTS_ASCII` → `NAMI_CODE_ASCII` for proper branding
- Updated all references in `commands.py`, `ui.py`, `input.py`
- Consistent branding across the CLI

#### Interactive Command Improvements (2d1a8cd)
- Improved agent creation prompts with better formatting
- Added example agent types with clearer descriptions
- Enhanced user guidance for agent configuration

### Bug Fixes

#### MCP Tool Loading Fix (037644f, 477f392)
- Fixed `tool_name_prefix` parameter issue in `load_mcp_tools()`
- Resolved errors for MCP servers: playwright, github, netlify

#### Subagent Output Visibility (037644f)
- Fixed subagent output visibility during task execution
- Removed namespace filtering that was hiding subagent messages
- Added visual labels (`🤖 [general-purpose]:`) for agent type

### Technical Changes

#### New Module: ACP Server (fdcd958)
- Added `acp/` directory with AI Communication Protocol server
- `acp/deepagents_acp/server.py` - 655 line server implementation
- Tests for chat model and server functionality
- Pyproject configuration for AI protocols

#### New Module: Image Utilities (2d1a8cd)
- New `namicode_cli/image_utils.py` for image loading/display
- Terminal-compatible image rendering support

#### New Module: Evaluation Framework (fdcd958)
- Added `evaluation/` directory with Harbor backend
- `deepagents_harbor/backend.py` - 377 line evaluation backend
- `deepagents_harbor/tracing.py` - LangSmith integration
- `evaluation/scripts/analyze.py` - Analysis script (796 lines)
- `evaluation/scripts/harbor_langsmith.py` - LangSmith integration (501 lines)
- Terminal-bench-2 integration for benchmark testing

#### Configuration Updates (493104c, 477f392)
- Added `nest-asyncio` dependency for async support
- Updated MCP-related dependencies
- Added `wcmatch` pattern matching library
- Added image processing dependencies (2d1a8cd)

#### Evaluation Framework Improvements (47e2801)
- Major refactor of `deepagents_wrapper.py` for better evaluation handling
- Added comprehensive `namicode_wrapper.py` with terminal-bench integration
- Added Terminal-Bench dataset test results (60+ evaluation tasks)
- Added test result artifacts for benchmark validation
- Added `evaluation/deepagents_harbor/config.json` for Harbor configuration

#### Memory System Architecture (fdcd958, 477f392)
- Added `InMemoryStore` singleton for agent/subagent communication
- `reset_shared_store()` for session reset
- LangGraph Store backend integration
- CompositeBackend for multi-backend routing

#### Gitignore Updates (73c52f6)
- Added `.serena/cache/` to gitignore
- Excludes Serena AI assistant cache files

### Documentation

#### NAMI.md Files (037644f)
- Added comprehensive `.nami/NAMI.md` file (574 lines)
- Added root-level `NAMI.md` file (536 lines)
- Covers project overview, architecture, workflows, best practices
- AI assistant guidance for working with the codebase

#### README Updates (176420e)
- Updated documentation
- Added project references and examples

#### EVALUATION.md Documentation (New)
- Added comprehensive `docs/EVALUATION.md` guide
- Complete setup instructions for Harbor evaluation framework
- LangSmith integration guide
- Troubleshooting section

### Files Changed Summary

| Commit | Files Changed | Lines Added/Removed | Description |
|--------|---------------|---------------------|-------------|
| 4a10323 | 3 files | +21/-78 | Harbor evaluation wrapper, Windows asyncio fix |
| 47e2801 | 200+ files | +11,500/-0 | Evaluation framework, Terminal-Bench results |
| 28f8928 | 5 files | +143/-22 | .gitignore rule, user preferences |
| 2d1a8cd | 9 files | +413/-34 | UI changes, NAMI branding, image utilities |
| 73c52f6 | 1 file | +4/-1 | .gitignore updates |
| 176420e | 3 files | +3/-1 | README changes |
| 037644f | 8 files | +1952/-35 | FileTrackerMiddleware, /files command, context thresholds |
| 28617c3 | 1 file | +1/-1 | README update |
| 477f392 | 14 files | +706/-37 | Agent colors, shared memory |
| 493104c | 1 file | +3/0 | pyproject.toml |
| fdcd958 | 26 files | +12569/-13 | ACP server, evaluation framework |
| **Total** | **270+ files** | **~27,170 lines** | |
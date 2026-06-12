# Changelog - v1.3

## New Features

### Council of Agents (`/council`)
- **Renamed from `/chat`**: The multi-agent discussion command is now `/council` — no backward-compatible alias
- **Democratic voting**: Each agent produces an independent answer; the final response is selected by majority vote
- **Cross-round history**: Council agents now carry conversation history across rounds for coherent multi-turn debates
- **Multi-`@agent` routing**: Route prompts to specific agents using `@agent` mentions inside the TUI

### HITL Policy Engine
- **Configurable approval policies**: Define policies (allow, deny, conditional) per tool or tool category
- **Approval notifications**: HITL interrupts surface as notification badges in the TUI status bar with pending approval count
- **Native approval modal**: Keyboard-friendly approve/dismiss flow with arrow-key navigation

### LangGraph Platform Deployment
- **`langgraph.json`**: Full LangGraph Platform deployment config with `source.kind=uv` for consistent dependency resolution
- **Docker support**: Docker Compose stack for self-hosted LangGraph server deployment
- **Async subagent server**: Remote LangGraph server endpoints for background documentation updates, code reviews, and test generation

### LLM Wiki
- **Persistent wiki system**: Scrapable, queryable wiki built from ingested documentation sources
- **`/ingest` command**: Pull external documentation into the wiki knowledge base
- **`/ask` command**: Query the wiki for context-backed answers

### Eval Harness
- **Automated evaluation**: Structured evaluation framework for benchmarking agent performance
- **LangSmith integration**: Trace and evaluate runs through LangSmith's evaluation pipeline

### Plugin System
- **Python entry-point plugins**: Plugins register slash commands, middleware at defined slots, and custom tools via `pyproject.toml` entry points
- **`/plugins` manager**: Native TUI screen to list, enable, and disable installed plugins
- **Repo reorganization**: Project structure reorganized to support the plugin discovery mechanism

### Ralph Integration
- **Ralph emit**: Inline Ralph expressions for quick calculations and data transformations within the chat

### `create` Command
- **`nova create <name>`**: Scaffold new projects with `uv init` and optional templates

## Improvements

### Hermes Learning System
- **Memory rework**: Full rewrite of the memory consolidation pipeline — cleaner two-tier separation (prompt-injected markdown vs. key-value store)
- **Self-evolution**: Autonomous skill refinement cycle: review → extract lesson → create/update skill → re-evaluate
- **Skill schema validation**: Skills are validated against an extended schema (frontmatter + steps structure)
- **Skill debate**: Compares new skill against existing ones to prevent duplication before creation
- **Overhauled tracker**: Improved `skill_usage` tracking with outcome-based refinement triggers

### TUI Enhancements
- **Native `/dream`**: Dream consolidation runs as a native TUI action with live status updates
- **`/clear` reset**: Full transcript clear resets the turn state and input buffer properly
- **Ralph emit**: Ralph results displayed inline in the TUI transcript
- **Multi-`@agent` routing**: Route prompts to specific subagents from the input line
- **`@`-mention autocomplete fix**: Corrected autocomplete popup behavior for file/agent mentions
- **Keyboard-friendly text selection**: `ctrl+c` copies selected text (if any), else quits
- **Bash alias mode**: `!command` prefix detected and styled with magenta accent in the input bar
- **Paste tracking**: Large paste detection with placeholder preview before submission
- **Matrix rain pause**: Animation pauses when terminal loses OS focus or is scrolled out of view

### Steering & Prompts
- **Mid-run steering**: Steering instructions now reach the agent while it's actively running (not just on next turn)
- **Prompt cleanup**: Removed outdated prompt fragments, tightened core system prompt
- **`/init` crash fixes**: Fixed crashes during project graph rebuild with certain project structures

### Sandbox & Safety
- **Pattern A sandbox**: New sandbox execution pattern for isolated agent runs
- **LangSmith sandbox**: New sandbox provider integration with LangSmith
- **Sandbox lifecycle hardening**: Proper cleanup of orphaned/stale sandbox containers on session end
- **Plugins security**: Plugin sandboxing with restricted tool access

### Session Management
- **Project memory always loaded**: `NOVA.md` / `CLAUDE.md` loaded into `<project_memory>` context even on session resume
- **Session picker honors `/clear`**: The resume session picker properly shows cleared sessions as fresh

## Bug Fixes

- **Async subagent initialization**: Fixed race conditions in async subagent startup
- **Shell/bash tool**: Fixed shell execution hanging on multi-line commands; improved error propagation
- **Vision handling**: Fixed initial bug where vision/image inputs weren't being passed to the model correctly
- **Vision captioning rework**: Image captioning now uses the vision model directly instead of a separate captioning call
- **`edit_file` UX**: Fixed edit failure not showing a clear error message to the user
- **Response streaming truncation**: Fixed edge case where streaming responses were cut off at the end
- **Hermes memory leak**: Fixed cross-session memory accumulation that inflated context windows
- **Steering prompt truncation**: Fixed steering instructions being silently dropped when combined with long system prompts
- **`/init` crashes**: Fixed crashes on projects without `pyproject.toml` or with circular dependencies

## Technical Changes

- **Repository reorganization**: Moved modules into clearer directory structure to support the plugin system
- **`pyproject.toml`**: Added `[project.entry-points."nova.plugins"]` for plugin discovery
- **Dependency updates**: Bumped `deepagents` framework dependency; added `langgraph` SDK for platform deployment
- **Test suite expansion**: Added new test coverage for Hermes review cycles, HITL policy engine, and sandbox lifecycle

---

## v1.2 - Previous Release

See [`CHANGELOG-v1.2.md`](CHANGELOG-v1.2.md) for the documentation update agent and async subagent configuration changes.
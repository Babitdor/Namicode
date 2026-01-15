# Changelog

All notable changes to the Nami-Code project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## v0.1.1 - TBD

### Features

- **Full TUI Integration**: Complete integration of all dialogs and commands in the Textual-based TUI
- **Model Selection Dialog**: Interactive model/provider selection (`ModelSelectionDialog`)
- **Sessions Dialog**: List, resume, and delete saved sessions (`SessionsDialog`)
- **Agents Dialog**: Browse and select available agents (`AgentsDialog`)
- **MCP Management Dialog**: Add/remove MCP servers (`MCPDialog`)
- **Continue Session Dialog**: Resume previous sessions on startup (`ContinueSessionDialog`)
- **Agent Mention Dialog**: Autocomplete for @agent mentions (`AgentMentionDialog`)
- **Auto-Save**: Sessions auto-save every 5 minutes with workspace state
- **Session Save on Exit**: Automatic session persistence when exiting
- **Dialog Methods**: All `_show_*_dialog()` methods integrated into `DeepAgentsApp`
- **Textual Command Handlers**: `/mcp`, `/model`, `/skills`, `/agents` commands now use native Textual dialogs instead of Rich console/prompt_toolkit
- **prompt_toolkit Removal**: Replaced all prompt_toolkit dependencies with Python's built-in `input()` and `getpass()` functions for console mode, while Textual UI uses the new dialog widgets

### Bug Fixes

- Fixed import errors in `tui_commands.py`
- Fixed session state tracking for auto-save
- Fixed dialog result handlers

### Improvements

- Command handlers now delegate to dialog methods when available
- Graceful fallback to inline messages if dialog methods not available
- Better error handling in session management

### Documentation

- Updated `CLAUDE.md` with TUI integration details
- Added inline documentation for all dialog classes

## v0.1.0 - Initial Release

- Basic Textual TUI implementation
- Chat interface with message widgets
- Approval menu for tool execution
- Basic command handling
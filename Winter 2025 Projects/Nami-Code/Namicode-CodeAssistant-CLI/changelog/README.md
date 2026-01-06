# Changelog Index

This directory contains detailed changelogs for Namicode CodeAssistant CLI.

## Recent Changes

### [2025-01-05] - Subagent Streaming & Backend Improvements
**File:** `2025-01-05-subagent-streaming-improvements.md`

Major improvements to subagent output streaming, display labeling, and backend configuration.

**Key Changes:**
- Added visual labels for subagents (e.g., `🤖 [general-purpose]:`)
- Enhanced streaming to capture all agent namespaces
- Fixed double printing of agent responses
- Backend configuration refactoring (with ongoing investigation)
- Improved multi-agent workflow visualization

**Files Modified:**
- `namicode_cli/execution.py` - Subagent tracking and labeling
- `namicode_cli/commands.py` - Backend configuration
- `namicode_cli/mcp/middleware.py` - Tool naming behavior

---

## Changelog Format

Each changelog entry includes:
- **Summary** - High-level overview of changes
- **Changes** - Detailed breakdown by category (User Experience, Backend, Bug Fixes)
- **Technical Details** - Implementation specifics
- **Migration Notes** - Breaking changes or actions needed
- **Future Work** - Planned improvements

---

## Commit History Reference

Recent commits:
- `4c10db9` - Reverted backend changes
- `0b8e0b1` - Backend reverted to original due to bugs (under Investigation)
- `a43a4ba` - Agent Backend changes
- `0611c4a` - Langsmith fixes and .env.template changes
- `7a7cc97` - Langsmith tracing added
- `0f6ad1c` - Issue Fixed : Double printing Agent responses
- `a515df0` - Major changes to Response output
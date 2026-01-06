# Changelog

## [2025-01-05] - Subagent Streaming & Backend Improvements

### Summary
Major improvements to subagent output streaming, display labeling, and backend configuration. These changes enhance the user experience when working with subagents by providing clear visual indicators and fixing duplicate response issues.

### Changes

#### 🎨 User Experience Improvements

**Subagent Labeling (`namicode_cli/execution.py`)**
- Added visual labels to identify which agent is generating responses
- Subagents now display with format: `🤖 [subagent-type]:` (e.g., `🤖 [general-purpose]:`)
- Agent labels appear when entering different agent namespaces
- Improved tracking of agent transitions during multi-agent workflows
- Removed restriction that prevented displaying subagent messages, now streaming all agent content

**Stream Processing Enhancements**
- Stream text from all namespaces (not just root namespace) to capture full agent output
- Track agent namespace transitions using model tags from metadata
- Stop spinner and flush buffers when switching between agents
- Better handling of reasoning blocks in multi-agent scenarios

#### 🔧 Backend Configuration

**Subagent Backend Refactoring (`namicode_cli/commands.py`)**
- **Commit a43a4ba**: Added CompositeBackend configuration for subagents with route for `/memies/`
- **Commit 0b8e0b1**: Reverted backend changes due to bugs (under investigation)
- **Commit 4c10db9**: Further simplified backend - removed CompositeBackend, now using direct backend
- Current state: Subagents use the same backend as the main agent

**MCP Middleware (`namicode_cli/mcp/middleware.py`)**
- Removed `tool_name_prefix=False` parameter, restoring default tool naming behavior

#### 🐛 Bug Fixes

**Double Printing Issue (Commit 0f6ad1c)**
- Fixed issue where agent responses were being printed twice
- Removed duplicate documentation files:
  - `Streaming.md` (878 lines)
  - `Subagents.md` (412 lines)
  - `subagent_fix_suggestions.md` (136 lines)
- Added `.gitignore` entries for better version control

### Technical Details

#### Namespace Tracking
The execution engine now tracks agent namespaces to provide clear labeling:
- Root namespace: `()` - main agent
- Subagent namespace: `("task", "model_node")` or `("custom_agent", "model_node")`
- Model tags in metadata identify the active agent

#### Streaming Flow
1. Detect namespace change via `_namespace` or metadata tags
2. Stop any active spinner and flush buffered text
3. Display agent label with robot emoji
4. Stream content from the new agent
5. Repeat when switching back to another agent

### Migration Notes

- If you were relying on subagent output being hidden, it will now be displayed
- Tool names may now include server prefixes (default MCP SDK behavior)
- Visual agent labels provide context in multi-agent conversations

### Future Work

- **Backend Investigation**: The CompositeBackend removal is temporary pending bug investigation
- Possible restoration of `/memories/` routing for subagents once issues are resolved
- Continued refinement of multi-agent streaming experience

---

## Related Commits

- `4c10db9` - Reverted backend changes
- `0b8e0b1` - Backend reverted to original due to bugs (under Investigation)
- `a43a4ba` - Agent Backend changes
- `0f6ad1c` - Issue Fixed : Double printing Agent responses

## Unstaged Changes

**namicode_cli/execution.py**
- Subagent namespace tracking and labeling implementation
- Enhanced streaming for all agent namespaces

**namicode_cli/mcp/middleware.py**
- Tool name prefix parameter removal

**samples/**
- New untracked directory (contents not yet reviewed)
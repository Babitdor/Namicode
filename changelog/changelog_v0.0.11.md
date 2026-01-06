## v0.0.11 - 2025-01-XX

### Features
- **Subagent Observability**: Fixed subagent output visibility during task execution
  - Subagents (invoked via `task` tool) now display their output in real-time
  - Added visual labels to distinguish between main agent and subagent output
  - Shows agent type (e.g., `🤖 [general-purpose]:`) when entering subagent namespaces
  - Support for custom subagent type labeling

### Bug Fixes
- Fixed MCP tool loading error: Removed unsupported `tool_name_prefix` parameter from `load_mcp_tools()` call in `namicode_cli/mcp/middleware.py`
  - Resolved errors: "load_mcp_tools() got an unexpected keyword argument 'tool_name_prefix'"
  - Affected MCP servers: playwright, github, netlify

### Technical Details
- Modified `namicode_cli/execution.py` to properly handle streaming from subagent namespaces
- Removed namespace filtering that was hiding all subagent messages
- Added `current_agent_namespace` tracking for agent identification
- Implemented tag-based agent source identification from model metadata
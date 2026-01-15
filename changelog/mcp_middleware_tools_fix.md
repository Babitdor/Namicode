# MCP Middleware Tools Fix

## Date
2025-01-15

## Type
Bug Fix

## Description
Fixed MCPMiddleware not registering discovered tools with the agent. The middleware was successfully discovering tools from MCP servers and storing them in `self.tools`, but these tools were never actually added to the agent's available tool list.

## Root Cause
The `wrap_model_call` and `awrap_model_call` methods in MCPMiddleware only modified the system prompt to document available MCP tools, but never injected the actual tools into the ModelRequest's tools list. This meant the agent knew about the tools from the documentation but couldn't actually call them.

## Changes
### namicode_cli/mcp/middleware.py
- Modified `wrap_model_call()` to merge `self.tools` with `request.tools` using `request.override(tools=updated_tools)`
- Modified `awrap_model_call()` with the same fix for async paths
- Now properly adds MCP tools to the agent's tool list while also documenting them in the system prompt

### deepagents-nami/nami_deepagents/middleware/mcp.py
- Applied identical fixes to keep both copies in sync

## Impact
- MCP tools are now actually callable by agents
- Tools are both registered AND documented in the system prompt
- Existing MCP server configurations will work correctly after this fix

## Testing
To verify the fix works:
1. Configure an MCP server in `~/.nami/mcp.json`
2. Start the agent: `uv run nami`
3. Ask the agent to use an MCP tool (e.g., "Use filesystem__read_file to list files")
4. The agent should be able to successfully call the MCP tool
# Nami-Code CLI Codebase Overview (Updated)

## Project
Nami-Code CLI - A terminal-based AI coding assistant built on the `deepagents` library, similar to Claude Code.

## Structure (59 Python files)

### Core Modules
- `main.py` - Entry point with CLI loop, args parsing, session management
- `agent.py` - Agent creation (`create_agent_with_config()`), tool descriptions, system prompt building, **shared store pattern**
- `execution.py` - Task execution, streaming output, tool approval
- `tools.py` - Built-in tools: http_request, fetch_url, web_search, shell, file operations, run_tests, dev_server tools
- `ui.py` - Rich-based terminal UI rendering

### MCP Integration (Model Context Protocol)
- `mcp/client.py`:
  - `build_mcp_server_config()` - Converts MCPServerConfig to dict format
  - `build_mcp_config_dict()` - Builds config for MultiServerMCPClient
  - `create_mcp_client()` - Factory for MultiServerMCPClient
  - `check_server_connection()` - Tests MCP server connectivity

- `mcp/middleware.py`:
  - `MCPMiddleware` class - Discovers and registers MCP tools using session context
  - `MCPState`, `MCPStateUpdate` - State schema

- `mcp/config.py`:
  - `MCPConfig` - Manages ~/.nami/mcp.json
  - `MCPServerConfig` - Pydantic model for server configs (transport: http|stdio)

- `mcp/presets.py` - Pre-configured servers: filesystem, github, brave-search, playwright, serena, etc.

- `mcp/commands.py` - Interactive /mcp command handler

### Skills System
- `skills/commands.py`, `skills/load.py`, `skills/middleware.py` - Progressive disclosure

### Subagent Module
- `subagent.py` - `create_subagent()` function for standalone subagent creation
- Uses same middleware stack as main agent
- **Shares the same store via `use_shared_store` parameter**

## Shared Store Pattern (agent.py)

### Module-Level Shared Store
```python
# agent.py
_shared_store: InMemoryStore | None = None

def get_shared_store() -> InMemoryStore:
    """Get or create the shared InMemoryStore for agent/subagent communication."""
    global _shared_store
    if _shared_store is None:
        _shared_store = InMemoryStore()
    return _shared_store

def reset_shared_store() -> None:
    """Reset the shared store (useful for new sessions)."""
    global _shared_store
    _shared_store = None
```

### create_agent_with_config() Signature
```
model: required
assistant_id: required
tools: required
sandbox: None
sandbox_type: None
store: None
use_shared_store: True  # <-- NEW: defaults to shared store
```

### create_subagent() Signature
```
agent_name: required
model: required
tools: required
backend: None
settings: required
store: None
use_shared_store: True  # <-- NEW: defaults to shared store
```

### Verified Behavior
```python
s1 = get_shared_store()
s2 = get_shared_store()
s1 is s2  # True - Same instance!
```

## Usage

### Main Agent + Subagent (shared memory by default)
```python
from namicode_cli.agent import create_agent_with_config
from namicode_cli.subagent import create_subagent

# Both use shared store by default
agent, _ = create_agent_with_config(model, "assistant", tools)
subagent, _ = create_subagent("researcher", model, subagent_tools, settings=settings)
```

### Explicit Store Passing
```python
my_store = InMemoryStore()
agent, _ = create_agent_with_config(model, "assistant", tools, store=my_store)
subagent, _ = create_subagent("researcher", model, subagent_tools, settings=settings, store=my_store)
```

### Isolated Memory (for testing)
```python
agent, _ = create_agent_with_config(model, "assistant", tools, use_shared_store=False)
subagent, _ = create_subagent("researcher", model, subagent_tools, settings=settings, use_shared_store=False)
```

### Reset for New Session
```python
from namicode_cli.agent import reset_shared_store
reset_shared_store()
```

## Tests
- `tests/unit_tests/mcp/test_middleware.py` - 10 tests
- Manual verification confirms shared store works correctly

## Dependencies
- langchain-mcp-adapters - MCP client management
- deepagents-nami - Custom deep agent library with SubAgentMiddleware
- Rich - Terminal UI
- prompt_toolkit - Interactive input
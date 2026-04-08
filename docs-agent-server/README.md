# Documentation Update Agent Server

A LangGraph server that runs the documentation update agent in the background.

## Setup

### 1. Install Dependencies

```bash
cd docs-agent-server
uv venv
source .venv/bin/activate  # or `.venv\Scripts\activate` on Windows
uv pip install -e .
```

### 2. Configure Environment

```bash
cp .env.example .env
# Edit .env and add your API keys
```

Required environment variables:
- `ANTHROPIC_API_KEY` - For the Claude model
- `LANGGRAPH_API_KEY` - For LangGraph Platform (optional for self-hosted)

### 3. Run the Server

**Development (local):**
```bash
langgraph up
```

**Production (LangGraph Platform):**
```bash
langgraph deploy
```

The server will be available at `http://localhost:8123` (development) or your LangGraph Platform URL.

## Usage with Nova CLI

Once the server is running, Nova CLI can start async documentation tasks:

```python
# In Nova CLI, the agent will have access to:
# - start_async_task: Start a documentation update task
# - check_async_task: Check task status
# - update_async_task: Send follow-up instructions
# - cancel_async_task: Cancel a running task
# - list_async_tasks: List all tracked tasks
```

### Example Workflow

1. **Start a task:**
   ```
   User: "I committed changes to the API, update the docs"
   Nova: [calls start_async_task]
         "Started documentation update (task_id: abc123)"
   ```

2. **Check status:**
   ```
   User: "Is the doc update done?"
   Nova: [calls check_async_task]
         "Status: running" or "Status: success. Updated README.md"
   ```

3. **Send follow-up:**
   ```
   User: "Also update the changelog"
   Nova: [calls update_async_task]
         "Sent follow-up to task abc123"
   ```

## Configuration

### Custom URL

If running on a custom server, update `async_subagents.py`:

```python
DOCUMENTATION_UPDATE_AGENT: AsyncSubAgent = {
    "name": "documentation-update-agent",
    "description": DOCUMENTATION_UPDATE_AGENT_DESCRIPTION,
    "graph_id": "documentation-update-agent",
    "url": "https://your-server.example.com",
    "headers": {"Authorization": "Bearer your-token"},  # Optional
}
```

### Authentication

For LangGraph Platform, set `LANGGRAPH_API_KEY` environment variable.

For self-hosted servers, use the `headers` field:

```python
"headers": {
    "Authorization": "Bearer your-token",
    "X-Custom-Header": "value",
}
```

## API

The agent accepts these inputs via the `start_async_task` tool:

- `description`: Detailed description of what documentation to update
- `subagent_type`: Always `"documentation-update-agent"`

The agent state can include:
- `repo_path`: Path to the repository
- `commit_info`: Commit messages or change descriptions
- `files_changed`: List of files that were modified

## Architecture

```
Nova CLI                    LangGraph Server
    │                              │
    │ start_async_task             │
    ├─────────────────────────────►│
    │                              │
    │  (task_id returned)          │
   ◄├─────────────────────────────┤
    │                              │
    │  (user continues working)    │ Agent processes
    │                              │ documentation
    │                              │
    │ check_async_task             │
    ├─────────────────────────────►│
    │                              │
    │  (status + result)           │
   ◄├─────────────────────────────┤
```
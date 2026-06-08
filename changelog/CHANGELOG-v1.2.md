# Changelog - v1.2

## New Features

### Documentation Update Agent
- Introduced a new `documentation-update-agent` built using the `deepagents` framework.
- **Capabilities**:
    - Automatically analyzes git commits and diffs to update project documentation.
    - Maintains README files and generates changelog entries.
    - Uses `gemma4:31b-cloud` via Ollama.
    - Equipped with custom tools: `get_recent_commits`, `get_commit_diff`, `get_changed_files_since`, and `list_documentation_files`.
    - Utilizes `CompositeBackend` (Filesystem + Store) for persistent project state.

## Refactors & Improvements

### Async Subagent Configuration
- Refactored async subagent initialization in `novacode_cli/agents/default_subagents/async_subagents.py`.
- Moved from static dictionary configuration to dynamic builder functions (`build_documentation_update_agent`).
- Added support for environment variable resolution for agent connectivity:
    - `DOC_AGENT_URL`: Explicit override for the documentation agent URL.
    - `LANGGRAPH_API_URL`: Shared LangGraph Platform URL.
    - `LANGGRAPH_API_KEY`: Authentication key for the remote server.

### Dependency Management
- Updated `langgraph.json` to use `source.kind=uv`, ensuring consistent dependency resolution via the `uv` package manager when using the LangGraph CLI.

## Technical Changes
- Updated exports in `novacode_cli/agents/default_subagents/__init__.py` to support the new builder pattern for async agents.

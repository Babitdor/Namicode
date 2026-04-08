# Async Subagents for NOVA CLI
# These run on remote LangGraph servers in the background

from typing import Any

from nova_deepagents.middleware.async_subagents import AsyncSubAgent


# Documentation Update Agent - Updates docs based on commits
DOCUMENTATION_UPDATE_AGENT_DESCRIPTION = """An async agent that automatically updates documentation in the background.

Use this agent when:
- You've committed code changes that need documentation updates
- README files need to reflect new features or API changes
- Changelog entries need to be generated from commit messages
- API documentation needs to be synchronized with code changes
- Code comments or docstrings need updating

The agent runs remotely and asynchronously, so you can continue working while it processes documentation updates.
"""

DOCUMENTATION_UPDATE_AGENT: AsyncSubAgent = {
    "name": "documentation-update-agent",
    "description": DOCUMENTATION_UPDATE_AGENT_DESCRIPTION,
    "graph_id": "documentation-update-agent",
    # URL is optional - defaults to LangGraph SDK default endpoint
    # Set LANGGRAPH_API_KEY environment variable for LangGraph Platform
    # "url": "https://your-langgraph-server.example.com",
}


def retrieve_async_subagents() -> list[AsyncSubAgent]:
    """Return the list of available async subagents.

    Async subagents run on remote Agent Protocol servers and execute
    in the background, returning a task ID immediately.

    Returns:
        List of AsyncSubAgent configurations.
    """
    return [
        DOCUMENTATION_UPDATE_AGENT,
    ]
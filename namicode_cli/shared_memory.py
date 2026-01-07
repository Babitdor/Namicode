"""Shared Memory Middleware for cross-agent communication.

This middleware provides memory tools that are shared between the main agent
and all subagents, enabling:
1. Cross-conversation memory (persists across agent invocations)
2. Attribution tracking (who wrote what)
3. Shared context between main agent and subagents
"""

import json
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any, NotRequired, TypedDict

from langchain.agents.middleware.types import (
    AgentMiddleware,
    AgentState,
    ModelRequest,
    ModelResponse,
)
from langchain.tools import BaseTool
from langchain_core.tools import StructuredTool
from langgraph.store.memory import InMemoryStore


class MemoryEntry(TypedDict):
    """A single memory entry with attribution."""

    content: str
    """The content of the memory."""

    author: str
    """Who wrote this memory (e.g., 'main-agent', 'subagent:researcher')."""

    timestamp: str
    """ISO timestamp when the memory was written."""

    tags: NotRequired[list[str]]
    """Optional tags for categorization."""


class SharedMemoryState(AgentState):
    """State schema for shared memory middleware."""

    shared_memories: NotRequired[dict[str, MemoryEntry]]
    """Dictionary of memory key -> MemoryEntry."""


# Module-level shared memory store
_shared_memory_store: InMemoryStore | None = None


def get_shared_memory_store() -> InMemoryStore:
    """Get or create the shared memory store.

    Returns:
        Shared InMemoryStore instance for memory operations.
    """
    global _shared_memory_store
    if _shared_memory_store is None:
        _shared_memory_store = InMemoryStore()
    return _shared_memory_store


def reset_shared_memory_store() -> None:
    """Reset the shared memory store (for new sessions)."""
    global _shared_memory_store
    _shared_memory_store = None


# Namespace for shared memories
MEMORY_NAMESPACE = ("shared_memory",)


def write_memory(
    key: str,
    content: str,
    author: str = "unknown",
    tags: list[str] | None = None,
) -> str:
    """Write a memory entry to the shared store.

    Args:
        key: Unique identifier for this memory.
        content: The content to store.
        author: Who is writing this memory.
        tags: Optional tags for categorization.

    Returns:
        Confirmation message.
    """
    store = get_shared_memory_store()

    entry: MemoryEntry = {
        "content": content,
        "author": author,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if tags:
        entry["tags"] = tags

    store.put(MEMORY_NAMESPACE, key, entry)

    return f"Memory '{key}' written successfully by {author}."


def read_memory(key: str) -> str:
    """Read a memory entry from the shared store.

    Args:
        key: The key of the memory to read.

    Returns:
        The memory content with attribution, or error message.
    """
    store = get_shared_memory_store()
    item = store.get(MEMORY_NAMESPACE, key)

    if item is None:
        return f"Memory '{key}' not found."

    entry = item.value
    author = entry.get("author", "unknown")
    timestamp = entry.get("timestamp", "unknown")
    content = entry.get("content", "")
    tags = entry.get("tags", [])

    result = f"Memory: {key}\n"
    result += f"Author: {author}\n"
    result += f"Written: {timestamp}\n"
    if tags:
        result += f"Tags: {', '.join(tags)}\n"
    result += f"\n{content}"

    return result


def list_memories(tag_filter: str | None = None) -> str:
    """List all available memories.

    Args:
        tag_filter: Optional tag to filter memories by.

    Returns:
        Formatted list of all memories with metadata.
    """
    store = get_shared_memory_store()

    # Get all items in the namespace
    items = store.search(MEMORY_NAMESPACE, limit=100)

    if not items:
        return "No memories stored yet."

    result_lines = ["# Shared Memories\n"]

    for item in items:
        entry = item.value
        key = item.key
        author = entry.get("author", "unknown")
        timestamp = entry.get("timestamp", "unknown")
        tags = entry.get("tags", [])
        content_preview = entry.get("content", "")[:100]

        # Apply tag filter if specified
        if tag_filter and tag_filter not in tags:
            continue

        result_lines.append(f"## {key}")
        result_lines.append(f"- **Author**: {author}")
        result_lines.append(f"- **Written**: {timestamp}")
        if tags:
            result_lines.append(f"- **Tags**: {', '.join(tags)}")
        result_lines.append(f"- **Preview**: {content_preview}...")
        result_lines.append("")

    if len(result_lines) == 1:
        return f"No memories found with tag '{tag_filter}'."

    return "\n".join(result_lines)


def delete_memory(key: str) -> str:
    """Delete a memory entry.

    Args:
        key: The key of the memory to delete.

    Returns:
        Confirmation or error message.
    """
    store = get_shared_memory_store()
    item = store.get(MEMORY_NAMESPACE, key)

    if item is None:
        return f"Memory '{key}' not found."

    store.delete(MEMORY_NAMESPACE, key)
    return f"Memory '{key}' deleted successfully."


def _create_memory_tools(author_id: str) -> list[BaseTool]:
    """Create memory tools with the specified author ID baked in.

    Args:
        author_id: The identifier for the author (e.g., 'main-agent' or 'subagent:researcher').

    Returns:
        List of memory tools.
    """

    def _write_memory(
        key: str,
        content: str,
        tags: list[str] | None = None,
    ) -> str:
        """Write a memory to the shared memory store.

        Use this to persist information that should be accessible to all agents
        (main agent and subagents). Memories persist across conversation turns.

        Args:
            key: A unique identifier for this memory (e.g., 'research-findings', 'user-preferences').
            content: The content to store. Can be any text including structured data.
            tags: Optional list of tags for categorization and filtering.

        Returns:
            Confirmation message.
        """
        return write_memory(key, content, author=author_id, tags=tags)

    def _read_memory(key: str) -> str:
        """Read a memory from the shared memory store.

        Use this to retrieve information that was previously stored by any agent.

        Args:
            key: The unique identifier of the memory to read.

        Returns:
            The memory content with author and timestamp information.
        """
        return read_memory(key)

    def _list_memories(tag_filter: str | None = None) -> str:
        """List all memories in the shared store.

        Use this to see what memories are available and who wrote them.

        Args:
            tag_filter: Optional tag to filter memories by.

        Returns:
            Formatted list of all memories with metadata.
        """
        return list_memories(tag_filter)

    def _delete_memory(key: str) -> str:
        """Delete a memory from the shared store.

        Args:
            key: The unique identifier of the memory to delete.

        Returns:
            Confirmation or error message.
        """
        return delete_memory(key)

    return [
        StructuredTool.from_function(
            name="write_memory",
            func=_write_memory,
            description=(
                "Write a memory to the shared memory store. Use this to persist information "
                "that should be accessible to all agents (main agent and subagents). "
                "Memories persist across conversation turns and include attribution tracking."
            ),
        ),
        StructuredTool.from_function(
            name="read_memory",
            func=_read_memory,
            description=(
                "Read a memory from the shared memory store. Use this to retrieve information "
                "that was previously stored by any agent. Shows who wrote the memory and when."
            ),
        ),
        StructuredTool.from_function(
            name="list_memories",
            func=_list_memories,
            description=(
                "List all memories in the shared store. Shows available memories with "
                "their authors, timestamps, and content previews. Can filter by tag."
            ),
        ),
        StructuredTool.from_function(
            name="delete_memory",
            func=_delete_memory,
            description="Delete a memory from the shared store.",
        ),
    ]


SHARED_MEMORY_SYSTEM_PROMPT = """
## Shared Memory System

You have access to a **shared memory store** that persists across all agents (main agent and subagents).

### Memory Tools Available:
- `write_memory(key, content, tags?)` - Store information with your author attribution
- `read_memory(key)` - Retrieve a specific memory (shows who wrote it)
- `list_memories(tag_filter?)` - See all available memories
- `delete_memory(key)` - Remove a memory

### When to Use Shared Memory:
1. **Cross-agent communication**: Share findings between main agent and subagents
2. **Persistent context**: Store information that should survive summarization
3. **Research aggregation**: Subagents can write their findings for the main agent to synthesize
4. **User preferences**: Store learned preferences that all agents should know

### Best Practices:
- Use descriptive keys (e.g., 'user-tech-stack', 'research-llm-providers', 'task-progress-summary')
- Include relevant tags for easy filtering
- Check existing memories before duplicating information
- Attribute correctly - your writes will be tagged with your agent ID

### Memory Attribution:
All memories track who wrote them. When you read a memory, you'll see:
- The author (main-agent or subagent:name)
- When it was written
- Any tags associated with it
"""


class SharedMemoryMiddleware(AgentMiddleware):
    """Middleware that provides shared memory tools to agents.

    This middleware:
    1. Adds memory tools (write_memory, read_memory, list_memories, delete_memory)
    2. Tracks attribution (who wrote each memory)
    3. Uses a shared store accessible by main agent and all subagents
    4. Injects system prompt instructions for using shared memory

    Args:
        author_id: The identifier for this agent's writes (e.g., 'main-agent', 'subagent:researcher').
        include_system_prompt: Whether to inject the shared memory system prompt.
    """

    state_schema = SharedMemoryState

    def __init__(
        self,
        author_id: str = "main-agent",
        include_system_prompt: bool = True,
    ) -> None:
        """Initialize the SharedMemoryMiddleware.

        Args:
            author_id: Identifier for attribution (e.g., 'main-agent' or 'subagent:researcher').
            include_system_prompt: Whether to add memory instructions to system prompt.
        """
        super().__init__()
        self.author_id = author_id
        self.include_system_prompt = include_system_prompt
        self.tools = _create_memory_tools(author_id)

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        """Inject shared memory instructions into the system prompt."""
        if self.include_system_prompt:
            system_prompt = (
                request.system_prompt + "\n\n" + SHARED_MEMORY_SYSTEM_PROMPT
                if request.system_prompt
                else SHARED_MEMORY_SYSTEM_PROMPT
            )
            return handler(request.override(system_prompt=system_prompt))
        return handler(request)

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        """(async) Inject shared memory instructions into the system prompt."""
        if self.include_system_prompt:
            system_prompt = (
                request.system_prompt + "\n\n" + SHARED_MEMORY_SYSTEM_PROMPT
                if request.system_prompt
                else SHARED_MEMORY_SYSTEM_PROMPT
            )
            return await handler(request.override(system_prompt=system_prompt))
        return await handler(request)


__all__ = [
    "SharedMemoryMiddleware",
    "get_shared_memory_store",
    "reset_shared_memory_store",
    "write_memory",
    "read_memory",
    "list_memories",
    "delete_memory",
]

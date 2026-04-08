"""Documentation Update Agent - LangGraph Server

This agent runs on a LangGraph server and handles documentation updates
in the background. It can be triggered by Nova CLI to update docs based
on code changes, commits, or manual requests.
"""

from typing import Annotated, TypedDict

from langchain_ollama import ChatOllama
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import StateGraph, add_messages
from langgraph.checkpoint.memory import MemorySaver


# System prompt for the documentation agent
DOCUMENTATION_AGENT_PROMPT = """You are a documentation specialist agent. Your job is to update documentation based on code changes.

## Your Responsibilities

1. **README Updates**: Update README.md files to reflect new features, changed APIs, or updated installation instructions.

2. **Changelog Updates**: Generate changelog entries from commit messages or change descriptions.

3. **API Documentation**: Update API documentation to match code signatures, parameters, and return types.

4. **Code Comments**: Suggest improvements to docstrings and inline comments.

5. **Migration Guides**: Create migration guides for breaking changes.

## Guidelines

- Be concise but thorough
- Use proper Markdown formatting
- Follow existing documentation style
- Include code examples where helpful
- Preserve existing content unless it needs updating
- Mark sections that need manual review with TODO comments

## Output Format

Provide the updated documentation content in Markdown format.
Clearly indicate which files should be updated and what changes were made.
"""


class AgentState(TypedDict):
    """State for the documentation agent."""
    messages: Annotated[list, add_messages]
    repo_path: str | None
    commit_info: str | None
    files_changed: list[str] | None


async def documentation_agent(state: AgentState) -> dict:
    """Process documentation update requests.
    
    This node receives information about code changes and generates
    appropriate documentation updates.
    """
    model = ChatOllama(
        model="glm-5:cloud",
    )
    
    # Build context from state
    context_parts = []
    
    if state.get("repo_path"):
        context_parts.append(f"Repository path: {state['repo_path']}")
    
    if state.get("commit_info"):
        context_parts.append(f"Commit info:\n{state['commit_info']}")
    
    if state.get("files_changed"):
        context_parts.append(f"Files changed: {', '.join(state['files_changed'])}")
    
    context = "\n\n".join(context_parts) if context_parts else "No additional context provided."
    
    # Create messages
    messages = [
        SystemMessage(content=DOCUMENTATION_AGENT_PROMPT),
        *state["messages"],
    ]
    
    # If this is the first message and we have context, add it
    if len(state["messages"]) == 1 and context_parts:
        messages.append(HumanMessage(content=f"Context:\n{context}\n\nPlease update the documentation accordingly."))
    
    response = await model.ainvoke(messages)
    
    return {"messages": [response]}


# Build the graph
graph_builder = StateGraph(AgentState)

# Add nodes
graph_builder.add_node("agent", documentation_agent)

# Set entry and finish points
graph_builder.set_entry_point("agent")
graph_builder.set_finish_point("agent")

# Compile with memory saver for checkpointing
graph = graph_builder.compile(checkpointer=MemorySaver())
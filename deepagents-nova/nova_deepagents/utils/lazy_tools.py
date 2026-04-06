"""Lazy tool loading middleware for context optimization."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from langchain.agents.middleware.types import (
    AgentMiddleware,
    AgentState,
    ContextT,
    ModelRequest,
    ModelResponse,
    ResponseT,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence

    from langchain_core.tools import BaseTool
    from langgraph.runtime import Runtime


class LazyToolLoadingMiddleware(AgentMiddleware[AgentState[ResponseT], ContextT, ResponseT]):
    """Middleware that dynamically loads tools based on task requirements.
    
    This middleware analyzes the current task and only includes tools that are
    actually needed, reducing context overhead from unused tool descriptions.
    
    Example:
        ```python
        from nova_deepagents.utils.lazy_tools import LazyToolLoadingMiddleware
        from langchain.agents import create_agent
        
        # Define tool groups
        tool_groups = {
            'filesystem': [read_file_tool, write_file_tool, edit_file_tool],
            'web': [web_search_tool, fetch_url_tool],
            'code': [lint_tool, test_tool, format_tool],
        }
        
        # Create middleware
        lazy_loader = LazyToolLoadingMiddleware(
            all_tools=tool_groups,
            default_groups=['filesystem'],  # Always load filesystem tools
        )
        
        # Create agent with lazy loading
        agent = create_agent(
            "openai:gpt-4o",
            middleware=[lazy_loader],
        )
        ```
    """
    
    def __init__(
        self,
        all_tools: dict[str, Sequence[BaseTool]] | Sequence[BaseTool],
        default_groups: list[str] | None = None,
        complexity_analyzer: Any | None = None,
    ) -> None:
        """Initialize the lazy tool loading middleware.
        
        Args:
            all_tools: Either a dict mapping group names to tool lists,
                or a flat list of all available tools.
            default_groups: Groups to always load (default: ['filesystem'])
            complexity_analyzer: Optional TaskComplexityAnalyzer instance
                for determining which tools to load.
        """
        super().__init__()
        
        # Normalize tools to dict format
        if isinstance(all_tools, dict):
            self.tool_groups = all_tools
        else:
            # Auto-group tools by name prefix
            self.tool_groups = self._auto_group_tools(all_tools)
        
        # Set default groups
        self.default_groups = default_groups or ['filesystem']
        
        # Import complexity analyzer if not provided
        if complexity_analyzer is None:
            from nova_deepagents.utils.complexity import TaskComplexityAnalyzer
            self.complexity_analyzer = TaskComplexityAnalyzer()
        else:
            self.complexity_analyzer = complexity_analyzer
        
        # Initialize with default tools
        self.tools = self._get_tools_for_groups(self.default_groups)
    
    def _auto_group_tools(self, tools: Sequence[BaseTool]) -> dict[str, list[BaseTool]]:
        """Automatically group tools by name prefix.
        
        Args:
            tools: Flat list of tools to group
            
        Returns:
            Dict mapping group names to tool lists
        """
        groups: dict[str, list[BaseTool]] = {
            'filesystem': [],
            'web': [],
            'code': [],
            'shell': [],
            'other': [],
        }
        
        # Keywords for each group
        group_keywords = {
            'filesystem': ['file', 'read', 'write', 'edit', 'ls', 'glob', 'grep', 'path'],
            'web': ['web', 'fetch', 'url', 'http', 'search', 'browser'],
            'code': ['lint', 'test', 'format', 'check', 'run', 'build'],
            'shell': ['shell', 'execute', 'bash', 'command', 'terminal'],
        }
        
        for tool in tools:
            tool_name = tool.name.lower()
            assigned = False
            
            # Check each group
            for group, keywords in group_keywords.items():
                if any(keyword in tool_name for keyword in keywords):
                    groups[group].append(tool)
                    assigned = True
                    break
            
            # Assign to 'other' if no group matched
            if not assigned:
                groups['other'].append(tool)
        
        return groups
    
    def _get_tools_for_groups(self, groups: list[str]) -> list[BaseTool]:
        """Get all tools for the specified groups.
        
        Args:
            groups: List of group names
            
        Returns:
            List of tools from all specified groups
        """
        tools = []
        for group in groups:
            if group in self.tool_groups:
                tools.extend(self.tool_groups[group])
        return tools
    
    def _determine_required_groups(self, state: AgentState[ResponseT]) -> list[str]:
        """Determine which tool groups are required for the current task.
        
        Args:
            state: Current agent state
            
        Returns:
            List of required group names
        """
        messages = state.get('messages', [])
        
        # Start with default groups
        required_groups = list(self.default_groups)
        
        # Analyze task complexity
        analysis = self.complexity_analyzer.analyze(messages)
        
        # Add groups based on analysis
        if analysis['needs_filesystem'] and 'filesystem' not in required_groups:
            required_groups.append('filesystem')
        
        # Check for web-related keywords
        web_keywords = ['web', 'search', 'url', 'http', 'fetch', 'browser']
        last_message = messages[-1].content if messages else ''
        if isinstance(last_message, str):
            if any(keyword in last_message.lower() for keyword in web_keywords):
                if 'web' not in required_groups:
                    required_groups.append('web')
        
        # Check for code-related keywords
        code_keywords = ['test', 'lint', 'format', 'build', 'run', 'check']
        if isinstance(last_message, str):
            if any(keyword in last_message.lower() for keyword in code_keywords):
                if 'code' not in required_groups:
                    required_groups.append('code')
        
        # Check for shell-related keywords
        shell_keywords = ['shell', 'execute', 'bash', 'command', 'terminal', 'run']
        if isinstance(last_message, str):
            if any(keyword in last_message.lower() for keyword in shell_keywords):
                if 'shell' not in required_groups:
                    required_groups.append('shell')
        
        return required_groups
    
    def wrap_model_call(
        self,
        request: ModelRequest[ContextT],
        handler: Callable[[ModelRequest[ContextT]], ModelResponse[ResponseT]],
    ) -> ModelResponse[ResponseT] | ResponseT:
        """Dynamically load tools based on task requirements.
        
        Args:
            request: Model request to execute
            handler: Callback that executes the model request
            
        Returns:
            Model response with dynamically loaded tools
        """
        # Determine required tool groups
        required_groups = self._determine_required_groups(request.state)
        
        # Get tools for required groups
        dynamic_tools = self._get_tools_for_groups(required_groups)
        
        # Merge with existing tools from request
        existing_tools = request.tools or []
        all_tools = list(existing_tools) + dynamic_tools
        
        # Remove duplicates (by tool name)
        seen_names = set()
        unique_tools = []
        for tool in all_tools:
            if tool.name not in seen_names:
                seen_names.add(tool.name)
                unique_tools.append(tool)
        
        # Override request with dynamic tools
        return handler(request.override(tools=unique_tools))
    
    async def awrap_model_call(
        self,
        request: ModelRequest[ContextT],
        handler: Callable[[ModelRequest[ContextT]], Awaitable[ModelResponse[ResponseT]]],
    ) -> ModelResponse[ResponseT] | ResponseT:
        """Async version of wrap_model_call.
        
        Args:
            request: Model request to execute
            handler: Callback that executes the model request
            
        Returns:
            Model response with dynamically loaded tools
        """
        # Determine required tool groups
        required_groups = self._determine_required_groups(request.state)
        
        # Get tools for required groups
        dynamic_tools = self._get_tools_for_groups(required_groups)
        
        # Merge with existing tools from request
        existing_tools = request.tools or []
        all_tools = list(existing_tools) + dynamic_tools
        
        # Remove duplicates (by tool name)
        seen_names = set()
        unique_tools = []
        for tool in all_tools:
            if tool.name not in seen_names:
                seen_names.add(tool.name)
                unique_tools.append(tool)
        
        # Override request with dynamic tools
        return await handler(request.override(tools=unique_tools))


__all__ = ['LazyToolLoadingMiddleware']
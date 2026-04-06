"""Dynamic middleware selection based on task complexity."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from langchain.agents.middleware.types import AgentMiddleware

if TYPE_CHECKING:
    from langchain_core.messages import BaseMessage
    from langchain_core.tools import BaseTool


class DynamicMiddlewareSelector:
    """Dynamically selects middleware based on task complexity.
    
    This system analyzes the current task and only loads the middleware
    that is actually needed, reducing context overhead.
    
    Example:
        ```python
        from nova_deepagents.utils.dynamic_middleware import DynamicMiddlewareSelector
        from nova_deepagents.middleware.todo import TodoListMiddleware
        from nova_deepagents.middleware.planning import PlanModeMiddleware
        
        # Define middleware options
        middleware_options = {
            'todo': TodoListMiddleware(agent_name="Agent"),
            'planning': PlanModeMiddleware(enabled_by_default=False),
            'filesystem': FilesystemMiddleware(backend=backend),
        }
        
        # Create selector
        selector = DynamicMiddlewareSelector(
            middleware_options=middleware_options,
            default_middleware=['filesystem'],  # Always load
        )
        
        # Get middleware for current task
        messages = [HumanMessage("Implement a complex feature")]
        selected = selector.select_middleware(messages)
        ```
    """
    
    def __init__(
        self,
        middleware_options: dict[str, AgentMiddleware],
        default_middleware: list[str] | None = None,
        complexity_analyzer: Any | None = None,
    ) -> None:
        """Initialize the dynamic middleware selector.
        
        Args:
            middleware_options: Dict mapping middleware names to instances
            default_middleware: Middleware to always load (default: ['filesystem'])
            complexity_analyzer: Optional TaskComplexityAnalyzer instance
        """
        self.middleware_options = middleware_options
        self.default_middleware = default_middleware or ['filesystem']
        
        # Import complexity analyzer if not provided
        if complexity_analyzer is None:
            from nova_deepagents.utils.complexity import TaskComplexityAnalyzer
            self.complexity_analyzer = TaskComplexityAnalyzer()
        else:
            self.complexity_analyzer = complexity_analyzer
    
    def select_middleware(
        self,
        messages: list[BaseMessage],
        estimated_steps: int | None = None,
    ) -> list[AgentMiddleware]:
        """Select middleware based on task complexity.
        
        Args:
            messages: Conversation messages to analyze
            estimated_steps: Optional estimated number of steps
            
        Returns:
            List of middleware instances to use
        """
        # Analyze task complexity
        analysis = self.complexity_analyzer.analyze(messages, estimated_steps)
        
        # Start with default middleware
        selected = []
        for name in self.default_middleware:
            if name in self.middleware_options:
                selected.append(self.middleware_options[name])
        
        # Add middleware based on analysis
        if analysis['needs_todo'] and 'todo' in self.middleware_options:
            selected.append(self.middleware_options['todo'])
        
        if analysis['needs_planning'] and 'planning' in self.middleware_options:
            selected.append(self.middleware_options['planning'])
        
        if analysis['needs_filesystem'] and 'filesystem' in self.middleware_options:
            if self.middleware_options['filesystem'] not in selected:
                selected.append(self.middleware_options['filesystem'])
        
        if analysis['needs_subagents'] and 'subagents' in self.middleware_options:
            selected.append(self.middleware_options['subagents'])
        
        return selected
    
    def get_required_capabilities(self, messages: list[BaseMessage]) -> list[str]:
        """Get list of required capabilities for the task.
        
        Args:
            messages: Conversation messages to analyze
            
        Returns:
            List of capability names
        """
        analysis = self.complexity_analyzer.analyze(messages)
        capabilities = []
        
        if analysis['needs_filesystem']:
            capabilities.append('filesystem')
        
        if analysis['needs_subagents']:
            capabilities.append('subagents')
        
        if analysis['needs_planning']:
            capabilities.append('planning')
        
        if analysis['needs_todo']:
            capabilities.append('todo')
        
        return capabilities
    
    def estimate_context_savings(
        self,
        messages: list[BaseMessage],
    ) -> dict[str, int]:
        """Estimate context savings from dynamic selection.
        
        Args:
            messages: Conversation messages to analyze
            
        Returns:
            Dictionary with estimated token savings
        """
        # Analyze task
        analysis = self.complexity_analyzer.analyze(messages)
        
        # Estimate token costs for each middleware
        # These are rough estimates based on typical usage
        middleware_costs = {
            'todo': 2100,  # System prompt + tool description
            'planning': 1600,  # System prompt + tool description
            'filesystem': 500,  # Tool descriptions only
            'subagents': 2700,  # Task tool description
        }
        
        # Calculate savings
        total_possible = sum(middleware_costs.values())
        selected_cost = 0
        
        # Always include default middleware
        for name in self.default_middleware:
            if name in middleware_costs:
                selected_cost += middleware_costs[name]
        
        # Add selected middleware
        if analysis['needs_todo']:
            selected_cost += middleware_costs.get('todo', 0)
        
        if analysis['needs_planning']:
            selected_cost += middleware_costs.get('planning', 0)
        
        if analysis['needs_filesystem'] and 'filesystem' not in self.default_middleware:
            selected_cost += middleware_costs.get('filesystem', 0)
        
        if analysis['needs_subagents']:
            selected_cost += middleware_costs.get('subagents', 0)
        
        savings = total_possible - selected_cost
        percentage = (savings / total_possible * 100) if total_possible > 0 else 0
        
        return {
            'total_possible_tokens': total_possible,
            'selected_tokens': selected_cost,
            'savings_tokens': savings,
            'savings_percentage': percentage,
            'middleware_selected': {
                'todo': analysis['needs_todo'],
                'planning': analysis['needs_planning'],
                'filesystem': analysis['needs_filesystem'],
                'subagents': analysis['needs_subagents'],
            },
        }


class MiddlewareProfile:
    """Predefined middleware profiles for common use cases.
    
    This class provides pre-configured middleware stacks for different
    types of tasks, making it easy to select the right middleware
    without manual configuration.
    
    Example:
        ```python
        from nova_deepagents.utils.dynamic_middleware import MiddlewareProfile
        
        # Get middleware for a research task
        middleware = MiddlewareProfile.get_profile('research')
        
        # Get middleware for a simple query
        middleware = MiddlewareProfile.get_profile('simple')
        
        # Get middleware for a complex implementation task
        middleware = MiddlewareProfile.get_profile('implementation')
        ```
    """
    
    # Predefined profiles
    PROFILES = {
        'simple': {
            'description': 'Simple queries and single-step tasks',
            'middleware': ['filesystem'],
            'features': {
                'needs_todo': False,
                'needs_planning': False,
                'needs_filesystem': True,
                'needs_subagents': False,
            },
        },
        'research': {
            'description': 'Research and exploration tasks',
            'middleware': ['filesystem', 'subagents'],
            'features': {
                'needs_todo': True,
                'needs_planning': False,
                'needs_filesystem': True,
                'needs_subagents': True,
            },
        },
        'implementation': {
            'description': 'Complex implementation tasks',
            'middleware': ['filesystem', 'todo', 'planning', 'subagents'],
            'features': {
                'needs_todo': True,
                'needs_planning': True,
                'needs_filesystem': True,
                'needs_subagents': True,
            },
        },
        'analysis': {
            'description': 'Code analysis and review tasks',
            'middleware': ['filesystem', 'todo'],
            'features': {
                'needs_todo': True,
                'needs_planning': False,
                'needs_filesystem': True,
                'needs_subagents': False,
            },
        },
        'testing': {
            'description': 'Testing and verification tasks',
            'middleware': ['filesystem', 'todo'],
            'features': {
                'needs_todo': True,
                'needs_planning': False,
                'needs_filesystem': True,
                'needs_subagents': False,
            },
        },
        'documentation': {
            'description': 'Documentation generation tasks',
            'middleware': ['filesystem', 'todo'],
            'features': {
                'needs_todo': True,
                'needs_planning': False,
                'needs_filesystem': True,
                'needs_subagents': False,
            },
        },
    }
    
    @classmethod
    def get_profile(cls, profile_name: str) -> dict[str, Any]:
        """Get a middleware profile by name.
        
        Args:
            profile_name: Name of the profile ('simple', 'research', etc.)
            
        Returns:
            Profile configuration dictionary
            
        Raises:
            ValueError: If profile name is not found
        """
        if profile_name not in cls.PROFILES:
            available = ', '.join(cls.PROFILES.keys())
            raise ValueError(
                f"Unknown profile '{profile_name}'. Available profiles: {available}"
            )
        
        return cls.PROFILES[profile_name]
    
    @classmethod
    def list_profiles(cls) -> list[str]:
        """List all available profiles.
        
        Returns:
            List of profile names
        """
        return list(cls.PROFILES.keys())
    
    @classmethod
    def get_middleware_for_profile(
        cls,
        profile_name: str,
        middleware_options: dict[str, AgentMiddleware],
    ) -> list[AgentMiddleware]:
        """Get middleware instances for a profile.
        
        Args:
            profile_name: Name of the profile
            middleware_options: Dict mapping middleware names to instances
            
        Returns:
            List of middleware instances
        """
        profile = cls.get_profile(profile_name)
        middleware_names = profile['middleware']
        
        selected = []
        for name in middleware_names:
            if name in middleware_options:
                selected.append(middleware_options[name])
        
        return selected


__all__ = ['DynamicMiddlewareSelector', 'MiddlewareProfile']
"""Task complexity detection for conditional middleware loading."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from langchain_core.messages import BaseMessage


class TaskComplexityAnalyzer:
    """Analyzes task complexity to determine middleware requirements.
    
    This helps optimize context usage by only loading expensive middleware
    when the task actually requires it.
    """
    
    # Patterns that indicate complex tasks
    COMPLEXITY_INDICATORS = [
        # Multi-step operations
        r'\b(?:first|second|third|then|next|after that|finally)\b',
        r'\b(?:step\s+\d+|phase\s+\d+|stage\s+\d+)\b',
        
        # Planning keywords
        r'\b(?:plan|planning|strategy|roadmap|approach)\b',
        r'\b(?:breakdown|break\s+down|decompose)\b',
        
        # Multiple files/operations
        r'\b(?:multiple|several|many|various)\s+(?:files|components|modules)\b',
        r'\b(?:refactor|restructure|reorganize)\b',
        
        # Research/analysis tasks
        r'\b(?:research|analyze|investigate|explore)\b',
        r'\b(?:compare|contrast|evaluate|assess)\b',
        
        # Implementation tasks
        r'\b(?:implement|build|create|develop|design)\b',
        r'\b(?:integrate|connect|combine|merge)\b',
        
        # Complex operations
        r'\b(?:optimize|improve|enhance|extend)\b',
        r'\b(?:debug|troubleshoot|fix|resolve)\b',
        
        # Coordination tasks
        r'\b(?:coordinate|orchestrate|manage|organize)\b',
        r'\b(?:collaborate|work\s+together|sync)\b',
    ]
    
    # Patterns that indicate simple tasks
    SIMPLICITY_INDICATORS = [
        # Single operations
        r'\b(?:just|only|simply|quickly)\b',
        r'\b(?:read|show|display|list|get)\b',
        r'\b(?:what|where|when|who|how)\b',
        
        # Simple queries
        r'\b(?:is\s+there|does\s+it|can\s+you|will\s+it)\b',
        r'\b(?:check|verify|validate|confirm)\b',
        
        # Single file operations
        r'\b(?:this\s+file|that\s+file|the\s+file)\b',
        r'\b(?:single|one|a\s+single)\b',
    ]
    
    # Minimum estimated steps to require todo tracking
    MIN_STEPS_FOR_TODO = 3
    
    @classmethod
    def analyze(
        cls,
        messages: list[BaseMessage],
        estimated_steps: int | None = None,
    ) -> dict[str, bool]:
        """Analyze task complexity to determine middleware requirements.
        
        Args:
            messages: Conversation messages to analyze
            estimated_steps: Optional estimated number of steps (if known)
            
        Returns:
            Dictionary of middleware requirements:
            - needs_todo: Whether TodoListMiddleware is needed
            - needs_planning: Whether PlanModeMiddleware is needed
            - needs_filesystem: Whether FilesystemMiddleware is needed
            - needs_subagents: Whether SubAgentMiddleware is needed
        """
        # Get the last user message (the current task)
        user_message = None
        for msg in reversed(messages):
            if hasattr(msg, 'type') and msg.type == 'human':
                user_message = msg.content
                break
            elif hasattr(msg, 'content') and isinstance(msg.content, str):
                user_message = msg.content
                break
        
        if not user_message:
            # Default to simple task if no user message
            return {
                'needs_todo': False,
                'needs_planning': False,
                'needs_filesystem': True,  # Default to filesystem access
                'needs_subagents': False,
            }
        
        # Count complexity indicators
        complexity_score = 0
        for pattern in cls.COMPLEXITY_INDICATORS:
            if re.search(pattern, user_message, re.IGNORECASE):
                complexity_score += 1
        
        # Count simplicity indicators
        simplicity_score = 0
        for pattern in cls.SIMPLICITY_INDICATORS:
            if re.search(pattern, user_message, re.IGNORECASE):
                simplicity_score += 1
        
        # Calculate net complexity
        net_complexity = complexity_score - simplicity_score
        
        # Determine middleware requirements
        needs_todo = (
            # Explicit step count
            (estimated_steps is not None and estimated_steps >= cls.MIN_STEPS_FOR_TODO) or
            # High complexity score
            net_complexity >= 1 or  # Lowered threshold
            # Multiple complexity indicators
            complexity_score >= 2 or  # Lowered threshold
            # Implementation keywords
            any(re.search(pattern, user_message, re.IGNORECASE) for pattern in [ # type: ignore
                r'\b(?:implement|build|create|develop|design)\b',
                r'\b(?:first|second|third|then|next|finally)\b',
            ])
        )
        
        needs_planning = (
            # Very high complexity
            net_complexity >= 3 or  # Lowered threshold
            # Multiple planning keywords
            complexity_score >= 4 or  # Lowered threshold
            # Planning keywords
            any(re.search(pattern, user_message, re.IGNORECASE) for pattern in [ # type: ignore
                r'\b(?:plan|planning|strategy|roadmap)\b',
                r'\b(?:architecture|design|approach)\b',
            ])
        )
        
        # Check for filesystem operations
        filesystem_keywords = [
            r'\b(?:file|directory|folder|path)\b',
            r'\b(?:read|write|edit|create|delete|move|copy)\b',
            r'\b(?:code|script|module|package)\b',
        ]
        needs_filesystem = any(
            re.search(pattern, user_message, re.IGNORECASE)
            for pattern in filesystem_keywords
        )
        
        # Check for subagent needs
        subagent_keywords = [
            r'\b(?:research|explore|investigate)\b',
            r'\b(?:parallel|concurrent|simultaneous)\b',
            r'\b(?:delegate|assign|distribute)\b',
        ]
        needs_subagents = (
            any(re.search(pattern, user_message, re.IGNORECASE) for pattern in subagent_keywords) or
            needs_planning  # Complex tasks often benefit from subagents
        )
        
        return {
            'needs_todo': needs_todo,
            'needs_planning': needs_planning,
            'needs_filesystem': needs_filesystem,
            'needs_subagents': needs_subagents,
        }
    
    @classmethod
    def should_use_todo_list(cls, messages: list[BaseMessage], estimated_steps: int | None = None) -> bool:
        """Determine if TodoListMiddleware should be used.
        
        Args:
            messages: Conversation messages to analyze
            estimated_steps: Optional estimated number of steps
            
        Returns:
            True if TodoListMiddleware should be used, False otherwise
        """
        analysis = cls.analyze(messages, estimated_steps)
        return analysis['needs_todo']
    
    @classmethod
    def should_enable_planning(cls, messages: list[BaseMessage]) -> bool:
        """Determine if PlanModeMiddleware should be enabled.
        
        Args:
            messages: Conversation messages to analyze
            
        Returns:
            True if PlanModeMiddleware should be enabled, False otherwise
        """
        analysis = cls.analyze(messages)
        return analysis['needs_planning']
    
    @classmethod
    def should_load_filesystem(cls, messages: list[BaseMessage]) -> bool:
        """Determine if FilesystemMiddleware should be loaded.
        
        Args:
            messages: Conversation messages to analyze
            
        Returns:
            True if FilesystemMiddleware should be loaded, False otherwise
        """
        analysis = cls.analyze(messages)
        return analysis['needs_filesystem']
    
    @classmethod
    def should_use_subagents(cls, messages: list[BaseMessage]) -> bool:
        """Determine if SubAgentMiddleware should be used.
        
        Args:
            messages: Conversation messages to analyze
            
        Returns:
            True if SubAgentMiddleware should be used, False otherwise
        """
        analysis = cls.analyze(messages)
        return analysis['needs_subagents']


__all__ = ['TaskComplexityAnalyzer']
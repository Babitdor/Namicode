# Default subagents for NOVA CLI

from .async_subagents import (
    DOCUMENTATION_UPDATE_AGENT,
    DOCUMENTATION_UPDATE_AGENT_DESCRIPTION,
    retrieve_async_subagents,
)
from .subagents import retrieve_core_subagents
from .prompt import (
    BUG_FIX_AGENT,
    BROWSER_AUTOMATION_AGENT,
    CODE_DOC_AGENT,
    CODE_SIMPLIFIER,
    REFACTORING_SPECIALIST_AGENT,
    REVIEWER_AGENT,
    SECURITY_AUDITOR_AGENT,
    TEST_WRITER_AGENT,
    TESTING_AGENT,
)

__all__ = [
    # Async subagents
    "DOCUMENTATION_UPDATE_AGENT",
    "DOCUMENTATION_UPDATE_AGENT_DESCRIPTION",
    "retrieve_async_subagents",
    # Sync subagents
    "retrieve_core_subagents",
    # Subagent prompts
    "BUG_FIX_AGENT",
    "BROWSER_AUTOMATION_AGENT",
    "CODE_DOC_AGENT",
    "CODE_SIMPLIFIER",
    "REFACTORING_SPECIALIST_AGENT",
    "REVIEWER_AGENT",
    "SECURITY_AUDITOR_AGENT",
    "TEST_WRITER_AGENT",
    "TESTING_AGENT",
]

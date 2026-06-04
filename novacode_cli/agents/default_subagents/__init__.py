# Default subagents for NOVA CLI

from .async_subagents import (
    DOCUMENTATION_UPDATE_AGENT,
    DOCUMENTATION_UPDATE_AGENT_DESCRIPTION,
    retrieve_async_subagents,
)
from .subagents import retrieve_core_subagents
from .prompt import (
    BACKEND_AGENT,
    BROWSER_AUTOMATION_AGENT,
    BUG_FIX_AGENT,
    CODE_DOC_AGENT,
    CODE_EXPLORER,
    CODE_SIMPLIFIER,
    DOCKER_AGENT,
    FINANCIAL_ANALYST,
    FRONTEND_AGENT,
    LITERATURE_REVIEWER,
    MARKET_ANALYST,
    REFACTORING_SPECIALIST_AGENT,
    REVIEWER_AGENT,
    SECURITY_AUDITOR_AGENT,
    TECHNICAL_RESEARCHER,
    TESTING_AGENT,
    TEST_WRITER_AGENT,
    WEB_RESEARCHER,
)

__all__ = [
    # Async subagents
    "DOCUMENTATION_UPDATE_AGENT",
    "DOCUMENTATION_UPDATE_AGENT_DESCRIPTION",
    "retrieve_async_subagents",
    # Sync subagents
    "retrieve_core_subagents",
    # Subagent prompts
    "BACKEND_AGENT",
    "BROWSER_AUTOMATION_AGENT",
    "BUG_FIX_AGENT",
    "CODE_DOC_AGENT",
    "CODE_EXPLORER",
    "CODE_SIMPLIFIER",
    "DOCKER_AGENT",
    "FINANCIAL_ANALYST",
    "FRONTEND_AGENT",
    "LITERATURE_REVIEWER",
    "MARKET_ANALYST",
    "REFACTORING_SPECIALIST_AGENT",
    "REVIEWER_AGENT",
    "SECURITY_AUDITOR_AGENT",
    "TECHNICAL_RESEARCHER",
    "TESTING_AGENT",
    "TEST_WRITER_AGENT",
    "WEB_RESEARCHER",
]

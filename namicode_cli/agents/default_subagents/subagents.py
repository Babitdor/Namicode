from nami_deepagents.middleware.subagents import SubAgent
from langchain.tools import BaseTool
from .prompt import CODE_SIMPLIFIER, CODE_EXPLORER, CODE_DOC_AAGENT


def retrieve_core_subagents(
    tools: list[BaseTool],
) -> list[SubAgent]:  # type: ignore

    subagents: list[SubAgent] = []
    code_explorer: SubAgent = {
        "name": "code-explorer-agent",
        "description": "Used to research more in depth questions",
        "system_prompt": CODE_EXPLORER,
        "tools": tools,
    }
    subagents.append(code_explorer)

    code_doc_agent: SubAgent = {
        "name": "code-doc-Agent",
        "description": "Generates human-readable documentation (README, API docs, docstrings) only from structured inputs such as IRs or retrieved code snippets. Does not explore the codebase independently.",
        "system_prompt": CODE_DOC_AAGENT,
        "tools": tools,
    }
    subagents.append(code_doc_agent)

    code_simplifier_agent: SubAgent = {
        "name": "code-simplifier-agent",
        "description": "Simplifies and refines code for clarity, consistency, and maintainability while preserving all functionality. Focuses on recently modified code unless instructed otherwise.",
        "system_prompt": CODE_SIMPLIFIER,
        "tools": tools,
    }

    subagents.append(code_simplifier_agent)

    return subagents

"""Research subagents must write findings to files, not just reply inline."""

import pytest

from novacode_cli.agents.default_subagents.prompt import (
    FACT_CHECKER,
    FINANCIAL_ANALYST,
    LITERATURE_REVIEWER,
    MARKET_ANALYST,
    RESEARCH_SYNTHESIZER,
    TECHNICAL_RESEARCHER,
    WEB_RESEARCHER,
)
from novacode_cli.prompts import render_template

_RESEARCH_SUBAGENTS = {
    "web-researcher": WEB_RESEARCHER,
    "literature-reviewer": LITERATURE_REVIEWER,
    "market-analyst": MARKET_ANALYST,
    "financial-analyst": FINANCIAL_ANALYST,
    "technical-researcher": TECHNICAL_RESEARCHER,
    "fact-checker": FACT_CHECKER,
    "research-synthesizer": RESEARCH_SYNTHESIZER,
}


@pytest.mark.parametrize("name,cfg", list(_RESEARCH_SUBAGENTS.items()))
def test_subagent_has_write_file_tool(name, cfg):
    assert "write_file" in cfg["tools"], f"{name} lacks write_file"


@pytest.mark.parametrize("name,cfg", list(_RESEARCH_SUBAGENTS.items()))
def test_subagent_prompt_mandates_file_write(name, cfg):
    prompt = cfg["prompt"].lower()
    assert "critical" in prompt, f"{name} prompt missing the write mandate"
    assert "write_file" in prompt, f"{name} prompt doesn't mention write_file"
    assert "failed task" in prompt, f"{name} prompt doesn't mark inline-only as failure"


def test_orchestrator_requires_files_and_recovers_missing():
    r = render_template(
        "research_swarm.jinja",
        mode="general",
        research_query="q",
        base_dir=".nova/research",
        agents=["web-researcher"],
        fast_mode=False,
        mode_description="x",
        agent_count=1,
        conversation_context="",
    )
    # Mandatory write instruction in task descriptions.
    assert "mandatory" in r.lower() and "write_file" in r
    # Phase 2.5 recovers when a subagent replied inline instead of writing.
    assert "missing or empty" in r

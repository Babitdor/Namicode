# Trello Board — Auto-Process Loaded Tasks

## Problem

The `/trello` watch loop only picked up tasks that were explicitly moved to `"processing"` status by clicking the **"Start"** button in the web UI. Newly added tasks sat in `"loaded"` status forever and were never automatically processed.

## Changes

### 1. `novacode_cli/commands/trello_server.py` — New method `pop_next_loaded_task()`

Added a method to `TrelloServer` that finds the first task in `"loaded"` status, marks it as `"processing"`, and returns it:

```python
def pop_next_loaded_task(self) -> dict | None:
    """Pop the next 'loaded' task and mark it as 'processing'.

    Returns:
        The task dict if one was available, or None.
    """
    with self._lock:
        for task in self._tasks:
            if task.get("status") == "loaded":
                task["status"] = "processing"
                return task.copy()
    return None
```

### 2. `novacode_cli/tui/app.py` — Updated `_trello_watch_loop()`

The watch loop now falls back to `pop_next_loaded_task()` when no explicit processing notification arrives:

```python
async def _trello_watch_loop(self, server: Any) -> None:
    """Background loop: poll for processing tasks and execute them."""
    try:
        while server.is_running:
            # First check for tasks explicitly moved to "processing" (web UI click)
            task = await server.get_next_processing_task()
            if not task:
                # Auto-pick the first "loaded" task
                task = server.pop_next_loaded_task()
            if task:
                ...
```

## Behavior

| Action | Before | After |
|--------|--------|-------|
| Add task via web UI | Sits in "loaded" forever | Auto-picked and processed |
| Click "Start" in web UI | Processed | Processed (still works) |
| Multiple tasks added | None processed | Processed one at a time in FIFO order |

---

## Subagent Skill-Aware Prompts + README Update

### Problem

Each default subagent prompt described its role and tools, but had no awareness of the skills being injected by `SkillsMiddleware`. The skills existed at the middleware level (`subagents.py`) but the prompts themselves never referenced them — so subagents didn't know they *had* specialized skill files to consult.

### Changes

#### 1. All 20 Subagent `.jinja` Templates — Added `## Available Skills` Section

Every subagent prompt template now ends with an explicit skills section that names the available skill files, their virtual paths, and when to read them. Key mappings:

| Subagent | Skills Added |
|----------|-------------|
| `code_doc_agent.jinja` | `code-documentation/` |
| `code_simplifier.jinja` | `code-review-expert/` |
| `code_explorer.jinja` | `codebase-explorer/`, `graphify/` |
| `reviewer_agent.jinja` | `code-review-expert/` |
| `security_auditor_agent.jinja` | `web-research/` |
| `refactoring_specialist_agent.jinja` | `improve-codebase-architecture/` |
| `bug_fix_agent.jinja` | `systematic-debugging/` |
| `test_writer_agent.jinja` | `test-driven-development/` |
| `testing_agent.jinja` | `testing-skills/`, `webapp-testing/` |
| `browser_automation_agent.jinja` | `agent-browser/`, `browser-use/` |
| `frontend_agent.jinja` | `frontend-design/`, `expert-css-skills/` |
| `backend_agent.jinja` | `backend-dev-guidelines/`, `async-python-patterns/` |
| `docker_agent.jinja` | `docker-deploy/` |
| `web_researcher.jinja` | `web-research/`, `arxiv-search/` |
| `fact_checker.jinja` | `web-research/` |
| `literature_reviewer.jinja` | `arxiv-search/`, `web-research/` |
| `market_analyst.jinja` | `web-research/` |
| `financial_analyst.jinja` | `web-research/`, `xlsx/` |
| `technical_researcher.jinja` | `web-research/`, `codebase-explorer/` |

`research_synthesizer.jinja` was intentionally skipped — it works from inline content only and never reads skill files.

#### 2. `README.md` — Subagent Documentation Overhaul

- **Features**: "Default Subagents" updated from 3 agents to "20+ built-in specialized agents with skill-aware prompts"
- **Built-in Tools table**: Added `remember`/`recall`/`list_memories`/`forget` (were missing)
- **Default Subagents section**: Replaced 3-row placeholder with a complete 20-subagent table organized by category (Code Quality, Test, Browser Automation, Domain Engineering, Research Swarm) with auto-loaded skills column
- **Architecture → Module Structure**: Updated `agents/default_subagents/` entry to describe 20+ subagents

### Files Changed Summary

| File | Changes |
|------|---------|
| `novacode_cli/prompts/subagents/code_doc_agent.jinja` | Added `## Available Skills` section |
| `novacode_cli/prompts/subagents/code_simplifier.jinja` | Added `## Available Skills` section |
| `novacode_cli/prompts/subagents/code_explorer.jinja` | Added `## Available Skills` section |
| `novacode_cli/prompts/subagents/reviewer_agent.jinja` | Added `## Available Skills` section |
| `novacode_cli/prompts/subagents/security_auditor_agent.jinja` | Added `## Available Skills` section |
| `novacode_cli/prompts/subagents/refactoring_specialist_agent.jinja` | Added `## Available Skills` section |
| `novacode_cli/prompts/subagents/bug_fix_agent.jinja` | Added `## Available Skills` section |
| `novacode_cli/prompts/subagents/test_writer_agent.jinja` | Added `## Available Skills` section |
| `novacode_cli/prompts/subagents/testing_agent.jinja` | Added `## Available Skills` section |
| `novacode_cli/prompts/subagents/browser_automation_agent.jinja` | Added `## Available Skills` section |
| `novacode_cli/prompts/subagents/frontend_agent.jinja` | Added `## Available Skills` section |
| `novacode_cli/prompts/subagents/backend_agent.jinja` | Added `## Available Skills` section |
| `novacode_cli/prompts/subagents/docker_agent.jinja` | Added `## Available Skills` section |
| `novacode_cli/prompts/subagents/web_researcher.jinja` | Added `## Available Skills` section |
| `novacode_cli/prompts/subagents/fact_checker.jinja` | Added `## Available Skills` section |
| `novacode_cli/prompts/subagents/literature_reviewer.jinja` | Added `## Available Skills` section |
| `novacode_cli/prompts/subagents/market_analyst.jinja` | Added `## Available Skills` section |
| `novacode_cli/prompts/subagents/financial_analyst.jinja` | Added `## Available Skills` section |
| `novacode_cli/prompts/subagents/technical_researcher.jinja` | Added `## Available Skills` section |
| `README.md` | Features, tools table, subagents table, architecture section updated |

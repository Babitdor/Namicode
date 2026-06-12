# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

NOVA is a terminal AI coding agent built on LangGraph + the `deepagents` framework. The README is an exhaustive feature catalog; this file covers the cross-file architecture and the conventions that aren't obvious from any single file.

## Commands

Use `uv` (the project is uv-managed; `make` targets wrap it).

```bash
uv run nova                       # run the CLI (or: make run)
uv run pytest tests/              # run the whole suite (make test_all)
uv run pytest tests/test_hermes/test_curator.py -q        # one file
uv run pytest tests/test_hermes/ -k "curation"            # one test by name
uv run ruff format . && uv run ruff check .               # format + lint (make format / make lint)
uv run mypy novacode_cli/         # type check (strict mode)
```

- `pytest` is configured with `asyncio_mode = "auto"` (no `@pytest.mark.asyncio` needed) and a **10s per-test timeout** (`timeout_method = "thread"`). Async tests are plain `async def`.
- The **TUI suite (`tests/test_tui_app.py`) is heavy** — it boots a real Textual app via `run_test()` and can take ~30s. Give it a generous wall-clock timeout; a tight outer timeout will look like a hang.
- The `make test` default (`TEST_FILE ?= tests/unit_tests`) points at paths that don't exist here — prefer `uv run pytest tests/...` directly.

## Big-picture architecture

### Entry → agent loop → two front-ends over one event stream
`main.py:cli_main()` parses args, builds `SessionState`, assembles the tool list, and calls `agents/core_agent.py:create_agent_with_config()` to build the LangGraph agent. The agent is driven by **one** canonical async generator, `core/agent_loop.py:iterate_agent_events()`, which yields `ui_events.py` dataclasses. Two renderers consume the same events:
- **Textual TUI** (`tui/app.py:NovaApp`) — the default front-end.
- **Rich REPL** (`main.py` loop + `ui/execution.py`) — the `--legacy-ui` front-end (prompt_toolkit, completers in `input.py`).

**Behavior/bug fixes belong in `iterate_agent_events` (or the agent/middleware), not in a renderer**, so both UIs benefit. The two UIs are *not* otherwise interchangeable — e.g. `@`-mention autocomplete is implemented separately (TUI: `tui/app.py:_palette_candidates`; REPL: `input.py` completers), and they can drift.

### The middleware stack (and a critical gotcha)
`create_agent_with_config` builds an **ordered** middleware list — that list literal is the source of truth, not the README (which is out of date). It currently leads with `ModelRetryMiddleware`, then `NovaLearningMiddleware` (placed early so it records tool usage for everything downstream), followed by Security, Bootstrap, GraphContext, Steering, FileTracker, Shell, etc. When MCP servers are configured, `MCPMiddleware` is `insert(3, …)`'d into the stack. Order is deliberate and commented inline — read those comments before reordering.

**Every middleware that overrides `wrap_model_call` (sync) MUST also implement `awrap_model_call` (async)** (and the same for `wrap_tool_call`/`awrap_tool_call`). The agent runs via `ainvoke`/`astream`, so a sync-only middleware raises `NotImplementedError` at runtime — this is an easy mistake when adding a middleware (it was a real bug here).

### Nothing in the agent loop may `console.print`
Middleware, tools, and the Hermes review all run *inside* the live agent loop. Printing to stdout corrupts the Textual TUI. Surface user-facing notices by appending to `novacode_cli/events.py:nova_event_log` (drained by `iterate_agent_events` into a rendered event); send diagnostics to a logger. This is load-bearing, not stylistic.

### Hermes — the autonomous learning subsystem (`novacode_cli/hermes/`)
`NovaLearningMiddleware` is a **thin orchestrator** delegating to three injected modules:
- `tracker.py:ToolUsageTracker` — counter, tool history, per-tool `tool_stats`, and **`skill_usage`** (real SKILL.md invocations + outcomes; this is what drives refinement).
- `review.py:ReviewRunner` — decides *when* to review (signal-based: failure bursts / substantive windows / hard cap, in `should_review`), then runs an **out-of-band `model.ainvoke`** (a single LLM call on a fire-and-forget `asyncio` task — *not* a sub-agent) and persists learnings.
- `skill_manager.py:SkillManager` — create-from-review, failure-grounded refinement, and the background curator.

Pure logic lives in `skill_discovery.py` (parse/write skill specs, `check_skill_effectiveness`, `refine_skill`) and `curator.py` (archive-unused + overlap flagging). All learning state persists in the durable store under the `("nova", …)` namespace (see below). Everything degrades gracefully — a learning failure must never break the agent turn.

### Skills system (two creation paths)
Skills are `SKILL.md` files (YAML frontmatter + steps) auto-loaded by deepagents' `SkillsMiddleware` via **progressive disclosure** — the agent invokes a skill by *reading its `SKILL.md` with `read_file`* (there is no "load skill" tool; the tracker detects skill use from these reads). Skills are created two ways:
- **Agent-driven**: the `skill_manage` tool (`tools/skill_tools.py`, actions `create/patch/edit/delete/history/rollback`), nudged by the `SKILLS_GUIDANCE` block in `prompts/core_agent_system.jinja`.
- **Review safety net**: the out-of-band review may emit a `<skill>` block.

Every mutation snapshots the prior version (`skills/versioning.py` → `<skill>/.history/`); `delete` is a recoverable soft-archive (`~/.nova/skills-archive/`). Bundled (`~/.claude/skills`) skills are read-only to these tools.

### Backends & sandboxing
File ops route through a `CompositeBackend` (deepagents) keyed by virtual path prefix (`/skills/`, `/claude-skills/`, `/project-skills-N/`, default → workspace). Local mode uses `FilesystemBackend(virtual_mode=True)` — the agent must use **virtual `/`-rooted paths**, never Windows absolute paths. Sandbox mode (`--sandbox modal|docker|…`) swaps in `integrations/workdir_backend.py` so virtual project paths map to the container workdir.

### Prompts
All system/agent prompts are **Jinja2 templates** in `prompts/*.jinja`, rendered via `prompts/__init__.py:render_template(name, **kwargs)`. Edit the template, not an inlined string — e.g. the periodic-review prompt is `nova_review.jinja`, the core system prompt is `core_agent_system.jinja`.

## State & storage locations
- Durable LangGraph store: **`~/.nova/store.db`** (SQLite via `memory/store.py`, stdlib-sqlite fallback). Hermes namespaces: `tool_counter`, `tool_history`, `tool_stats`, `skill_usage`, `reviews`, `created_skills`, `curation_log`, `meta`.
- Agent memory tiers: `~/.nova/agents/<id>/` → `USER.md` (user model) + `MEMORY.md` (cross-session facts), auto-maintained by the review and compacted at ~12K chars.
- Global skills: `~/.nova/skills/`; project skills: `.nova/skills/` or `.claude/skills/`.
- Project graph: `.nova/project-graph.json` (built by `/init`), surfaced as a legend by `GraphContextMiddleware` and queried on demand via the `query_project_graph` tool.

## Conventions
- **Subagents run unattended.** `_harden_subagent_specs` in `core_agent.py` clears `interrupt_on` and adds retry middleware per subagent — a HITL interrupt raised inside a subagent bubbles out of the `task` tool as an unresolvable `GraphInterrupt` and crashes the turn. The main agent is the sole HITL boundary.
- **Don't add a SummarizationMiddleware** — `create_deep_agent` already provides one; a duplicate fails agent construction.
- New tools: define with `@tool` under `tools/`, export through `tools/__init__.py`, and register in the tool list in `main.py`.
- Ruff is configured `select = ["ALL"]` with line-length 100 and Google-style docstrings; match the surrounding ignore conventions rather than fighting the linter.

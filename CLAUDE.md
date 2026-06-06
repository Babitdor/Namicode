# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Nova is a terminal AI coding assistant (like Claude Code) built on the `deepagents` library + LangGraph. The package is `novacode_cli`; the CLI entry point is `nova`.

## Commands

This project uses **`uv`** (not pip directly). All commands run inside the uv-managed `.venv`.

- **Run the CLI:** `uv run nova` (or `make run`). TUI: `uv run nova --tui`; classic REPL: `--legacy-ui`; auto-approve tools: `--auto-approve`; resume latest: `--continue`; isolation: `--sandbox docker`.
- **Sync deps after editing `pyproject.toml`:** `uv sync` (or `make sync`). Force reinstall the local packages: `make reinstall`.
- **Run all tests:** `uv run pytest tests/` (or `make test_all`). Note: `make test` defaults to `tests/unit_tests` which does not exist — the tests are flat under `tests/` plus `tests/test_hermes/`; prefer `pytest tests/` or `make test_all`.
- **Run a single test:** `uv run pytest tests/test_hermes/test_memory_tiers.py::TestEnsureMemoryTiers::test_creates_user_md`
- **Lint / format:** `make lint` (= `uv run ruff format --check` + `uv run ruff check`); auto-fix: `make format`. Ruff is configured `select = ["ALL"]`, line length 100.
- **Type check:** Pyright (config in `pyrightconfig.json`).

### Test gotchas
- `pytest` is configured `asyncio_mode = "auto"` with a **10s default per-test timeout** (`timeout_method = "thread"` for Windows). Tests that legitimately take longer must raise it: the Textual TUI tests (`tests/test_tui_app.py`) drive a real app via `App.run_test()` and need `--timeout=180`.
- This is a **Windows-first** codebase: the global Rich `console` is forced to UTF-8, and git will warn about LF→CRLF. Avoid emoji in strings that may be printed to a non-UTF-8 stream / logged.

## Architecture

### Agent = deepagents graph + a middleware stack
The agent is built in `agents/core_agent.py:create_agent_with_config()` via `deepagents.create_deep_agent(...)`, which compiles a LangGraph graph wrapped by an ordered **middleware stack**. Understanding the stack is the key to this codebase:

- **Middleware order matters.** Tools contributed by middleware are collected via each middleware's `.tools` attribute **at graph-build time** (`[t for m in middleware for t in m.tools]`). Anything that adds tools (e.g. MCP) must populate `.tools` *before* `create_deep_agent` runs — hence MCP tools are **eagerly discovered** before build (see `mcp/middleware.py` + the discovery call in `core_agent.py`).
- **Async hooks are the real ones.** Middleware implements `awrap_tool_call` / `awrap_model_call` / `abefore_agent`; the sync `wrap_*` variants are pass-through stubs (the agent runs via `astream`). Valid hook names are limited (`before_agent`/`before_model`/`wrap_*` + async) — `on_session_start` is **not** a hook.
- A separate **plan-mode agent** (`agents/plan_agent/`) is built with `PlanModeMiddleware` (blocks writes/exec outside `.nova/plans/`); plans are surfaced via `exit_plan_mode(plan=...)` for approval.

### Event stream (don't print from deep code)
`core/agent_loop.py:iterate_agent_events()` consumes the LangGraph `astream` and yields plain dataclasses from `ui_events.py` (`ToolCall`, `ToolResult`, `AssistantMessage`, `StatusUpdate`, `ContextMessage`, …). **Two renderers consume the same stream**: the Rich console REPL (`ui/execution.py`) and the Textual TUI (`tui/app.py`). To surface something in the UI, emit an event — don't `console.print` from agent/tool/middleware code. (Module-level buffers like `hermes.middleware.nova_event_log` are drained into `ContextMessage`s in the loop.)

### Memory: two distinct halves
1. **Filesystem markdown memory** via a deepagents `CompositeBackend` whose routes are wired in `core_agent.py`. Virtual `/`-rooted paths map to real dirs: `/memories/agent.md`, `/user-memory/USER.md`, `/session-memory/MEMORY.md` (the last two under `~/.nova/<assistant_id>/`), `/project-memory/NOVA.md`, `/skills/`, `/.nova/plans/`. `memory/agent_memory.py:AgentMemoryMiddleware` auto-injects `agent.md` + project `NOVA.md`/`CLAUDE.md` into the system prompt each turn (USER.md/MEMORY.md are **not** auto-injected — read on demand).
2. **Durable structured KV store** (`memory/store.py`) passed to `create_deep_agent`. It's a `DualModeStore` over one sqlite DB at `~/.nova/store.db`: sync callers use it directly; async callers (middleware `aput`/`aget`) run it in a worker thread under a lock. Prefers `langgraph-checkpoint-sqlite`'s `SqliteStore`, falls back to a built-in stdlib-`sqlite3` `BaseStore`, then in-memory.

### Hermes — the Nova learning system (`hermes/`)
`NovaLearningMiddleware` counts tool calls and records usage in the store. Every ~N tool calls it runs an **out-of-band self-review**: a *separate* `model.ainvoke` (no tools) whose text output is parsed by middleware code to update USER.md/MEMORY.md and, every few reviews, to **create/refine skills** via `skill_discovery.py` → `skills/skill_creation.py:_generate_skill()` (which spins up its own file-writing `create_deep_agent`). The review never replaces the user's turn.

### Sessions vs. checkpointer
- **Conversation state** lives in the LangGraph **checkpointer**, keyed by `thread_id`. `/clear` assigns a new `thread_id` (empty context) and marks the old session `cleared`.
- **Cross-restart persistence** is file-based in `session/` (`save_session` → `recent.jsonl` + `archive.jsonl`, keyed by `session_id`). `--continue` restores the latest **non-cleared** session and rebuilds a continuation prompt (`session_prompt_builder.py`); message tool-call/result pairing is repaired before seeding.

### Prompts
All system/agent prompts are **Jinja templates** in `prompts/`, rendered via `prompts.render_template(...)`. The final system prompt is assembled from several templates plus runtime middleware injections (memory, project graph, MCP). Edit prompts here, not inline strings.

### Project graph (`/init`)
`commands/init_handler.py` + `init/` use the `graphifyy` library (the `graphify` optional extra) to build `.nova/project-graph.json` (communities, god nodes, cross-module links). `bootstrap/graph_context.py:GraphContextMiddleware` injects a summary into the system prompt; `tools/graph_tools.py:query_project_graph` lets the agent query it. Note: graph nodes can have **null `label`s**, so always guard `(node.get("label") or "")` before `.lower()`. The graphify run caches an AST under `graphify-out/` (gitignored).

### Other subsystems
- **MCP** (`mcp/`): lazy-singleton `MCPMiddleware`; tools are loaded with `tool_name_prefix=True` (so server `serena`'s `read_file` becomes `serena_read_file`, avoiding collisions with built-ins); failures are wrapped to return an error result instead of aborting the turn.
- **Sandboxes** (`integrations/`): docker/modal/runloop/daytona/e2b, plugged in as the default backend of the CompositeBackend.
- **Agent file ops use virtual paths** (`FilesystemBackend(virtual_mode=True)`): always `/`-rooted (e.g. `/src/main.py`), never host/Windows absolute paths.
- **Optional extras** (`pyproject.toml`): `graphify` (`graphifyy`), `code-search` (`semble`), `remote-discord`, `voice`. Features degrade gracefully when an extra is absent.

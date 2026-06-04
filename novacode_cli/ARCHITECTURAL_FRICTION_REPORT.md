# Nova-Code CLI — Architectural Friction Report

**Codebase:** `/workspace/novacode_cli/`  
**Files analyzed:** ~75 source files (~33K total lines)  
**Date:** Analysis based on reading across all structural modules, packages, and command handlers

---

## 1. Shallow Modules

### 1.1 Barrel / Re-export `__init__.py` Files (Prevalent Pattern)

| File | Lines | Role | Verdict |
|---|---|---|---|
| `security/__init__.py` | 28 | Pure re-export of `unicode_security.py` | **Shallow** |
| `remote/__init__.py` | 30 | Pure re-export of `bridge.py` + `config.py` | **Shallow** |
| `tools/__init__.py` | 69 | Re-export barrel (try/except imports) | **Shallow** |
| `mcp/__init__.py` | 68 | Lazy-import barrel + singleton accessor | **Shallow** |
| `tracking/__init__.py` | 9 | Just a docstring, no exports | **Near-empty** |
| `commands/__init__.py` | 3 | `"""..."""` only | **Effectively empty** |
| `utils/__init__.py` | 0 | Empty | **Empty** |

**Severity: Low** — These are standard Python `__init__.py` patterns, but the sheer number of them (7 packages, some with no useful init logic) indicates the package structure was grown organically rather than designed intentionally. The worst offenders are `commands/__init__.py` (which should organize what `commands` provides) and `tracking/__init__.py`, which provides no import convenience at all.

### 1.2 `cli_session.py` (336 lines)

**Claim:** "This module contains extracted functions from main.py for better organization" (line 6-7).

**Reality:** It's a grab-bag of unrelated utilities — signal handlers (`GracefulShutdown`), message ID tracking (`SeenMessageIds`), splash screen display, model info display, auto-save management, memory status display, Tavily warnings, tips display. These are grouped only by "things that used to be in main.py."

**Deletion test:** If deleted, `main.py` would re-grow by 336 lines of inline code. This means extraction was not driven by module cohesion but by file-size reduction.

**Severity: Medium** — The module has no unifying concept; it's "stuff that main.py didn't need in its face."

---

## 2. Leaky Seams

### 2.1 `main.py` — The God Module (2,399 lines)

**The Problem:**
- Imports from **~25 distinct sub-modules** spanning every package: `agents`, `commands`, `config`, `input`, `tracking`, `integrations`, `mcp`, `migrate`, `path_approval`, `skills`, `states`, `tools`, `ui`, `vixie`, `process_manager`, `server_runner`, `hooks`, `cli_session`, `compaction`, `recovery`, `onboarding`, `doctor`, `security`.
- Contains **both** argument parsing (`parse_args()`, ~100 lines) **and** the main CLI loop (`run_cli_session`, ~1,000+ lines) **and** startup configuration, signal handling, etc.
- Changing anything about how the agent runs, how tools appear, how sessions save, or how the UI renders requires touching this file.

**Deletion test:** If deleted, **the entire application disappears.** All complexity concentrates here.

**Severity: High** — This is the single highest-risk module. Its size makes it hard to reason about, hard to test, and dangerous to refactor.

### 2.2 `commands/commands.py` — Mega-Dispatcher (1,122 lines)

**The Problem:**
- A single `handle_command()` function with **~40+ `if cmd == ...` branches**, each routing to a different handler module.
- Each branch is wrapped in its own try/except with nearly identical error messages.
- The function signature requires **9 parameters** — a telltale sign of poor cohesion.
- It imports from **18 different sub-modules** in `commands/` alone.

**Deletion test:** If deleted, every single command handler becomes orphaned. All the complexity is in the **orchestration pattern** (how branches are organized, error-handled, and parameter-passed), which is duplicated ~40 times. The complexity would just spread into `main.py` or a differently-organized dispatcher.

**Severity: High** — This is a textbook "leaky seam" between command parsing and command execution. Adding a new command requires: (1) writing a handler file, (2) adding an import to `commands.py`, (3) adding an `if cmd == "..."` branch, (4) duplicating the error-handling pattern.

### 2.3 `SessionState` — The Omnibus Dataclass

**File:** `states/Session.py` (299 lines)  
**The Problem:** `SessionState.__init__` (lines 49-99) initializes 25+ attributes spanning:
- Auto-approve mode, splash, verbose, plan mode, prompt decomposition
- Steering instructions (imports from `bootstrap/steering`)
- Background Ralph tasks
- Trello server instance
- Remote bridge manager, queues, locks (Discord/Telegram)
- Agent components: agent, backend, checkpointer, store, tools, model
- Token tracker, image tracker, seen message IDs
- Notifications queue

**Severity: Medium** — Every new feature adds a field to this central state object. It creates implicit coupling: the `remote` package accesses `_remote_message_queue`, `_auto_approve`; the `bootstrap/steering` package accesses `steering_instructions`; the `commands` package accesses `background_ralph_tasks`. A change to any of these requires touching `SessionState`.

### 2.4 Cross-Module Coupling via main.py's Imports

**The Problem:** `main.py` imports from `tools` (all tool functions individually), `ui.execution`, `ui.ui_elements`, `input`, `config.config`, `config.model_create`, `tracking.tracing`, `integrations.sandbox_factory`, `mcp.commands`, `skills.skill_creation`, `agents/core_agent`, `cli_session`, etc.

This means `main.py` is a **structural hub**: every module that wants to be used by the CLI must have a path through `main.py`. There is no clean dependency inversion — `main.py` directly instantiates and wires everything.

**Severity: High** — This prevents independent testing of modules. To test `ui/execution.py`, you need to look at how `main.py` calls it. There's no clean `App` or `Application` class that encapsulates the wiring.

---

## 3. Fragmented Responsibility

### 3.1 Context Window Management — 9+ Files Across 2 Packages

**The Files:**

| File | Lines | Purpose |
|---|---|---|
| `context/context_manager.py` | 582 | Main context tracking, token counting, breakdown |
| `utils/context_budget.py` | 146 | `ContextBudget` class for middleware layers |
| `utils/context_growth_tracker.py` | 331 | Per-turn growth tracking with alerts |
| `utils/context_eviction.py` | 296 | Old-message eviction strategies |
| `utils/context_tracking.py` | 116 | Decorator/functions to track context usage |
| `utils/context_optimization.py` | 304 | Example/integration class (labeled "integration example") |
| `utils/conversation_context.py` | 72 | Recent-conversation digest extractor |
| `utils/dynamic_context.py` | 371 | Ollama dynamic context detection |
| `utils/model_config.py` | 576 | Model-specific config (context windows, budgets, etc.) |

**Total: ~2,794 lines across 9 files, 2 packages**

**The Problem:**
- `context/context_manager.py` has `ContextBreakdown` and `CompactionResult` and `ContextManager` — but the "budget" concept lives in `utils/context_budget.py`.
- `utils/context_optimization.py` is literally labeled as an "integration example" — but it imports from the same modules and is used in production? Unclear.
- `utils/model_config.py` (576 lines) is a massive dataclass + lookup table that duplicates model context windows also found in `context/context_manager.py`.
- `utils/dynamic_context.py` queries Ollama for context length — but `utils/model_config.py` has hardcoded fallback values. Are these coordinated?

**Deletion test:** Deleting any one file would require understanding which logic is duplicated vs. complementary. The complexity is **distributed**, not localized. Understanding "how does context management work?" requires reading at least 5 of these files.

**Severity: High** — This is the most fragmented responsibility in the codebase. The split between `context/` and `utils/` seems arbitrary, and the presence of `context_optimization.py` (labeled as example) alongside real production modules suggests poor boundaries.

### 3.2 Command Handling — 23 Handler Files + 1 Mega-Dispatcher

| Category | Files | Lines |
|---|---|---|
| `commands/commands.py` | 1 (dispatcher) | 1,122 |
| Command handlers | 22 files | ~8,100 total |

Every command is in its own file (`model_handler.py`, `ralph_handler.py`, `hooks_handler.py`, ...) yet they all share:
- Same try/except/console.print error pattern
- Same parameter passing conventions
- No abstract base or protocol

**Severity: Medium** — Each handler is individually testable (good!), but there's no shared command abstraction. Adding `--json` output support would require touching all 22 files.

### 3.3 Session Persistence — 5 Files, 3 Locations

| File | Lines | Purpose |
|---|---|---|
| `session/session_persistence.py` | 770 | Core save/load, SessionManager, SessionMeta, SessionData |
| `session/session_prompt_builder.py` | 190 | Build prompts for continuation |
| `session/session_restore.py` | 362 | Validate & restore sessions |
| `session/session_summarization.py` | 150 | Generate memory.md from messages |
| `cli_session.py` | 336 | Auto-save timing constants, shutdown helpers |

Note: `cli_session.py` claims to be "extracted from main.py" (line 6) but contains auto-save logic that depends on session concepts. Session-related code lives in **4 files in `session/`** plus **`cli_session.py`** plus **`commands/session_commands.py`**.

**Severity: Medium** — The split between `session/` package and `cli_session.py` is confusing. Auto-save intervals (`AUTO_SAVE_INTERVAL_SECONDS`) live in `cli_session.py` while the actual save logic lives in `session/session_persistence.py`.

---

## 4. Pass-Through Modules (Deletion Test Candidates)

### 4.1 `security/__init__.py` (28 lines)

**What it does:** Re-exports everything from `unicode_security.py`.

**Deletion test:** All 8 imports just change from `from novacode_cli.security import check_url_safety` to `from novacode_cli.security.unicode_security import check_url_safety`. **Complexity would not vanish — it would shift to the importer.**

**Verdict:** Pass-through. Delete candidate if consumers are adjusted.

**Severity: Low**

### 4.2 `remote/__init__.py` (30 lines)

**What it does:** Re-exports from `bridge.py` and `config.py`.

**Deletion test:** Same as security. Complexity shifts to importers.

**Verdict:** Pass-through.

**Severity: Low**

### 4.3 `tools/__init__.py` (69 lines)

**What it does:** Re-exports 10 tools from 5 sub-modules, plus try/except for optional code_search.

**Deletion test:** tools are imported in `main.py` individually (`from novacode_cli.tools import web_search, fetch_url, ...`). Removing this would require importing from individual tool modules. Some value in the try/except for code_search.

**Verdict:** Borderline. The try/except pattern for optional code_search provides value, but this is primarily a barrel.

**Severity: Low**

### 4.4 `mcp/__init__.py` (68 lines)

**What it does:** Lazy-import barrel + shared singleton getter/reset for MCP middleware.

**Deletion test:** The singleton logic (`get_shared_mcp_middleware`, `reset_shared_mcp_middleware`) is genuinely useful here. Without it, every agent creation would reconnect MCP servers. This is more than pass-through.

**Verdict:** Not a pass-through — the singleton logic justifies its existence.

**Severity: None**

### 4.5 Commands as Pass-Through Candidates

Many command handler files are thin wrappers. Example:

| File | Lines | What it does | Pass-through? |
|---|---|---|---|
| `dream_handler.py` | 168 | Thin agent invocation + display | Partial |
| `vision_handler.py` | 201 | Wraps vision model calls | Partial |
| `notifications_handler.py` | 93 | Menu + list/dismiss notifications | **Borderline** |
| `trello_handler.py` | 176 | Menu + relay to trello_server.py | Partial |

These aren't true pass-throughs since they handle user interaction (menus, rich display). But they follow no shared pattern.

---

## 5. Modules Extracted Purely for Testability

### 5.1 `cli_session.py` (336 lines)

**The tell:** Line 6: *"This module contains extracted functions from main.py for better organization"*

**What was extracted:** `GracefulShutdown`, `SeenMessageIds`, display functions (splash, model info, tips, etc.), auto-save manager.

**Where the real bugs hide:** The extraction was mechanical (move code from A to B), not conceptual. The functions still take `session_state`, `agent`, and other live objects as parameters. The interactions between these functions (e.g., does `display_splash_screen` need to happen before `display_model_info`? Does auto-save depend on session state?) are not documented or enforced.

**Deletion test:** Complexity returns to `main.py` cleanly. No loss of abstraction.

**Severity: Medium** — Extraction-for-testability is fine, but it means the real integration bugs (race conditions in auto-save, shutdown ordering) hide in main.py's orchestration, not in the extracted functions.

### 5.2 `commands/session_commands.py` (287 lines)

**The tell:** `/compact` and `/save` and `/sessions` were extracted from commands.py.

**Where the real bugs hide:** The real complexity is in `SessionManager.save_session()` in `session_persistence.py` (checkpointing, JSON serialization, file I/O). The extracted handler is just a thin menu that calls `session_manager.list_sessions()` and `session_manager.delete_session()`. Testability improved, but the integration bug (what happens if you /save while Ralph is running?) lives in commands.py's orchestration.

**Severity: Low**

### 5.3 `commands/skill_invoke.py` (302 lines)

**What it does:** Was extracted from commands.py's `if cmd.startswith("skill:")` branch.

**Where the real bugs hide:** The logic for reading skill files, handling project vs. user skills, and building the prompt is here. But the caller in commands.py still has fallthrough handling (`if skill_prompt is not None: return skill_prompt` / `else: print("Unknown skill")`). The real bug scenario (/skill with no skills installed, /skill:non-existent) is handled in the dispatcher, not the extracted module.

**Severity: Low**

---

## Summary & Recommendations

### Highest Priority Issues

| # | Issue | Type | Severity | Recommendation |
|---|---|---|---|---|
| 1 | `main.py` (2,399 lines) imports ~25 modules | Leaky seam / God module | **High** | Extract an `App` class or `Session` orchestrator that wires components |
| 2 | `commands/commands.py` (1,122 lines) — 40 `if cmd ==` branches | Leaky seam | **High** | Replace with a command registry pattern (dict mapping cmd → handler function) |
| 3 | Context management in 9 files across 2 packages | Fragmented responsibility | **High** | Consolidate into a single `context/` package with clear sub-module boundaries |

### Medium Priority Issues

| # | Issue | Type | Severity | Recommendation |
|---|---|---|---|---|
| 4 | `SessionState` omnibus with 25+ fields across 5 domains | Leaky seam | **Medium** | Split into focused state holders (e.g., `AgentState`, `RemoteState`, `UISettings`) |
| 5 | `cli_session.py` — grab-bag of extracted utilities | Shallow / testability | **Medium** | Split by concern: `signal_handlers.py`, `display_helpers.py`, `auto_save.py` |
| 6 | 22 command handlers with no shared abstraction | Fragmented responsibility | **Medium** | Define a `CommandHandler` protocol or abstract base |
| 7 | Session logic in `session/` + `cli_session.py` + `commands/session_commands.py` | Fragmented responsibility | **Medium** | Move auto-save constants into `session/` package |

### Low Priority Issues

| # | Issue | Type | Severity | Recommendation |
|---|---|---|---|---|
| 8 | Barrel re-export files (`security/__init__.py`, `remote/__init__.py`, `tools/__init__.py`) | Pass-through / shallow | **Low** | Keep for convenience but ensure they export intentionally, not exhaustively |
| 9 | `commands/__init__.py` (3 lines), `tracking/__init__.py` (9 lines), `utils/__init__.py` (0 lines) | Shallow | **Low** | Either add useful exports or document why they're minimal |
| 10 | `context_optimization.py` labeled "integration example" alongside production code | Fragmented | **Low** | Rename to `_example_integration.py` or refactor into real integration logic |

### Structural Health Metrics

| Metric | Value |
|---|---|
| God modules (>500 lines) | `main.py` (2,399), `commands.py` (1,122), `shell.py` (1,586), `skill_creation.py` (1,822), `execution.py` (1,140), `talk_handler.py` (1,105), `config.py` (931), `input.py` (879), `core_agent.py` (836) |
| Empty/trivial `__init__.py` files | 3 (commands, utils, tracking) |
| Packages with >5 files | `utils/` (15), `commands/` (23), `ui/` (11), `session/` (4), `tracking/` (5) |
| Cross-package fragments | Context management (2 packages), Session (3 locations) |
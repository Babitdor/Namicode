# Test Structure and Testability Analysis — `novacode-cli`

> Based on reading all 37 test files in `/workspace/tests/` + source modules.

---

## 0. Test Infrastructure

| Property | Value |
|---|---|
| Test framework | pytest 8+ (`asyncio_mode = auto`) |
| Timeout | 10s default (`timeout_method = thread`) |
| Dev deps | pytest, pytest-asyncio, pytest-timeout, black, ruff, mypy |
| Conftest | **None found** — no shared fixtures |
| Test discovery | `tests/*` (flat), `tests/test_hermes/` (one sub-package) |
| Ruff for tests | D1, S101, ANN201, INP001, PLR2004 suppressed |

The absence of `conftest.py` is notable: every test file builds its own fakes and fixtures from scratch. This keeps things explicit but means there's **no shared fake-construction pattern** across the codebase — each test module reinvents `_FakeAgent`, `_Chunk`, etc.

---

## 1. Test Coverage: What's Well-Tested vs. Untested

### ✅ Well-Tested Modules (≥80% logical coverage)

| Module | Test File(s) | Pattern |
|---|---|---|
| `security/middleware.py` | `test_security_middleware.py` | URL arg sanitization, side-effect emission |
| `bootstrap/steering.py` | `test_steering.py` | System-prompt injection, one-time delivery |
| `bootstrap/graph_context.py` | `test_graph_context.py` | Legend-only injection contract |
| `integrations/workdir_backend.py` | `test_workdir_backend.py`, `test_workdir_grep.py` | Path rebasing, grep command builder + parser |
| `plugins/loader.py` | `test_plugins.py` | Enable/disable lifecycle, middleware injection slots |
| `council.py` | `test_chat_handler.py` | Score/vote parsing, fenced JSON recovery |
| `context/_analysis.py` | `test_context_breakdown_tokens.py` | Token counting, tool-call args in AIMessage |
| `context/_dynamic.py` | `test_ollama_context.py` | `ollama ps` parsing, num_ctx env override |
| `commands/ralph_handler.py` | `test_ralph_progress.py`, `test_ralph_ui.py` | Emit-sink pattern, progress tracking |
| `commands/dream_handler.py` | `test_dream_handler.py` | Emit-sink pattern, virtual path references |
| `commands/skill_invoke.py` | `test_skill_invoke.py` | Name matching, presentation-free resolver |
| `commands/notifications_handler.py` | `test_notifications.py` | Add/dismiss/clear lifecycle, maxlen bounding |
| `commands/chat_handler.py` | `test_chat_handler.py` | Council event generator |
| `agents/core_agent.py` | `test_subagent_resilience.py`, `test_subagent_hitl.py`, `test_summarization_profile.py` | Subagent hardening, HITL clearing, profile seeding |
| `input.py` | `test_agent_mentions.py` | `@agent` mention parsing |
| `init/extract.py` | `test_init_semantic.py`, `test_normalize_source_paths.py` | JSON fence parsing, path normalization |
| `init/generate.py` | `test_init_nova_md.py` | NOVA.md generation |
| `utils/backend_patches.py` | `test_write_file_content_patch.py`, `test_host_path.py` | Dict→JSON coercion, host→virtual path |
| `session/session_persistence.py` | `test_session_clear.py`, `test_store_memory.py` | Cleared session filtering, store round-trips |
| `hermes/middleware.py` | `test_hermes_middleware.py` | Counter lifecycle, review injection |
| `hermes/memory_tiers.py` | `test_hermes/test_memory_tiers.py` | File creation, compaction, updates |
| `hermes/skill_discovery.py` | `test_hermes/test_skill_discovery.py` | Pattern detection, candidate evaluation |
| `states/slices/notifications.py` | `test_notifications.py` | Slice-level add/dismiss/clear |
| `tui/app.py` | `test_tui_app.py` | Headless smoke test via Textual pilot |
| `tui/pickers.py` | `test_tui_pickers.py` | Session picker, onboarding app |

### ⚠️ Partially Tested Modules

| Module | What's Tested | What's NOT Tested |
|---|---|---|
| `integrations/sandbox_factory.py` | Pure helpers (`_sandbox_image`, `_skip_provision`, `_build_provision_script`, `_provision_sandbox_tools`) | **All context managers**: `create_docker_sandbox`, `create_modal_sandbox`, `create_runloop_sandbox` — 200+ lines of orchestration, cleanup, setup script running |
| `memory/agent_memory.py` | NOVA.md loading, `skip_project_memory` flag | `before_agent()` beyond NOVA.md, user memory, memory index, truncation, state updates |
| `core/agent_loop.py` | Happy-path event sequence (text + tool call + todo) for `iterate_agent_events` | Interrupt resolution (3 types), HITL flow, subagent events, error handling, cache metrics, `_post_summarization`, `_flush_events` discard paths, streaming edge cases |
| `hermes/skill_discovery.py` | Pure pattern detection from tool history | **LLM skill refinement path** — the actual model call for generating skill content |

### ❌ Untested Modules (Zero Tests)

| Module | Lines | Testability |
|---|---|---|
| `hooks.py` | ~270 | **Easily testable** — pure `_validate_command`, `_sanitize_env_for_hook`, `_load_hooks` with tmp_path |
| `recovery.py` | ~210 | **Easily testable** — `FileRecoveryManager` methods work with tmp_path and fake files |
| `file_ops.py` | ~350 | Partially testable — `_safe_read`, `compute_unified_diff` are pure; `FileOpTracker` needs fakes |
| `compaction.py` | — | No tests |
| `doctor.py` | — | No tests |
| `git_safety.py` | — | No tests |
| `image_utils.py` | — | No tests |
| `migrate.py` | — | No tests |
| `onboarding.py` | — | No tests |
| `path_approval.py` | — | No tests |
| `process_manager.py` | — | No tests |
| `shell.py` | — | No tests |
| `plans.py` | — | No tests |
| `security/unicode_security.py` | — | Pure functions — should be tested alongside middleware |
| `security/validator.py` | — | No tests |
| `mcp/` | — | No tests |
| `remote/` | — | No tests |
| `skills/` | — | No tests |
| Most `ui/` modules | — | Heavy rich/textual deps |
| Most `config/` modules | — | Settings/singletons, harder to isolate |

---

## 2. Testability Friction Points Per Module

### 2.1 Hooks System (`hooks.py`) — **No seam at all**

```python
_hooks_config: list[dict[str, Any]] | None = None  # Module-level cache
HOOKS_FILE = Path.home() / ".nova" / "hooks.json"  # Hard-coded path
```

**Problems:**
- `_load_hooks()` caches into a module-level global — requires `importlib.reload` or manual reset between tests
- `HOOKS_DIR` / `HOOKS_FILE` are module-level constants, not injectable
- `_run_single_hook` calls `subprocess.run()` directly — no test seam for the subprocess call
- `fire_hook_async` uses module-level `_background_tasks` set — test isolation problem
- `fire_hook` fires `asyncio.ensure_future` — thread-pool jobs that can leak across tests

**Fix path:** Make `HOOKS_DIR` configurable (constructor parameter or fixture), wrap `subprocess.run` in a strategy/callable, clear `_hooks_config` and `_background_tasks` in a conftest fixture.

### 2.2 FileRecoveryManager (`recovery.py`) — **Good structure, zero tests**

The class is actually **well-structured for testing**:
- `_TRASH_ROOT` is a module-level constant but relative to `Path.home()` — overridable via `monkeypatch`
- Each method does a discrete filesystem operation
- `SnapshotEntry` is a simple dataclass

**Missing tests:**
- `snapshot()` — file exists, missing, too large, directory, OSError
- `snapshot_from_content()` — empty content, success
- `list_snapshots()` — current session, cross-session, max 3 other sessions
- `restore()` — success, missing snapshot, target dir creation
- `_relative()` — relative path calculation
- `_make_snapshot_name()` — timestamp/uid formatting

### 2.3 Sandbox Factory (`integrations/sandbox_factory.py`) — **Missing orchestration tests**

The three context managers (`create_docker_sandbox`, `create_modal_sandbox`, `create_runloop_sandbox`) are **the testability antipattern**:
- They embed Docker/Modal/Runloop SDK calls directly
- They self-cleanup in `finally` blocks
- `create_docker_sandbox` uses `docker.from_env()` — no seam
- `create_modal_sandbox` calls `modal.App()`, `modal.Sandbox.create()`, polls for readiness
- `_run_sandbox_setup` validates path traversal, reads files, expands env vars — but is tested **only through the untested context managers**

**Fix path:** Extract the adapter creation into injectable factory functions. The provision logic (`_provision_sandbox_tools`, `_run_sandbox_setup`) is already testable — the gap is merely wiring it to a fake backend.

### 2.4 Agent Loop (`core/agent_loop.py`) — **Interface is the test surface, but 400+ lines deep**

```
iterate_agent_events(user_input, agent, assistant_id, session_state, ...)
    → AsyncIterator[UIEvent]
```

**Good:** The yield protocol IS the interface. Both UIs consume these events.

**Bad:** The function is 400+ lines with:
- 8+ branches per event type (updates vs messages, tool vs text, main vs subagent)
- 3 interrupt resolution types (question, plan, tool HITL)
- Internal state machines (`_flush_events`, `_post_summarization`, `pending_text`)
- Hard import: `from novacode_cli.hermes.middleware import nova_event_log`
- Direct agent API calls: `agent.astream()`, `agent.aget_state()`, `agent.aupdate_state()`

**Tests test past the interface:**
```python
# test_agent_stream.py: tests call iterate_agent_events directly, not
# the public run_agent_stream wrapper. They assert on internal protocol
# (event types, ordering) rather than observable behavior.
```

**What's untested and risky:**
- Interrupt flow: HITL tool approval → future resolution → `Command(resume=...)` → agent continues
- Summarization detection: `_post_summarization` logic
- Subagent tracking events
- Tool result display formatting
- Error recovery: what happens when `agent.astream` raises mid-stream?

### 2.5 AgentMemoryMiddleware (`memory/agent_memory.py`) — **Interface gap**

The `before_agent()` method loads up to 3 memory sources (user, project, index), truncates each to `MAX_MEMORY_CHARS`, and injects into state. Only the project memory path (NOVA.md loading) is tested.

**Missing tests:**
- `before_agent()` with all 3 sources populated
- Truncation behavior at `MAX_MEMORY_CHARS`
- Missing files, broken symlinks, permission errors
- State merge when some keys already exist
- The `after_agent()` extraction path

### 2.6 Hooks + Recovery — **Systematic gaps**

Both modules have **zero tests** despite being inherently testable with `tmp_path` + `monkeypatch`. They represent the biggest testability quick wins in the codebase.

---

## 3. Specific Deepening Candidates

### Priority 1: Low-Hanging Fruit (Pure Functions, No Dependencies)

| Candidate | Module | Effort | Impact |
|---|---|---|---|
| `_validate_command` | `hooks.py` | 1 hour | Catches command injection filter bugs |
| `_sanitize_env_for_hook` | `hooks.py` | 30 min | Prevents API key leakage regression |
| `_load_hooks` / `_load_manifest_file` | `hooks.py`, `recovery.py` | 1 hour | Tests JSON parsing, caching, error recovery |
| `FileRecoveryManager.snapshot` | `recovery.py` | 2 hours | Tests file/dir/missing/too-large boundary |
| `_relative`, `_make_snapshot_name` | `recovery.py` | 30 min | Path calculation correctness |

### Priority 2: Module-Level Isolation (Need Fixtures)

| Candidate | Module | What to Deepen |
|---|---|---|
| `agent_memory.py` `before_agent()` | `memory/agent_memory.py` | Full 3-source flow, truncation, error handling |
| `iterate_agent_events` interrupt paths | `core/agent_loop.py` | HITL tool/plan/question resolution via fake futures |
| `_provision_sandbox_tools` summary parsing | `integrations/sandbox_factory.py` | Already partially tested, but add MISSING edge cases |

### Priority 3: Architectural Deepening (Needs Seam Changes)

| Candidate | Module | Change Required |
|---|---|---|
| Sandbox factory context managers | `integrations/sandbox_factory.py` | Extract `docker.from_env()` behind an injectable factory, or make context managers take a pre-created backend |
| `hooks.py` global state | `hooks.py` | Make `_hooks_config` / `HOOKS_DIR` configurable (class or closure), wrap `subprocess.run` |
| `recovery.py` `_TRASH_ROOT` | `recovery.py` | Make trash root injectable (parameterized class or fixture) |
| `agent_loop.py` simplification | `core/agent_loop.py` | Extract interrupt handling into focused helper functions that can be unit-tested independently |

---

## 4. "Interface Is the Test Surface" Assessment

### Agent Loop (`iterate_agent_events` / `run_agent_stream`)

```
Interface: AsyncIterator[ev.*] — 12+ event types
```

**Assessment: ⚠️ Partial.** The function correctly yields UI events as its interface, and tests verify this. But:

1. Tests bypass `run_agent_stream` and call `iterate_agent_events` directly — coupling to the lower-level import
2. The `_collect()` helper in `test_agent_stream.py` handles interrupt resolution inline, mixing test infrastructure with test assertions
3. The 400+ line function body means the "interface" is too coarse — a single test cannot cover all branches
4. **Better approach:** Extract the interrupt-handling, subagent-tracking, and event-draining into testable helpers; test each independently; then test the orchestrator with a known-complete set of helpers

### Middleware Stack (`awrap_tool_call`, `before_agent`, `after_agent`)

Each middleware module | Interface
---|---
**Assessment: ✅ Good.** Each middleware has a well-defined `AgentMiddleware` interface:
- `SecurityMiddleware.awrap_tool_call(request, handler)` — wraps a single tool call
- `SteeringMiddleware._inject(request)` — transforms a `ModelRequest`
- `AgentMemoryMiddleware.before_agent(state)` — returns `AgentMemoryStateUpdate`
- `NovaLearningMiddleware.awrap_tool_call(request, handler)` — wraps tool call + state

Tests correctly exercise these interfaces with minimal fakes. The rare exception is `AgentMemoryMiddleware.before_agent()` which has untested branches.

### Sandbox Factory (`create_*_sandbox` context managers)

```
Interface: contextmanager → Generator[SandboxBackendProtocol, None, None]
```

**Assessment: ❌ Poor.** The public API is a context manager, but:
- There's no test seam to substitute the real Docker/Modal/Runloop SDK
- The cleanup logic (`try/finally`) is intertwined with creation
- **Fix:** These should accept a pre-created backend or have a pluggable adapter. The `_provision_sandbox_tools` and `_run_sandbox_setup` helpers ARE testable but are only reachable through the untested context managers.

### Hooks System (`fire_hook`)

```
Interface: fire_hook(event, payload) — side-effect only
```

**Assessment: ❌ Missing.** The only tested function is `get_hooks_config` (indirectly). The core dispatch (`fire_hook`, `fire_hook_async`, `_dispatch_hook_sync`, `_run_single_hook`) has zero test coverage despite being pure-function-heavy.

**What makes it hard:**
- Module-level globals (`_hooks_config`, `_background_tasks`)
- Hard-coded `HOOKS_FILE = Path.home() / ".nova" / "hooks.json"`
- Direct `subprocess.run()` call

**What makes it easy:**
- `_validate_command` is pure
- `_sanitize_env_for_hook` is pure
- `_load_hooks` is almost-pure (filesystem → JSON → list)
- `_dispatch_hook_sync` is sequential dispatch with no callbacks

### FileRecoveryManager

```
Interface: snapshot(file_path, reason, command) → bool
           list_snapshots() → list[tuple[str, SnapshotEntry]]
           restore(entry, session_id) → bool
```

**Assessment: ✅ Would be good, if tested.** The interface is clean:
- Each method takes explicit parameters
- `SnapshotEntry` is a simple dataclass with no hidden state
- Filesystem interactions are isolated to single operations
- **Only missing:** tests — and a way to inject `_TRASH_ROOT` without `monkeypatch`

### WorkdirSandboxBackend

```
Interface: SandboxBackendProtocol (execute, download_files, upload_files, grep)
```

**Assessment: ✅ Excellent.** Tests verify:
- Path rebasing via `_rebase` (pure)
- Grep command building via `_build_grep_command` (pure)
- Grep output parsing via `_parse_grep_output` (pure)
- Round-trip via stub inner backend (execute/download/upload passthrough)
- Idempotency: `_rebase(_rebase(x)) == _rebase(x)`

---

## 5. Pattern Observations

### Good Patterns in the Codebase

1. **Extract-and-test:** Pure functions isolated for testability
   ```
   _build_provision_script()       # sandbox_factory.py
   _parse_grep_output()            # workdir_backend.py
   _validate_command()             # hooks.py
   _harden_subagent_specs()        # core_agent.py
   _seed_summarization_profile()   # core_agent.py
   ```
   These are the most reliable tests in the suite.

2. **Emit-sink decoupling:** Ralph, Dream, and Skill handlers take an `emit` callable, allowing tests to capture output without mocking `console.print`:
   ```python
   def _sink():
       lines = []
       return lines, lines.append
   ```
   This is a clean testability pattern that more modules should adopt.

3. **Minimal fakes, not mocks:** The test suite almost exclusively uses hand-written fake classes (50+ across the suite) rather than `unittest.mock`. This produces clearer failure messages and documents the protocol.

4. **Headless UI tests:** `test_tui_app.py` and `test_tui_pickers.py` use Textual's `run_test()` pilot for smoke-level UI testing without a terminal.

### Anti-Patterns

1. **Integration-only modules:** Hooks and recovery have zero tests because they're small enough to "trust" — but bugs in command validation or snapshot directory resolution have real consequences.

2. **Tests past the interface:** `test_agent_stream.py` calls `iterate_agent_events` directly (not via `run_agent_stream`), and `_collect()` inlines the interrupt-resolution protocol. This means the public `run_agent_stream` has no dedicated tests.

3. **No conftest:** Every test file defines its own `_Chunk`, `_State`, `_FakeAgent`, etc. Some of these are duplicated across files (e.g., `_Chunk` in `test_agent_stream.py` and `test_tui_app.py`). A shared conftest with canonical fakes would reduce duplication and ensure consistency.

4. **Happy-path-only testing:** Of the 37 test files, fewer than 5 contain deliberate error-path tests (e.g., `test_provision_survives_execute_exception`). The remaining ~32 files test only success scenarios.

5. **Missing component boundary tests:** The `AgentMemoryMiddleware` sits between file reads and state injection — but no test verifies what happens when the file read fails. The agent loop sits between `agent.astream` and UI events — but no test verifies what happens when the stream raises.
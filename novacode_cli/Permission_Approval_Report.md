# Permission & Approval Workflow in NovaCode CLI — Full Report

> **Scope**: Path access, Human-in-the-Loop (HITL) tool approvals, plan-mode approvals,
> security middleware, and remote-bridge handling.
> All line numbers are as of the current codebase.

---

## 1. What Triggers a Permission Check?

There are **four distinct triggering systems**:

### 1A. Tool-Level HITL Interrupts (LangGraph `interrupt_on`)

**Source**: `hitl/interrupts.py` — `get_interrupt_configs()` (line 357–382)

Every agent built via `create_agent_with_config` (`agents/core_agent.py`, line 1039–1044)
or `create_plan_agent_with_config` (`agents/plan_agent/plan_agent.py`, line 243–246)
receives interrupt configs unless `auto_approve=True`.

**Triggered tools** (defined in `INTERRUPT_SPECS`, `hitl/interrupts.py` lines 71–168):

| Tool | Classification | Why Interrupted |
|------|---------------|-----------------|
| `shell` | Destructive | Arbitrary shell execution |
| `execute` | Destructive | Remote sandbox command |
| `write_file` | Destructive | Modifies filesystem |
| `edit_file` | Destructive | Modifies filesystem |
| `web_search` | External | Uses Tavily API credits |
| `fetch_url` | External | Fetches external content |
| `run_tests` | Code execution | Runs user's test suite |
| `start_dev_server` | Code execution | Starts a background process |
| `write_memory` | Memory operations | Writes persistent memory |
| `duckduckgo_search` | Search | Makes web requests |
| `docs_search` | Search | Makes web requests |

Each config allows `["approve", "edit", "reject"]` decisions (`hitl/interrupts.py` line 378).

### 1B. Plan Mode Blocking (Middleware Layer)

**Source**: `agents/plan_agent/plan_mode_middleware.py` lines 1–86

The `PlanModeMiddleware` intercepts tool calls at the middleware level (not interrupts):

- **`BLOCKED_TOOLS`** (from `config/plan_mode.py` lines 14–29): `shell`, `execute_bash`, `execute`,
  `start_dev_server`, `stop_server`, `run_tests`, `git_branch`, `git_stash`, `write_todos`
  → these return a `ToolMessage` with status `"error"` immediately, without prompting.

- **`RESTRICTED_WRITE_TOOLS`** (from `config/plan_mode.py` lines 34–37): `write_file`, `edit_file`
  → allowed **only** when the target path is inside `.nova/plans/` (checked by `_is_inside_plan_dir`,
  line 64–86).

### 1C. Plan Approval via `exit_plan_mode` Tool

**Source**: `tools/plan_mode_tools.py` lines 120–154

`exit_plan_mode(plan: str = "")` calls `interrupt({"type": "plan_approval", ...})` (line 137–143).
This is a **LangGraph `interrupt()` call** that pauses the graph and triggers a plan approval UI.

### 1D. Path Access Approval

**Source**: `path_approval.py` lines 1–275

At **startup**, `main.py` line 564 calls `check_path_approval()` which checks if the current
working directory is in the approved list. If not, it prompts the user via
`PathApprovalManager.prompt_for_approval()` (line 175–255).

The `PathApprovalManager` (line 14) stores approved paths in `~/.nova/approved_paths.json`
and supports:
- **Exact match** (O(1)): `is_path_approved()` line 102–129
- **Recursive prefix** (O(depth)): walks up directory tree checking `_recursive_prefixes`
- User can approve with or without recursive (subdirectory) access

The CLI also exposes `/paths list`, `/paths revoke <path>`, `/paths clear` commands
(`main.py` lines 361–389).

### 1E. Security Middleware (Warn + Sanitize, Not Block)

**Source**: `security/middleware.py` lines 1–87

The `SecurityMiddleware` screens URL-bearing tool arguments (`url`, `uri`, `href`, `link`, etc.)
for deceptive Unicode and punycode domain spoofing. It **never blocks** — it sanitizes in place
and emits events via the `nova_event_log` buffer (`_emit_security_event`, line 39–46).

Triggered on every tool call that has dict args with a URL-like key (line 52–63, `awrap_tool_call`).

### 1F. Security Validator (Explicit Validation Calls)

**Source**: `security/validator.py` lines 1–163

Provides `validate_url_for_fetch()`, `validate_tool_arguments()`, `validate_user_input()`
as explicit validation functions that **can** block (return `(False, error_message)` tuples).
These are not automatically wired in — they are called explicitly where needed.

---

## 2. How Does the Approval Flow Work?

### 2A. HITL Tool Approval Flow

```
Agent emits tool call
        │
        ▼
LangGraph interrupt_on matches tool name
        │
        ▼
Graph pauses with __interrupt__ event
        │
        ▼
core/agent_loop.py:line 255-298
  Detects interrupt in stream data:
  - Validates via _HITL_REQUEST_ADAPTER (line 289)
  - Creates asyncio.Future (line 463)
  - Yields ev.InterruptRequest(kind="tool", payload, future)
        │
        ▼
Consumer (ui/execution.py OR tui/app.py) receives InterruptRequest
        │
        ▼
ui/execution.py:line 369-387 (Rich REPL consumer):
  ┌─ process_hitl_approval() called ──────────────────────┐
  │                                                       │
  │ 1. check_plan_mode_blocked()  (hitl_approval.py:28)   │
  │    - If plan mode active && tool is BLOCKED_TOOLS:    │
  │      → auto-reject silently                           │
  │    - If plan mode active && tool in RESTRICTED:       │
  │      → auto-reject if NOT targeting .nova/plans/      │
  │                                                       │
  │ 2. Check session_state.auto_approve  (line 111)       │
  │    - If True → auto-approve all, return immediately   │
  │                                                       │
  │ 3. prompt_for_batch_approval()  (line 132)            │
  │    - Single action → prompt_for_tool_approval()       │
  │    - Multiple actions → rich interactive menu:        │
  │      (A)pprove all / (R)eject all / (I)ndividual      │
  │      / (Auto)-accept all going forward                │
  │                                                       │
  │ 4. Process decisions:                                 │
  │    - "auto_approve_all" → set session_state.auto_approve=True
  │    - "approve" → mark file ops via file_op_tracker    │
  │    - "reject" → flag any_rejected=True                │
  │                                                       │
  │ 5. Return (decisions, any_rejected, spinner_active)   │
  └───────────────────────────────────────────────────────┘
        │
        ▼
event.future.set_result({"decisions": ..., "any_rejected": ...})
        │
        ▼
core/agent_loop.py:line 497-499
  Graph resumes with Command(resume=hitl_response)
```

### 2B. Plan Approval Flow

```
Agent calls exit_plan_mode(plan="...")
        │
        ▼
tools/plan_mode_tools.py:line 137
  interrupt({"type": "plan_approval", "plan": plan})
        │
        ▼
core/agent_loop.py:line 278-286
  Detects interrupt with type="plan_approval"
  → pending_interrupts.append((id, "plan", payload))
        │
        ▼
Yields ev.InterruptRequest(kind="plan", ...)
        │
        ▼
ui/execution.py OR tui/app.py receives it
        │
        ▼
Handler: handle_plan_approval_interrupt()
  (ui/interrupt_handlers.py:292-411)
        │
        ├─ 1. Resolve plan content (priority order):
        │     a. Inline plan from exit_plan_mode(plan=...) → Priority 0
        │     b. Session state plan_content → Priority 1
        │     c. File system .nova/plans/plan*.md → Priority 2
        │     d. Todos-to-markdown fallback → Priority 3
        │     (resolve_plan_content, lines 124-264)
        │
        ├─ 2. Render plan inline (render_plan_content, lines 267-289)
        │
        ├─ 3. prompt_for_plan_approval() 
        │     (ui/question_prompt.py:264-458)
        │     Options:
        │       a. Auto-accept: execute autonomously (auto_approve=True)
        │       b. Manual-accept: approve each step (auto_approve=False)
        │       c. Reject: stay in plan mode
        │       d. Edit: continue planning
        │
        ├─ 4. If approved:
        │     - Set plan_mode_enabled=False
        │     - Store approved plan for hand-off to main agent
        │     - If "auto" mode: enable auto-approve temporarily
        │     - Return {approved: True, mode: "auto"|"manual"}
        │
        └─ 5. If rejected:
              - Return {approved: False, action, feedback}
              - Spinner restarts → plan agent continues planning
```

### 2C. Path Approval Flow

```
CLI startup (main.py:564)
        │
        ▼
check_path_approval() (path_approval.py:258-275)
        │
        ├─ PathApprovalManager.is_path_approved(path)
        │     - O(1) exact match + O(depth) prefix walk
        │
        ├─ If NOT approved → prompt_for_approval(path)
        │     - Shows rich panel with path info
        │     - Options: (y)es recursive / (o)nly this dir / (n)o
        │     - Uses prompt_toolkit for async input
        │     - Saves to ~/.nova/approved_paths.json
        │
        └─ If denied → exits with error (sys.exit(1))
```

### 2D. Plan Mode Blocking (Middleware) Flow

```
PlanModeMiddleware.awrap_tool_call() (plan_mode_middleware.py:30-62)
        │
        ├─ If tool_name in BLOCKED_TOOLS:
        │     → Return ToolMessage(content="[Plan Mode] ... blocked ...", status="error")
        │       (NO interrupt, NO prompt — silent block)
        │
        ├─ If tool_name in RESTRICTED_WRITE_TOOLS:
        │     → Check _is_inside_plan_dir(path)
        │     → If outside .nova/plans/: return error ToolMessage
        │     → If inside .nova/plans/: allow (pass through to handler)
        │
        └─ Otherwise: allow (pass through)
```

---

## 3. Where Are Approvals Surfaced?

### 3A. Tool Approval Modals (TUI / Rich Terminal)

| File | Lines | Mode | Description |
|------|-------|------|-------------|
| `ui/tool_approval.py` | 26–143 | **Batch prompt** | Multiple actions: rich Panel + arrow-key menu with `(A)pprove all / (R)eject all / (I)ndividual / (Auto)-accept all`. Falls back to sequential prompts for individual mode. |
| `ui/tool_approval.py` | 146–300 | **Single tool prompt** | Arrow-key menu with `(A)pprove / (R)eject / (Auto)-accept all`. Shows tool args, diff preview via `build_approval_preview()`. |
| `ui/tool_approval.py` | 69–121 | ANSI raw-mode interactive menu (termios) | |
| `ui/tool_approval.py` | 123–134 | Fallback for Windows/restricted terminals | Text-based `input()` prompt |
| `ui/tool_approval.py` | 280–292 | Fallback for single tool prompt | Text-based `input()` prompt |

### 3B. Plan Approval Modals

| File | Lines | Description |
|------|-------|-------------|
| `ui/question_prompt.py` | 264–458 | `prompt_for_plan_approval()` — Rich Panel with plan steps, arrow-key menu for Auto-accept / Manual-accept / Reject / Edit |
| `ui/interrupt_handlers.py` | 292–411 | `handle_plan_approval_interrupt()` — orchestrates rendering + approval + state transition |
| `commands/plan_handler.py` | 192–277 | `_disable_plan_mode()` — `/plan off` path, uses same `prompt_for_plan_approval()` |
| `commands/plan_handler.py` | 280–324 | `handle_plan_approval()` — older/deprecated plan approval handler |

### 3C. Path Approval Panel

| File | Lines | Description |
|------|-------|-------------|
| `path_approval.py` | 184–255 | `prompt_for_approval()` — Rich Panel with lock icon, path info, `y/o/n` prompt via `prompt_toolkit` |

### 3D. HITL Rendering Helpers

| File | Lines | Description |
|------|-------|-------------|
| `file_ops.py` | 261–355 | `build_approval_preview()` — generates diff previews for `write_file` and `edit_file`, returns `ApprovalPreview` dataclass with title, details, diff |
| `ui/ui_elements.py` | (indirect) | `render_diff_block()` is called from `tool_approval.py` line 189 to render the diff after the approval panel |
| `ui/hitl_approval.py` | 76–161 | `process_hitl_approval()` — shared approval processing logic consumed by both Rich REPL and TUI |
| `ui/hitl_approval.py` | 28–73 | `check_plan_mode_blocked()` — pre-checks plan mode before showing prompts |

### 3E. Status Spinner

During approval, the `console.status("Agent is thinking...")` spinner is stopped (`status.stop()`)
before prompting, and restarted after (`status.start()`). This is done in:
- `ui/execution.py` lines 373–384 (tool approval)
- `ui/interrupt_handlers.py` lines 320–322 (plan approval)
- `ui/hitl_approval.py` lines 113–125 (auto-approve)

---

## 4. Remote Bridge (Discord/Telegram) Handling

**Key Insight**: When a remote bridge is active, **auto-approve is forcibly enabled** because
interactive terminal prompts are impossible over Discord/Telegram.

### 4A. Remote Bridge State Management

**Source**: `states/slices/remote_bridge.py` lines 1–25

```python
class RemoteBridgeState:
    _pre_remote_auto_approve: bool | None = None  # Snapshot of previous auto_approve
```

The `SessionState` exposes `_pre_remote_auto_approve` property (`states/Session.py` lines 281–286)
which delegates to `_remote_bridge._pre_remote_auto_approve`.

### 4B. `/remote start` Forces Auto-Approve

**Source**: `commands/commands.py` lines 927–929

```python
if not session_state.auto_approve:
    session_state._pre_remote_auto_approve = False  # was off before remote
    session_state.auto_approve = True
```

### 4C. `/remote stop` Restores Previous State

**Source**: `commands/commands.py` lines 685–689 and 701–704

```python
if session_state._pre_remote_auto_approve is not None:
    session_state.auto_approve = session_state._pre_remote_auto_approve
    session_state._pre_remote_auto_approve = None
    if not session_state.auto_approve:
        console.print("  [dim]Auto-approve restored to off.[/dim]")
```

### 4D. Remote Message Processor Also Forces Auto-Approve

**Source**: `remote/processor.py` lines 180–181 and 236

```python
_prev_auto_approve = getattr(session_state, "auto_approve", False)
session_state.auto_approve = True
# ... execute task ...
session_state.auto_approve = _prev_auto_approve  # Restored in finally block
```

### 4E. Tool Notification Hook (Remote Fallback)

**Source**: `ui/execution.py` lines 246–251

```python
_notify = getattr(session_state, "_remote_tool_notify", None)
if _notify is not None:
    try:
        _notify(event.name, event.display_str)
    except Exception:
        pass
```

When remote is active, `_remote_tool_notify` is set to `_record_tool` (`remote/processor.py` line 191)
which collects tool names for the activity footer sent as the chat reply.

### 4F. Special Cases / Auto-Approve Toggle in Other Background Contexts

| File | Lines | Context |
|------|-------|---------|
| `commands/init_handler.py` | 260–261 | `/init` command: forces auto-approve temporarily |
| `commands/init_renderer.py` | 203–204 | Init rendering: forces auto-approve temporarily |
| `commands/ralph_handler.py` | 391–392 | Ralph background agent: forces auto-approve temporarily |
| `tui/app.py` | 1966–1967 | `/init` in TUI: forces auto-approve temporarily |
| `tui/app.py` | 3892–3893, 4525–4557 | `_run_auto_init()` in TUI: forces auto-approve |
| `tui/app.py` | 4624–4625 | `auto_improve` feature: forces auto-approve |

### 4G. Summary: No Approval Is Possible Over Remote Bridges

The design is clear: **when a user is connected via Discord or Telegram, all tools are
automatically approved** without any interactive prompt. The system saves the previous
auto-approve state and restores it when the bridge stops. There is no remote-specific
approval UI or fallback mechanism for inline decision-making via chat messages.

---

## 5. APIs and Interfaces

### 5A. Core Approval Functions

| Function | Location | Signature | Returns |
|----------|----------|-----------|---------|
| `get_interrupt_configs()` | `hitl/interrupts.py:357` | `() -> dict[str, InterruptOnConfig]` | Dict of tool-name → {allowed_decisions, description, args_schema} |
| `_format_interrupt_description()` | `hitl/interrupts.py:302` | `(ToolCall, AgentState, Runtime) -> str` | Human-readable description for the approval prompt |
| `process_hitl_approval()` | `ui/hitl_approval.py:76` | `(hitl_request, session_state, assistant_id, backend, spinner_active, status, dbg_func) -> tuple[list, bool, bool]` | (decisions, any_rejected, spinner_active) |
| `check_plan_mode_blocked()` | `ui/hitl_approval.py:28` | `(hitl_request, plan_mode_enabled, dbg_func) -> tuple[bool, dict\|None]` | (is_blocked, rejection_response) |
| `prompt_for_batch_approval()` | `ui/tool_approval.py:26` | `(action_requests: list[ActionRequest], assistant_id) -> list[Decision\|dict]` | List of decisions (Approve/Reject/auto_approve_all) |
| `prompt_for_tool_approval()` | `ui/tool_approval.py:146` | `(action_request: ActionRequest, assistant_id) -> Decision\|dict` | Single decision |
| `build_approval_preview()` | `file_ops.py:261` | `(tool_name, args, assistant_id) -> ApprovalPreview\|None` | Preview with title, details, diff, error |
| `build_hitl_response()` | `ui/hitl_approval.py:163` | `(interrupt_id, decisions, response, approved, mode) -> dict` | HITL response dict for resuming |

### 5B. Plan Approval Functions

| Function | Location | Signature | Returns |
|----------|----------|-----------|---------|
| `handle_plan_approval_interrupt()` | `ui/interrupt_handlers.py:292` | `(current_todos, session_state, spinner_active, status, dbg_func, interrupt_payload) -> tuple[dict, bool, bool, dict]` | (hitl_response, interrupt_occurred, spinner_active, state_update) |
| `handle_plan_approval()` | `commands/plan_handler.py:280` | `(agent, session_state, plan_content) -> bool` | True if approved |
| `prompt_for_plan_approval()` | `ui/question_prompt.py:264` | `(todos, plan_summary) -> PlanApprovalResult` | {approved, action, feedback} |
| `resolve_plan_content()` | `ui/interrupt_handlers.py:124` | `(current_todos, session_state, dbg_func, backend, inline_plan) -> tuple[str\|None, Path\|None]` | (plan_content, plan_path) |
| `render_plan_content()` | `ui/interrupt_handlers.py:267` | `(plan_content, max_lines) -> None` | Prints to console |
| `exit_plan_mode()` (tool) | `tools/plan_mode_tools.py:120` | `(plan: str) -> str` | "Plan approved..." or "Plan rejected..." |

### 5B. Path Approval Classes/Functions

| Name | Location | Signature / Description |
|------|----------|------------------------|
| `PathApprovalManager` | `path_approval.py:14` | Class — manages `~/.nova/approved_paths.json` |
| `is_path_approved(path)` | `path_approval.py:102` | `(Path) -> bool` — O(1) exact + O(depth) prefix check |
| `approve_path(path, recursive)` | `path_approval.py:131` | `(Path, bool) -> None` — saves to JSON |
| `revoke_path(path)` | `path_approval.py:148` | `(Path) -> bool` — removes from JSON |
| `list_approved_paths()` | `path_approval.py:167` | `() -> dict` — returns all approved paths |
| `prompt_for_approval(path)` | `path_approval.py:175` | `(Path) -> bool` — interactive Rich panel |
| `check_path_approval(path)` | `path_approval.py:258` | `(Path\|None) -> bool` — convenience wrapper |

### 5C. Middleware Classes

| Class | Location | Method | Description |
|-------|----------|--------|-------------|
| `SecurityMiddleware` | `security/middleware.py:49` | `awrap_tool_call(request, handler)` | Screens URL args for deceptive Unicode (warn + sanitize) |
| `PlanModeMiddleware` | `agents/plan_agent/plan_mode_middleware.py:18` | `awrap_tool_call(request, handler)` | Blocks/restricts tools during plan mode |

### 5D. Security Validator Functions

| Function | Location | Signature | Returns |
|----------|----------|-----------|---------|
| `validate_url_for_fetch()` | `security/validator.py:28` | `(url, *, show_warnings) -> tuple[bool, str]` | (is_safe, sanitized_url_or_error) |
| `validate_tool_arguments()` | `security/validator.py:63` | `(args) -> dict[str, Any]` | Sanitized args dict |
| `validate_user_input()` | `security/validator.py:117` | `(text, *, show_warnings) -> tuple[bool, str]` | (is_safe, sanitized_text) |
| `display_security_warning()` | `security/validator.py:145` | `(title, message, details) -> None` | Prints warning to console |

### 5E. Event/UI Types

| Type | Location | Fields |
|------|----------|--------|
| `InterruptSpec` | `hitl/interrupts.py:53` | `fields: list[tuple[str, FieldSpec]]`, `static_lines`, `warnings` |
| `FieldSpec` | `hitl/interrupts.py:36` | `label`, `truncate`, `transform`, `default_display` |
| `InterruptRequest` | `ui_events.py:157` | `kind: str`, `payload: Any`, `future: asyncio.Future` |
| `ApprovalPreview` | `file_ops.py` (dataclass) | `title`, `details`, `diff`, `diff_title`, `error` |
| `PlanApprovalResult` | `ui/question_prompt.py:259` | `approved: bool`, `action: str`, `feedback: str` |
| `RemoteBridgeState` | `states/slices/remote_bridge.py:14` | `_pre_remote_auto_approve`, queue, lock, manager |

### 5F. Decision Types (from LangChain)

| Type | Usage |
|------|-------|
| `ApproveDecision` | `{"type": "approve"}` — imported from `langchain.agents.middleware.human_in_the_loop` |
| `RejectDecision` | `{"type": "reject", "message": "..."}` — same import |
| `auto_approve_all` (custom dict) | `{"type": "auto_approve_all"}` — special marker to toggle auto-approve mode |

---

## 6. Key Architectural Observations

1. **Two-layer defense for plan mode**: Plan mode uses BOTH middleware-level blocking
   (`PlanModeMiddleware` in the middleware stack) AND interrupt-level rejection
   (`check_plan_mode_blocked` in `process_hitl_approval`). The middleware catches
   tools that bypass the interrupt system, while the HITL handler catches tools that
   do trigger interrupts.

2. **Single source of truth for blocked tools**: `config/plan_mode.py` defines
   `BLOCKED_TOOLS` and `RESTRICTED_WRITE_TOOLS` as a `frozenset`, imported by both
   the middleware and the HITL approval handler.

3. **Subagents run unattended**: `agents/core_agent.py` lines 1046-1066 explicitly
   clears `interrupt_on` for all declarative subagents and gives them
   `ModelRetryMiddleware`. Nested HITL interrupts from subagents would crash the
   turn (they surface as `GraphInterrupt` exceptions, not `__interrupt__` events).

4. **All remote-bridge approvals are auto-approved**: The design intentionally skips
   any approval prompts when the user is connected via Discord/Telegram, saving and
   restoring the prior auto-approve state.

5. **`auto_approve` is a session-level toggle**: Stored in `UISettings.auto_approve`
   (`states/slices/ui_settings.py:22`), accessible via `SessionState.auto_approve`
   property (`states/Session.py:97-102`). It can be toggled:
   - By the user via the approval menu ("Auto-accept all going forward")
   - By `/remote start` (forced on)
   - By `/auto-approve` command
   - By plan approval "Auto-execute" option (temporarily)
   - By background tasks like `/init`, `/ralph` (temporarily)
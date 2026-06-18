# Loop Engineering — Phased Implementation Plan

## Executive Summary

This plan adds five "Loop Engineering" enhancements to Nova-Code CLI across four phases. The phasing respects architectural dependencies: Phase 1 lays the data-reading foundation (threshold tuning) so later phases consume accurate signals; Phase 2 adds in-turn verification (Loop 2), which requires no new persistent state; Phase 3 adds the external ingress infrastructure (cron + webhooks) that share the same queue; Phase 4 adds prompt hill-climbing (Loop 4 upgrade), the riskiest enhancement, last.

---

## Phase 0 — Pre-flight: Store Schema & Conventions

Before any feature work, establish two conventions that all five enhancements share.

### 0.1 Durable Store Namespaces

Add the following new namespaces alongside the existing `("nova", …)` keys in `store.db`. Document them in the store module's module-level docstring:

| Namespace | Purpose |
|---|---|
| `("nova", "harness_config")` | Tuned threshold values written by Enhancement 4's auto-tuner |
| `("nova", "prompt_versions")` | Versioned Jinja template snapshots (Enhancement 2) |
| `("nova", "prompt_ab_log")` | Per-run quality scores for A/B comparison (Enhancement 2) |
| `("nova", "cron_schedules")` | Serialized cron job definitions (Enhancement 3) |
| `("nova", "webhook_config")` | Webhook secrets and allowlists (Enhancement 5) |
| `("nova", "verification_log")` | Inline verifier retry outcomes (Enhancement 1) |

No migration needed — the `DualModeStore` creates entries lazily.

### 0.2 Config Constants Module

Create `novacode_cli/hermes/config.py` as the single source of truth for all numeric thresholds:

- `_FAILURE_BURST = 3` (migrated from `review.py`)
- `_REVIEW_THRESHOLD_DEFAULT = 10` (migrated from `middleware.py`)
- `INLINE_VERIFIER_MAX_RETRIES = 3` (new)
- `PROMPT_AB_MIN_RUNS = 20` (new)
- `CRON_MAX_CONCURRENT = 3` (new)

### 0.3 Event Types

Register new event type strings in `novacode_cli/events.py` module docstring:
- `nova_verification_retry`
- `nova_verification_pass`
- `nova_verification_fail`
- `nova_prompt_evolved`
- `nova_threshold_tuned`
- `nova_cron_fired`
- `nova_webhook_received`

**Files touched in Phase 0:**
- `novacode_cli/memory/store.py` (docstring update)
- `novacode_cli/hermes/config.py` (new file)
- `novacode_cli/events.py` (docstring update)

---

## Phase 1 — Enhancement 4: Middleware Threshold Auto-Tuner

**Why first:** All other enhancements benefit from accurate thresholds. Entirely additive (a new background task) with zero runtime-path risk.

### 1.1 New File: `novacode_cli/hermes/tuner.py`

`ThresholdTuner` class with a single public coroutine `run_tuning_pass(store)`. It:

1. Reads `("nova", "tool_stats")` and `("nova", "reviews")` from the store.
2. Computes two metrics:
   - **Review frequency**: average tool calls between consecutive reviews — if consistently below `0.7 × threshold`, the threshold is too loose; above `1.5 × threshold`, too tight.
   - **Failure burst rate**: what fraction of reviews were triggered by `_FAILURE_BURST` — if dominant, `_FAILURE_BURST` should drop; if never triggered, it should rise.
3. Proposes new values with damping (`new = 0.8 × old + 0.2 × suggested`) to prevent oscillation.
4. Writes to `("nova", "harness_config")` key `"thresholds"` as `{"review_threshold": int, "failure_burst": int, "tuned_at": float, "basis_reviews": int}`.
5. Emits `nova_threshold_tuned` event via `nova_event_log`.

Hard safety floors: `review_threshold >= 5`, `failure_burst >= 2`.
Hard ceiling: `review_threshold <= 50`, `failure_burst <= 10`.

### 1.2 Modify `novacode_cli/hermes/review.py`

`ReviewRunner.__init__` gains `_load_thresholds_from_store()` — an async helper called lazily on first `should_review()` invocation. Reads `("nova", "harness_config")` → `"thresholds"` and overrides hardcoded constants with instance variables `self._failure_burst` and `self._review_threshold`. Falls back to `config.py` defaults when the key is absent.

### 1.3 Modify `novacode_cli/hermes/skill_manager.py`

`SkillManager.maybe_curate()` also calls `ThresholdTuner.run_tuning_pass(self._store)` when `basis_reviews >= 10`. Runs as a fire-and-forget task via `self.spawn_task(...)`.

### 1.4 Acceptance Criteria
- `("nova", "harness_config")` key `"thresholds"` is written after the 10th review.
- `ReviewRunner` reads thresholds from store on first trigger, falling back to defaults if absent.
- Unit test `tests/test_hermes/test_tuner.py`: feed synthetic `tool_stats` + `reviews`, assert written thresholds are within floor/ceiling bounds.

---

## Phase 2 — Enhancement 1: Inline Verification Loop

**Why second:** No external infrastructure needed. Wraps `iterate_agent_events` from outside. Reuses the OOB model-call pattern from `ReviewRunner`.

### 2.1 New File: `novacode_cli/hermes/verifier.py`

```python
@dataclass
class VerifierVerdict:
    passed: bool
    score: float        # 0.0–1.0
    feedback: str       # injected as retry prompt
    checks: list[str]

class InlineVerifier:
    async def grade(self, task: str, agent_output: str, file_ops: list[FileOp]) -> VerifierVerdict: ...
    async def build_rubric(self, task: str) -> str: ...
```

`grade()` runs an OOB model call tagged `nova_oob=True` checking:
- Were all files mentioned in the task actually created/modified? (checks `file_ops`)
- Did any shell tool calls end with non-zero exit? (checks tool history)
- Is the final assistant message semantically responsive to the task?

Outcomes logged to `("nova", "verification_log")` for the threshold tuner to consume.

### 2.2 New Jinja Template: `novacode_cli/prompts/nova_verify.jinja`

Instructs the model to respond with structured XML:
```xml
<verdict>
  <passed>true|false</passed>
  <score>0.0-1.0</score>
  <feedback>What the agent should fix and how.</feedback>
  <checks>
    <check name="files_written" result="pass|fail"/>
    <check name="no_shell_errors" result="pass|fail"/>
    <check name="responsive" result="pass|fail"/>
  </checks>
</verdict>
```

### 2.3 New File: `novacode_cli/core/verification_loop.py`

`run_with_verification(...)` — async generator that:

1. Calls `iterate_agent_events(...)` and yields all events immediately.
2. On `ev.Done`: extracts full assistant text and `FileOp` list from collected events.
3. Calls `verifier.grade(...)` OOB.
4. If verdict passes or retries exhausted: yields `ev.Done` and returns.
5. If verdict fails and retries remain: emits a `nova_verification_retry` event via `nova_event_log` with the feedback summary, then calls `iterate_agent_events` again with a synthesized retry prompt: `f"[VERIFICATION FEEDBACK] {verdict.feedback}\n\nOriginal task: {user_input}"`.

Hard cap at `INLINE_VERIFIER_MAX_RETRIES` from `hermes/config.py`.

### 2.4 Wire Up: `novacode_cli/ui/execution.py`

Add `verify: bool = False` parameter to `execute_task()`. When `True`, call `run_with_verification(...)` instead of `iterate_agent_events(...)` directly. Default `False` — no breaking change for existing callers. The remote processor and TUI can opt in via session config or a `/verify on` command.

**No changes to `iterate_agent_events` itself.**

### 2.5 Acceptance Criteria
- `tests/test_hermes/test_verifier.py`: mock OOB model returning a fail verdict → retry prompt injected, retry count increments; pass verdict → `Done` yielded immediately.
- The `nova_oob` tag on the grader call prevents its output appearing as an assistant message in either UI.

---

## Phase 3 — Enhancements 3 + 5: Cron Triggers + Webhook Ingress

**Why together:** Both share the same `asyncio.Queue[RemoteMessage]` used by Discord/Telegram bridges. Both are "sources that push `RemoteMessage` onto the queue". Can be built in parallel within the phase.

### 3a — Enhancement 3: Cron/Heartbeat Scheduler

#### New File: `novacode_cli/remote/scheduler.py`

```python
class CronScheduler:
    def __init__(self, queue: asyncio.Queue[RemoteMessage]) -> None: ...
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def add_job(self, cron_expr: str, task: str, *, job_id: str | None = None) -> str: ...
    async def remove_job(self, job_id: str) -> bool: ...
    async def list_jobs(self) -> list[dict]: ...
    async def _tick(self) -> None: ...
```

Uses a minimal in-house cron-expression parser (avoid new dependency). When a scheduled time arrives, constructs `RemoteMessage(platform=RemotePlatform.CRON, ...)` and puts it on the queue. Job definitions persist to `("nova", "cron_schedules")` and survive restarts.

#### Modify `novacode_cli/remote/bridge.py`

Add `RemotePlatform.CRON = "cron"` to the enum. Add `CronScheduler` management to `RemoteBridgeManager`.

#### New CLI Command: `/cron`

Handler at `novacode_cli/commands/cron_handler.py`:
- `/cron add "0 9 * * *" "review project state"`
- `/cron list`
- `/cron remove <job_id>`
- `/cron now "check CI status"` — one-off immediate enqueue

#### Wire into `main.py`

```python
cron_scheduler = CronScheduler(session_state._remote_message_queue)
_cron_task = asyncio.create_task(cron_scheduler.start(), name="cron-scheduler")
```

Cron messages flow through `_remote_processor_wrapper` unchanged. Reply functions are no-ops for `CRON` platform.

### 3b — Enhancement 5: Webhook Ingress

#### New File: `novacode_cli/remote/webhook_server.py`

`WebhookServer` using `aiohttp.web` (already a transitive dependency):

```python
class WebhookServer:
    def __init__(self, queue: asyncio.Queue[RemoteMessage], *, host: str = "127.0.0.1", port: int = 9876, store: BaseStore) -> None: ...
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def register_source(self, source: str, secret: str, *, event_types: list[str]) -> None: ...
```

Default host is `127.0.0.1` — users must explicitly opt into public exposure.

#### New File: `novacode_cli/remote/webhook_adapters.py`

Pure functions, one per platform:
- `parse_github(headers, body, secret) -> RemoteMessage | None` — verifies `X-Hub-Signature-256` (HMAC-SHA256)
- `parse_linear(headers, body, secret) -> RemoteMessage | None` — verifies `linear-signature`
- `parse_generic(headers, body, secret) -> RemoteMessage | None` — requires `X-Nova-Secret` header + `{"task": "..."}` body

Security: signatures via `hmac.compare_digest` (timing-safe). Secrets stored in `("nova", "webhook_config")`. Incoming task text capped at 2000 chars, no embedded null bytes.

#### New CLI Command: `/webhook`

Handler at `novacode_cli/commands/webhook_handler.py`:
- `/webhook start [--port 9876]`
- `/webhook stop`
- `/webhook register github --secret <s> --events push,pull_request`
- `/webhook status`

Server started lazily on `/webhook start`, not at CLI boot.

### 3.3 Acceptance Criteria
- `tests/test_remote_cron.py`: `* * * * *` expression fires within 61 seconds; persisted jobs survive simulated restart (mock store).
- `tests/test_webhook_server.py`: valid GitHub `push` payload with correct HMAC → `RemoteMessage` on queue; invalid signature → no enqueue, no exception.
- `RemotePlatform.CRON` messages flow through existing `remote_message_processor` without modification.

---

## Phase 4 — Enhancement 2: Prompt-Template Hill Climbing

**Why last:** Most complex. Requires operational data from prior phases (review patterns from the tuner, quality scores from the verifier). Largest surface area. Demands robust rollback before touching production templates.

### 4.1 New File: `novacode_cli/hermes/prompt_evolution.py`

```python
class PromptEvolutionEngine:
    def __init__(self, store: BaseStore, *, prompts_dir: Path, enabled: bool = True) -> None: ...
    async def maybe_evolve_prompt(self, template_name: str, pattern_evidence: str) -> None: ...
    async def run_evolution(self, template_name: str, evidence: str) -> None: ...
    async def _apply_candidate(self, template_name: str, candidate: str) -> str: ...
    async def _rollback(self, template_name: str, version_id: str) -> None: ...
    async def record_run_quality(self, thread_id: str, score: float) -> None: ...
    async def _check_ab_result(self, template_name: str) -> str | None: ...
```

#### Pattern Detection

Modify `ReviewRunner._apply_review_content()` to detect persistent patterns via a new optional XML tag in review output:
```xml
<prompt_issue template="core_agent_system">description of recurring misunderstanding</prompt_issue>
```

Add a `_detect_persistent_patterns()` helper: if the same `template` pattern appears in >= 3 of the last 5 reviews, it is "persistent" and triggers `PromptEvolutionEngine.maybe_evolve_prompt()`.

Update `prompts/nova_review.jinja` with a `### 5. Prompt Issues` section that instructs the model to emit `<prompt_issue>` blocks when it notices the agent consistently misunderstanding a class of task.

#### Template Versioning

Snapshots stored in `~/.nova/prompt_history/<template_name>/`:
- Per-version files: `<version_id>.jinja`
- Manifest: `manifest.json`
- Active candidate: `candidate.jinja`

The `("nova", "prompt_versions")` store key tracks `{"active": version_id, "candidate": version_id | None}`.

`_apply_candidate()` writes to `~/.nova/prompt_history/<name>/candidate.jinja` — it does NOT overwrite the package `.jinja` file. Override files are entirely user-space.

#### A/B Routing in `novacode_cli/prompts/__init__.py`

```python
_PROMPT_HISTORY_DIR = Path.home() / ".nova" / "prompt_history"

def render_template(name: str, **kwargs: Any) -> str:
    override = _PROMPT_HISTORY_DIR / name.replace(".jinja", "") / "candidate.jinja"
    if override.exists() and _should_use_candidate(name):
        return _candidate_env.get_template(str(override)).render(**kwargs)
    return _env.get_template(name).render(**kwargs)
```

`_candidate_env` is a SEPARATE `Environment` instance to prevent cross-contamination.

50% of turns (seeded by `thread_id` for determinism within a thread) use the candidate. After `PROMPT_AB_MIN_RUNS` (20) runs per variant:
- Candidate better by >5%: promote (overwrite production override).
- No significant improvement after 50 runs: discard candidate.

Quality signal source: verification pass rate from `("nova", "verification_log")` (Phase 2 output) — avoids recursive LLM-grading.

#### OOB Evolution Call

`run_evolution()` issues an OOB model call (`nova_oob=True`) using a new `prompts/prompt_evolution.jinja`. Instructs the model to produce a targeted diff of the template and return the full new body in `<new_template>...</new_template>`. Stateless — no agent conversation context, only current template text + evidence.

### 4.2 New CLI Command: `/prompt`

Handler at `novacode_cli/commands/prompt_handler.py`:
- `/prompt status` — show active candidates + A/B scores
- `/prompt rollback <name>` — restore previous version
- `/prompt accept <name>` — force-promote candidate
- `/prompt reject <name>` — discard candidate

### 4.3 Acceptance Criteria
- `tests/test_hermes/test_prompt_evolution.py`: 3 repeated `<prompt_issue>` blocks trigger `maybe_evolve_prompt()`; candidate file appears at expected path; A/B routing routes ~50% of calls to candidate.
- `render_template("core_agent_system.jinja")` still works when no candidate exists.
- `/prompt rollback` restores prior template and removes candidate file.
- No package `.jinja` files are overwritten during tests.

---

## Cross-Cutting Concerns

### Rollback Strategy (per enhancement)

| Enhancement | Rollback |
|---|---|
| Threshold Tuner | Absent `harness_config` key → `ReviewRunner` falls back to `config.py` defaults |
| Inline Verifier | `verify=False` default in `execute_task()` — existing callers unchanged |
| Cron | Never started unless user runs `/cron add` |
| Webhook | Never started unless user runs `/webhook start` |
| Prompt Evolution | Override files in `~/.nova/prompt_history/`; `/prompt rollback` restores instantly; package `.jinja` files never touched |

### Middleware Contract

Every new class implementing `AgentMiddleware` must provide both sync and async pairs:
- `wrap_model_call` / `awrap_model_call`
- `wrap_tool_call` / `awrap_tool_call`
- `before_agent` / `abefore_agent`
- `after_agent` / `aafter_agent`

`InlineVerifier` does NOT implement `AgentMiddleware` — it wraps at the generator level, sidestepping this requirement entirely.

### nova_event_log Convention

All new modules surface notices via `nova_event_log.append(...)` + `cap_event_log()`. Never `console.print` from inside the agent loop or any middleware. Follow the `_emit_event()` pattern from `hermes/review.py`.

### Subagent Safety

`_harden_subagent_specs` in `core_agent.py` requires no changes — none of the new enhancements add middleware to the main stack.

### Ruff Compliance

All new files must pass `ruff check --select ALL`. Key rules: `ANN` (type annotations), `BLE001` (bare except with `# noqa`), `D` (docstrings), `C901`/`PLR0912` (complexity). Follow `SkillManager.spawn_task` as the model for fire-and-forget `asyncio.create_task` patterns.

---

## Risk Flags

**Phase 2 — Verifier retry loop.** Hard cap at `max_retries` is the primary guard. The `[VERIFICATION FEEDBACK]` prefix in the retry prompt signals self-correction context, not a new user task — this wording is load-bearing.

**Phase 3 — Queue double-consumption in TUI mode.** The existing `if not getattr(session_state, "use_tui", False)` gate in `main.py` controls which consumer drains the queue. Cron and webhook sources must respect the same gate — audit `_remote_processor_wrapper` and the new startup paths before merging.

**Phase 4 — Jinja `FileSystemLoader` caching.** The `_candidate_env` must be a SEPARATE `Environment` instance from `_env`. Any mistake here silently serves the wrong template to all renders.

**Phase 4 — A/B scoring signal quality.** Quality signal MUST come from an objective observable (verification pass rate from Phase 2's `verification_log`) — not another LLM call, which would create a recursive quality-assessment loop.

**Phase 1 — Tuner overfitting.** A session with unusual tool patterns (all-trivial tools, long exploration) could push thresholds in the wrong direction. Damping factor + minimum basis (`>= 10 reviews`) + hard floors/ceilings partially mitigate. The tuner should also skip tuning if `basis_reviews < 10`.

---

## Implementation Sequencing Summary

| Phase | Enhancements | Key New Files | Key Modified Files | Complexity |
|---|---|---|---|---|
| 0 | Foundation | `hermes/config.py` | `memory/store.py`, `events.py` | Low |
| 1 | Threshold Tuner | `hermes/tuner.py` | `hermes/review.py`, `hermes/skill_manager.py` | Low-Med |
| 2 | Inline Verifier | `hermes/verifier.py`, `core/verification_loop.py`, `prompts/nova_verify.jinja` | `ui/execution.py` | Medium |
| 3a | Cron Scheduler | `remote/scheduler.py`, `commands/cron_handler.py` | `remote/bridge.py`, `main.py` | Medium |
| 3b | Webhook Ingress | `remote/webhook_server.py`, `remote/webhook_adapters.py`, `commands/webhook_handler.py` | `main.py` | Medium |
| 4 | Prompt Evolution | `hermes/prompt_evolution.py`, `prompts/prompt_evolution.jinja`, `commands/prompt_handler.py` | `prompts/__init__.py`, `hermes/review.py`, `prompts/nova_review.jinja` | High |

### Critical Reference Files

- `novacode_cli/hermes/review.py` — threshold-reading seam (Phase 1), pattern-detection hook (Phase 4), OOB model-call pattern (Phase 2 replicates this)
- `novacode_cli/core/agent_loop.py` — canonical async generator Phase 2 wraps; `_drain_nova_events()` and `nova_oob` filter are essential reference patterns
- `novacode_cli/remote/bridge.py` — `RemoteBridgeManager` and `RemoteMessage` dataclass Phase 3 must produce messages into
- `novacode_cli/main.py` — where all new background tasks start and where `execute_task` is called with the new `verify=` flag
- `novacode_cli/prompts/__init__.py` — `render_template()` that Phase 4 extends with candidate-override lookup

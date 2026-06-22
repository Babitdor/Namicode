# Design — Success-grounded "good habits" learning

**Date:** 2026-06-22
**Status:** Approved (design); pending implementation plan
**Area:** Hermes autonomous learning
**Approach:** 1 (piggyback the existing review; new injected `HABITS.md`)

## 1. Goal & scope

Hermes currently learns almost entirely from **failures**: reviews trigger on
failure bursts or substantive windows, and the strongest nudge to capture a
skill is literally "you recovered from an error." There is no path that says
"you did this *well* — capture the good habit behind it."

This feature adds a **success path**: when Nova does substantive work *cleanly*,
an out-of-band review distills a reusable **good habit** and reinforces it on
future runs by injecting it into the system prompt.

It is built entirely on existing machinery — the out-of-band review's single
LLM call, the semantic memory writers, and `AgentMemoryMiddleware` injection —
so it adds **no new LLM calls** and minimal new code.

Out of scope (explicitly not built here): a user-marked `/good` override, a
dedicated separate success-review with its own model call (Approach 2),
inline-verifier-verdict gating, exemplar/code-snippet storage, and cross-agent
habit sharing.

## 2. Decisions locked during brainstorming

| Decision | Choice |
|---|---|
| How a "success" is detected | **Automatic, signal-based** — derived from the tracker window the review already has. |
| What a remembered success is | **A distilled "good habit"** (short, general principle) stored in `HABITS.md` and injected each run — distinct from skills (procedures) and lessons (facts). |
| Where capture happens | **Piggyback the existing periodic review** (Approach 1) — no new LLM call. |
| Detection signal source | **Zero-failure substantive window** (no inline-verifier dependency, which is opt-in and would need thread-id plumbing). |
| Trigger | **Include a bounded clean-win early trigger** so a fresh win is captured promptly. |

## 3. Current system (context)

- `ReviewRunner` (`hermes/review.py`) runs an out-of-band `model.ainvoke` when
  `should_review()` is true (failure burst / substantive threshold / hard cap),
  then `_apply_review_content()` parses the result and persists it.
- `should_review()` already inspects the **tracker window** (calls since the
  last counter reset), computing `failures` and a `substantive` flag using
  `_SUBSTANTIVE_TOOLS` (`write_file`/`edit_file`/`execute`/`run_tests`) and
  `_TRIVIAL_BUILTINS` (read-only browsing).
- The review prompt `prompts/nova_review.jinja` is rendered with signal flags
  such as `recovered_from_error`, and asks the model to emit XML blocks
  (`<user_model>`, `<lesson topic="…">`, `<skill>`).
- `memory_tiers.py` owns the semantic writers: `parse_review_response()`
  extracts the XML blocks; `record_lesson()` / `update_user_model()` write the
  files; `_dedup_against()` dedupes and `compact_memory_file()` enforces
  `MAX_MEMORY_CHARS`.
- `AgentMemoryMiddleware` (`memory/agent_memory.py`) injects the always-on
  memory surface — `~/.nova/<agent>/agent.md` and `memories/INDEX.md` — into the
  system prompt every turn, via the `longterm_memory.jinja` template.

## 4. Detection signal

A **clean win** is defined from the existing tracker window only:

> The window contains substantive work (a `write_file` / `edit_file` /
> `execute` / `run_tests` call, or any non-builtin tool) **and** has **zero
> failed tool calls**.

The window-level check only decides whether to *ask*. The model then
self-assesses whether the work was genuinely habit-worthy, mirroring the
existing discipline that stops it proposing skills for generic read→edit→test
activity. This keeps false positives low without a hard quality gate.

The inline verifier's verdict is intentionally **not** a dependency: it is
opt-in (`verify` flag) so often absent, and reading it in the OOB review would
require thread-id plumbing the review doesn't currently have. It can be added
later as an optional stronger gate.

## 5. Trigger

Add a **clean-win early trigger** to `ReviewRunner.should_review`, mirroring the
existing `failure_burst` early trigger but inverted:

```
clean_win = has_substantive_work and failures == 0 and count >= min_floor
```

where `min_floor = max(3, review_threshold // 2)` (the value already computed in
`should_review`). `has_substantive_work` requires the window to actually
*contain* a substantive tool call — it must not reuse the existing `substantive`
flag, which defaults to `True` for an empty window (a "clean win" with no work
done is meaningless). In practice `count >= min_floor` already guarantees a
non-empty window, but the condition is stated on real tool presence to be
unambiguous. A review fires when any of `hard_cap`, `failure_burst`,
`(reached and substantive)`, **or** `clean_win` holds. It remains bounded by the
existing `just_completed` guard, so it cannot fire on consecutive windows.

`run_review` computes the same `clean_win` boolean from the window it already
fetches and passes it into the template (see §6).

## 6. Capture (reuses the existing OOB review call)

`run_review` passes a new `clean_win` flag into `render_template("nova_review.jinja", …)`
alongside `recovered_from_error`. When `clean_win` is true, the template renders
an additional section:

> **### Did you do something notably well?**
> If this turn used a clean, reusable approach worth repeating — a good fix
> pattern, an elegant simplification, a production-ready practice — capture it as
> a short, general **habit** (not a step-by-step workflow). Emit a `<habit>`
> block with 1–2 bullets. Skip generic edits.

Output format additions (documented in the template's format section): a single
optional `<habit>` block containing bullet lines.

`memory_tiers.parse_review_response()` gains a `<habit>…</habit>` regex (sibling
to the existing `<lesson>` / `<user_model>` parsing) and returns the extracted
habit bullets under a new `"habits"` key in its result dict. Absent block →
empty.

## 7. Storage & dedup

New writer `record_habit(agent_dir, bullets)` in `memory_tiers.py`, modeled on
`record_lesson`:

- Target file: `~/.nova/<agent>/HABITS.md` (created with a default H1 header if
  absent).
- Dedup new bullets against existing content via `_dedup_against`; if all
  duplicates, emit a memory event and return without writing.
- Prepend a timestamped `## Review — <UTC>` section with the new bullets
  (newest-first), matching `record_lesson`'s layout.
- Call `compact_memory_file(HABITS.md)` to enforce `MAX_MEMORY_CHARS`.

`ReviewRunner._apply_review_content` calls `record_habit(self._agent_dir, parsed["habits"])`
when `self._agent_dir` and `parsed["habits"]` are present, alongside the existing
`update_from_review` call.

## 8. Injection (what makes it "learn")

`AgentMemoryMiddleware._load_memory` registers `HABITS.md` as an always-injected
surface (next to `agent.md` and `memories/INDEX.md`), reading it from the same
local-filesystem path resolution used for `agent.md`. The `longterm_memory.jinja`
template renders the habits content under a heading such as
"Good Habits — keep doing these" when present; when the file is missing or
empty, nothing is injected and the prompt is unchanged.

Hot-reload: `HABITS.md` participates in the same change-detection that already
re-reads `agent.md` / `INDEX.md`, so a habit recorded by a review surfaces on
the next turn without a restart.

## 9. Data flow

```
clean substantive turn
  → ReviewRunner.should_review(): clean_win trigger true
  → existing OOB review runs (model.ainvoke) with clean_win=True
  → model emits <habit> block
  → parse_review_response() → parsed["habits"]
  → record_habit(agent_dir, bullets) → HABITS.md (dedup + compact)
  → AgentMemoryMiddleware injects HABITS.md into the system prompt next run
```

## 10. Error handling

All new work runs inside the out-of-band review, which already catches and logs
exceptions and never breaks the agent turn. `record_habit` is best-effort
(matching `record_lesson`): a write failure logs and returns. A missing or empty
`HABITS.md` injects nothing. The clean-win trigger degrades gracefully — if the
window is unavailable, it is simply not treated as a clean win (no false
trigger).

## 11. Testing

- `parse_review_response`: extracts a `<habit>` block's bullets; returns empty
  habits when the block is absent; existing `<lesson>`/`<user_model>` parsing
  unaffected.
- `record_habit`: creates `HABITS.md` with header; appends a timestamped
  section; dedupes identical bullets; compacts when over `MAX_MEMORY_CHARS`
  (tmp_path).
- `should_review`: returns true for a clean substantive window at `min_floor`;
  returns false for a window containing a failure; returns false for an
  all-trivial (read-only) window; `just_completed` still suppresses.
- `nova_review.jinja`: renders the habit section only when `clean_win=True`;
  omits it otherwise.
- `AgentMemoryMiddleware`: injects `HABITS.md` content into the assembled memory
  when the file is present; injects nothing when absent.

## 12. Files touched

- `novacode_cli/hermes/review.py` — `clean_win` computation in `should_review`
  (trigger) and `run_review` (template flag); `record_habit` call in
  `_apply_review_content`.
- `novacode_cli/prompts/nova_review.jinja` — clean-win habit section + output
  format note.
- `novacode_cli/hermes/memory_tiers.py` — `<habit>` parsing in
  `parse_review_response`; new `record_habit` writer.
- `novacode_cli/memory/agent_memory.py` — inject `HABITS.md`.
- `novacode_cli/prompts/longterm_memory.jinja` — render the habits section.
- Tests across the above (new + extended).

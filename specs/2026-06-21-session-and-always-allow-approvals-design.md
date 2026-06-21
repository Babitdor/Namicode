# Design — "Allow for session / Always allow" tool approvals

**Date:** 2026-06-21
**Status:** Approved (design); pending implementation plan
**Area:** Permissions / human-in-the-loop approvals
**Scope tag:** QoL feature P2

## 1. Goal & scope

At any tool-approval prompt, offer two decisions beyond the current
approve / reject / auto-accept:

- **Allow for session** — remember a *generalized* rule in memory so matching
  tool calls stop prompting until Nova exits.
- **Always allow…** — propose a generalized policy rule, let the user
  confirm/edit it and choose **project vs global**, then persist it so matching
  calls never prompt again.

Both reuse the existing risk-tiered `ApprovalPolicy`
(`novacode_cli/security/policy.py`) matching engine and its JSON config format,
so there is a single source of truth for permissions. Built-in `deny` rules can
never be overridden by either decision (see §6).

This is the only feature in scope. Explicitly **out of scope** (separate
candidates, not built here): granular auto-approve modes, a `/permissions`
viewer/editor, a permission audit log, and reject-with-feedback.

## 2. Decisions locked during brainstorming

| Decision | Choice |
|---|---|
| What "always allow" remembers | **Smart generalize + confirm** — Nova derives a sensible rule per tool family and shows it for confirmation/edit before saving. |
| Where a confirmed rule is saved | **Ask each time** — the confirm step always makes the user pick `project` vs `global`; no default highlighted. |
| Implementation strategy | **Approach 1** — extend the existing policy layer (one source of truth) rather than a separate remembered-approvals store. |
| Session-allow confirm | **None** — session allows are ephemeral and low-stakes, so they apply immediately with a one-line notice (no confirm dialog). |

## 3. Current system (context)

- `security/policy.py` resolves every tool call to a tier — `allow` (run
  silently) / `ask` (HITL prompt) / `deny` (hard block). Shell/path/URL tools
  are judged on their arguments via allow/deny regexes and path/domain globs.
  Precedence is **deny → ask → allow → per-tool default**; built-in denies are
  always applied and cannot be loosened by config.
- The policy merges built-in defaults with `~/.nova/approval-policy.json` and an
  optional `<project>/.nova/approval-policy.json`. `get_policy(refresh=True)`
  rebuilds the process-cached policy.
- `ui/hitl_approval.py::evaluate_tool_actions` is the **UI-agnostic gate** in the
  agent loop: it folds plan-mode blocking, session `auto_approve`, and the
  policy into one per-action verdict, returning `approve` / `reject` dicts or
  `None` ("ask the user"). Only `None` actions surface a prompt, so both UIs
  behave identically.
- Two approval renderers consume the prompt:
  - REPL: `ui/tool_approval.py` arrow-menu → returns `ApproveDecision` /
    `RejectDecision` / `{"type": "auto_approve_all"}`.
  - TUI: `tui/app.py::ApprovalModal` (`ModalScreen[str]`) → returns
    `"approve"` / `"auto"` / `"reject"`.

## 4. New components

Three small, focused modules plus one pure glue helper:

- **`security/rule_synthesis.py`** — pure function
  `synthesize_rule(tool_name, args) -> ProposedRule`.
  `ProposedRule(category, value, human, tool_name)` where
  `category ∈ {"shell", "paths", "domains", "tool"}`, `value` is the
  regex/glob/domain/tier string, and `human` is a plain-English summary for the
  confirm UI.
- **`security/session_allow.py`** — `SessionAllowList` process singleton holding
  a list of `ProposedRule` in memory, with `add(rule)` and
  `matches(tool_name, args) -> bool`. It reuses the same regex/glob/host
  matchers the policy uses (shared helpers), so session and persistent rules
  behave identically.
- **`security/policy_writer.py`** —
  `append_rule(rule, *, target, project_root) -> Path`: read the target JSON
  (or `{}`), merge the rule into the correct section (`tools` / `shell.allow` /
  `paths.allow` / `domains.allow`) with de-duplication, write atomically
  (temp + replace, creating `.nova/` if needed), then call
  `get_policy(refresh=True)`. Returns the written path.
- **`security/remember.py`** — pure UI-agnostic glue:
  `apply_remember(kind, action_request, target=None) -> RememberResult`, where
  `kind ∈ {"session", "always"}`. Synthesizes the rule, then either adds it to
  the `SessionAllowList` or writes it via `policy_writer`. Returns a small
  result (rule + written path or `None`) for the UI to display. This keeps both
  front-ends thin and lets the logic be unit-tested without a terminal.

## 5. Rule synthesis (the core)

| Tool family | Input arg | Generalized rule | Example |
|---|---|---|---|
| `shell`, `execute`, `run_tests`, `start_dev_server` | `command` | Anchored regex on the program, plus the subcommand for known multiplexers (`npm`, `yarn`, `pnpm`, `uv`, `git`, `cargo`, `docker`, `make`); bare program otherwise. | `npm run build` → `shell.allow += ^\s*npm\s+run\s+build\b` |
| `write_file`, `edit_file` | `file_path` | Directory glob, virtual `/`-rooted. | `/src/app.py` → `paths.allow += /src/**` |
| `fetch_url` | `url` | Host → domain allow. | `https://docs.python.org/3/…` → `domains.allow += docs.python.org` |
| Other `ask` tools (`write_memory`, …) | — | Tool-tier rule. | `tools.write_memory = "allow"` |

- Command tokens are tokenized (shlex-style) and `re.escape`'d before being
  joined into the anchored regex.
- The confirm step (for "always") shows the exact rule and lets the user **edit**
  it — e.g. narrow `/src/**` to the exact file, or broaden/narrow the regex.
- Session-allow uses the **same** synthesized rule (no edit step).

## 6. Session-allow layer & safety ordering

`evaluate_tool_actions` gains exactly one new check, ordered so it can never
bypass a hard deny:

```
plan-mode blocked?      → reject (unchanged)
session auto_approve?   → approve (unchanged)
policy.evaluate(tool):
    tier == "deny"      → reject        (always wins)
    tier == "allow"     → approve
    tier == "ask"       → SessionAllowList.matches()? approve : ask
```

- **Deny is inviolable.** Session-allow is consulted *only* on the `ask` tier, so
  it cannot loosen a denied call. Persistent "always allow" writes an `allow`
  rule, but the policy's `deny → ask → allow` precedence means a user allow can
  never override a built-in deny (`rm -rf /`, `sudo`, `/etc/**`, SSRF hosts,
  blocked git ops, …).
- Session-allow is in-memory only and disappears when the process exits.

## 7. Prompt + confirm UX

**REPL** (`ui/tool_approval.py`): the menu becomes
`Approve · Reject · Allow for session (s) · Always allow… (!) · Auto-accept all`.
Choosing "Always allow" opens a one-line confirm that prints the proposed rule
and offers `[P]roject  [G]lobal  [E]dit  [C]ancel` (no default highlighted, per
the locked decision). New decision markers returned upward:
`{"type": "allow_session"}` and `{"type": "allow_always"}`.

**TUI** (`tui/app.py`): `ApprovalModal` gains options `Allow for session (s)` and
`Always allow… (!)`. Selecting "Always allow" pushes a new `RememberRuleModal`
with an editable, prefilled `Input` (the proposed rule) and `Project` / `Global`
/ `Cancel` buttons.

In both UIs the "remember" is a **side-effect**: after performing it (via
`apply_remember`), the current action still resolves to a plain `approve` that
LangGraph receives. A one-line confirmation is shown — for session,
`✓ Allowed \`npm run build\` for this session`; for always,
`✓ Saved to <path>`.

## 8. Data flow

1. Agent emits a tool call → `evaluate_tool_actions` resolves it silently if a
   session/persistent rule now matches; otherwise it surfaces a prompt.
2. User picks "Allow for session" → `apply_remember("session", …)` adds the rule
   to `SessionAllowList`. User picks "Always allow" → confirm → edit/target →
   `apply_remember("always", …, target)` writes the file and refreshes the
   policy cache.
3. The current call resolves as `approve`.
4. The **next** matching call is resolved silently by the gate — no prompt.

## 9. Error handling

- **Config write failure:** show a notice and keep the rule in the
  `SessionAllowList` so the current session still benefits; never crash the turn.
- **Synthesis failure** (unexpected/missing args): fall back to approve-once with
  a "couldn't generalize — approved this call only" notice.
- **Policy refresh failure:** logged to file; the just-added session rule keeps
  working regardless.
- All config reads/writes are best-effort and must never raise into the agent
  loop (matches existing policy-loading conventions).

## 10. Testing

- `synthesize_rule` for each tool family: shell program/subcommand extraction
  (multiplexer vs bare program), metacharacter escaping, path → directory glob,
  url → domain, fallback → tool-tier, and empty/missing-arg edge cases.
- `append_rule`: merges and de-dups into project **and** global JSON under
  `tmp_path`; after `get_policy(refresh=True)` the matching call evaluates to
  `allow`.
- `SessionAllowList.matches`: positive/negative matches; and **a denied command
  is still rejected** even with a broad session/always rule present.
- `evaluate_tool_actions`: returns `approve` once a session rule is added;
  returns `reject` for denied calls regardless of any remember rule.
- `apply_remember`: pure-helper tests (session vs always, target selection) with
  no terminal involved.

## 11. Files touched

**New:** `security/rule_synthesis.py`, `security/session_allow.py`,
`security/policy_writer.py`, `security/remember.py` (+ tests under `tests/`).

**Modified:** `ui/hitl_approval.py` (session-allow check in the gate; interpret
the new decision markers), `ui/tool_approval.py` (REPL menu + confirm),
`tui/app.py` (`ApprovalModal` options + new `RememberRuleModal` + wiring).

## 12. Out of scope (YAGNI)

Granular auto-approve modes (P3), the `/permissions` viewer/editor (P1), a
permission audit log (P4), and reject-with-feedback. P2 only.

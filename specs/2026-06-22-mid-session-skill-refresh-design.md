# Design — Mid-session skill refresh

**Date:** 2026-06-22
**Status:** Approved (design); pending implementation plan
**Area:** Skills / agent middleware

## 1. Goal & scope

Close the within-session learning loop. When a skill is **created or changed
mid-session** — by the agent's `skill_manage` tool or by a Hermes review
emitting a `<skill>` block — the agent's injected **Available Skills** list
should refresh on its next turn so it can actually *use* what it just learned.

Today it cannot: deepagents' `SkillsMiddleware.before_agent` loads the skills
list **once per session** and caches it in the agent state key `skills_metadata`
(every later turn sees the key present and skips reloading). Nova never
invalidates that cache (`skills_metadata` is referenced nowhere in the
codebase), so a freshly-created skill is invisible to the agent until a restart.

Out of scope (explicitly not built): refreshing subagent skill lists; a
`/skills` usage view; reinforcing skill *usage* in the prompt; any change to how
skills are created, tracked, or stored.

## 2. Background (verified)

- `create_deep_agent(..., skills=skill_sources, ...)` (deepagents) appends
  `SkillsMiddleware(backend=backend, sources=skills)` to the agent's middleware.
- `SkillsMiddleware.before_agent` / `abefore_agent`: *"Loads skills once per
  session... If `skills_metadata` is already present in state... the load is
  skipped."* `wrap_model_call` injects the **Available Skills** list and usage
  guidance into the system prompt from `state["skills_metadata"]`.
- Nova builds the agent in `core_agent.py:create_agent_with_config`, where the
  `composite_backend`, the virtual `skill_sources` (`/skills/`,
  `/claude-skills/`, `/project-skills-N/`), and the **real** skill directories
  (`skills_dir`, `claude_skills_dir`, `project_skills_dirs`) are all in scope.
- The agent runs via `ainvoke`/`astream`, so the **async** middleware hooks fire
  (`abefore_agent`, `awrap_model_call`).

## 3. Component — `RefreshingSkillsMiddleware(SkillsMiddleware)`

A thin subclass in a new module `novacode_cli/skills/refreshing_middleware.py`.
It overrides **only** `before_agent` and `abefore_agent`; all other behaviour
(listing, parsing, error handling, the `wrap_model_call` prompt injection) is
inherited from `SkillsMiddleware` unchanged.

Constructor:

```python
RefreshingSkillsMiddleware(
    *,
    backend,                 # same CompositeBackend the default middleware uses
    sources,                 # same virtual sources (list[str] / (path, label))
    watch_dirs: list[Path],  # real filesystem skill dirs, for change detection
)
```

`backend` and `sources` are forwarded to `super().__init__`. `watch_dirs` is the
new, refresh-specific input.

## 4. Change signature

Each turn, compute a cheap signature over `watch_dirs`:

- For each directory in `watch_dirs`, glob `*/SKILL.md` and collect
  `(str(path), mtime)` pairs.
- The signature is the `frozenset` of those pairs across all `watch_dirs`.

Compare against the last-seen signature stored on the instance
(`self._last_signature`, initially a sentinel meaning "never loaded"). A
difference (including the first call) means **refresh**. This catches **add /
remove / rename / edit** — an in-place description edit changes that file's
mtime, so the list stays accurate. Cost is one glob per `watch_dir` plus a
`stat` per `SKILL.md` per turn — bounded by the skill count.

`_skills_changed()` updates `self._last_signature` as a side effect and returns
whether it changed.

`_last_signature` lives on the (process-wide, single) middleware instance, not in
per-thread state. For Nova's single-user CLI this is fine: the first turn to
observe a change refreshes its own thread's `skills_metadata`. The only edge case
is two concurrent threads sharing the agent (e.g. a background `/ralph` run) —
whichever thread observes the change first advances `_last_signature`, so the
other keeps its cached list until *its own* next observed change. Accepted; a
per-thread signature would add state-schema surface for no real single-user
benefit (YAGNI).

## 5. Force-reload mechanism

deepagents' `before_agent` is: *if `skills_metadata` in state → skip; else load
and return `{skills_metadata: …}`*. The override forces a reload by hiding the
cached key from `super()` when skills changed:

```python
def before_agent(self, state, runtime, config):
    if self._skills_changed():
        state = {k: v for k, v in state.items() if k != "skills_metadata"}
    return super().before_agent(state, runtime, config)
```

Popping the key from a **shallow copy** makes `super()` re-run deepagents' own
load and return a fresh `{skills_metadata: …}` update that overwrites the stale
value in the real state. When nothing changed, control falls straight through to
`super()` unchanged → behaviour identical to today (apart from the cheap
signature check). `abefore_agent` is overridden identically, calling
`await super().abefore_agent(...)`.

## 6. Wiring in `core_agent.py`

In `create_agent_with_config`:

- Pass `skills=None` to `create_deep_agent` so it does **not** append the
  default `SkillsMiddleware`.
- Append our middleware to `agent_middleware`:

```python
watch_dirs = [skills_dir]
if claude_skills_dir.exists():
    watch_dirs.append(claude_skills_dir)
watch_dirs.extend(project_skills_dirs)

agent_middleware.append(
    RefreshingSkillsMiddleware(
        backend=composite_backend,
        sources=skill_sources,
        watch_dirs=watch_dirs,
    )
)
```

All referenced values already exist in that function. The subagent skills path
(deepagents builds a separate `SkillsMiddleware` per subagent) is left unchanged
— out of scope.

## 7. Sync + async

Both `before_agent` and `abefore_agent` are overridden identically (the agent
runs the async path; a sync-only override would silently never fire — the
documented middleware gotcha in CLAUDE.md). `_skills_changed()` is shared sync
code called by both.

## 8. Error handling

`_skills_changed()` is best-effort: any `OSError`/glob failure is caught and
treated as "not changed", deferring to `super()` (current behaviour). The
refresh can never break a turn — worst case it behaves exactly like today
(stale until restart).

## 9. Testing

- `_skills_changed`: returns `False` on the second call with no change; `True`
  after a new `SKILL.md` directory appears; `True` after one is removed; `True`
  after an existing `SKILL.md`'s mtime changes (all under `tmp_path`).
- `before_agent`: with an unchanged signature **and** `skills_metadata` already
  in state → returns `None` (defers, no reload). After a change → returns an
  update whose `skills_metadata` includes the new skill.
- Parity: `RefreshingSkillsMiddleware` on first load (empty state) populates
  `skills_metadata` exactly like the base `SkillsMiddleware`.
- `abefore_agent` mirrors `before_agent` (async test), proving the async path
  refreshes too.

Tests construct the middleware against a `FilesystemBackend` rooted at a
`tmp_path` skills directory (mirroring how `novacode_cli/skills/load.py` builds
backends), so they exercise the real deepagents listing without a full agent.

## 10. Files touched

- New: `novacode_cli/skills/refreshing_middleware.py` (+ tests under `tests/`).
- Modify: `novacode_cli/agents/core_agent.py` — pass `skills=None`, build
  `watch_dirs`, append `RefreshingSkillsMiddleware` to `agent_middleware`.

## 11. Out of scope (YAGNI)

Subagent skill-list refresh; `/skills` usage view; prompt reinforcement of skill
*usage*; per-directory-only signature (the per-file signature is used so
description edits are caught).

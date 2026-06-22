# Mid-session Skill Refresh — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a skill created mid-session (by `skill_manage` or a Hermes review) usable in the same session by refreshing the agent's injected skills list when the skill files change.

**Architecture:** A thin `RefreshingSkillsMiddleware(SkillsMiddleware)` subclass overrides `before_agent`/`abefore_agent`: when a per-file `SKILL.md` mtime signature over the real skill directories changes, it drops the cached `skills_metadata` from a state copy so deepagents' own loader re-runs. Wire it into `core_agent.py` in place of the default `SkillsMiddleware` (`skills=None` + append our middleware). Reuses all deepagents listing/parse/prompt-injection logic.

**Tech Stack:** Python 3.12, `uv`, `pytest` (asyncio auto-mode, plain `async def`), `ruff` (select=ALL, line 100, Google docstrings), deepagents `SkillsMiddleware`. Reference: `specs/2026-06-22-mid-session-skill-refresh-design.md`.

---

## File structure

**New source**
- `novacode_cli/skills/refreshing_middleware.py` — `RefreshingSkillsMiddleware`: change-signature + force-reload override. One responsibility.

**Modified**
- `novacode_cli/agents/core_agent.py` — pass `skills=None` to `create_deep_agent`, build `watch_dirs`, append `RefreshingSkillsMiddleware` to `agent_middleware`.

**Tests**
- `tests/test_refreshing_skills.py` (new) — signature detection + refresh behaviour (sync + async).

**Verified facts (used below):**
- `deepagents.middleware.skills` exports `SkillsMiddleware`, `SkillsState`, `SkillsStateUpdate`.
- `SkillsMiddleware.before_agent(self, state, runtime, config) -> SkillsStateUpdate | None`; async twin `abefore_agent`.
- A middleware built as `SkillsMiddleware(backend=OptimizedFilesystemBackend(root_dir=str(dir), virtual_mode=True), sources=["."])` lists skills under `dir`; calling `before_agent({}, None, None)` (and `await abefore_agent({}, None, None)`) returns `{"skills_metadata": [<SkillMetadata dicts with "name">]}`. `runtime`/`config` may be `None` because the backend is a direct (non-callable) instance.
- At the `create_deep_agent(...)` call in `core_agent.py:create_agent_with_config`, these locals are in scope: `skill_sources`, `skills_dir`, `claude_skills_dir`, `project_skills_dirs`, `composite_backend`, `agent_middleware`.

**Conventions:** one test `uv run pytest <path>::<test> -q`; format/lint `uv run ruff format <files> && uv run ruff check <files>`. For test fixture params that trip `ANN001`, add `# noqa: ANN001` (repo convention).

---

## Task 1: `RefreshingSkillsMiddleware` + tests

**Files:**
- Create: `novacode_cli/skills/refreshing_middleware.py`
- Test: `tests/test_refreshing_skills.py`

- [ ] **Step 1: Write the failing tests at `tests/test_refreshing_skills.py`**

```python
"""Tests for RefreshingSkillsMiddleware mid-session skill refresh."""

from __future__ import annotations

import os
import shutil
import time

from novacode_cli.backends import OptimizedFilesystemBackend as FilesystemBackend
from novacode_cli.skills.refreshing_middleware import RefreshingSkillsMiddleware


def _write_skill(skills_dir, name, desc="does things"):  # noqa: ANN001
    sk = skills_dir / name
    sk.mkdir(parents=True, exist_ok=True)
    (sk / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {desc}\n---\n\n# {name}\n", encoding="utf-8"
    )


def _make(skills_dir):  # noqa: ANN001, ANN202
    backend = FilesystemBackend(root_dir=str(skills_dir), virtual_mode=True)
    return RefreshingSkillsMiddleware(backend=backend, sources=["."], watch_dirs=[skills_dir])


def test_skills_changed_first_call_then_stable(tmp_path):  # noqa: ANN001
    _write_skill(tmp_path, "alpha")
    mw = _make(tmp_path)
    assert mw._skills_changed() is True  # first call establishes the baseline
    assert mw._skills_changed() is False  # nothing changed since


def test_skills_changed_detects_add(tmp_path):  # noqa: ANN001
    _write_skill(tmp_path, "alpha")
    mw = _make(tmp_path)
    mw._skills_changed()  # baseline
    _write_skill(tmp_path, "beta")
    assert mw._skills_changed() is True


def test_skills_changed_detects_remove(tmp_path):  # noqa: ANN001
    _write_skill(tmp_path, "alpha")
    _write_skill(tmp_path, "beta")
    mw = _make(tmp_path)
    mw._skills_changed()  # baseline
    shutil.rmtree(tmp_path / "beta")
    assert mw._skills_changed() is True


def test_skills_changed_detects_edit(tmp_path):  # noqa: ANN001
    _write_skill(tmp_path, "alpha", desc="v1")
    mw = _make(tmp_path)
    mw._skills_changed()  # baseline
    p = tmp_path / "alpha" / "SKILL.md"
    p.write_text(p.read_text(encoding="utf-8").replace("v1", "v2"), encoding="utf-8")
    future = time.time() + 10
    os.utime(p, (future, future))  # ensure a distinct mtime
    assert mw._skills_changed() is True


def test_before_agent_defers_when_unchanged(tmp_path):  # noqa: ANN001
    _write_skill(tmp_path, "alpha")
    mw = _make(tmp_path)
    upd1 = mw.before_agent({}, None, None)
    assert upd1 is not None
    assert "alpha" in {s["name"] for s in upd1["skills_metadata"]}
    state = {"skills_metadata": upd1["skills_metadata"]}
    assert mw.before_agent(state, None, None) is None  # deferred, no reload


def test_before_agent_refreshes_after_new_skill(tmp_path):  # noqa: ANN001
    _write_skill(tmp_path, "alpha")
    mw = _make(tmp_path)
    upd1 = mw.before_agent({}, None, None)
    state = {"skills_metadata": upd1["skills_metadata"]}
    _write_skill(tmp_path, "beta")
    upd2 = mw.before_agent(state, None, None)
    assert upd2 is not None
    assert {s["name"] for s in upd2["skills_metadata"]} == {"alpha", "beta"}


async def test_abefore_agent_refreshes_after_new_skill(tmp_path):  # noqa: ANN001
    _write_skill(tmp_path, "alpha")
    mw = _make(tmp_path)
    upd1 = await mw.abefore_agent({}, None, None)
    state = {"skills_metadata": upd1["skills_metadata"]}
    _write_skill(tmp_path, "beta")
    upd2 = await mw.abefore_agent(state, None, None)
    assert "beta" in {s["name"] for s in upd2["skills_metadata"]}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_refreshing_skills.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'novacode_cli.skills.refreshing_middleware'`.

- [ ] **Step 3: Write the implementation at `novacode_cli/skills/refreshing_middleware.py`**

```python
"""Skills middleware that refreshes its list when the skill files change.

deepagents' :class:`SkillsMiddleware` loads the available-skills list once per
session and caches it in the ``skills_metadata`` agent-state key, so a skill
created mid-session (by ``skill_manage`` or a Hermes review) is invisible to the
agent until a restart. This subclass re-lists when the watched skill directories
change, closing the within-session learning loop. See
``specs/2026-06-22-mid-session-skill-refresh-design.md``.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from deepagents.middleware.skills import SkillsMiddleware

if TYPE_CHECKING:
    from collections.abc import Sequence

    from deepagents.middleware.skills import SkillsState, SkillsStateUpdate
    from langchain_core.runnables import RunnableConfig
    from langgraph.runtime import Runtime


class RefreshingSkillsMiddleware(SkillsMiddleware):
    """:class:`SkillsMiddleware` that re-lists skills when watched dirs change.

    A change is detected by a per-file ``SKILL.md`` mtime signature over
    ``watch_dirs`` (real filesystem paths). When it changes, the cached
    ``skills_metadata`` is dropped from a state copy so the parent's loader
    re-runs; otherwise behaviour is identical to the base middleware.
    """

    def __init__(
        self,
        *,
        backend: object,
        sources: Sequence[object],
        watch_dirs: Sequence[Path],
    ) -> None:
        super().__init__(backend=backend, sources=sources)  # type: ignore[arg-type]
        self._watch_dirs = [Path(d) for d in watch_dirs]
        self._last_signature: frozenset[tuple[str, float]] | None = None

    def _compute_signature(self) -> frozenset[tuple[str, float]]:
        """A (path, mtime) frozenset over every ``*/SKILL.md`` under watch dirs."""
        sig: set[tuple[str, float]] = set()
        for directory in self._watch_dirs:
            try:
                skill_files = list(directory.glob("*/SKILL.md"))
            except OSError:
                continue
            for skill_md in skill_files:
                try:
                    sig.add((str(skill_md), skill_md.stat().st_mtime))
                except OSError:
                    continue
        return frozenset(sig)

    def _skills_changed(self) -> bool:
        """True if the skill files changed since the last call (best-effort)."""
        try:
            current = self._compute_signature()
        except Exception:  # noqa: BLE001 - best-effort; never break a turn
            return False
        changed = current != self._last_signature
        self._last_signature = current
        return changed

    def before_agent(
        self, state: SkillsState, runtime: Runtime, config: RunnableConfig
    ) -> SkillsStateUpdate | None:
        if self._skills_changed():
            state = {  # type: ignore[assignment]
                k: v for k, v in state.items() if k != "skills_metadata"
            }
        return super().before_agent(state, runtime, config)

    async def abefore_agent(
        self, state: SkillsState, runtime: Runtime, config: RunnableConfig
    ) -> SkillsStateUpdate | None:
        if self._skills_changed():
            state = {  # type: ignore[assignment]
                k: v for k, v in state.items() if k != "skills_metadata"
            }
        return await super().abefore_agent(state, runtime, config)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_refreshing_skills.py -q`
Expected: PASS (7 passed). If the edit-detection test is flaky on a coarse filesystem, confirm `os.utime` set a distinct mtime (the `+10` future offset guarantees it).

- [ ] **Step 5: Format, lint, commit**

```bash
uv run ruff format novacode_cli/skills/refreshing_middleware.py tests/test_refreshing_skills.py
uv run ruff check novacode_cli/skills/refreshing_middleware.py tests/test_refreshing_skills.py
```
Fix any NEW lint findings in the two files (keep the shown `# noqa` comments; match surrounding conventions — do not weaken rules globally). Commit ONLY these two files:
```bash
git add novacode_cli/skills/refreshing_middleware.py tests/test_refreshing_skills.py
git commit -m "feat(skills): RefreshingSkillsMiddleware re-lists on skill-file change"
```
End the commit body with:
`Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`

---

## Task 2: Wire `RefreshingSkillsMiddleware` into `core_agent.py`

**Files:**
- Modify: `novacode_cli/agents/core_agent.py`

This is an integration change (the full agent can't be cheaply unit-tested), so verification is an import smoke + a targeted source check + a documented manual smoke. The behaviour itself is covered by Task 1.

- [ ] **Step 1: Add the import**

Near the other top-level `novacode_cli` imports in `novacode_cli/agents/core_agent.py` (e.g. next to the `from novacode_cli.backends import ...` line around line 109), add:

```python
from novacode_cli.skills.refreshing_middleware import RefreshingSkillsMiddleware
```

(`refreshing_middleware.py` imports only `deepagents` + stdlib, so there is no import cycle.)

- [ ] **Step 2: Build `watch_dirs` and append the middleware before the `create_deep_agent(...)` call**

In `create_agent_with_config`, immediately BEFORE the `agent = create_deep_agent(` call (the one passing `name=assistant_id, model=wrapped_model, skills=skill_sources, ...`), insert:

```python
    # Refresh the injected skills list when the skill dirs change, so a skill
    # created mid-session (skill_manage / Hermes review) is usable this session
    # instead of only after a restart. Replaces create_deep_agent's default
    # SkillsMiddleware (see skills=None below).
    skill_watch_dirs = [skills_dir]
    if claude_skills_dir.exists():
        skill_watch_dirs.append(claude_skills_dir)
    skill_watch_dirs.extend(project_skills_dirs)
    agent_middleware.append(
        RefreshingSkillsMiddleware(
            backend=composite_backend,
            sources=skill_sources,
            watch_dirs=skill_watch_dirs,
        )
    )
```

- [ ] **Step 3: Pass `skills=None` so deepagents does not add its own `SkillsMiddleware`**

In that same `create_deep_agent(...)` call, change:
```python
        skills=skill_sources,
```
to:
```python
        skills=None,  # our RefreshingSkillsMiddleware (in agent_middleware) handles skills
```

- [ ] **Step 4: Verify — import smoke + source check**

```bash
uv run python -c "import novacode_cli.agents.core_agent; print('import ok')"
```
Expected: `import ok` (no import error / cycle).

```bash
grep -n "RefreshingSkillsMiddleware\|skills=None" novacode_cli/agents/core_agent.py
```
Expected: shows the import, the `agent_middleware.append(RefreshingSkillsMiddleware(...))`, and `skills=None` in the `create_deep_agent` call.

- [ ] **Step 5: Manual smoke (document the result in the commit message or PR)**

Run `uv run nova`. In one session: ask the agent to create a skill via `skill_manage` (or trigger a review that creates one), then in a later turn ask it to do a task that the new skill covers — confirm the agent now lists/reads the new skill **without** restarting. (Before this change it would not appear until restart.)

- [ ] **Step 6: Format, lint, commit**

```bash
uv run ruff format novacode_cli/agents/core_agent.py
uv run ruff check novacode_cli/agents/core_agent.py
```
Only fix lint findings your change INTRODUCED (this file has a large pre-existing baseline; compare with `git stash` if unsure). Commit:
```bash
git add novacode_cli/agents/core_agent.py
git commit -m "feat(agent): use RefreshingSkillsMiddleware for mid-session skill refresh"
```
End the commit body with the Co-Authored-By trailer.

---

## Task 3: Full-suite verification

**Files:** none (verification only)

- [ ] **Step 1: Run the new suite + skill-adjacent suites**

```bash
uv run pytest tests/test_refreshing_skills.py tests/test_skill_invoke.py tests/test_hermes/test_skill_discovery.py -q
```
Expected: PASS (all). (`test_skill_invoke.py` and `test_skill_discovery.py` exercise the skills surface; confirm no regression.)

- [ ] **Step 2: Lint the changed surface**

```bash
uv run ruff check novacode_cli/skills/refreshing_middleware.py novacode_cli/agents/core_agent.py
```
Expected: `refreshing_middleware.py` clean; `core_agent.py` shows no new findings beyond its pre-existing baseline.

- [ ] **Step 3: Import smoke for the agent build path**

```bash
uv run python -c "import novacode_cli.agents.core_agent, novacode_cli.skills.refreshing_middleware; print('ok')"
```
Expected: `ok`.

- [ ] **Step 4: Commit any fixups** (if Steps 1-2 surfaced issues)

```bash
git add -A
git commit -m "test: verify mid-session skill refresh end-to-end"
```

---

## Self-review notes (author)

- **Spec coverage:** §3 component → Task 1 (class); §4 signature → Task 1 (`_compute_signature`/`_skills_changed` + add/remove/edit tests); §5 force-reload → Task 1 (`before_agent`/`abefore_agent` defer-vs-refresh tests); §6 wiring → Task 2 (`skills=None` + append + `watch_dirs`); §7 sync+async → Task 1 (both overridden; async test) + the sync/async parity; §8 error handling → `_skills_changed` try/except returns False (and the `_compute_signature` per-entry `OSError` guards); §9 testing → Task 1 covers each listed case.
- **Type consistency:** `RefreshingSkillsMiddleware(backend, sources, watch_dirs)` constructor matches Tasks 1 & 2; `_skills_changed()`/`_compute_signature()` names consistent; `skills_metadata` state key spelled identically in the override, the tests, and matches deepagents.
- **No new LLM calls / no new state schema:** the refresh reuses the existing `skills_metadata` key and deepagents' loader; nothing else added.
- **Manual-verification honesty:** Task 2 is an integration wiring step; its correctness rests on Task 1's unit tests plus the documented manual smoke (the full agent build is too heavy to unit-test cheaply).

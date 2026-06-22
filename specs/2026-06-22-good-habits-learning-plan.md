# Good-Habits Learning — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give Hermes a success path — when Nova does substantive work *cleanly*, the existing out-of-band review distills a reusable "good habit" into an always-injected `HABITS.md` so it reinforces good practices on future runs.

**Architecture:** Reuse the existing OOB review's single LLM call (no new model calls). A zero-failure substantive window adds a `clean_win` trigger to `ReviewRunner.should_review`; the review prompt gains a habit section; the model emits a `<habit>` block; a new `record_habit` writer persists it to `~/.nova/agents/<id>/HABITS.md`; `AgentMemoryMiddleware` injects that file into the system prompt every turn.

**Tech Stack:** Python 3.12, `uv`, `pytest` (asyncio auto-mode, plain `async def`), `ruff` (select=ALL, line 100, Google docstrings), Jinja2 prompts. Reference: `specs/2026-06-22-good-habits-learning-design.md`.

---

## File structure

**Modified source**
- `novacode_cli/hermes/memory_tiers.py` — `parse_review_response` gains `<habit>` parsing; new `record_habit(agent_dir, bullets)` writer (sibling of `record_lesson`).
- `novacode_cli/prompts/nova_review.jinja` — clean-win habit section + output-format note.
- `novacode_cli/hermes/review.py` — `clean_win` trigger in `should_review`; stash + pass `clean_win` into the template in `run_review`; call `record_habit` in `_apply_review_content`.
- `novacode_cli/memory/agent_memory.py` — load `HABITS.md` into middleware state and render it in the memory section.
- `novacode_cli/prompts/longterm_memory.jinja` — render the habits block.

**Tests**
- `tests/test_hermes/test_memory_tiers.py` (append) — parse + `record_habit`.
- `tests/test_hermes/test_learning_improvements.py` (append) — clean-win trigger (reuses `store` fixture + `_make_review`/`_seed_window`).
- `tests/test_hermes/test_good_habits.py` (new) — `nova_review.jinja` + `longterm_memory.jinja` render.
- `tests/test_good_habits_injection.py` (new) — `AgentMemoryMiddleware` loads `HABITS.md` into state.

**Conventions:** Run one test with `uv run pytest <path>::<test> -q`. Format/lint: `uv run ruff format <files> && uv run ruff check <files>`. Match the style of `tests/test_hermes/test_learning_improvements.py` (has a `FakeStore` + `store` fixture) and `tests/test_provider_errors.py`.

**Path alignment (verified):** `agent.md` is `settings.get_agent_dir(aid)/agent.md`; `HABITS.md` is `settings.get_agent_dir(aid)/HABITS.md`. `ReviewRunner._agent_dir` is `settings.get_agent_dir(aid)` (from `core_agent.py:732`), and the injector reads the sibling of `agent.md`, so writer and reader resolve to the same file.

---

## Task 1: `record_habit` writer + `<habit>` parsing

**Files:**
- Modify: `novacode_cli/hermes/memory_tiers.py`
- Test: `tests/test_hermes/test_memory_tiers.py` (append)

- [ ] **Step 1: Append failing tests to `tests/test_hermes/test_memory_tiers.py`**

```python
# --- good habits (<habit> parsing + HABITS.md writer) ----------------------


def test_parse_extracts_habit_block():
    from novacode_cli.hermes.memory_tiers import parse_review_response

    content = "<habit>\n- Test-first for races: write the failing test first.\n</habit>"
    parsed = parse_review_response(content)
    assert "Test-first for races" in parsed["habits"]
    assert parsed["lessons"] == []  # habit-only must NOT be misfiled as a lesson
    assert parsed["user_model"] == ""


def test_parse_no_habit_block_is_empty():
    from novacode_cli.hermes.memory_tiers import parse_review_response

    parsed = parse_review_response("<lesson topic='t'>\n- a fact\n</lesson>")
    assert parsed["habits"] == ""
    assert len(parsed["lessons"]) == 1


def test_record_habit_creates_and_appends(tmp_path):
    from novacode_cli.hermes.memory_tiers import record_habit

    record_habit(tmp_path, "- Flatten nesting with guard clauses.")
    habits = (tmp_path / "HABITS.md").read_text(encoding="utf-8")
    assert "Good Habits" in habits  # header
    assert "Flatten nesting with guard clauses" in habits


def test_record_habit_dedups(tmp_path):
    from novacode_cli.hermes.memory_tiers import record_habit

    record_habit(tmp_path, "- Extract magic numbers to named constants.")
    record_habit(tmp_path, "- Extract magic numbers to named constants.")
    habits = (tmp_path / "HABITS.md").read_text(encoding="utf-8")
    assert habits.count("Extract magic numbers to named constants") == 1


def test_record_habit_empty_is_noop(tmp_path):
    from novacode_cli.hermes.memory_tiers import record_habit

    record_habit(tmp_path, "   ")
    assert not (tmp_path / "HABITS.md").exists()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_hermes/test_memory_tiers.py -k "habit" -q`
Expected: FAIL — `record_habit` not importable; `parsed["habits"]` KeyError.

- [ ] **Step 3a: Add `<habit>` parsing in `parse_review_response`**

In `novacode_cli/hermes/memory_tiers.py`, change the result initializer (currently `result: dict[str, Any] = {"user_model": "", "lessons": []}`) to include habits:

```python
    result: dict[str, Any] = {"user_model": "", "lessons": [], "habits": ""}
```

After the `<lesson>` loop (the `for match in _LESSON_BLOCK_RE.finditer(...)` block) and BEFORE the unstructured-fallback `if`, add:

```python
    habit_matches = re.findall(
        r"<habit>(.*?)</habit>",
        response_content,
        re.DOTALL | re.IGNORECASE,
    )
    if habit_matches:
        result["habits"] = "\n".join(m.strip() for m in habit_matches if m.strip())
```

Update the unstructured-fallback condition so a habit-only response is NOT re-filed as a lesson. Change:

```python
    if not result["user_model"] and not result["lessons"] and response_content.strip():
```
to:
```python
    if (
        not result["user_model"]
        and not result["lessons"]
        and not result["habits"]
        and response_content.strip()
    ):
```

- [ ] **Step 3b: Add the `record_habit` writer**

Add a module-level header constant near `_DEFAULT_TOPIC_HEADER`:

```python
# H1 header for a freshly-created HABITS.md (the always-injected good-habits file).
_HABITS_HEADER = "# Good Habits\n\nReusable practices that worked well, captured during reviews.\n"
```

Add this function next to `record_lesson` (it mirrors it; reuses `_dedup_against` and `compact_memory_file`):

```python
def record_habit(agent_dir: Path, bullets: str) -> None:
    """Record good-habit bullets to ``HABITS.md`` (the always-injected file).

    Mirrors :func:`record_lesson`: bullets are prepended (newest-first) under a
    timestamped section, deduped against what the file already holds, and the
    file is compacted when it exceeds ``MAX_MEMORY_CHARS``. Best-effort.

    Args:
        agent_dir: The agent directory (``~/.nova/agents/<id>/``).
        bullets: Bullet lines describing reusable good habits.
    """
    if not (bullets or "").strip():
        return
    agent_dir.mkdir(parents=True, exist_ok=True)
    habits_file = agent_dir / "HABITS.md"

    content = habits_file.read_text(encoding="utf-8") if habits_file.exists() else _HABITS_HEADER

    deduped = _dedup_against(content, bullets)
    if not deduped:
        _emit_memory_event("Habit added no new memory (all duplicates)")
        return

    insert_at = content.find("\n## ")
    if insert_at == -1:
        insert_at = len(content)
    before, after = content[:insert_at], content[insert_at:]
    timestamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
    entry = f"\n## Review — {timestamp}\n\n{deduped}\n"
    habits_file.write_text(before.rstrip() + "\n" + entry + after, encoding="utf-8")

    _emit_memory_event("Recorded good habit to HABITS.md", icon="✨")
    compact_memory_file(habits_file)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_hermes/test_memory_tiers.py -k "habit" -q`
Expected: PASS (5 passed). Also run the whole file to confirm no regression: `uv run pytest tests/test_hermes/test_memory_tiers.py -q`.

- [ ] **Step 5: Format, lint, commit**

```bash
uv run ruff format novacode_cli/hermes/memory_tiers.py tests/test_hermes/test_memory_tiers.py
uv run ruff check novacode_cli/hermes/memory_tiers.py tests/test_hermes/test_memory_tiers.py
git add novacode_cli/hermes/memory_tiers.py tests/test_hermes/test_memory_tiers.py
git commit -m "feat(hermes): parse <habit> blocks and record them to HABITS.md"
```
End the commit body with:
`Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`

---

## Task 2: Clean-win habit section in the review prompt

**Files:**
- Modify: `novacode_cli/prompts/nova_review.jinja`
- Test: `tests/test_hermes/test_good_habits.py` (new)

- [ ] **Step 1: Write the failing test at `tests/test_hermes/test_good_habits.py`**

```python
"""Render tests for the good-habits prompt + injection blocks."""

from __future__ import annotations

from novacode_cli.prompts import render_template


def test_review_prompt_shows_habit_section_on_clean_win():
    out = render_template(
        "nova_review.jinja",
        tool_call_count=10,
        prior_lessons="",
        recovered_from_error=False,
        clean_win=True,
    )
    assert "<habit>" in out
    assert "notably well" in out.lower()


def test_review_prompt_omits_habit_section_without_clean_win():
    out = render_template(
        "nova_review.jinja",
        tool_call_count=10,
        prior_lessons="",
        recovered_from_error=False,
        clean_win=False,
    )
    assert "notably well" not in out.lower()
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_hermes/test_good_habits.py -q`
Expected: FAIL — the habit section/text isn't in the template yet.

- [ ] **Step 3: Edit `novacode_cli/prompts/nova_review.jinja`**

Add a new section after the "### 2. Reusable Skills" block (which ends with the `{% if recovered_from_error %}…{% endif %}`) and before "### 3. Memory Health Check":

```jinja
{% if clean_win %}
### 2b. Did you do something notably well?
This window was clean (substantive work, no failed tool calls). If it used a
reusable approach worth repeating — a good fix pattern, an elegant
simplification, a production-ready practice — capture it as a short, general
**habit** (NOT a step-by-step workflow; that's a skill). 1-2 bullets, phrased as
durable guidance. Skip generic edits and anything already known above.
{% endif %}
```

In the "### Output Format" list, add a bullet describing the block (after the `<skill>` bullet):

```jinja
- `<habit>` — at most one. Only on a clean win (step 2b): 1-2 bullets of reusable good-practice guidance. Written to `HABITS.md` (always injected). Omit unless genuinely notable.
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_hermes/test_good_habits.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Format, lint, commit**

```bash
uv run ruff format tests/test_hermes/test_good_habits.py
uv run ruff check tests/test_hermes/test_good_habits.py
git add novacode_cli/prompts/nova_review.jinja tests/test_hermes/test_good_habits.py
git commit -m "feat(hermes): add clean-win good-habit section to review prompt"
```
End the commit body with the Co-Authored-By trailer.

---

## Task 3: Clean-win trigger + flag + persist in `ReviewRunner`

**Files:**
- Modify: `novacode_cli/hermes/review.py`
- Test: `tests/test_hermes/test_learning_improvements.py` (append)

- [ ] **Step 1: Append failing tests to `tests/test_hermes/test_learning_improvements.py`**

These reuse the existing module-level `_make_review`, `_seed_window`, and the `store` fixture.

```python
class TestCleanWinTrigger:
    async def test_clean_substantive_window_triggers_below_threshold(self, store):
        # threshold=10 -> min_floor=5. 5 clean substantive calls, no failures,
        # below the substantive threshold and below the failure-burst count.
        review = _make_review(store, threshold=10)
        await _seed_window(store, [{"tool": "edit_file", "success": True}] * 5)
        assert await review.should_review() is True
        assert review._pending_clean_win is True

    async def test_window_with_failure_is_not_clean_win(self, store):
        review = _make_review(store, threshold=10)
        window = [{"tool": "edit_file", "success": True}] * 4 + [
            {"tool": "execute", "success": False}
        ]
        await _seed_window(store, window)  # 5 calls, 1 failure, below threshold
        assert await review.should_review() is False

    async def test_all_trivial_window_is_not_clean_win(self, store):
        review = _make_review(store, threshold=10)
        await _seed_window(store, [{"tool": "read_file", "success": True}] * 5)
        assert await review.should_review() is False
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_hermes/test_learning_improvements.py::TestCleanWinTrigger -q`
Expected: FAIL — `test_clean_substantive_window_triggers_below_threshold` fails (no clean-win trigger yet; `_pending_clean_win` attribute missing).

- [ ] **Step 3a: Add `_pending_clean_win` state in `ReviewRunner.__init__`**

In `novacode_cli/hermes/review.py`, in `__init__`, after `self._enabled = enabled` add:

```python
        # Set by should_review when a clean-win review fires; read (and cleared)
        # by run_review to render the good-habit prompt section.
        self._pending_clean_win = False
```

- [ ] **Step 3b: Add the clean-win trigger in `should_review`**

In `should_review`, the current trigger block is:

```python
        failure_burst = failures >= self._failure_burst and count >= min_floor
        reached = count >= self._review_threshold
        hard_cap = count >= 2 * self._review_threshold

        if not (hard_cap or failure_burst or (reached and substantive)):
            return False
```

Replace it with (adds `clean_win`, explicit non-empty window, and stashes the flag):

```python
        failure_burst = failures >= self._failure_burst and count >= min_floor
        reached = count >= self._review_threshold
        hard_cap = count >= 2 * self._review_threshold
        # A clean win: real substantive work, zero failures, past the floor. The
        # window is non-empty here because count >= min_floor (>= 3).
        clean_win = bool(window) and substantive and failures == 0 and count >= min_floor

        if not (hard_cap or failure_burst or (reached and substantive) or clean_win):
            return False
```

Then, just before the final `return True` (after the `just_completed` guard), stash the flag:

```python
        self._pending_clean_win = clean_win
        return True
```

(The existing `just_completed` early `return False` stays as-is — when a review is skipped we don't set the flag.)

- [ ] **Step 3c: Pass `clean_win` into the template in `run_review`**

In `run_review`, the `render_template("nova_review.jinja", …)` call currently passes `tool_call_count`, `prior_lessons`, `recovered_from_error`. Read and clear the stashed flag before the call and pass it:

```python
            clean_win = self._pending_clean_win
            self._pending_clean_win = False
            review_content = render_template(
                "nova_review.jinja",
                tool_call_count=self._review_threshold,
                prior_lessons=prior_lessons,
                recovered_from_error=recovered_from_error,
                clean_win=clean_win,
            )
```

- [ ] **Step 3d: Persist habits in `_apply_review_content`**

In `_apply_review_content`, after the existing `if self._agent_dir and (parsed["user_model"] or parsed["lessons"]): update_from_review(...)` block, add:

```python
            if self._agent_dir and parsed.get("habits"):
                from novacode_cli.hermes.memory_tiers import record_habit

                record_habit(self._agent_dir, parsed["habits"])
                logger.info("Nova review recorded a good habit")
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/test_hermes/test_learning_improvements.py -q`
Expected: PASS (all existing + 3 new). Confirms no regression to the existing trigger tests (e.g. `test_substantive_window_triggers` still passes — it triggers via `reached`).

- [ ] **Step 5: Format, lint, commit**

```bash
uv run ruff format novacode_cli/hermes/review.py tests/test_hermes/test_learning_improvements.py
uv run ruff check novacode_cli/hermes/review.py tests/test_hermes/test_learning_improvements.py
git add novacode_cli/hermes/review.py tests/test_hermes/test_learning_improvements.py
git commit -m "feat(hermes): clean-win review trigger + record good habits"
```
End the commit body with the Co-Authored-By trailer.

---

## Task 4: Load `HABITS.md` into `AgentMemoryMiddleware` state

**Files:**
- Modify: `novacode_cli/memory/agent_memory.py`
- Test: `tests/test_good_habits_injection.py` (new)

- [ ] **Step 1: Write the failing test at `tests/test_good_habits_injection.py`**

```python
"""HABITS.md is loaded into AgentMemoryMiddleware state for injection."""

from __future__ import annotations

import types


def _make_middleware(tmp_path, monkeypatch):
    from novacode_cli.memory import agent_memory

    mw = agent_memory.AgentMemoryMiddleware.__new__(agent_memory.AgentMemoryMiddleware)
    # Minimal attributes the sync loader reads.
    mw.assistant_id = "nova-agent"
    mw.agent_dir = tmp_path
    mw.skip_project_memory = True
    mw._backend = None
    mw._mtimes = {}
    agent_md = tmp_path / "agent.md"
    agent_md.write_text("# agent\n", encoding="utf-8")
    mw.settings = types.SimpleNamespace(
        get_user_agent_md_path=lambda _aid: agent_md,
        get_project_agent_md_paths=lambda: [],
    )
    return mw, agent_md


def test_habits_md_loaded_into_state(tmp_path, monkeypatch):
    mw, agent_md = _make_middleware(tmp_path, monkeypatch)
    (tmp_path / "HABITS.md").write_text(
        "# Good Habits\n\n- Test-first for races.\n", encoding="utf-8"
    )
    result = mw.before_agent({})
    assert "Test-first for races" in result["habits_memory"]


def test_habits_md_absent_leaves_state_unset(tmp_path, monkeypatch):
    mw, agent_md = _make_middleware(tmp_path, monkeypatch)
    result = mw.before_agent({})
    assert "habits_memory" not in result
```

NOTE: before writing the implementation, READ `novacode_cli/memory/agent_memory.py` `before_agent` (and its `_files_changed`/`_read_file`/`_record_mtimes` helpers) to confirm the attribute names used by the stub (`_backend`, `_mtimes`, `settings`, `agent_dir`). If a helper reads an attribute the stub doesn't set, set it minimally in `_make_middleware` and note it. Keep the test focused on the load behavior.

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_good_habits_injection.py -q`
Expected: FAIL — `habits_memory` not populated (loader doesn't read HABITS.md yet).

- [ ] **Step 3a: Add `habits_memory` to the state TypedDicts**

In `novacode_cli/memory/agent_memory.py`, add to BOTH `AgentMemoryState` (after `memory_index: NotRequired[str]`) and `AgentMemoryStateUpdate`:

```python
    habits_memory: NotRequired[str]
    """Good-habits surface (~/.nova/agents/<id>/HABITS.md), always injected."""
```

- [ ] **Step 3b: Load `HABITS.md` in `before_agent`**

In `before_agent`, after `index_path = self.agent_dir / "memories" / "INDEX.md"`, add:

```python
        habits_path = user_path.parent / "HABITS.md"
```

Add `habits_path` to the `all_paths` list:

```python
        all_paths = [user_path, index_path, habits_path] + list(project_paths)
```

After the `memory_index` load block (the `if needs_reload or "memory_index" not in state:` block), add:

```python
        # Load the always-injected good-habits file (HABITS.md), if present.
        if needs_reload or "habits_memory" not in state:
            habits_content = self._read_file(habits_path)
            if habits_content is not None and habits_content.strip():
                if len(habits_content) > MAX_MEMORY_CHARS:
                    habits_content = habits_content[:MAX_MEMORY_CHARS] + _MEMORY_TRUNCATION_NOTICE
                result["habits_memory"] = habits_content
```

- [ ] **Step 3c: Load `HABITS.md` in `abefore_agent`**

`abefore_agent` mirrors `before_agent` but reads via `await self._aread_file(...)` (verified). Apply the same three edits there: define `habits_path = user_path.parent / "HABITS.md"`, add it to that method's `all_paths` (which is `[user_path, index_path, *project_paths]` → `[user_path, index_path, habits_path, *project_paths]`), and after its `memory_index` load block add:

```python
        if needs_reload or "habits_memory" not in state:
            habits_content = await self._aread_file(habits_path)
            if habits_content is not None and habits_content.strip():
                if len(habits_content) > MAX_MEMORY_CHARS:
                    habits_content = habits_content[:MAX_MEMORY_CHARS] + _MEMORY_TRUNCATION_NOTICE
                result["habits_memory"] = habits_content
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_good_habits_injection.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Format, lint, commit**

```bash
uv run ruff format novacode_cli/memory/agent_memory.py tests/test_good_habits_injection.py
uv run ruff check novacode_cli/memory/agent_memory.py tests/test_good_habits_injection.py
git add novacode_cli/memory/agent_memory.py tests/test_good_habits_injection.py
git commit -m "feat(memory): load HABITS.md into agent memory state"
```
End the commit body with the Co-Authored-By trailer.

---

## Task 5: Render the habits block into the system prompt

**Files:**
- Modify: `novacode_cli/memory/agent_memory.py` (`_build_memory_section` / `wrap_model_call` body + cache fields)
- Modify: `novacode_cli/prompts/longterm_memory.jinja`
- Test: `tests/test_hermes/test_good_habits.py` (append)

- [ ] **Step 1: Append a failing render test to `tests/test_hermes/test_good_habits.py`**

```python
def test_longterm_memory_renders_good_habits_when_present():
    out = render_template(
        "longterm_memory.jinja",
        agent_dir_absolute="/x",
        agent_dir_display="x",
        project_memory_info="None",
        project_deepagents_dir="/project-memory/",
        memory_index="",
        habits_memory="- Test-first for races.",
    )
    assert "Test-first for races" in out
    assert "good_habits" in out.lower()


def test_longterm_memory_omits_good_habits_when_absent():
    out = render_template(
        "longterm_memory.jinja",
        agent_dir_absolute="/x",
        agent_dir_display="x",
        project_memory_info="None",
        project_deepagents_dir="/project-memory/",
        memory_index="",
        habits_memory="",
    )
    assert "good_habits" not in out.lower()
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_hermes/test_good_habits.py -k longterm -q`
Expected: FAIL — the template doesn't render a good_habits block yet.

- [ ] **Step 3a: Render the block in `longterm_memory.jinja`**

Add this block to `novacode_cli/prompts/longterm_memory.jinja` immediately after the `{% if memory_index %}…{% endif %}` block:

```jinja
{% if habits_memory %}
<good_habits>
These are good habits you've reinforced from your own clean, successful work
(maintained automatically by self-review). Keep doing them — they reflect what
"good" has looked like for this user and codebase.

{{ habits_memory }}
</good_habits>
{% endif %}
```

- [ ] **Step 3b: Pass `habits_memory` through the memory-section builder**

In `novacode_cli/memory/agent_memory.py`, in the method that builds the memory section (the one that does `user_memory = state.get("user_memory")` and calls `render_template("longterm_memory.jinja", …)`):

Read the habits value next to the others:
```python
        habits_memory = state.get("habits_memory")
```

Add it to the cache-key tuple and the cache comparison. Change:
```python
        memory_content = (user_memory or "", project_memory or "", memory_index or "")
```
to:
```python
        memory_content = (
            user_memory or "",
            project_memory or "",
            memory_index or "",
            habits_memory or "",
        )
```
and add a fourth comparison to `can_use_cache`:
```python
            and (self._cached_habits_memory or "") == memory_content[3]
```

Pass it into the template render:
```python
            memory_section += "\n\n" + render_template(
                "longterm_memory.jinja",
                agent_dir_absolute=self.agent_dir_absolute,
                agent_dir_display=self.agent_dir_display,
                project_memory_info=project_memory_info,
                project_deepagents_dir=project_deepagents_dir,
                memory_index=memory_index,
                habits_memory=habits_memory,
            )
```

In the cache-store block (where `self._cached_user_memory = memory_content[0]` etc. are assigned), add:
```python
            self._cached_habits_memory = memory_content[3]
```

- [ ] **Step 3c: Initialize the cache field**

In `__init__`, next to `self._cached_memory_index: str | None = None`, add:
```python
        self._cached_habits_memory: str | None = None
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_hermes/test_good_habits.py -q`
Expected: PASS (4 passed). Then a quick import smoke: `uv run python -c "import novacode_cli.memory.agent_memory; print('ok')"`.

- [ ] **Step 5: Format, lint, commit**

```bash
uv run ruff format novacode_cli/memory/agent_memory.py tests/test_hermes/test_good_habits.py
uv run ruff check novacode_cli/memory/agent_memory.py tests/test_hermes/test_good_habits.py
git add novacode_cli/memory/agent_memory.py novacode_cli/prompts/longterm_memory.jinja tests/test_hermes/test_good_habits.py
git commit -m "feat(memory): inject HABITS.md into the system prompt"
```
End the commit body with the Co-Authored-By trailer.

---

## Task 6: Full-suite verification

**Files:** none (verification only)

- [ ] **Step 1: Run all new + adjacent suites**

```bash
uv run pytest tests/test_hermes/test_memory_tiers.py tests/test_hermes/test_learning_improvements.py \
  tests/test_hermes/test_good_habits.py tests/test_good_habits_injection.py \
  tests/test_hermes/test_hermes_middleware.py -q
```
Expected: PASS (all).

- [ ] **Step 2: Lint the changed surface**

```bash
uv run ruff check novacode_cli/hermes/memory_tiers.py novacode_cli/hermes/review.py novacode_cli/memory/agent_memory.py
```
Expected: no new findings beyond each file's pre-existing baseline (compare with `git stash` if unsure).

- [ ] **Step 3: End-to-end sanity (no model call)**

Run this to confirm the write→inject loop wires up against a temp agent dir:
```bash
uv run python -c "
import tempfile, pathlib
from novacode_cli.hermes.memory_tiers import record_habit, parse_review_response
d = pathlib.Path(tempfile.mkdtemp())
p = parse_review_response('<habit>\n- Prefer early-return guard clauses.\n</habit>')
record_habit(d, p['habits'])
print('HABITS.md:', (d/'HABITS.md').read_text())
assert 'guard clauses' in (d/'HABITS.md').read_text()
print('OK')
"
```
Expected: prints the habits file containing the bullet and `OK`.

- [ ] **Step 4: Commit any fixups** (if Steps 1-2 surfaced issues)

```bash
git add -A
git commit -m "test: verify good-habits learning end-to-end"
```

---

## Self-review notes (author)

- **Spec coverage:** §4 signal + §5 trigger → Task 3 (`clean_win` in `should_review` + tests); §6 capture → Task 1 (`<habit>` parse) + Task 2 (prompt) + Task 3 (pass flag, call `record_habit`); §7 storage → Task 1 (`record_habit`); §8 injection → Task 4 (load) + Task 5 (render); §10 error handling: `record_habit` is best-effort and called inside the OOB review which already swallows exceptions; §11 testing spread across tasks.
- **Type consistency:** `parse_review_response` returns the `"habits"` key (Task 1) consumed in Task 3; `record_habit(agent_dir, bullets)` signature consistent in Tasks 1/3; `habits_memory` state key consistent across Tasks 4/5; `_pending_clean_win` consistent across Task 3 steps; `clean_win` template var consistent across Tasks 2/3/5-ish.
- **Cross-call signal:** the counter is reset before `run_review`, so `clean_win` is computed in `should_review` (where the window is live) and stashed in `self._pending_clean_win`, read+cleared in `run_review` — avoids recomputing from a different lookback.
- **Sync+async:** Task 4 edits BOTH `before_agent` and `abefore_agent` (the agent runs via the async path; CLAUDE.md flags sync-only middleware as a runtime bug).

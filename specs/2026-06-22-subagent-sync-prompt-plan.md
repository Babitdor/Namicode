# `<subagents>` Orchestration Prompt — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the agent ending its turn to "wait" after dispatching a synchronous `task` subagent, by adding a `<subagents>` guidance block to the core system prompt.

**Architecture:** Prompt-only change — add a static `<subagents>` block to `novacode_cli/prompts/core_agent_system.jinja` (after `<todo_management>`, before `<plan_mode>`) plus a render test. No code change; the agent loop and `task` tool already work correctly.

**Tech Stack:** Jinja2 prompt templates (`render_template`), `pytest`, `ruff` (select=ALL, line 100). Reference: `specs/2026-06-22-subagent-sync-prompt-design.md`.

**Verified facts (rely on these):**
- `render_template("core_agent_system.jinja")` renders cleanly with NO kwargs (the Jinja env uses lenient `Undefined`) — output is ~5,780 chars and already contains `<todo_management>`.
- The prompt's block order is `<todo_management>` → `<plan_mode>` → `<human_in_the_loop>` → `<learning_system>`; the new block goes between `<todo_management>` and `<plan_mode>`.

---

## File structure

- Modify: `novacode_cli/prompts/core_agent_system.jinja` — add the static `<subagents>` block (no Jinja variables).
- New: `tests/test_core_prompt_subagents.py` — render assertions.

---

## Task 1: Add the `<subagents>` block + render test

**Files:**
- Modify: `novacode_cli/prompts/core_agent_system.jinja`
- Test: `tests/test_core_prompt_subagents.py`

- [ ] **Step 1: Write the failing test at `tests/test_core_prompt_subagents.py`**

```python
"""The core system prompt tells the agent the task tool is synchronous."""

from __future__ import annotations

from novacode_cli.prompts import render_template


def _core_prompt() -> str:
    # Lenient Jinja Undefined => no kwargs needed for this static-block assertion.
    return render_template("core_agent_system.jinja")


def test_core_prompt_has_subagents_block():
    out = _core_prompt()
    assert "<subagents>" in out
    assert "</subagents>" in out


def test_core_prompt_states_task_is_synchronous_and_no_wait():
    out = _core_prompt()
    assert "synchronous" in out
    assert "Never end your turn" in out


def test_subagents_block_follows_todo_management():
    out = _core_prompt()
    assert "<todo_management>" in out and "<subagents>" in out
    assert out.index("<subagents>") > out.index("</todo_management>")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_core_prompt_subagents.py -q`
Expected: FAIL — the prompt has no `<subagents>` block yet (the first two tests fail; the ordering test errors on `out.index("<subagents>")`).

- [ ] **Step 3: Add the block to `novacode_cli/prompts/core_agent_system.jinja`**

Find the `<todo_management>` block:
```jinja
<todo_management>
Use only for complex tasks (3+ steps); skip simple 1–2 step work. Keep lists minimal (3–6 items max). Workflow: create → present → wait for approval → mark in_progress → update as you go.
</todo_management>
```
Insert the new block immediately AFTER it (so it sits between `</todo_management>` and `<plan_mode>`):
```jinja

<subagents>
The `task` tool is **synchronous**: the subagent runs to completion and its full
report is returned to you in the tool result — it is not a background job.

Never end your turn to "wait" for a subagent. The moment its result returns, read
it and continue the work yourself in the same turn — review it, fix issues,
dispatch the next step, or finish.
</subagents>
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_core_prompt_subagents.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Format, lint, commit**

```bash
uv run ruff format tests/test_core_prompt_subagents.py
uv run ruff check tests/test_core_prompt_subagents.py
```
Expected: the test file is clean (the `.jinja` template is not linted by ruff). Commit:
```bash
git add novacode_cli/prompts/core_agent_system.jinja tests/test_core_prompt_subagents.py
git commit -m "feat(prompt): tell the agent the task tool is synchronous (continue, don't wait)"
```
End the commit body with: `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`

---

## Task 2: Verification

**Files:** none (verification only)

- [ ] **Step 1: Run the new test + adjacent prompt tests**

```bash
uv run pytest tests/test_core_prompt_subagents.py tests/test_hermes/test_prompt_evolution.py -q
```
Expected: PASS (the prompt-evolution tests reference `core_agent_system` and confirm nothing else broke).

- [ ] **Step 2: Confirm the rendered prompt is intact**

```bash
uv run python -c "from novacode_cli.prompts import render_template; o=render_template('core_agent_system.jinja'); print('len', len(o)); print('blocks ok', all(b in o for b in ('<todo_management>','<subagents>','<plan_mode>','<learning_system>')))"
```
Expected: `len` ~6,100 and `blocks ok True` (all blocks present, in a longer prompt).

- [ ] **Step 3: Commit any fixups** (only if Step 1 failed)

```bash
git add -A
git commit -m "test: verify subagents prompt block"
```

---

## Self-review notes (author)

- **Spec coverage:** §2 the block + placement → Task 1 Step 3; §4 testing (render contains block + key phrases, ordering after `<todo_management>`, existing tests pass) → Task 1 Steps 1/3 + Task 2 Step 1; §5 files touched → matches.
- **Placeholder scan:** none — the exact block text and exact test code are inline.
- **Consistency:** the asserted phrases (`"synchronous"`, `"Never end your turn"`, `<subagents>`/`</subagents>`) match the block text verbatim; the ordering assertion matches the verified block order.
- **Scope:** prompt-only, single block; no code/loop/`task`-tool change (per spec §3).

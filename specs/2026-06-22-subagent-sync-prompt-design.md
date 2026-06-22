# Design — `<subagents>` orchestration guidance in the core prompt

**Date:** 2026-06-22
**Status:** Approved (design); pending implementation plan
**Area:** Prompts / agent orchestration

## 1. Problem & goal

When the main agent dispatches a subagent via the `task` tool, it sometimes ends
its turn with a message like *"the implementer is working… let me wait for them
to report back"*, forcing the user to type **Proceed** to continue.

Diagnosis (confirmed in code): this is **not** a loop or wiring bug. The
`general-purpose` `task` tool is **synchronous** — the subagent runs to
completion and its full report is returned to the orchestrator as a tool message
in the same turn. Nova's agent loop ends a turn only when the model stops calling
tools; here the model *chose* to stop ("wait") instead of acting on the report it
already had. Contributing factors: a weak orchestration model
(`deepseek-v4-flash`) and the fact that `core_agent_system.jinja` contains **zero
guidance** about how the `task` tool / subagents behave.

Goal: add a short prompt block that tells the agent the `task` tool is
synchronous and that it must continue acting on the returned report instead of
ending its turn to "wait". This is a **prompt-only** change.

## 2. The change

Add one block to `novacode_cli/prompts/core_agent_system.jinja`, immediately
after the `<todo_management>` block and before `<plan_mode>` (the
execution-workflow neighbourhood). It contains no Jinja variables — pure static
guidance:

```jinja
<subagents>
The `task` tool is **synchronous**: the subagent runs to completion and its full
report is returned to you in the tool result — it is not a background job.

Never end your turn to "wait" for a subagent. The moment its result returns, read
it and continue the work yourself in the same turn — review it, fix issues,
dispatch the next step, or finish.
</subagents>
```

No other block changes. The block is part of the always-on core system prompt,
so it is injected every turn (~5 lines).

## 3. Why this works / scope

- It directly counters the observed failure mode (the model's "let me wait for
  them to report back" mental model) by stating **synchronous**, **never wait**,
  and **continue in the same turn**.
- The core prompt currently has no subagent guidance at all, so this fills a real
  gap without touching unrelated content.
- **Out of scope (YAGNI):** a full delegation playbook (when/how to delegate,
  choosing a subagent, parallel vs sequential dispatch); any code change to the
  agent loop or `task` tool (they already work correctly); the separate,
  non-repo skill wording that said "wait for them to report back"; and the model
  choice itself (this helps weak models but does not replace using a stronger
  one for orchestration).

## 4. Testing

Animation-free, deterministic prompt content — assert it renders:

- A render test: `render_template("core_agent_system.jinja")` (no kwargs needed —
  the Jinja env uses lenient `Undefined`, verified to render cleanly) contains
  the `<subagents>` block and its key phrases, e.g. `"synchronous"` and
  `"Never end your turn"`.
- The block is placed after `<todo_management>` — assert ordering if convenient
  (the `<subagents>` opening tag appears after the `<todo_management>` closing
  tag in the rendered output).
- Existing prompt/system-prompt tests still pass (no other block changed).

## 5. Files touched

- Modify: `novacode_cli/prompts/core_agent_system.jinja` (add the `<subagents>`
  block).
- Test: `tests/test_core_prompt_subagents.py` (new) — the render assertions above.

# nova-context-plugin

A Nova plugin that injects dynamic context (timestamp, workspace name, and custom variables) into every model call's system prompt, keeping the agent aware of its environment.

**Version:** 0.1.0

---

## Overview

| Contribution | What it adds |
|--------------|-------------|
| **middleware** `ContextInjectionMiddleware` | Injects a dynamic context block into the system prompt before each model call via `wrap_model_call`. Includes UTC timestamp, day of week, workspace name, and any custom context variables. |
| **tool** `read_context` | Inspect the current context variables and see exactly what block is injected into the system prompt. |
| **command** `/context` | View or set custom context variables at runtime. |
| **subagent** `context-writer` | A delegate agent that researches and saves context snippets for the session. |

---

## Install

```bash
uv pip install -e plugins/nova-context-plugin
```

## Enable

In Nova: `/plugins` → select **nova-context-plugin** → Enable → restart session.

---

## Usage

### Middleware — Automatic Context Injection

Once enabled, every model call automatically receives a context block appended to the system prompt. No action needed.

The injected block looks like:

```
--- dynamic context (nova-context-plugin) ---
Current timestamp (UTC): 2025-07-15 14:30:00
Day of week: Tuesday
Workspace: my-project
Custom context variables:
  topic = python-async
  language = rust
--- end dynamic context ---
```

The middleware uses `wrap_model_call` (registered in the `before_shell` slot) to:
1. Read the existing system message content blocks.
2. Build a context block from the current time, workspace, and custom variables.
3. Append the context block as a new text content block.
4. Return an overridden request via `handler(request.override(system_message=new_system))`.

### Tool — `read_context`

The agent can inspect the current context at any time:

```
read_context()
```

Returns the full context block that would be injected on the next model call, including timestamp, workspace, and any custom variables.

### Command — `/context`

View or set custom context variables:

```
# View current context
/context
→ Current context injection state:
  --- dynamic context (nova-context-plugin) ---
  Current timestamp (UTC): 2025-07-15 14:30:00
  ...

# Set custom variables
/context topic=python-async language=rust
→ ✅ Set 2 custom context variable(s). They will appear in the system prompt on the next model call.

# Override a variable
/context topic=python-sync
→ ✅ Set 1 custom context variable(s).
```

### Subagent — `context-writer`

The `context-writer` subagent is a specialist that researches and saves context snippets. Invoke it by asking the agent:

> "Use the context-writer subagent to set the current project's tech stack as context."

The subagent will:
1. Call `read_context()` to check what context is already set.
2. Use the `/context` command to set any new context variables you request.
3. Output a brief summary of the context state.

---

## Configuration

Context variables are stored in a global mutable dictionary (`_context_vars: dict[str, str]`). They persist for the lifetime of the Nova process and can be modified at any time via the `/context` command.

| Setting | Type | Default | Description |
|---------|------|---------|-------------|
| `_context_vars` | `dict[str, str]` | `{}` | Custom key-value pairs injected into the system prompt |

---

## Source Code Details

### Context Block Assembly

```python
def _build_context_block() -> str:
    now = datetime.now(timezone.utc)
    parts = [
        "--- dynamic context (nova-context-plugin) ---",
        f"Current timestamp (UTC): {now.strftime('%Y-%m-%d %H:%M:%S')}",
        f"Day of week: {now.strftime('%A')}",
        f"Workspace: {Path.cwd().name}",
    ]
    if _context_vars:
        parts.append("Custom context variables:")
        for k, v in _context_vars.items():
            parts.append(f"  {k} = {v}")
    parts.append("--- end dynamic context ---")
    return "\n".join(parts)
```

### Middleware: `ContextInjectionMiddleware`

Uses `wrap_model_call` to inject context into the system prompt:

```python
class ContextInjectionMiddleware(AgentMiddleware):
    def wrap_model_call(self, request, handler):
        context_block = _build_context_block()
        existing_blocks = list(request.system_message.content_blocks)
        new_content = existing_blocks + [{"type": "text", "text": context_block}]
        new_system = SystemMessage(content=new_content)
        return handler(request.override(system_message=new_system))
```

Both sync (`wrap_model_call`) and async (`awrap_model_call`) paths are implemented with identical logic.

### Entry Point

```python
def register() -> dict[str, Any]:
    return {
        "name": "nova-context-plugin",
        "version": "0.1.0",
        "description": "Injects dynamic context (time, workspace, custom vars)...",
        "tools": [read_context],
        "commands": [{"name": "context", "description": "...", "handler": context_command}],
        "middleware": [{"instance": ContextInjectionMiddleware(), "slot": "before_shell"}],
        "subagents": [{"name": "context-writer", "description": "...", "prompt": "...", "tools": [read_context]}],
    }
```

---

## Package Structure

```
plugins/nova-context-plugin/
├── pyproject.toml
├── README.md
└── src/nova_context_plugin/
    └── __init__.py          # ContextInjectionMiddleware, read_context, context_command, context-writer subagent, register()
```

---

## Examples

### Keep the agent aware of the current task

```
/context task=implementing-auth-flow
```

Now every model call includes `task = implementing-auth-flow` in the system prompt, helping the agent stay focused.

### Environment-specific context

```
/context os=linux python_version=3.12 cuda_version=12.1
```

### Agent-driven context setting

> "Set the context to note that we're working on the payment API."

The agent can call `read_context()` to check current state, then use `/context` to set new values.

---

## See Also

- [Middleware.md](../Middleware.md) — Custom middleware API reference (see `wrap_model_call` docs)
- [nova-audit-plugin](../nova-audit-plugin/README.md) — Companion plugin for tool audit trail
- [nova-shell-compact-plugin](../nova-shell-compact-plugin/README.md) — Compacts long shell outputs to save tokens
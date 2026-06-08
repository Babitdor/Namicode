# nova-audit-plugin

A Nova plugin that records every tool call and result into a thread-safe, in-memory circular buffer, making the full audit trail queryable at runtime.

**Version:** 0.1.0

---

## Overview

| Contribution | What it adds |
|--------------|-------------|
| **middleware** `ToolAuditMiddleware` | Intercepts every tool call/result via `awrap_tool_call`. Records the tool name, arguments preview, timestamp, status (success/error), and error messages. |
| **tool** `tool_audit` | Query the audit trail by tool name, status, or recency. Returns formatted entries with timestamps. |
| **command** `/audit` | View recent tool activity directly in the REPL/TUI with `--tool`, `--status`, and `--limit` filters. |
| **subagent** `auditor` | A delegate agent that analyzes tool usage patterns — calls `tool_audit` and produces a bullet-point report. |

---

## Install

```bash
uv pip install -e plugins/nova-audit-plugin
```

## Enable

In Nova: `/plugins` → select **nova-audit-plugin** → Enable → restart session.

Commands work immediately; the middleware, tool, and subagent take effect after restart.

---

## Usage

### Middleware — Automatic Recording

Once enabled, every tool call is automatically recorded. No action needed.

The middleware hooks into the `before_tools` slot, wrapping every tool call:

- **On call:** Records `tool.call` event with tool name, args preview (first 200 chars), and UTC timestamp.
- **On success:** Records `tool.result` event with status `"success"`.
- **On error:** Records `tool.result` event with status `"error"` and error message (first 200 chars), then re-raises the exception.

### Tool — `tool_audit`

The agent can query the audit trail at any time:

```
# Show last 10 entries (default)
tool_audit()

# Show last 20 entries for the "shell" tool
tool_audit(tool_name="shell", limit=20)

# Show only failed tool calls
tool_audit(status="error", limit=50)

# Show results for "read_file" that succeeded
tool_audit(tool_name="read_file", status="success")
```

**Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `tool_name` | `str \| None` | `None` | Filter by tool name (e.g. `"shell"`, `"read_file"`) |
| `status` | `str \| None` | `None` | Filter by result status (`"success"` or `"error"`) |
| `limit` | `int` | `10` | Max entries to return (capped at 50) |

**Example output:**

```
Tool audit trail (last 3 of 15):
  [14:30:22] CALL  shell(ls -la /workspace)
  [14:30:23] RESULT shell → success
  [14:30:25] CALL  read_file(path="/workspace/README.md")
```

### Command — `/audit`

View recent tool activity in the REPL/TUI:

```
/audit
→ Last 10 tool calls ...

/audit --tool shell
→ All shell tool calls

/audit --status error
→ All failed tool calls

/audit --tool read_file --limit 5
→ Last 5 read_file calls
```

**Options:**

| Option | Description |
|--------|-------------|
| `--tool <name>` | Filter by tool name |
| `--status <success\|error>` | Filter by result status |
| `--limit <N>` | Number of entries to show (default: 10) |

### Subagent — `auditor`

The `auditor` subagent is a specialist that analyzes the tool usage audit trail. Invoke it by asking the agent:

> "Use the auditor subagent to analyze my tool usage patterns."

The subagent will:
1. Call `tool_audit(limit=50)` to fetch recent tool activity.
2. Summarize which tools were used, how often, and whether any failed.
3. Flag any patterns worth noting (e.g. repeated errors, excessive shell usage).
4. Output a concise bullet-point report.

---

## Configuration

The audit buffer is configured at the module level:

| Setting | Default | Description |
|---------|---------|-------------|
| `_MAX_AUDIT_ENTRIES` | `500` | Maximum number of audit entries kept in the circular buffer. Oldest entries are evicted when capacity is exceeded. |

These are compile-time constants — change them in the source if you need a different buffer size.

---

## Source Code Details

### Thread Safety

The audit buffer uses a `threading.Lock` to protect concurrent access. This is important because the agent graph loop runs asynchronously, while some callers may be synchronous. The `_push_entry()` function acquires the lock before appending and evicting.

### Circular Buffer

```python
_MAX_AUDIT_ENTRIES = 500
_audit_lock = threading.Lock()
_audit_buffer: list[dict[str, Any]] = []

def _push_entry(entry: dict[str, Any]) -> None:
    global _audit_buffer
    with _audit_lock:
        _audit_buffer.append(entry)
        if len(_audit_buffer) > _MAX_AUDIT_ENTRIES:
            _audit_buffer = _audit_buffer[-_MAX_AUDIT_ENTRIES:]
```

### Middleware: `ToolAuditMiddleware`

Registered in the `before_tools` slot, wrapping every tool call:

```python
class ToolAuditMiddleware(AgentMiddleware):
    async def awrap_tool_call(self, request, handler):
        # Record the call
        _push_entry({"event": "tool.call", "tool": tool_name, ...})
        try:
            result = await handler(request)
            _push_entry({"event": "tool.result", "status": "success", ...})
            return result
        except Exception as exc:
            _push_entry({"event": "tool.result", "status": "error", ...})
            raise
```

### Entry Point

```python
def register() -> dict[str, Any]:
    return {
        "name": "nova-audit-plugin",
        "version": "0.1.0",
        "description": "Records every tool call/result...",
        "tools": [tool_audit],
        "commands": [{"name": "audit", "description": "...", "handler": audit_command}],
        "middleware": [{"instance": ToolAuditMiddleware(), "slot": "before_tools"}],
        "subagents": [{"name": "auditor", "description": "...", "prompt": "...", "tools": [tool_audit]}],
    }
```

---

## Package Structure

```
plugins/nova-audit-plugin/
├── pyproject.toml
├── README.md
└── src/nova_audit_plugin/
    └── __init__.py          # ToolAuditMiddleware, tool_audit, audit_command, auditor subagent, register()
```

---

## Examples

### Track down failing tools

```
/audit --status error --limit 20
→ Shows the last 20 failed tool calls with error messages
```

### Agent-driven analysis

> "What tools have been used so far in this session?"

The agent calls `tool_audit()` and summarizes the results.

### Deep analysis with the auditor subagent

> "Use the auditor subagent to check if I've been using too many shell commands."

The subagent fetches the trail and reports on usage patterns.

---

## See Also

- [Middleware.md](../Middleware.md) — Custom middleware API reference
- [nova-context-plugin](../nova-context-plugin/README.md) — Companion plugin for context injection
- [nova-shell-compact-plugin](../nova-shell-compact-plugin/README.md) — Compacts long shell outputs to save tokens
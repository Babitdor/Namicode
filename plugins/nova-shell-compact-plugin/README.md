# nova-shell-compact-plugin

Compacts long **shell** tool outputs before they're fed back to the agent, saving tokens while preserving the head, tail, and key signals (errors, exit codes, tracebacks).

**Version:** 0.1.0

---

## Overview

| Contribution | What it does |
|--------------|-------------|
| **middleware** `ShellCompactMiddleware` | Intercepts every tool call result via `wrap_tool_call`. If the tool is `"shell"` and its output exceeds a configurable threshold, the middle section is truncated — head and tail are kept, plus any lines containing errors, tracebacks, or exit codes. |
| **command** `/shell-compact` | View or change the compaction configuration at runtime — threshold, head lines, tail lines, and enable/disable toggle. |

---

## Install

```bash
uv pip install -e plugins/nova-shell-compact-plugin
```

## Enable

In Nova: `/plugins` → select **nova-shell-compact-plugin** → Enable → restart session.

---

## Usage

### Middleware — Automatic Compaction

Once enabled, long shell outputs are automatically compacted. No action needed.

When a shell command produces output exceeding the threshold, the middleware:

1. **Preserves the first N lines** (head) — default: 20.
2. **Preserves the last N lines** (tail) — default: 10.
3. **Preserves any error lines** — lines matching `error`, `Error`, `ERROR`, `traceback`, `exception`, `fail`, or `exit <code>` anywhere in the output.
4. **Replaces the middle** with a compact summary header showing original vs. compacted size.

**Example compacted output:**

```
[compact: 2431→847 chars, showing 20 head + 10 tail + 3 error lines, omitted 412 lines]

total 42
drwxr-xr-x  12 user  staff    384 Jul 15 14:30 .
drwxr-xr-x   5 user  staff    160 Jul 15 14:00 ..
...
… [truncated]
── key error lines ──
Error: something went wrong in module.py:42
── end error lines ──
… [resumed]
drwxr-xr-x   2 user  staff     64 Jul 15 14:30 node_modules
```

### Command — `/shell-compact`

View or change the compaction configuration:

```
# Show current configuration
/shell-compact
→ ShellCompact configuration:
    enabled:   True
    threshold: 1500 chars
    head:      20 lines
    tail:      10 lines

# Change the character threshold
/shell-compact 1000
→ ✅ ShellCompact updated:
    enabled:   True
    threshold: 1000 chars
    head:      20 lines
    tail:      10 lines

# Change head/tail lines
/shell-compact --head 50 --tail 20
→ ✅ ShellCompact updated:
    enabled:   True
    threshold: 1500 chars
    head:      50 lines
    tail:      20 lines

# Enable/disable compaction
/shell-compact --off
→ ✅ ShellCompact updated:
    enabled:   False
    ...

/shell-compact --on
→ ✅ ShellCompact updated:
    enabled:   True
    ...
```

---

## Configuration

| Setting | Default | Description |
|---------|---------|-------------|
| `threshold` | `1500` chars | Outputs longer than this many characters are compacted |
| `head_lines` | `20` | Number of leading lines to preserve |
| `tail_lines` | `10` | Number of trailing lines to preserve |
| `enabled` | `True` | Master toggle — set to `False` to disable all compaction |

All settings are mutable at runtime via the `/shell-compact` command.

---

## Source Code Details

### Compaction Algorithm

The `_compact_output()` function implements the core logic:

1. **Check threshold** — If `len(output) <= threshold` or `enabled == False`, return the original output unchanged.
2. **Split into lines** — Preserve line endings with `splitlines(keepends=True)`.
3. **Identify error lines** — Scan all lines for the regex pattern `(?i)(error|traceback|exception|fail|exit \d)`.
4. **Build compacted output:**
   - Header showing original → compacted char count, head/tail/error line counts, and omitted line count.
   - Head lines (first N).
   - Truncation marker (`… [truncated]`).
   - Error lines outside head/tail range (with `── key error lines ──` markers).
   - Resumption marker (`… [resumed]`).
   - Tail lines (last N).
5. **Update header** — Replace the placeholder char count with the actual compacted char count.

### Middleware: `ShellCompactMiddleware`

Registered in the `after_tools` slot, running after the tool executes but before the result reaches the agent loop:

```python
class ShellCompactMiddleware(AgentMiddleware):
    def wrap_tool_call(self, request, handler):
        result = handler(request)
        tool_name = request.tool_call.get("name", "")
        if tool_name == "shell" and isinstance(result, ToolMessage):
            original = result.content if isinstance(result.content, str) else ""
            compacted = _compact_output(original, tool_name)
            if compacted != original:
                result = ToolMessage(
                    content=compacted,
                    tool_call_id=result.tool_call_id,
                    name=result.name,
                    status=result.status,
                    artifact=result.artifact,
                )
        return result
```

Both sync (`wrap_tool_call`) and async (`awrap_tool_call`) paths are implemented. The async variant delegates to the sync implementation.

### Error Pattern Detection

```python
error_pattern = re.compile(r"(?i)(error|traceback|exception|fail|exit \d)")
```

This case-insensitive pattern catches:
- `error`, `Error`, `ERROR`
- `traceback`, `Traceback`, `TRACEBACK`
- `exception`, `Exception`, `EXCEPTION`
- `fail`, `Fail`, `FAIL`
- `exit 0`, `exit 1`, `exit 42`, etc.

### Entry Point

```python
def register() -> dict[str, Any]:
    return {
        "name": "nova-shell-compact-plugin",
        "version": "0.1.0",
        "description": "Compacts long shell tool outputs before they reach the agent...",
        "tools": [],
        "commands": [{"name": "shell-compact", "description": "...", "handler": shell_compact_command}],
        "middleware": [{"instance": ShellCompactMiddleware(), "slot": "after_tools"}],
        "subagents": [],
    }
```

---

## Package Structure

```
plugins/nova-shell-compact-plugin/
├── pyproject.toml
├── README.md
└── src/nova_shell_compact_plugin/
    └── __init__.py          # _compact_output, ShellCompactMiddleware, shell_compact_command, register()
```

---

## Examples

### Before and After

**Without plugin** (1500+ char output sent to LLM as-is):

```
$ find /workspace -name "*.py"
/src/main.py
/src/utils.py
... 500+ more lines ...
```

**With plugin** (compacted to head + tail + errors):

```
[compact: 24310→1247 chars, showing 20 head + 10 tail + 3 error lines, omitted 487 lines]

/src/main.py
/src/utils.py
...
… [truncated]
── key error lines ──
Error: /src/broken.py:42 syntax error
── end error lines ──
… [resumed]
/src/views/end.py
```

### Adjusting for Different Workflows

- **Code review sessions:** Increase `--head 100 --tail 30` to see more context.
- **Build/deploy logs:** Keep `--head 20 --tail 10` but lower `threshold 500` to catch verbose build output.
- **Debugging:** Set `--off` to see full output, then `--on` when done.

---

## See Also

- [Middleware.md](../Middleware.md) — Custom middleware API reference (see `wrap_tool_call` docs)
- [nova-audit-plugin](../nova-audit-plugin/README.md) — Companion plugin for tool audit trail
- [nova-context-plugin](../nova-context-plugin/README.md) — Companion plugin for context injection
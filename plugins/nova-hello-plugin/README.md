# nova-hello-plugin (example)

A minimal, working **Nova plugin** that demonstrates every extension point:

| Contribution | What it adds |
|--------------|--------------|
| **tool** `greet` | the agent can call it to greet someone |
| **command** `/hello [name]` | a slash command you type in the TUI/REPL |
| **middleware** `HelloMiddleware` | wraps every model call (logs it) |
| **subagent** `greeter` | a delegate agent dispatchable via the `task` tool |

## Install

From the Nova repo root, into Nova's environment:

```bash
uv pip install -e examples/nova-hello-plugin
# or:  pip install -e examples/nova-hello-plugin
```

This registers the `nova.plugins` entry point so Nova can discover it. Installing
does **not** activate it — plugins are opt-in.

## Enable

In Nova:

```
/plugins
```

Select **nova-hello-plugin**, press **Enable / Disable**, then **restart the
session**.

- `/hello` works immediately after enabling (commands are loaded on enable).
- The tool, middleware, and subagent are wired in when the agent graph is built,
  so they take effect after the **restart**.

## Try it

```
/hello Ada
→ 👋 Hello, Ada! This /hello command comes from nova-hello-plugin.

use the greet tool on Bob
→ (the agent calls greet → "Hello, Bob! 👋 (from nova-hello-plugin)")

ask the greeter subagent to welcome the team
→ (the agent dispatches the `greeter` subagent via task)
```

## How it works

`register()` (in `src/nova_hello_plugin/__init__.py`) returns a dict; Nova's
loader injects each part:

- `tools` → appended to the agent's tools (deduped by name)
- `commands` → registered in both the TUI and the REPL (built-ins always win)
- `middleware` → inserted at the requested `slot` (here `before_shell`)
- `subagents` → added to the delegate-agent list before the graph is built

See `docs/plugins.md` for the full contract, the available slots, and lifecycle
hooks.

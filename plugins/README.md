# Nova Plugins

A collection of plugins for the [Nova](https://github.com/nova-ai) agent framework. Each plugin is a pip-installable Python package that extends Nova with middleware, tools, commands, and/or subagents.

---

## Plugin Index

| Plugin | Description | Key Features |
|--------|-------------|--------------|
| [nova-hello-mw](./src/nova_hello_mw/README.md) | Demo middleware that prints "Hello, World!" before every model call | Stub middleware, `before_shell` slot |
| [nova-audit-plugin](./nova-audit-plugin/README.md) | Tool audit trail — records every tool call/result | `ToolAuditMiddleware`, `tool_audit` query tool, `/audit` command, `auditor` subagent |
| [nova-context-plugin](./nova-context-plugin/README.md) | Dynamic context injection into every model call | `ContextInjectionMiddleware`, `read_context` tool, `/context` command, `context-writer` subagent |
| [nova-mw-builder-plugin](./nova-mw-builder-plugin/README.md) | Meta-plugin that generates other middleware plugins | `mw-builder` subagent, `scaffold_middleware_plugin` tool, `/mw-build` command |
| [nova-shell-compact-plugin](./nova-shell-compact-plugin/README.md) | Compacts long shell tool outputs to save tokens | `ShellCompactMiddleware`, `/shell-compact` command, configurable threshold/head/tail |

---

## Quick Start

### Install all plugins

```bash
# From the plugins/ directory
uv pip install -e ./nova-hello-mw
uv pip install -e ./nova-audit-plugin
uv pip install -e ./nova-context-plugin
uv pip install -e ./nova-mw-builder-plugin
uv pip install -e ./nova-shell-compact-plugin
```

### Enable a plugin

In Nova, run `/plugins`, select the plugin, click **Enable**, then restart the session.

### Verify

After restart, check that the plugin is active:

```
/plugins
```

---

## Architecture

Each plugin follows the same structure:

```
plugins/<name>/
├── pyproject.toml              # Package metadata + nova.plugins entry point
├── README.md                   # Documentation
└── src/<package_name>/
    └── __init__.py             # Middleware class(es), tool(s), command(s), subagent(s), register()
```

The `register()` function in each `__init__.py` returns a plugin spec dictionary:

```python
{
    "name": "plugin-name",
    "version": "0.1.0",
    "description": "...",
    "tools": [...],          # @tool-decorated functions
    "commands": [...],       # {name, description, handler} dicts
    "middleware": [          # {instance, slot} dicts
        {"instance": MyMiddleware(), "slot": "before_shell"},
    ],
    "subagents": [...],      # {name, description, prompt, tools} dicts
}
```

### Middleware Slots

| Slot | Position | Use Case |
|------|----------|----------|
| `before_shell` | Early — before ShellMiddleware | Context injection, logging |
| `before_tools` | Before tool execution | Monitoring, auditing |
| `after_tools` | After tool execution | Compacting results, post-processing |

### Middleware Hook Types

| Hook | Type | When It Runs |
|------|------|-------------|
| `before_agent` | Node-style | Once before the agent starts |
| `before_model` | Node-style | Before each model call |
| `after_model` | Node-style | After each model response |
| `after_agent` | Node-style | Once after the agent completes |
| `wrap_model_call` | Wrap-style | Around each model call |
| `wrap_tool_call` | Wrap-style | Around each tool call |

See [Middleware.md](./Middleware.md) for the full custom middleware API reference.

---

## Development

### Creating a new plugin

Use the **nova-mw-builder-plugin** to scaffold a new middleware plugin from a natural-language description:

```
/mw-build a middleware that logs every tool call to a file
```

Or ask the agent directly:

> "Use the mw-builder subagent to create a middleware plugin called nova-rate-limiter that limits shell commands to 5 per minute, using before_model with can_jump_to=['end']"

### Plugin conventions

- Package names use underscores: `nova_hello_mw`
- Plugin names use kebab-case: `nova-hello-mw`
- Entry point name matches the plugin name: `nova-hello-mw = "nova_hello_mw:register"`
- Middleware class names are PascalCase: `HelloMwMiddleware`
- Loggers follow the pattern: `nova.plugins.<short-name>`

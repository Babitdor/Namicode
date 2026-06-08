# nova-mw-builder-plugin

A **meta-plugin** for Nova that generates other middleware plugins. Describe what you want in natural language, and the **mw-builder** subagent scaffolds a complete, installable Nova middleware plugin — including `pyproject.toml`, package directory, middleware class, and `register()` entry point.

**Version:** 0.1.0

---

## Overview

| Contribution | What it does |
|--------------|-------------|
| **subagent** `mw-builder` | Takes a natural-language description and generates a full middleware plugin. Knows the complete [Middleware.md](../Middleware.md) contract — hook types, slots, and plugin structure. |
| **tool** `scaffold_middleware_plugin` | Writes the plugin files to disk. The subagent calls this, but you can also invoke it directly. |
| **command** `/mw-build` | Quick way to describe a middleware and dispatch the builder. |

---

## Install

```bash
uv pip install -e plugins/nova-mw-builder-plugin
```

## Enable

In Nova: `/plugins` → select **nova-mw-builder-plugin** → Enable → restart session.

---

## Usage

### Quick Start — `/mw-build`

```
/mw-build a middleware that logs every tool call to a file
```

This records the description and tells you how to invoke the mw-builder subagent. Then ask the agent:

> "Use the mw-builder subagent to create a middleware that logs every tool call to a file."

### Using the Subagent Directly

Just tell the agent what you want:

> "Scaffold a middleware plugin called nova-tool-logger that logs every tool call, using wrap_tool_call."

The subagent will:
1. Ask clarifying questions if the description is ambiguous (e.g., which hook type, whether you want a tool or command, what slot to use).
2. Call `scaffold_middleware_plugin` with the right parameters to generate the plugin files on disk.
3. Print the plugin structure and install instructions.

### Using the Tool Directly

The `scaffold_middleware_plugin` tool can also be called directly:

```python
scaffold_middleware_plugin(
    plugin_name="nova-rate-limiter",
    description="Limits shell commands to 5 per minute using before_model with can_jump_to=['end']",
    hook_type="before_model",
    slot="before_shell",
    include_tool=True,
    include_command=True,
    output_dir="/workspace/plugins/nova-rate-limiter",
)
```

---

## Tool Reference: `scaffold_middleware_plugin`

### Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `plugin_name` | `str` | (required) | Short kebab-case name, e.g. `"nova-my-mw"` |
| `description` | `str` | (required) | One-line description of what the middleware does |
| `hook_type` | `str` | `"wrap_model_call"` | Which middleware hook to implement. See [Hook Types](#hook-types) below. |
| `slot` | `str` | `""` (auto) | Middleware slot in the stack. Auto-chosen from hook_type if empty. |
| `include_tool` | `bool` | `False` | If `True`, include a stub `@tool` in the plugin |
| `include_command` | `bool` | `False` | If `True`, include a stub `/command` in the plugin |
| `output_dir` | `str` | `""` (auto) | Directory to create the plugin in. Defaults to `CWD/plugins/<plugin_name>` |

### Hook Types

| Hook | Type | When It Runs | Best For |
|------|------|-------------|----------|
| `before_agent` | Node-style | Once before the agent starts | Setup, initialization |
| `before_model` | Node-style | Before each model call | Rate limiting, guardrails (can use `can_jump_to=["end"]`) |
| `after_model` | Node-style | After each model response | Logging, monitoring, response tracking |
| `after_agent` | Node-style | Once after the agent completes | Teardown, cleanup |
| `wrap_model_call` | Wrap-style | Around each model call | Context injection, retry, dynamic model switching |
| `wrap_tool_call` | Wrap-style | Around each tool call | Monitoring, output compaction, permissions |

### Slot Auto-Selection

| Hook Type | Auto-Selected Slot |
|-----------|-------------------|
| `wrap_model_call` | `before_shell` |
| `wrap_tool_call` | `after_tools` |
| `before_agent` / `before_model` | `before_shell` |
| `after_model` / `after_agent` | `after_tools` |

### Available Slots

| Slot | Position | Use Case |
|------|----------|----------|
| `before_shell` | Early — before ShellMiddleware | Context injection, logging |
| `before_tools` | Before tool execution | Monitoring, auditing |
| `after_tools` | After tool execution | Compacting results, post-processing |

---

## Generated Plugin Structure

When `scaffold_middleware_plugin` runs, it creates:

```
plugins/<name>/
├── pyproject.toml          # Package metadata + nova.plugins entry point
├── README.md               # Install/enable instructions
└── src/<package_name>/
    └── __init__.py         # Middleware class + register() function
```

### Generated `pyproject.toml`

```toml
[project]
name = "{package_name}"
version = "0.1.0"
description = "{description}"
requires-python = ">=3.11"
dependencies = [
    "langchain-core>=1.0",
    "langchain>=1.0",
]

[project.entry-points."nova.plugins"]
{entry_point_name} = "{module_path}"

[build-system]
requires = ["setuptools>=77"]
build-backend = "setuptools.build_meta"
```

### Generated `__init__.py`

The generated `__init__.py` contains:
- A middleware class extending `AgentMiddleware` with the chosen hook(s)
- Optional stub `@tool` function
- Optional stub async command handler
- A `register()` function returning the plugin spec

### Generated `README.md`

A minimal README with install and enable instructions.

---

## Source Code Details

### Templates

The plugin uses two string templates:

- **`PYPROJECT_TOML_TEMPLATE`** — Generates a valid `pyproject.toml` with the `nova.plugins` entry point.
- **`INIT_PY_TEMPLATE`** — Generates a complete `__init__.py` with middleware class, optional tool/command, and `register()` function.

### Hook Body Templates

Pre-defined hook body templates are stored in `HOOK_BODIES` for all six hook types. Each template includes both sync and async variants:

```python
HOOK_BODIES: dict[str, str] = {
    "before_agent": "...",   # before_agent + abefore_agent
    "before_model": "...",   # before_model + abefore_model
    "after_model": "...",    # after_model + aafter_model
    "after_agent": "...",    # after_agent + aafter_agent
    "wrap_model_call": "...", # wrap_model_call + awrap_model_call
    "wrap_tool_call": "...",  # wrap_tool_call + awrap_tool_call
}
```

### Entry Point

```python
def register() -> dict[str, Any]:
    return {
        "name": "nova-mw-builder-plugin",
        "version": "0.1.0",
        "description": "Nova plugin: a subagent that builds middleware plugins...",
        "tools": [scaffold_middleware_plugin],
        "commands": [{"name": "mw-build", "description": "...", "handler": mw_build_command}],
        "middleware": [],
        "subagents": [{"name": "mw-builder", "description": "...", "prompt": MW_BUILDER_PROMPT, "tools": [scaffold_middleware_plugin]}],
    }
```

Note: This plugin has **no middleware** — it's a meta-plugin that generates other plugins.

---

## Package Structure

```
plugins/nova-mw-builder-plugin/
├── pyproject.toml
├── README.md
└── src/nova_mw_builder_plugin/
    └── __init__.py          # Templates, scaffold_middleware_plugin tool, mw_build_command, mw-builder subagent, register()
```

---

## Examples

### Create a context injection plugin

> "Use the mw-builder subagent to create a middleware called nova-git-context that injects the current git branch and status into the system prompt, using wrap_model_call."

The subagent will scaffold `nova-git-context` with a `wrap_model_call` hook in the `before_shell` slot.

### Create a rate limiter

> "Scaffold a middleware plugin called nova-rate-limiter that limits shell commands to 5 per minute, using before_model with can_jump_to=['end'], and include a command to check the current rate limit status."

The subagent will ask clarifying questions, then generate the plugin with a `before_model` hook and a `/rate-limiter` command.

### Create an output filter

> "Build a middleware that filters sensitive information (API keys, passwords) from tool outputs, using wrap_tool_call, and include a tool to configure the filter patterns."

---

## See Also

- [Middleware.md](../Middleware.md) — Full custom middleware API reference (the subagent knows this file)
- [nova-hello-mw](../nova-hello-mw/README.md) — Example of a plugin generated by this builder
- [nova-audit-plugin](../nova-audit-plugin/README.md) — Example of a fully implemented middleware plugin with tool, command, and subagent
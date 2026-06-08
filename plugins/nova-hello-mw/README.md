# nova-hello-mw

A demo middleware plugin for Nova that prints "Hello, World!" before every model call.

**Version:** 0.1.0

---

## Overview

| Contribution | What it does |
|--------------|-------------|
| **middleware** `HelloMwMiddleware` | A stub middleware registered in the `before_shell` slot. Currently has placeholder `before_model` / `abefore_model` methods ready for implementation. |
| **entry point** `register()` | Returns the plugin spec with the middleware instance, ready for Nova to load. |

---

## Install

```bash
uv pip install -e plugins/src/nova_hello_mw
```

## Enable

In Nova: `/plugins` → select **nova-hello-mw** → Enable → restart session.

---

## Source Code

### `HelloMwMiddleware`

```python
class HelloMwMiddleware(AgentMiddleware):
    """A demo middleware that prints "Hello, World!" before every model call."""

    def before_model(self, state, runtime) -> dict[str, Any] | None:
        # TODO: implement
        return None

    async def abefore_model(self, state, runtime) -> dict[str, Any] | None:
        return self.before_model(state, runtime)
```

The class inherits from `AgentMiddleware` and implements the `before_model` hook (and its async counterpart). Currently a stub — ready for you to add custom logic.

### `register()` entry point

```python
def register() -> dict[str, Any]:
    return {
        "name": "nova_hello_mw",
        "version": "0.1.0",
        "description": "A demo middleware that prints ...",
        "tools": [],
        "commands": [],
        "middleware": [
            {
                "instance": HelloMwMiddleware(),
                "slot": "before_shell",
            },
        ],
        "subagents": [],
    }
```

---

## Extending

### Add a greeting in `before_model`

```python
def before_model(self, state, runtime) -> dict[str, Any] | None:
    print("Hello, World!")
    return None
```

### Add a tool

1. Define a `@tool` decorated function in `__init__.py`
2. Add it to the `"tools"` list in `register()`

### Add a command

1. Define a command handler function
2. Add it to the `"commands"` list in `register()`

---

## Package Structure

```
nova_hello_mw/
├── __init__.py    # Middleware class, register() entry point
├── README.md      # This file
pyproject.toml     # Package metadata and entry point config
```

## `pyproject.toml`

```toml
[project.entry-points."nova.plugins"]
nova-hello-mw = "nova_hello_mw:register"
```

This registers the plugin so Nova discovers it via the `nova.plugins` entry point group.

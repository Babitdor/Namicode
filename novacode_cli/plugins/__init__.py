"""Nova plugin system — third‑party middleware, tools, and lifecycle hooks.

Plugins are pip‑installable packages that register themselves via the
``nova.plugins`` entry point group in ``pyproject.toml``::

    [project.entry-points."nova.plugins"]
    my-plugin = "my_package:register"

The ``register()`` function returns a :class:`PluginSpec` dict describing what
the plugin provides (middleware instances, tools, hooks).  The Nova plugin
loader discovers, validates, and injects them into the agent middleware stack
at the appropriate slot.

Slot semantics
--------------

Plugins declare where their middleware should sit relative to the built‑in
layers.  A slot inserts the middleware *immediately before* the named built‑in
(see ``_SLOT_BEFORE`` in :mod:`novacode_cli.plugins.loader`). Available slots:

    ``early``           → position 0 (before every built‑in)
    ``before_security``  → before SecurityMiddleware
    ``before_bootstrap`` → before BootstrapMiddleware
    ``before_steering``  → before SteeringMiddleware
    ``before_shell``     → before ShellMiddleware
    ``before_memory``    → before AgentMemoryMiddleware
    ``tail``            → end of the stack (default)

If a slot's target middleware isn't present, the plugin middleware is appended.
This prevents ordering chaos while giving plugin authors enough flexibility to
integrate at the right point in the stack.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable, TypedDict

from langchain.agents.middleware.types import AgentMiddleware
from langchain.tools import BaseTool


# ── Plugin contract types ──────────────────────────────────────────────────


class MiddlewareSlot(TypedDict, total=False):
    """A middleware instance plus its desired position in the stack."""

    instance: AgentMiddleware
    """The middleware instance to insert."""
    slot: str
    """Slot name (``early``, ``before_security``, ``before_bootstrap``,
    ``before_steering``, ``before_shell``, ``before_memory``, ``tail``).
    Defaults to ``tail``."""


class PluginCommand(TypedDict, total=False):
    """A slash command contributed by a plugin.

    The ``handler`` is UI-agnostic: it receives the raw argument string (the
    text after ``/<name>``) and returns text to display. The loader wires it
    into both the legacy REPL command registry and the Textual TUI dispatch.
    """

    name: str
    """Command name **without** the leading slash (e.g. ``weather``)."""
    description: str
    """One-line help shown in listings."""
    handler: Callable[[str], Awaitable[str]]
    """``async (args: str) -> str`` — returns the text to render."""


class PluginSpec(TypedDict, total=False):
    """Return value from a plugin's ``register()`` function."""

    name: str
    """Short, unique plugin name (e.g. ``my-subagents``).  Used for display
    and deduplication."""
    description: str
    """Human‑readable one‑liner shown in ``/plugins list``."""
    version: str
    """Semantic version string (e.g. ``0.1.0``)."""
    middleware: list[MiddlewareSlot]
    """Middleware instances to inject, each with an optional slot hint."""
    tools: list[BaseTool]
    """Additional tools to register with the agent."""
    subagents: list[Any]
    """SubAgent specs (deepagents ``SubAgent`` dicts) to register as delegate
    agents the main agent can dispatch via the ``task`` tool."""
    commands: list[PluginCommand]
    """Slash commands to register in both the REPL and the TUI."""
    hooks: NotRequired[dict[str, Callable[..., Awaitable[None]]]]
    """Lifecycle hooks:
        ``before_agent_setup`` → called before the agent graph is built
        ``after_agent_setup``  → called after the agent graph is built
    """


# TypedDict does not natively support ``NotRequired`` on older Python; the
# field-level import works around that.  Re‑export for plugin authors.
try:
    from typing import NotRequired
except ImportError:
    from typing_extensions import NotRequired  # Python ≤3.11

    PluginSpec.__annotations__["hooks"] = NotRequired[
        dict[str, Callable[..., Awaitable[None]]]
    ]

# Convenience alias so plugin authors import from ``novacode_cli.plugins``.
PluginFactory = Callable[[], PluginSpec]
"""Type of a ``register()`` entry point.  Zero‑arg callable returning a
:class:`PluginSpec`."""


__all__ = [
    "PluginSpec",
    "PluginCommand",
    "PluginFactory",
    "MiddlewareSlot",
    "NotRequired",
]
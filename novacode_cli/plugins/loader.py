"""Entry-point discovery, validation, and injection for Nova plugins.

This module loads third-party plugins installed via ``pip`` and registered
under the ``nova.plugins`` entry-point group.  It provides:

- :func:`discover_plugins` — scan all installed packages for registered plugins
- :func:`load_enabled_plugins` — load only plugins the user has opted into
- :func:`merge_plugin_middleware` — inject middleware at the correct stack slots
- :func:`merge_plugin_tools` — append plugin tools, deduplicated by name
- Manifest management via :func:`enable_plugin` / :func:`disable_plugin`
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from novacode_cli.plugins import PluginSpec

if TYPE_CHECKING:
    from langchain.agents.middleware.types import AgentMiddleware
    from langchain.tools import BaseTool

logger = logging.getLogger("nova.plugins.loader")

# ── Slot → target middleware class name mapping ────────────────────────────

_SLOT_BEFORE: dict[str, str | None] = {
    "early": None,  # prepend at position 0
    "before_security": "SecurityMiddleware",
    "before_bootstrap": "BootstrapMiddleware",
    "before_steering": "SteeringMiddleware",
    "before_shell": "ShellMiddleware",
    "before_memory": "AgentMemoryMiddleware",
    "tail": None,  # append
    # Back-compat aliases for earlier plan names.
    "mid": "BootstrapMiddleware",  # alias of before_bootstrap
    "late": "AgentMemoryMiddleware",  # alias of before_memory
}

_MANIFEST_FILENAME = "manifest.json"


# ── Manifest (opt-in persistence) ──────────────────────────────────────────


def get_plugins_dir() -> Path:
    """Return ``~/.nova/plugins/``, creating it if needed."""
    d = Path.home() / ".nova" / "plugins"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_manifest_path() -> Path:
    """Return the manifest file path inside the plugins directory."""
    return get_plugins_dir() / _MANIFEST_FILENAME


def _read_manifest() -> dict[str, Any]:
    """Read the manifest; returns ``{"enabled": [...]}`` on success, empty otherwise."""
    path = get_manifest_path()
    if not path.exists():
        return {"enabled": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        logger.warning("Corrupt plugin manifest at %s — starting fresh", path)
        return {"enabled": []}


def _write_manifest(data: dict[str, Any]) -> None:
    """Atomically write manifest."""
    path = get_manifest_path()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(path)


def list_enabled_plugins() -> list[str]:
    """Return list of package names the user has enabled."""
    return _read_manifest().get("enabled", [])


def enable_plugin(package_name: str) -> bool:
    """Add *package_name* to the enabled set.  Returns ``False`` if already present."""
    manifest = _read_manifest()
    enabled: list[str] = manifest.get("enabled", [])
    if package_name in enabled:
        return False
    enabled.append(package_name)
    manifest["enabled"] = enabled
    _write_manifest(manifest)
    return True


def disable_plugin(package_name: str) -> bool:
    """Remove *package_name* from the enabled set.  Returns ``False`` if not found."""
    manifest = _read_manifest()
    enabled: list[str] = manifest.get("enabled", [])
    if package_name not in enabled:
        return False
    enabled.remove(package_name)
    manifest["enabled"] = enabled
    _write_manifest(manifest)
    return True


# ── Discovery ──────────────────────────────────────────────────────────────


def discover_plugins() -> list[tuple[str, PluginSpec]]:
    """Scan all installed packages for ``nova.plugins`` entry points.

    Returns:
        List of ``(package_name, plugin_spec)`` tuples for every package
        that exposes a ``nova.plugins`` entry point — **regardless** of
        whether the user has enabled it.
    """
    return _discover_entry_points()


def discover_enabled_plugins() -> list[tuple[str, PluginSpec]]:
    """Discover and return only user‑enabled plugins.

    Returns:
        List of ``(package_name, plugin_spec)`` tuples for plugins that are
        both installed **and** listed in the manifest.
    """
    enabled = set(list_enabled_plugins())
    if not enabled:
        return []
    return [(name, spec) for name, spec in _discover_entry_points() if name in enabled]


def _discover_entry_points() -> list[tuple[str, PluginSpec]]:
    """Low‑level entry‑point scan using ``importlib.metadata``."""
    results: list[tuple[str, PluginSpec]] = []
    try:
        from importlib.metadata import entry_points

        eps = entry_points(group="nova.plugins")
    except Exception:
        logger.debug("importlib.metadata.entry_points not available", exc_info=True)
        return results

    for ep in eps:
        try:
            factory = ep.load()
            spec: PluginSpec = factory() if callable(factory) else factory
            name = spec.get("name", ep.name)
            results.append((name, spec))
            logger.debug("Discovered plugin '%s' (dist=%s)", name, ep.dist.name if ep.dist else "?")
        except Exception:
            logger.warning("Failed to load plugin entry point '%s'", ep.name, exc_info=True)

    return results


# ── Injection helpers ──────────────────────────────────────────────────────


def merge_plugin_middleware(
    middlewares: list[AgentMiddleware],
    plugin_specs: list[PluginSpec],
) -> list[AgentMiddleware]:
    """Inject plugin middleware into the stack at the correct slots.

    Each plugin may declare multiple middleware entries, each with an optional
    ``slot`` hint.  The slot determines where in the stack the middleware is
    inserted relative to Nova's built‑in layers.

    Args:
        middlewares: The built middleware list (mutated in‑place).
        plugin_specs: Plugin specs from :func:`discover_enabled_plugins`.

    Returns:
        The same list (mutated) for convenience.
    """
    for _pkg_name, spec in plugin_specs:
        for mw_entry in spec.get("middleware", []):
            instance = mw_entry.get("instance")
            if instance is None:
                continue
            slot = mw_entry.get("slot", "tail")
            _inject(middlewares, instance, slot)
    return middlewares


def _inject(
    stack: list[AgentMiddleware],
    instance: AgentMiddleware,
    slot: str,
) -> None:
    """Insert *instance* into *stack* at the position indicated by *slot*."""
    slot = slot.lower().strip()

    # Positional slots first.
    if slot == "early":
        stack.insert(0, instance)
        return
    if slot == "tail":
        stack.append(instance)
        return

    # Unknown slot → warn (don't silently mis-place) and append.
    if slot not in _SLOT_BEFORE:
        logger.warning(
            "Unknown plugin middleware slot '%s' — appending at tail. Valid slots: %s",
            slot,
            ", ".join(sorted(_SLOT_BEFORE)),
        )
        stack.append(instance)
        return

    # Insert before the first built‑in with the target class name.  Robust even
    # when MCPMiddleware conditionally shifts stack indices.
    target_class = _SLOT_BEFORE[slot]
    for i, mw in enumerate(stack):
        if type(mw).__name__ == target_class:
            stack.insert(i, instance)
            return

    # Target middleware not present (e.g. conditionally added) → append.
    logger.debug(
        "Slot '%s' target '%s' not found in middleware stack — appending",
        slot,
        target_class,
    )
    stack.append(instance)


def merge_plugin_tools(
    tools: list[BaseTool],
    plugin_specs: list[PluginSpec],
) -> list[BaseTool]:
    """Append plugin tools, deduplicating by ``.name``.

    Args:
        tools: The tool list (mutated in‑place).
        plugin_specs: Plugin specs from :func:`discover_enabled_plugins`.

    Returns:
        The same list (mutated) for convenience.
    """
    existing_names = {t.name for t in tools}
    for _pkg_name, spec in plugin_specs:
        for tool in spec.get("tools", []):
            if tool.name not in existing_names:
                tools.append(tool)
                existing_names.add(tool.name)
    return tools


def merge_plugin_subagents(
    subagents: list[Any],
    plugin_specs: list[PluginSpec],
) -> list[Any]:
    """Append plugin subagent specs, deduplicating by ``name``.

    Plugin subagents become delegate agents the main agent can dispatch via the
    ``task`` tool — they're added to the list passed to ``create_deep_agent``.

    Args:
        subagents: The assembled subagent list (mutated in-place).
        plugin_specs: Plugin specs from :func:`discover_enabled_plugins`.

    Returns:
        The same list (mutated) for convenience.
    """
    existing = {
        s.get("name") for s in subagents if isinstance(s, dict) and s.get("name")
    }
    for _pkg_name, spec in plugin_specs:
        for sub in spec.get("subagents", []):
            name = sub.get("name") if isinstance(sub, dict) else getattr(sub, "name", None)
            if name and name in existing:
                logger.debug("Plugin subagent '%s' already present — skipping", name)
                continue
            subagents.append(sub)
            if name:
                existing.add(name)
    return subagents


def collect_plugin_commands(
    plugin_specs: list[PluginSpec],
) -> dict[str, dict[str, Any]]:
    """Flatten plugin slash commands into a ``{name: command}`` map.

    Names are normalized (leading ``/`` stripped). Duplicates across plugins are
    dropped (first wins) with a warning. Collisions with Nova's *built-in*
    commands are resolved at the registration sites, where built-ins win.

    Args:
        plugin_specs: Plugin specs from :func:`discover_enabled_plugins`.

    Returns:
        Mapping of command name (no slash) → the command dict (``name``,
        ``description``, ``handler``).
    """
    out: dict[str, dict[str, Any]] = {}
    for _pkg_name, spec in plugin_specs:
        for cmd in spec.get("commands", []):
            name = (cmd.get("name") or "").lstrip("/").strip()
            handler = cmd.get("handler")
            if not name or handler is None:
                logger.warning("Skipping malformed plugin command in '%s'", _pkg_name)
                continue
            if name in out:
                logger.warning(
                    "Plugin command '/%s' already registered — skipping duplicate", name
                )
                continue
            out[name] = cmd
    return out
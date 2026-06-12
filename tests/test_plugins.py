"""Tests for the Nova plugin system."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def temp_plugins_dir():
    """Fixture that patches ~/.nova/plugins/ to a temp dir."""
    with tempfile.TemporaryDirectory() as td:
        plugins_dir = Path(td) / ".nova" / "plugins"
        plugins_dir.mkdir(parents=True)
        with patch("novacode_cli.plugins.loader.get_plugins_dir", return_value=plugins_dir):
            yield plugins_dir


# ── Manifest tests ──────────────────────────────────────────────────────────


def test_manifest_created_on_enable(temp_plugins_dir):
    from novacode_cli.plugins.loader import enable_plugin, list_enabled_plugins

    # File doesn't exist before first operation
    assert not (temp_plugins_dir / "manifest.json").exists()

    enable_plugin("my-plugin")
    assert (temp_plugins_dir / "manifest.json").exists()
    assert list_enabled_plugins() == ["my-plugin"]


def test_enable_and_disable_round_trip(temp_plugins_dir):
    from novacode_cli.plugins.loader import enable_plugin, disable_plugin, list_enabled_plugins

    assert enable_plugin("my-plugin") is True
    assert list_enabled_plugins() == ["my-plugin"]

    # Calling enable again returns False (already present)
    assert enable_plugin("my-plugin") is False
    assert list_enabled_plugins() == ["my-plugin"]

    assert disable_plugin("my-plugin") is True
    assert list_enabled_plugins() == []

    # Calling disable again returns False
    assert disable_plugin("my-plugin") is False


def test_manifest_persistence_across_reloads(temp_plugins_dir):
    from novacode_cli.plugins.loader import enable_plugin, disable_plugin, list_enabled_plugins

    enable_plugin("plugin-a")
    enable_plugin("plugin-b")

    # Read back (simulates a fresh load)
    assert list_enabled_plugins() == ["plugin-a", "plugin-b"]

    # Verify raw JSON
    manifest = json.loads((temp_plugins_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest == {"enabled": ["plugin-a", "plugin-b"]}


def test_corrupt_manifest_returns_empty(temp_plugins_dir):
    from novacode_cli.plugins.loader import list_enabled_plugins

    (temp_plugins_dir / "manifest.json").write_text("not-json")
    assert list_enabled_plugins() == []


# ── Entry-point discovery tests ─────────────────────────────────────────────


def test_discover_plugins_calls_importlib_metadata():
    from novacode_cli.plugins.loader import _discover_entry_points

    # Create a fake entry point
    fake_ep = MagicMock()
    fake_ep.name = "test-plugin"
    fake_ep.dist.name = "test-plugin-pkg"

    def fake_factory():
        return {
            "name": "test-plugin",
            "description": "A test plugin",
            "version": "0.1.0",
        }

    fake_ep.load.return_value = fake_factory

    with patch("importlib.metadata.entry_points", return_value=[fake_ep]):
        results = _discover_entry_points()

    assert len(results) == 1
    name, spec = results[0]
    assert name == "test-plugin"
    assert spec["version"] == "0.1.0"


def test_discover_plugins_skips_failed_loads():
    from novacode_cli.plugins.loader import _discover_entry_points

    # Good plugin
    good_ep = MagicMock()
    good_ep.name = "good-plugin"
    good_ep.dist.name = "good-pkg"
    good_ep.load.return_value = lambda: {"name": "good-plugin"}

    # Bad plugin (raises on load)
    bad_ep = MagicMock()
    bad_ep.name = "bad-plugin"
    bad_ep.dist.name = "bad-pkg"
    bad_ep.load.side_effect = RuntimeError("oops")

    with patch("importlib.metadata.entry_points", return_value=[good_ep, bad_ep]):
        results = _discover_entry_points()

    assert len(results) == 1
    assert results[0][0] == "good-plugin"


def test_discover_enabled_plugins_only_returns_enabled(temp_plugins_dir):
    from novacode_cli.plugins.loader import discover_enabled_plugins, enable_plugin

    good_ep = MagicMock()
    good_ep.name = "enabled-plugin"
    good_ep.dist.name = "enabled-pkg"
    good_ep.load.return_value = lambda: {"name": "enabled-plugin"}

    skipped_ep = MagicMock()
    skipped_ep.name = "disabled-plugin"
    skipped_ep.dist.name = "disabled-pkg"
    skipped_ep.load.return_value = lambda: {"name": "disabled-plugin"}

    # Enable only one
    enable_plugin("enabled-plugin")

    with patch("importlib.metadata.entry_points", return_value=[good_ep, skipped_ep]):
        results = discover_enabled_plugins()

    assert len(results) == 1
    assert results[0][0] == "enabled-plugin"


# ── Middleware injection tests ──────────────────────────────────────────────


class FakeMiddleware:
    """Minimal fake middleware for testing injection logic."""

    def __init__(self, name: str):
        self.name = name


def test_merge_plugin_middleware_tail_default():
    from novacode_cli.plugins.loader import merge_plugin_middleware

    stack = [FakeMiddleware("Bootstrap")]
    mw = FakeMiddleware("plugin-mw")
    plugin_specs = [
        ("pkg", {"middleware": [{"instance": mw}]}),  # no slot → tail
    ]

    merge_plugin_middleware(stack, plugin_specs)
    assert len(stack) == 2
    assert stack[-1] is mw


def test_merge_plugin_middleware_early():
    from novacode_cli.plugins.loader import merge_plugin_middleware

    stack = [FakeMiddleware("First"), FakeMiddleware("Second")]
    mw = FakeMiddleware("plugin-mw")
    plugin_specs = [
        ("pkg", {"middleware": [{"instance": mw, "slot": "early"}]}),
    ]

    merge_plugin_middleware(stack, plugin_specs)
    assert stack[0] is mw  # inserted at position 0


def test_merge_plugin_middleware_by_class_name():
    from novacode_cli.plugins.loader import merge_plugin_middleware

    class BootstrapMiddleware:
        pass

    class ShellMiddleware:
        pass

    stack = [
        FakeMiddleware("ModelRetry"),
        BootstrapMiddleware(),
        ShellMiddleware(),
    ]
    mw = FakeMiddleware("plugin-mw")
    plugin_specs = [
        ("pkg", {"middleware": [{"instance": mw, "slot": "before_bootstrap"}]}),
    ]

    merge_plugin_middleware(stack, plugin_specs)
    # Should be inserted before BootstrapMiddleware (index 1)
    assert stack[1] is mw
    assert isinstance(stack[2], BootstrapMiddleware)


def test_merge_plugin_tools_deduplicates_by_name():
    from novacode_cli.plugins.loader import merge_plugin_tools

    tool_a = MagicMock(name="tool-a")
    tool_a.name = "tool-a"
    tool_a_dup = MagicMock(name="tool-a")
    tool_a_dup.name = "tool-a"
    tool_b = MagicMock(name="tool-b")
    tool_b.name = "tool-b"

    tools = [tool_a]
    plugin_specs = [
        ("pkg", {"tools": [tool_a_dup, tool_b]}),
    ]

    merge_plugin_tools(tools, plugin_specs)
    assert len(tools) == 2
    assert tools[0] is tool_a  # unchanged
    assert tools[1] is tool_b  # appended


# ── Slot mapping boundary cases ─────────────────────────────────────────────


def test_inject_fallback_when_target_class_missing():
    from novacode_cli.plugins.loader import _inject

    stack = [FakeMiddleware("A"), FakeMiddleware("B")]
    mw = FakeMiddleware("plugin-mw")
    _inject(stack, mw, "before_steering")  # SteeringMiddleware not in stack
    assert stack[-1] is mw  # fell back to append


def test_inject_unknown_slot_behaves_as_tail():
    from novacode_cli.plugins.loader import _inject

    stack = [FakeMiddleware("A")]
    mw = FakeMiddleware("plugin-mw")
    _inject(stack, mw, "nonexistent-slot")
    assert stack[-1] is mw


def test_slot_aliases_mid_and_late():
    """`mid` aliases before_bootstrap; `late` aliases before_memory."""
    from novacode_cli.plugins.loader import _inject

    class BootstrapMiddleware:
        pass

    class AgentMemoryMiddleware:
        pass

    stack = [FakeMiddleware("ModelRetry"), BootstrapMiddleware(), AgentMemoryMiddleware()]
    mid_mw = FakeMiddleware("mid")
    _inject(stack, mid_mw, "mid")
    assert stack[1] is mid_mw  # before BootstrapMiddleware

    stack2 = [BootstrapMiddleware(), AgentMemoryMiddleware()]
    late_mw = FakeMiddleware("late")
    _inject(stack2, late_mw, "late")
    # before AgentMemoryMiddleware (now at the end)
    assert isinstance(stack2[-1], AgentMemoryMiddleware)
    assert stack2[-2] is late_mw


# ── Subagent injection ──────────────────────────────────────────────────────


def test_merge_plugin_subagents_appends_and_dedupes():
    from novacode_cli.plugins.loader import merge_plugin_subagents

    existing = [{"name": "general-purpose"}]
    plugin_specs = [
        ("pkg", {"subagents": [{"name": "db-expert"}, {"name": "general-purpose"}]}),
    ]
    merge_plugin_subagents(existing, plugin_specs)
    names = [s["name"] for s in existing]
    assert names == ["general-purpose", "db-expert"]  # dup skipped


# ── Slash command collection ────────────────────────────────────────────────


def test_collect_plugin_commands_strips_slash_and_dedupes():
    from novacode_cli.plugins.loader import collect_plugin_commands

    async def h1(_args):
        return "one"

    async def h2(_args):
        return "two"

    plugin_specs = [
        ("pkg-a", {"commands": [{"name": "/weather", "handler": h1}]}),
        ("pkg-b", {"commands": [{"name": "weather", "handler": h2}]}),  # dup name
    ]
    cmds = collect_plugin_commands(plugin_specs)
    assert set(cmds) == {"weather"}
    assert cmds["weather"]["handler"] is h1  # first wins


def test_collect_plugin_commands_skips_malformed():
    from novacode_cli.plugins.loader import collect_plugin_commands

    async def h(_args):
        return "x"

    plugin_specs = [
        ("pkg", {"commands": [
            {"name": "good", "handler": h},
            {"name": "", "handler": h},        # no name
            {"name": "nohandler"},             # no handler
        ]}),
    ]
    cmds = collect_plugin_commands(plugin_specs)
    assert set(cmds) == {"good"}


# ── Legacy registry adapter ─────────────────────────────────────────────────


async def test_legacy_command_adapter_passes_args_and_catches_errors():
    from novacode_cli.commands import CommandContext, _make_plugin_command_handler

    captured = {}

    async def handler(args: str) -> str:
        captured["args"] = args
        return f"echo: {args}"

    adapted = _make_plugin_command_handler(handler)
    ctx = MagicMock(spec=CommandContext)
    ctx.cmd = "echo"
    ctx.cmd_args = "hello world"
    out = await adapted(ctx)
    assert captured["args"] == "hello world"
    assert out == "echo: hello world"

    # A throwing handler is caught and surfaced, not propagated.
    async def boom(_args: str) -> str:
        raise RuntimeError("nope")

    ctx2 = MagicMock(spec=CommandContext)
    ctx2.cmd = "boom"
    ctx2.cmd_args = ""
    out2 = await _make_plugin_command_handler(boom)(ctx2)
    assert "failed" in out2 and "nope" in out2
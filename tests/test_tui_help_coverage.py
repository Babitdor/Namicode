"""The TUI command table (TUI_COMMANDS) is THE registry — autocomplete,
dispatch, and /help derive from it. These tests pin the derivations and the
table's integrity (every handler must resolve to a real NovaApp method)."""

from novacode_cli.tui.app import (
    _TUI_COMMAND_ALIASES,
    _TUI_SLASH_COMMANDS,
    TUI_COMMANDS,
    NovaApp,
)


def test_help_documents_every_slash_command():
    help_str = NovaApp._help_text(None).plain
    missing = [c for c in _TUI_SLASH_COMMANDS if c not in help_str]
    assert not missing, f"commands missing from /help: {missing}"


def test_every_table_handler_resolves():
    missing = [
        f"{name} -> {spec.handler}"
        for name, spec in TUI_COMMANDS.items()
        if not hasattr(NovaApp, spec.handler)
    ]
    assert not missing, f"table handlers not found on NovaApp: {missing}"


def test_autocomplete_derived_from_table():
    for name in TUI_COMMANDS:
        assert f"/{name}" in _TUI_SLASH_COMMANDS


def test_aliases_point_at_real_commands():
    for alias, target in _TUI_COMMAND_ALIASES.items():
        assert target in TUI_COMMANDS, f"alias {alias!r} -> unknown command {target!r}"

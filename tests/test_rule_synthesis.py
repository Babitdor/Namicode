"""Tests for generalized approval-rule synthesis from a tool call."""

from __future__ import annotations

from novacode_cli.security.rule_synthesis import ProposedRule, synthesize_rule


def test_shell_multiplexer_keeps_subcommand():
    r = synthesize_rule("shell", {"command": "npm run build"})
    assert r.category == "shell"
    assert r.value == r"^\s*npm\s+run\s+build\b"
    assert r.tool_name == "shell"


def test_shell_multiplexer_stops_at_first_flag():
    r = synthesize_rule("shell", {"command": "git commit -m wip"})
    assert r.category == "shell"
    assert r.value == r"^\s*git\s+commit\b"


def test_shell_bare_program_only_first_token():
    r = synthesize_rule("shell", {"command": "pytest -q tests/"})
    assert r.category == "shell"
    assert r.value == r"^\s*pytest\b"


def test_shell_escapes_regex_metacharacters():
    r = synthesize_rule("shell", {"command": "g++ main.cpp"})
    assert r.category == "shell"
    assert r.value == r"^\s*g\+\+\b"


def test_path_generalizes_to_directory_glob():
    r = synthesize_rule("edit_file", {"file_path": "/src/app.py"})
    assert r.category == "paths"
    assert r.value == "/src/**"


def test_path_root_file_uses_root_glob():
    r = synthesize_rule("write_file", {"file_path": "/main.py"})
    assert r.category == "paths"
    assert r.value == "/**"


def test_url_generalizes_to_domain():
    r = synthesize_rule("fetch_url", {"url": "https://docs.python.org/3/library/os.html"})
    assert r.category == "domains"
    assert r.value == "docs.python.org"


def test_unknown_tool_falls_back_to_tool_tier():
    r = synthesize_rule("write_memory", {"content": "x"})
    assert r.category == "tool"
    assert r.value == "allow"
    assert r.tool_name == "write_memory"


def test_empty_command_falls_back_to_tool_tier():
    r = synthesize_rule("shell", {"command": ""})
    assert r.category == "tool"
    assert r.value == "allow"


def test_proposed_rule_is_frozen():
    r = synthesize_rule("shell", {"command": "ls"})
    assert isinstance(r, ProposedRule)
    assert r.human  # non-empty summary for the confirm UI

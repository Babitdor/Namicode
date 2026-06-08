"""Tests for hooks.py — pure functions for hook validation and env sanitization."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from novacode_cli.hooks import (
    _validate_command,
    _sanitize_env_for_hook,
    _load_hooks,
    HOOKS_FILE,
)


class TestValidateCommand:
    """_validate_command: returns None for valid, str for invalid."""

    def test_valid_simple_command(self):
        assert _validate_command(["echo", "hello"]) is None

    def test_valid_absolute_binary(self):
        assert _validate_command(["/bin/sh", "-c", "echo hi"]) is None

    def test_empty_list(self):
        err = _validate_command([])
        assert err is not None
        assert "empty" in err.lower()

    def test_not_a_list(self):
        err = _validate_command("echo hello")
        assert err is not None
        assert "list" in err.lower()

    def test_non_string_parts(self):
        err = _validate_command(["echo", 42])
        assert err is not None
        assert "string" in err.lower()

    def test_binary_not_found(self):
        err = _validate_command(["/nonexistent/binary"])
        assert err is not None
        assert "not found" in err.lower()

    def test_binary_not_on_path(self):
        err = _validate_command(["thisbinarydoesnotexist_xyz"])
        assert err is not None
        assert "not found" in err.lower() or "PATH" in err

    def test_shell_metacharacters_blocked(self):
        err = _validate_command(["echo", "hello; rm -rf /"])
        assert err is not None
        assert "metacharacter" in err.lower()

    def test_all_metacharacters_blocked(self):
        for char in "`$|;&":
            err = _validate_command(["echo", f"bad{char}stuff"])
            assert err is not None, f"Metacharacter {char!r} not blocked"


class TestSanitizeEnvForHook:
    """_sanitize_env_for_hook: strips API key env vars."""

    def test_strips_known_api_keys(self):
        env = {
            "PATH": "/usr/bin",
            "OPENAI_API_KEY": "sk-...",
            "ANTHROPIC_API_KEY": "sk-ant-...",
            "HOME": "/home/user",
        }
        result = _sanitize_env_for_hook(env)
        assert "PATH" in result
        assert "HOME" in result
        assert "OPENAI_API_KEY" not in result
        assert "ANTHROPIC_API_KEY" not in result

    def test_strips_suffix_matched_keys(self):
        env = {
            "PATH": "/usr/bin",
            "MY_CUSTOM_API_KEY": "secret",
            "SOME_TOKEN": "tok",
        }
        result = _sanitize_env_for_hook(env)
        assert "PATH" in result
        assert "MY_CUSTOM_API_KEY" not in result
        assert "SOME_TOKEN" not in result

    def test_preserves_non_secret_vars(self):
        env = {
            "PATH": "/usr/bin",
            "HOME": "/home/user",
            "USER": "test",
            "SHELL": "/bin/bash",
        }
        result = _sanitize_env_for_hook(env)
        for key in env:
            assert key in result

    def test_empty_env(self):
        assert _sanitize_env_for_hook({}) == {}

    def test_case_insensitive_suffix_matching(self):
        env = {"MY_api_key": "secret", "normal_var": "value"}
        result = _sanitize_env_for_hook(env)
        assert "MY_api_key" not in result
        assert "normal_var" in result


class TestLoadHooks:
    """_load_hooks: loads and caches hook config from HOOKS_FILE."""

    def test_no_config_file_returns_empty(self, monkeypatch):
        # Point HOOKS_FILE to a non-existent path
        monkeypatch.setattr(
            "novacode_cli.hooks.HOOKS_FILE",
            Path("/tmp/nova-test-hooks/nonexistent.json"),
        )
        # Reset the global cache
        monkeypatch.setattr("novacode_cli.hooks._hooks_config", None)
        result = _load_hooks()
        assert result == []

    def test_valid_config_file(self, monkeypatch, tmp_path):
        config = {"hooks": [{"command": ["echo", "hi"], "events": ["session.start"]}]}
        hooks_file = tmp_path / "hooks.json"
        hooks_file.write_text(json.dumps(config))
        monkeypatch.setattr("novacode_cli.hooks.HOOKS_FILE", hooks_file)
        monkeypatch.setattr("novacode_cli.hooks._hooks_config", None)
        result = _load_hooks()
        assert len(result) == 1
        assert result[0]["command"] == ["echo", "hi"]

    def test_malformed_json_returns_empty(self, monkeypatch, tmp_path):
        hooks_file = tmp_path / "hooks.json"
        hooks_file.write_text("not json")
        monkeypatch.setattr("novacode_cli.hooks.HOOKS_FILE", hooks_file)
        monkeypatch.setattr("novacode_cli.hooks._hooks_config", None)
        result = _load_hooks()
        assert result == []

    def test_non_dict_root_returns_empty(self, monkeypatch, tmp_path):
        hooks_file = tmp_path / "hooks.json"
        hooks_file.write_text(json.dumps(["not a dict"]))
        monkeypatch.setattr("novacode_cli.hooks.HOOKS_FILE", hooks_file)
        monkeypatch.setattr("novacode_cli.hooks._hooks_config", None)
        result = _load_hooks()
        assert result == []

    def test_non_list_hooks_returns_empty(self, monkeypatch, tmp_path):
        hooks_file = tmp_path / "hooks.json"
        hooks_file.write_text(json.dumps({"hooks": "not a list"}))
        monkeypatch.setattr("novacode_cli.hooks.HOOKS_FILE", hooks_file)
        monkeypatch.setattr("novacode_cli.hooks._hooks_config", None)
        result = _load_hooks()
        assert result == []

    def test_caching(self, monkeypatch, tmp_path):
        config = {"hooks": [{"command": ["echo", "first"]}]}
        hooks_file = tmp_path / "hooks.json"
        hooks_file.write_text(json.dumps(config))
        monkeypatch.setattr("novacode_cli.hooks.HOOKS_FILE", hooks_file)
        monkeypatch.setattr("novacode_cli.hooks._hooks_config", None)

        result1 = _load_hooks()
        assert len(result1) == 1

        # Change the file — cache should still return the old value
        hooks_file.write_text(json.dumps({"hooks": [{"command": ["echo", "second"]}]}))
        result2 = _load_hooks()
        assert result2[0]["command"] == ["echo", "first"]  # cached

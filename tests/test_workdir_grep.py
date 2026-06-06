"""Tests for the sandbox grep override in WorkdirSandboxBackend.

The base sandbox grep runs a plain ``grep -r`` with NO directory exclusions, so
on a real project tree it scans .venv / node_modules / .git and times out. The
wrapper overrides ``grep`` with a fast, exclusion-aware command (ripgrep first,
``grep -r`` fallback) and parses the output. These tests cover the pure command
builder + output parser (no container needed) and the async/sync grep paths via
a stub inner backend.
"""

from __future__ import annotations

from novacode_cli.integrations.workdir_backend import (
    _GREP_EXCLUDE_DIRS,
    WorkdirSandboxBackend,
)


class TestBuildGrepCommand:
    def test_prefers_rg_with_grep_fallback(self):
        cmd = WorkdirSandboxBackend._build_grep_command("TODO", "/workspace", None)
        assert "command -v rg" in cmd
        assert "rg -n --no-heading -F" in cmd
        assert "grep -rHnF" in cmd
        # No-match (exit 1) must not look like a failure.
        assert cmd.rstrip().endswith("; true")

    def test_excludes_heavy_dirs_in_both_engines(self):
        cmd = WorkdirSandboxBackend._build_grep_command("x", "/p", None)
        for d in _GREP_EXCLUDE_DIRS:
            assert f"!{d}" in cmd, d            # ripgrep exclusion glob
            assert f"--exclude-dir={d}" in cmd, d  # grep exclusion
        # The biggest offenders must be there.
        assert ".venv" in _GREP_EXCLUDE_DIRS
        assert "node_modules" in _GREP_EXCLUDE_DIRS
        assert ".git" in _GREP_EXCLUDE_DIRS

    def test_glob_adds_include_to_both(self):
        cmd = WorkdirSandboxBackend._build_grep_command("x", "/p", "*.py")
        assert "-g '*.py'" in cmd          # ripgrep include
        assert "--include='*.py'" in cmd   # grep include

    def test_pattern_is_shell_quoted(self):
        # A pattern with spaces / shell metachars must be safely quoted.
        cmd = WorkdirSandboxBackend._build_grep_command("a b; rm -rf /", "/p", None)
        assert "'a b; rm -rf /'" in cmd


class TestParseGrepOutput:
    def test_parses_path_line_text(self):
        out = "/w/a.py:12:  # TODO fix\n/w/b.py:3:x=1  # TODO\n"
        assert WorkdirSandboxBackend._parse_grep_output(out) == [
            {"path": "/w/a.py", "line": 12, "text": "  # TODO fix"},
            {"path": "/w/b.py", "line": 3, "text": "x=1  # TODO"},
        ]

    def test_keeps_colons_in_text(self):
        out = "/w/a.py:5:url = http://x"
        assert WorkdirSandboxBackend._parse_grep_output(out) == [
            {"path": "/w/a.py", "line": 5, "text": "url = http://x"},
        ]

    def test_skips_malformed_and_empty(self):
        out = "badline\n\n/w/a.py:notanumber:hi\n/w/a.py:7:ok\n"
        assert WorkdirSandboxBackend._parse_grep_output(out) == [
            {"path": "/w/a.py", "line": 7, "text": "ok"},
        ]

    def test_empty_output(self):
        assert WorkdirSandboxBackend._parse_grep_output("") == []
        assert WorkdirSandboxBackend._parse_grep_output(None) == []


class _FakeExecResult:
    def __init__(self, output: str) -> None:
        self.output = output


class _StubInner:
    """Minimal BaseSandbox-like inner that records the command and replays output."""

    id = "stub"

    def __init__(self, output: str = "") -> None:
        self.output = output
        self.last_cmd: str | None = None

    def execute(self, command, *, timeout=None):
        self.last_cmd = command
        return _FakeExecResult(self.output)

    async def aexecute(self, command, *, timeout=None):
        self.last_cmd = command
        return _FakeExecResult(self.output)


class TestGrepRoundTrip:
    def _backend(self, output: str) -> tuple[WorkdirSandboxBackend, _StubInner]:
        inner = _StubInner(output)
        be = WorkdirSandboxBackend(inner, workdir="/workspace")
        return be, inner

    def test_sync_grep_rebases_and_parses(self):
        be, inner = self._backend("/workspace/x.py:1:hit\n")
        res = be.grep("hit", path="/x.py")
        # Path rebased under the workdir.
        assert "/workspace" in (inner.last_cmd or "")
        assert res.error is None
        assert res.matches == [{"path": "/workspace/x.py", "line": 1, "text": "hit"}]

    async def test_async_grep_parses(self):
        be, _ = self._backend("/workspace/y.py:9:found\n")
        res = await be.agrep("found")
        assert res.error is None
        assert res.matches == [{"path": "/workspace/y.py", "line": 9, "text": "found"}]

    def test_grep_error_is_captured_not_raised(self):
        class _Boom(_StubInner):
            def execute(self, command, *, timeout=None):
                raise RuntimeError("exec down")

        be = WorkdirSandboxBackend(_Boom(), workdir="/workspace")
        res = be.grep("x")
        assert res.matches is None
        assert "exec down" in (res.error or "")

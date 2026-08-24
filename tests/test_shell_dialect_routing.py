"""Shell dialect auto-fallback: when the chosen shell rejects a command's SYNTAX
(e.g. bash sent to the PowerShell `shell`/`execute` tool on Windows), the command
is retried once in the other shell. Empirical — driven by the shell's own error,
not a hardcoded command list."""

from __future__ import annotations

from langchain_core.messages import ToolMessage

from novacode_cli.shell.middleware import (
    ShellMiddleware,
    _looks_like_shell_rejection,
)

PWSH = ["pwsh", "-NoProfile", "-Command"]
BASH = ["bash", "-c"]


def _err(text: str) -> ToolMessage:
    return ToolMessage(content=text, tool_call_id="1", status="error")


# ── rejection detection ──────────────────────────────────────────────────
def test_recognizes_shell_rejections():
    assert _looks_like_shell_rejection(_err("'grep' is not recognized as a cmdlet"))
    assert _looks_like_shell_rejection("bash: grep: command not found")
    assert _looks_like_shell_rejection(_err("A parameter cannot be found that matches parameter name 'rf'."))
    assert _looks_like_shell_rejection(_err("ParserError: Unexpected token '&&'"))


def test_legit_errors_are_not_rejections():
    # A command that ran and failed for real must NOT be retried in another shell.
    assert not _looks_like_shell_rejection(_err("fatal: not a git repository"))
    assert not _looks_like_shell_rejection(_err("Test failed: 3 failed, 1 passed"))
    assert not _looks_like_shell_rejection("build succeeded")
    # A non-error ToolMessage is never a rejection even if text is odd.
    assert not _looks_like_shell_rejection(
        ToolMessage(content="command not found", tool_call_id="1", status="success")
    )


# ── fallback runner ──────────────────────────────────────────────────────
def _mw(*, native_is_pwsh=True):
    mw = object.__new__(ShellMiddleware)
    mw._native_is_pwsh = native_is_pwsh
    mw._native_prog = PWSH
    mw._bash_prog = BASH
    return mw


def _install_run(mw, results: dict):
    """results maps id(prog) -> result; None prog handled separately."""
    calls = []

    def _run(command, *, tool_call_id, prog):
        calls.append(prog)
        return results[id(prog)]

    mw._run_shell_command = _run
    return calls


def test_bash_in_powershell_retries_in_bash_and_succeeds():
    mw = _mw()
    calls = _install_run(mw, {id(PWSH): _err("'grep' is not recognized as a cmdlet"), id(BASH): "matched 3 lines"})
    out = mw._run_foreground_with_fallback("grep foo *.py", tool_call_id="1", prog=PWSH)
    assert out == "matched 3 lines"
    assert calls == [PWSH, BASH]  # tried native, then bash


def test_real_error_is_not_retried():
    mw = _mw()
    calls = _install_run(mw, {id(PWSH): _err("fatal: not a git repository")})
    out = mw._run_foreground_with_fallback("git status", tool_call_id="1", prog=PWSH)
    assert isinstance(out, ToolMessage) and "not a git repository" in out.content
    assert calls == [PWSH]  # no retry


def test_both_reject_returns_original():
    mw = _mw()
    orig = _err("'frobnicate' is not recognized as a cmdlet")
    _install_run(mw, {id(PWSH): orig, id(BASH): _err("bash: frobnicate: command not found")})
    out = mw._run_foreground_with_fallback("frobnicate", tool_call_id="1", prog=PWSH)
    assert out is orig  # neither shell has it → keep the first (native) error


def test_no_fallback_off_windows():
    mw = _mw(native_is_pwsh=False)
    calls = _install_run(mw, {id(PWSH): _err("'grep' is not recognized as a cmdlet")})
    mw._run_foreground_with_fallback("grep foo x", tool_call_id="1", prog=PWSH)
    assert calls == [PWSH]  # never retries when native shell is already POSIX

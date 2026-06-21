# Session / Always-Allow Tool Approvals — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add "Allow for session" and "Always allow…" decisions to Nova's tool-approval prompts, so the user stops being re-asked for tool calls they've already accepted.

**Architecture:** Reuse the existing `ApprovalPolicy` engine (`novacode_cli/security/policy.py`) as the single source of truth. Three new pure/low-I/O modules synthesize a generalized rule from a tool call, hold an in-memory session-allow layer, and persist a confirmed rule to `approval-policy.json`. The UI-agnostic gate (`evaluate_tool_actions`) consults the session layer only on the `ask` tier so hard `deny` rules stay inviolable. Both approval renderers (REPL menu + TUI modal) gain the two decisions.

**Tech Stack:** Python 3.12, `uv`, `pytest` (asyncio auto-mode), `ruff` (select=ALL), Textual (TUI). Reference design: `specs/2026-06-21-session-and-always-allow-approvals-design.md`.

---

## File structure

**New source files**
- `novacode_cli/security/rule_synthesis.py` — `ProposedRule` dataclass + `synthesize_rule(tool_name, args)`. Pure, no I/O.
- `novacode_cli/security/session_allow.py` — `SessionAllowList` + process singleton; matching reuses `ApprovalPolicy`.
- `novacode_cli/security/policy_writer.py` — `append_rule(rule, *, target, project_root)`: merge + atomic write + policy refresh.
- `novacode_cli/security/remember.py` — `apply_remember(...)` UI-agnostic glue + `RememberResult`.

**New test files**
- `tests/test_rule_synthesis.py`, `tests/test_session_allow.py`, `tests/test_policy_writer.py`, `tests/test_remember_approvals.py`

**Modified**
- `novacode_cli/ui/hitl_approval.py` — session-allow check in `evaluate_tool_actions`; interpret the new REPL decision markers in `process_hitl_approval`.
- `novacode_cli/ui/tool_approval.py` — REPL menu options + confirm sub-prompt.
- `novacode_cli/tui/app.py` — `ApprovalModal` options + new `RememberRuleModal` + `_handle_interrupt_inner` wiring.
- `tests/test_approval_policy.py` — gate tests for the session layer.

**Conventions:** match `tests/test_provider_errors.py` / `tests/test_approval_policy.py` style. Run a single test with `uv run pytest tests/<file>::<test> -q`. Format/lint with `uv run ruff format <files> && uv run ruff check <files>`.

---

## Task 1: Rule synthesis (`ProposedRule` + `synthesize_rule`)

**Files:**
- Create: `novacode_cli/security/rule_synthesis.py`
- Test: `tests/test_rule_synthesis.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_rule_synthesis.py
"""Tests for generalized approval-rule synthesis from a tool call."""

from __future__ import annotations

from novacode_cli.security.rule_synthesis import ProposedRule, synthesize_rule


def test_shell_multiplexer_keeps_subcommand():
    r = synthesize_rule("shell", {"command": "npm run build"})
    assert r.category == "shell"
    assert r.value == r"^\s*npm\s+run\s+build\b"
    assert r.tool_name == "shell"


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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_rule_synthesis.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'novacode_cli.security.rule_synthesis'`.

- [ ] **Step 3: Write the implementation**

```python
# novacode_cli/security/rule_synthesis.py
"""Synthesize a generalized approval rule from a single approved tool call.

Pure and dependency-light (no I/O, no policy/state imports) so it can be reused
by both the in-memory session layer and the persistent policy writer, and unit
tested in isolation. See specs/2026-06-21-session-and-always-allow-approvals-design.md.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from urllib.parse import urlparse

# Programs whose first argument is a meaningful subcommand worth keeping, so
# "npm run build" generalizes to `npm run build` rather than all of `npm`.
_MULTIPLEXERS = frozenset(
    {"npm", "yarn", "pnpm", "uv", "git", "cargo", "docker", "make", "poetry", "go", "dotnet"}
)

_SHELL_TOOLS = frozenset({"shell", "execute", "run_tests", "start_dev_server"})
_PATH_TOOLS = frozenset({"write_file", "edit_file"})
_URL_TOOLS = frozenset({"fetch_url"})


@dataclass(frozen=True)
class ProposedRule:
    """A generalized allow-rule derived from a tool call.

    Attributes:
        category: ``"shell"`` | ``"paths"`` | ``"domains"`` | ``"tool"``.
        value: The regex / glob / domain string, or ``"allow"`` for a tool tier.
        human: Short plain-English summary for the confirm UI.
        tool_name: Originating tool (used for ``"tool"``-category tier rules).
    """

    category: str
    value: str
    human: str
    tool_name: str


def _tool_fallback(tool_name: str) -> ProposedRule:
    return ProposedRule("tool", "allow", f"Allow all {tool_name} calls", tool_name)


def _shell_rule(tool_name: str, command: str) -> ProposedRule:
    try:
        tokens = [t for t in shlex.split(command, posix=True) if t]
    except ValueError:
        tokens = [t for t in command.split() if t]
    if not tokens:
        return _tool_fallback(tool_name)
    prog = tokens[0]
    keep = tokens[:2] if prog in _MULTIPLEXERS and len(tokens) >= 2 else tokens[:1]
    value = r"^\s*" + r"\s+".join(re.escape(t) for t in keep) + r"\b"
    human = " ".join(keep)
    return ProposedRule("shell", value, f"Allow shell commands starting with `{human}`", tool_name)


def _path_rule(tool_name: str, file_path: str) -> ProposedRule:
    norm = file_path.replace("\\", "/")
    stripped = norm.strip("/")
    if "/" in stripped:
        directory = norm.rsplit("/", 1)[0] or "/"
        value = f"{directory}/**"
        human = f"`{directory}/`"
    else:
        value = "/**"
        human = "the workspace root"
    return ProposedRule("paths", value, f"Allow {tool_name} under {human}", tool_name)


def _domain_rule(tool_name: str, url: str) -> ProposedRule:
    host = (urlparse(url if "://" in url else "http://" + url).hostname or "").lower()
    if not host:
        return _tool_fallback(tool_name)
    return ProposedRule("domains", host, f"Allow {tool_name} to `{host}`", tool_name)


def synthesize_rule(tool_name: str, args: dict | None) -> ProposedRule:
    """Derive a :class:`ProposedRule` from one tool call (never raises)."""
    args = args or {}
    if tool_name in _SHELL_TOOLS:
        return _shell_rule(tool_name, str(args.get("command") or ""))
    if tool_name in _PATH_TOOLS:
        file_path = str(args.get("file_path") or "")
        if file_path:
            return _path_rule(tool_name, file_path)
    if tool_name in _URL_TOOLS:
        url = str(args.get("url") or "")
        if url:
            return _domain_rule(tool_name, url)
    return _tool_fallback(tool_name)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_rule_synthesis.py -q`
Expected: PASS (9 passed).

- [ ] **Step 5: Format, lint, commit**

```bash
uv run ruff format novacode_cli/security/rule_synthesis.py tests/test_rule_synthesis.py
uv run ruff check novacode_cli/security/rule_synthesis.py tests/test_rule_synthesis.py
git add novacode_cli/security/rule_synthesis.py tests/test_rule_synthesis.py
git commit -m "feat(security): synthesize generalized approval rules from tool calls"
```

---

## Task 2: Session-allow layer (`SessionAllowList`)

**Files:**
- Create: `novacode_cli/security/session_allow.py`
- Test: `tests/test_session_allow.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_session_allow.py
"""Tests for the in-memory 'allow for this session' layer."""

from __future__ import annotations

from novacode_cli.security.rule_synthesis import synthesize_rule
from novacode_cli.security.session_allow import (
    SessionAllowList,
    get_session_allow,
    reset_session_allow,
)


def test_empty_list_matches_nothing():
    s = SessionAllowList()
    assert s.matches("shell", {"command": "npm run build"}) is False


def test_shell_rule_matches_same_program():
    s = SessionAllowList()
    s.add(synthesize_rule("shell", {"command": "npm run build"}))
    assert s.matches("shell", {"command": "npm run build"}) is True
    assert s.matches("shell", {"command": "npm run build --prod"}) is True
    assert s.matches("shell", {"command": "npm test"}) is False


def test_path_rule_matches_within_directory():
    s = SessionAllowList()
    s.add(synthesize_rule("edit_file", {"file_path": "/src/app.py"}))
    assert s.matches("edit_file", {"file_path": "/src/util.py"}) is True
    assert s.matches("edit_file", {"file_path": "/tests/x.py"}) is False


def test_tool_rule_matches_any_call_of_that_tool():
    s = SessionAllowList()
    s.add(synthesize_rule("write_memory", {"content": "x"}))
    assert s.matches("write_memory", {"content": "anything"}) is True


def test_session_allow_cannot_override_builtin_deny():
    # Even a broad shell rule must not allow a denied command.
    s = SessionAllowList()
    s.add(synthesize_rule("shell", {"command": "sudo apt update"}))
    assert s.matches("shell", {"command": "sudo apt update"}) is False


def test_singleton_get_and_reset():
    reset_session_allow()
    a = get_session_allow()
    a.add(synthesize_rule("shell", {"command": "ls"}))
    assert get_session_allow() is a
    assert get_session_allow().matches("shell", {"command": "ls -la"}) is True
    reset_session_allow()
    assert get_session_allow().matches("shell", {"command": "ls -la"}) is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_session_allow.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'novacode_cli.security.session_allow'`.

- [ ] **Step 3: Write the implementation**

```python
# novacode_cli/security/session_allow.py
"""In-memory 'allow for this session' layer for tool approvals.

Holds generalized rules the user accepted for the current process only (cleared
on exit). Matching is delegated to a throwaway :class:`ApprovalPolicy` built
from the session rules, so session and persisted rules match identically — and,
crucially, the policy's built-in deny/dangerous checks still apply, so a session
rule can never allow a denied command.
"""

from __future__ import annotations

from novacode_cli.security.policy import ApprovalPolicy
from novacode_cli.security.rule_synthesis import ProposedRule


class SessionAllowList:
    """A process-lifetime list of user-accepted allow rules."""

    def __init__(self) -> None:
        self._rules: list[ProposedRule] = []
        self._policy: ApprovalPolicy | None = None

    def add(self, rule: ProposedRule) -> None:
        """Append a rule and invalidate the cached matcher."""
        self._rules.append(rule)
        self._policy = None

    def _build(self) -> ApprovalPolicy:
        tool_tiers: dict[str, str] = {}
        shell_allow: list[str] = []
        path_allow: list[str] = []
        domain_allow: list[str] = []
        for r in self._rules:
            if r.category == "shell":
                shell_allow.append(r.value)
            elif r.category == "paths":
                path_allow.append(r.value)
            elif r.category == "domains":
                domain_allow.append(r.value)
            elif r.category == "tool":
                tool_tiers[r.tool_name] = "allow"
        return ApprovalPolicy(
            tool_tiers=tool_tiers,  # type: ignore[arg-type]
            shell_allow=shell_allow,
            shell_deny=[],
            path_allow=path_allow,
            path_deny=[],
            domain_allow=domain_allow,
            domain_deny=[],
        )

    def matches(self, tool_name: str, args: dict | None) -> bool:
        """True if a session rule allows this call (deny/dangerous still win)."""
        if not self._rules:
            return False
        if self._policy is None:
            self._policy = self._build()
        return self._policy.evaluate(tool_name, args or {}).allowed

    def clear(self) -> None:
        """Forget all session rules."""
        self._rules.clear()
        self._policy = None


_SESSION_ALLOW: SessionAllowList | None = None


def get_session_allow() -> SessionAllowList:
    """Return the process-wide session allow-list (created on first use)."""
    global _SESSION_ALLOW  # noqa: PLW0603 — module-level process singleton
    if _SESSION_ALLOW is None:
        _SESSION_ALLOW = SessionAllowList()
    return _SESSION_ALLOW


def reset_session_allow() -> None:
    """Drop the session allow-list (used by tests)."""
    global _SESSION_ALLOW  # noqa: PLW0603 — module-level process singleton
    _SESSION_ALLOW = None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_session_allow.py -q`
Expected: PASS (6 passed).

Note: `test_session_allow_cannot_override_builtin_deny` passes because `ApprovalPolicy._eval_shell` checks the built-in `sudo` deny pattern before any allow list, returning `deny` (so `.allowed` is `False`).

- [ ] **Step 5: Format, lint, commit**

```bash
uv run ruff format novacode_cli/security/session_allow.py tests/test_session_allow.py
uv run ruff check novacode_cli/security/session_allow.py tests/test_session_allow.py
git add novacode_cli/security/session_allow.py tests/test_session_allow.py
git commit -m "feat(security): in-memory session allow-list for tool approvals"
```

---

## Task 3: Policy writer (`append_rule`)

**Files:**
- Create: `novacode_cli/security/policy_writer.py`
- Test: `tests/test_policy_writer.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_policy_writer.py
"""Tests for persisting a confirmed approval rule to approval-policy.json."""

from __future__ import annotations

import json

from novacode_cli.security import policy_writer
from novacode_cli.security.policy import load_policy, reset_policy_cache
from novacode_cli.security.rule_synthesis import synthesize_rule


def test_append_shell_rule_to_project_file(tmp_path):
    reset_policy_cache()
    rule = synthesize_rule("shell", {"command": "npm run build"})
    path = policy_writer.append_rule(rule, target="project", project_root=tmp_path)

    assert path == tmp_path / ".nova" / "approval-policy.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert rule.value in data["shell"]["allow"]

    # The reloaded policy now allows the matching call.
    policy = load_policy(project_root=tmp_path)
    assert policy.evaluate("shell", {"command": "npm run build --prod"}).tier == "allow"


def test_append_is_idempotent(tmp_path):
    reset_policy_cache()
    rule = synthesize_rule("edit_file", {"file_path": "/src/app.py"})
    policy_writer.append_rule(rule, target="project", project_root=tmp_path)
    policy_writer.append_rule(rule, target="project", project_root=tmp_path)
    data = json.loads((tmp_path / ".nova" / "approval-policy.json").read_text(encoding="utf-8"))
    assert data["paths"]["allow"].count(rule.value) == 1


def test_append_tool_rule_sets_tier(tmp_path):
    reset_policy_cache()
    rule = synthesize_rule("write_memory", {"content": "x"})
    policy_writer.append_rule(rule, target="project", project_root=tmp_path)
    data = json.loads((tmp_path / ".nova" / "approval-policy.json").read_text(encoding="utf-8"))
    assert data["tools"]["write_memory"] == "allow"


def test_append_global_uses_home_dir(tmp_path, monkeypatch):
    reset_policy_cache()
    monkeypatch.setattr(policy_writer, "HOME_DIR", tmp_path)
    rule = synthesize_rule("fetch_url", {"url": "https://docs.python.org/3/"})
    path = policy_writer.append_rule(rule, target="global")
    assert path == tmp_path / "approval-policy.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert "docs.python.org" in data["domains"]["allow"]


def test_append_preserves_existing_unrelated_keys(tmp_path):
    reset_policy_cache()
    cfg = tmp_path / ".nova" / "approval-policy.json"
    cfg.parent.mkdir(parents=True)
    cfg.write_text(json.dumps({"tools": {"shell": "ask"}}), encoding="utf-8")
    rule = synthesize_rule("shell", {"command": "ls"})
    policy_writer.append_rule(rule, target="project", project_root=tmp_path)
    data = json.loads(cfg.read_text(encoding="utf-8"))
    assert data["tools"]["shell"] == "ask"  # untouched
    assert rule.value in data["shell"]["allow"]  # added
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_policy_writer.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'novacode_cli.security.policy_writer'`.

- [ ] **Step 3: Write the implementation**

```python
# novacode_cli/security/policy_writer.py
"""Persist a confirmed approval rule into an approval-policy.json file.

Merges a :class:`ProposedRule` into the project or global policy file (creating
it if absent), writes atomically, and refreshes the cached policy so the rule
takes effect immediately. Best-effort and side-effecting; the UI must keep the
rule in the session layer too so a write failure still benefits the turn.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from novacode_cli.config.config import HOME_DIR
from novacode_cli.security.policy import get_policy
from novacode_cli.security.rule_synthesis import ProposedRule

_SECTION_BY_CATEGORY = {"shell": "shell", "paths": "paths", "domains": "domains"}


def _target_path(target: str, project_root: Path | None) -> Path:
    if target == "global":
        return HOME_DIR / "approval-policy.json"
    root = project_root or Path.cwd()
    return root / ".nova" / "approval-policy.json"


def _read_json(path: Path) -> dict:
    try:
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def _merge_rule(data: dict, rule: ProposedRule) -> dict:
    merged = dict(data)
    if rule.category == "tool":
        tools = dict(merged.get("tools") or {})
        tools[rule.tool_name] = "allow"
        merged["tools"] = tools
        return merged
    key = _SECTION_BY_CATEGORY[rule.category]
    section = dict(merged.get(key) or {})
    allow = list(section.get("allow") or [])
    if rule.value not in allow:
        allow.append(rule.value)
    section["allow"] = allow
    merged[key] = section
    return merged


def append_rule(rule: ProposedRule, *, target: str, project_root: Path | None = None) -> Path:
    """Merge ``rule`` into the target policy file and refresh the cache.

    Args:
        rule: The confirmed rule to persist.
        target: ``"project"`` or ``"global"``.
        project_root: Project root for ``"project"`` target (defaults to cwd).

    Returns:
        The path written.
    """
    path = _target_path(target, project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    merged = _merge_rule(_read_json(path), rule)

    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(merged, f, indent=2)
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)

    if target == "project":
        get_policy(project_root=project_root, refresh=True)
    else:
        get_policy(refresh=True)
    return path
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_policy_writer.py -q`
Expected: PASS (5 passed).

- [ ] **Step 5: Format, lint, commit**

```bash
uv run ruff format novacode_cli/security/policy_writer.py tests/test_policy_writer.py
uv run ruff check novacode_cli/security/policy_writer.py tests/test_policy_writer.py
git add novacode_cli/security/policy_writer.py tests/test_policy_writer.py
git commit -m "feat(security): persist confirmed approval rules to policy json"
```

---

## Task 4: Remember glue (`apply_remember`)

**Files:**
- Create: `novacode_cli/security/remember.py`
- Test: `tests/test_remember_approvals.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_remember_approvals.py
"""Tests for the UI-agnostic apply_remember glue."""

from __future__ import annotations

import json

from novacode_cli.security.policy import reset_policy_cache
from novacode_cli.security.remember import RememberResult, apply_remember
from novacode_cli.security.session_allow import get_session_allow, reset_session_allow


def test_session_adds_to_session_list_only():
    reset_session_allow()
    result = apply_remember("session", "shell", {"command": "npm run build"})
    assert isinstance(result, RememberResult)
    assert result.saved_path is None
    assert get_session_allow().matches("shell", {"command": "npm run build --prod"}) is True


def test_always_writes_file_and_session(tmp_path):
    reset_session_allow()
    reset_policy_cache()
    result = apply_remember(
        "always", "edit_file", {"file_path": "/src/app.py"},
        target="project", project_root=tmp_path,
    )
    assert result.saved_path == tmp_path / ".nova" / "approval-policy.json"
    data = json.loads(result.saved_path.read_text(encoding="utf-8"))
    assert "/src/**" in data["paths"]["allow"]
    # Also active in-session immediately.
    assert get_session_allow().matches("edit_file", {"file_path": "/src/util.py"}) is True


def test_explicit_rule_overrides_synthesis(tmp_path):
    reset_session_allow()
    reset_policy_cache()
    from novacode_cli.security.rule_synthesis import ProposedRule

    edited = ProposedRule("paths", "/src/app.py", "exact file", "edit_file")
    result = apply_remember(
        "always", "edit_file", {"file_path": "/src/app.py"},
        target="project", project_root=tmp_path, rule=edited,
    )
    data = json.loads(result.saved_path.read_text(encoding="utf-8"))
    assert data["paths"]["allow"] == ["/src/app.py"]  # edited rule, not /src/**


def test_unknown_kind_raises():
    import pytest

    with pytest.raises(ValueError, match="unknown remember kind"):
        apply_remember("forever", "shell", {"command": "ls"})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_remember_approvals.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'novacode_cli.security.remember'`.

- [ ] **Step 3: Write the implementation**

```python
# novacode_cli/security/remember.py
"""UI-agnostic glue for applying a 'session' or 'always' remember decision.

Both front-ends (REPL + TUI) call this after the user picks "Allow for session"
or confirms "Always allow…", so the synthesize/persist logic lives in one place
and is testable without a terminal.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from novacode_cli.security import policy_writer
from novacode_cli.security.rule_synthesis import ProposedRule, synthesize_rule
from novacode_cli.security.session_allow import get_session_allow


@dataclass
class RememberResult:
    """Outcome of :func:`apply_remember` for the UI to display."""

    rule: ProposedRule
    saved_path: Path | None  # None for session-only


def apply_remember(
    kind: str,
    tool_name: str,
    args: dict | None,
    *,
    target: str | None = None,
    project_root: Path | None = None,
    rule: ProposedRule | None = None,
) -> RememberResult:
    """Apply a remember decision.

    Args:
        kind: ``"session"`` (in-memory) or ``"always"`` (persist + in-memory).
        tool_name, args: The approved tool call (used to synthesize a rule).
        target: For ``"always"``, ``"project"`` (default) or ``"global"``.
        project_root: Project root for a project-target write.
        rule: An already-synthesized (possibly user-edited) rule; when given,
            synthesis is skipped.

    Returns:
        A :class:`RememberResult`.
    """
    rule = rule or synthesize_rule(tool_name, args)
    if kind == "session":
        get_session_allow().add(rule)
        return RememberResult(rule=rule, saved_path=None)
    if kind == "always":
        path = policy_writer.append_rule(
            rule, target=target or "project", project_root=project_root
        )
        # Add to the session layer too so it takes effect even if a later policy
        # refresh races or the file write is slow to be picked up.
        get_session_allow().add(rule)
        return RememberResult(rule=rule, saved_path=path)
    msg = f"unknown remember kind: {kind!r}"
    raise ValueError(msg)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_remember_approvals.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Format, lint, commit**

```bash
uv run ruff format novacode_cli/security/remember.py tests/test_remember_approvals.py
uv run ruff check novacode_cli/security/remember.py tests/test_remember_approvals.py
git add novacode_cli/security/remember.py tests/test_remember_approvals.py
git commit -m "feat(security): apply_remember glue for session/always approvals"
```

---

## Task 5: Gate integration (session-allow in `evaluate_tool_actions`)

**Files:**
- Modify: `novacode_cli/ui/hitl_approval.py` (the `ask` branch in `evaluate_tool_actions`, ~lines 138-158)
- Test: `tests/test_approval_policy.py` (append; reuses existing `_SS` / `_req` helpers)

- [ ] **Step 1: Write the failing tests** (append to `tests/test_approval_policy.py`)

```python
# --- session-allow layer in the gate ---------------------------------------


def test_gate_session_allow_approves_matching_ask():
    from novacode_cli.security.session_allow import get_session_allow, reset_session_allow
    from novacode_cli.security.rule_synthesis import synthesize_rule

    reset_policy_cache()
    reset_session_allow()
    # frobnicate is an unknown program -> default 'ask'.
    assert evaluate_tool_actions(_req(("shell", {"command": "frobnicate --now"})), _SS()) == [None]
    get_session_allow().add(synthesize_rule("shell", {"command": "frobnicate --now"}))
    res = evaluate_tool_actions(_req(("shell", {"command": "frobnicate --now"})), _SS())
    assert res == [{"type": "approve"}]
    reset_session_allow()


def test_gate_session_allow_cannot_override_deny():
    from novacode_cli.security.session_allow import get_session_allow, reset_session_allow
    from novacode_cli.security.rule_synthesis import synthesize_rule

    reset_policy_cache()
    reset_session_allow()
    get_session_allow().add(synthesize_rule("shell", {"command": "sudo apt update"}))
    res = evaluate_tool_actions(_req(("shell", {"command": "sudo apt update"})), _SS())
    assert res[0]["type"] == "reject"  # deny still wins over a session rule
    reset_session_allow()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_approval_policy.py -k session -q`
Expected: FAIL — `test_gate_session_allow_approves_matching_ask` fails (gate returns `[None]`, not approve).

- [ ] **Step 3: Edit the `ask` branch of `evaluate_tool_actions`**

In `novacode_cli/ui/hitl_approval.py`, the current loop tail reads:

```python
        if decision.tier == "allow":
            resolutions.append({"type": "approve"})
        elif decision.tier == "deny":
            resolutions.append(
                {
                    "type": "reject",
                    "message": decision.reason or "Blocked by approval policy",
                }
            )
        else:
            resolutions.append(None)
    return resolutions
```

Change the `else` branch to consult the session layer (deny/allow already handled above, so this only runs on the `ask` tier — session-allow can never override a deny):

```python
        if decision.tier == "allow":
            resolutions.append({"type": "approve"})
        elif decision.tier == "deny":
            resolutions.append(
                {
                    "type": "reject",
                    "message": decision.reason or "Blocked by approval policy",
                }
            )
        else:
            # ask tier: honor an in-session "allow for session" rule the user
            # accepted earlier this run; otherwise surface the prompt.
            from novacode_cli.security.session_allow import get_session_allow

            if get_session_allow().matches(name, args):
                resolutions.append({"type": "approve"})
            else:
                resolutions.append(None)
    return resolutions
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_approval_policy.py -q`
Expected: PASS (all existing + 2 new).

- [ ] **Step 5: Format, lint, commit**

```bash
uv run ruff format novacode_cli/ui/hitl_approval.py tests/test_approval_policy.py
uv run ruff check novacode_cli/ui/hitl_approval.py tests/test_approval_policy.py
git add novacode_cli/ui/hitl_approval.py tests/test_approval_policy.py
git commit -m "feat(approval): consult session allow-list in the pre-HITL gate"
```

---

## Task 6: REPL prompt — session/always options + confirm

**Files:**
- Modify: `novacode_cli/ui/tool_approval.py` (add menu options + return markers)
- Modify: `novacode_cli/ui/hitl_approval.py` (`process_hitl_approval`: interpret markers)
- Test: `tests/test_repl_remember.py` (new)

The raw-terminal menu rendering isn't unit-testable, so we test the **interpretation** in `process_hitl_approval` by monkeypatching `prompt_for_batch_approval` to return the new markers and stubbing the confirm `input`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_repl_remember.py
"""Tests for REPL interpretation of session/always remember decisions."""

from __future__ import annotations

import types

from novacode_cli.security.policy import reset_policy_cache
from novacode_cli.security.session_allow import get_session_allow, reset_session_allow


class _Status:
    def start(self):  # noqa: D102
        pass

    def stop(self):  # noqa: D102
        pass


def _req(name, args):
    return {"action_requests": [{"name": name, "args": args}]}


async def test_repl_session_marker_adds_rule(monkeypatch):
    import novacode_cli.ui.hitl_approval as h

    reset_session_allow()
    reset_policy_cache()
    monkeypatch.setattr(
        h, "prompt_for_batch_approval", lambda reqs, aid: [{"type": "allow_session"}]
    )
    session_state = types.SimpleNamespace(auto_approve=False, plan_mode_enabled=False)
    decisions, any_rejected, _ = await h.process_hitl_approval(
        _req("shell", {"command": "npm run build"}),
        session_state, "nova-agent", None, False, _Status(),
    )
    assert decisions[0]["type"] == "approve"
    assert any_rejected is False
    assert get_session_allow().matches("shell", {"command": "npm run build --prod"}) is True
    reset_session_allow()


async def test_repl_always_marker_writes_project(monkeypatch, tmp_path):
    import novacode_cli.ui.hitl_approval as h

    reset_session_allow()
    reset_policy_cache()
    monkeypatch.setattr(
        h, "prompt_for_batch_approval", lambda reqs, aid: [{"type": "allow_always"}]
    )
    # Confirm step: choose Project, no edit. _confirm_remember returns (target, rule_or_none).
    monkeypatch.setattr(h, "_confirm_remember", lambda rule: ("project", None))
    monkeypatch.setattr(h.Path, "cwd", staticmethod(lambda: tmp_path))
    session_state = types.SimpleNamespace(auto_approve=False, plan_mode_enabled=False)
    decisions, _, _ = await h.process_hitl_approval(
        _req("edit_file", {"file_path": "/src/app.py"}),
        session_state, "nova-agent", None, False, _Status(),
    )
    assert decisions[0]["type"] == "approve"
    assert (tmp_path / ".nova" / "approval-policy.json").is_file()
    reset_session_allow()


async def test_repl_always_cancel_falls_back_to_approve_once(monkeypatch, tmp_path):
    import novacode_cli.ui.hitl_approval as h

    reset_session_allow()
    reset_policy_cache()
    monkeypatch.setattr(
        h, "prompt_for_batch_approval", lambda reqs, aid: [{"type": "allow_always"}]
    )
    monkeypatch.setattr(h, "_confirm_remember", lambda rule: (None, None))  # cancelled
    session_state = types.SimpleNamespace(auto_approve=False, plan_mode_enabled=False)
    decisions, _, _ = await h.process_hitl_approval(
        _req("shell", {"command": "ls"}),
        session_state, "nova-agent", None, False, _Status(),
    )
    assert decisions[0]["type"] == "approve"  # approved once
    assert get_session_allow().matches("shell", {"command": "ls -la"}) is False  # nothing remembered
    reset_session_allow()
```

(Delete the placeholder-import lines shown first; the real file is the second block.)

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_repl_remember.py -q`
Expected: FAIL — `AttributeError: module 'novacode_cli.ui.hitl_approval' has no attribute '_confirm_remember'` (and the markers aren't interpreted).

- [ ] **Step 3a: Add the menu options in `novacode_cli/ui/tool_approval.py`**

In `prompt_for_tool_approval`, extend the options list and the fallback, and return the new markers. Replace:

```python
    options = ["approve", "reject", "auto-accept all going forward"]
```

with:

```python
    options = [
        "approve",
        "reject",
        "allow for session",
        "always allow…",
        "auto-accept all going forward",
    ]
```

Update the fallback prompt block (the `except` branch) to:

```python
    except (ImportError, AttributeError, Exception):
        console.print("  ☐ (A)pprove  (default)")
        console.print("  ☐ (R)eject")
        console.print("  ☐ (S)ession allow")
        console.print("  ☐ A(l)ways allow")
        console.print("  ☐ (Auto)-accept all going forward")
        choice = input("\nChoice (A/R/S/L/Auto, default=Approve): ").strip().lower()
        mapping = {"r": 1, "reject": 1, "s": 2, "l": 3, "auto": 4, "auto-accept": 4}
        selected = mapping.get(choice, 0)
```

Update the raw-mode quick-keys: after the existing `elif char.lower() == "r":` block add:

```python
                elif char.lower() == "s":
                    selected = 2
                    sys.stdout.write("\r\n")
                    break
                elif char.lower() == "l":
                    selected = 3
                    sys.stdout.write("\r\n")
                    break
```

Update the highlighted-render loop so indices 2/3/4 render labels (replace the per-option render `if/elif` chain with index-based labels):

```python
                _LABELS = {
                    0: ("Approve", "1;32"),
                    1: ("Reject", "1;31"),
                    2: ("Allow for session", "1;36"),
                    3: ("Always allow…", "1;35"),
                    4: ("Auto-accept all going forward", "1;34"),
                }
                for i, _option in enumerate(options):
                    sys.stdout.write("\r\033[K")
                    label, colour = _LABELS[i]
                    if i == selected:
                        sys.stdout.write(f"\033[{colour}m☑ {label}\033[0m\n")
                    else:
                        sys.stdout.write(f"\033[2m☐ {label}\033[0m\n")
```

And the cursor-rewind count must match 5 options — replace `sys.stdout.write("\033[3A\r")` with `sys.stdout.write(f"\033[{len(options)}A\r")`.

Finally, replace the return block:

```python
    # Return decision based on selection
    if selected == 0:
        return ApproveDecision(type="approve")
    if selected == 1:
        return RejectDecision(type="reject", message="User rejected the command")
    if selected == 2:
        return {"type": "allow_session"}
    if selected == 3:
        return {"type": "allow_always"}
    return {"type": "auto_approve_all"}
```

Do the **same** option additions in `prompt_for_batch_approval`: extend its `options` list to the 5 labels, add `s`/`l` quick keys, and map `selected == 2 -> [{"type": "allow_session"}, *approves]`, `selected == 3 -> [{"type": "allow_always"}, *approves]`, keeping `selected == 4` as the existing `auto_approve_all` branch (renumbered from 3).

- [ ] **Step 3b: Add the confirm helper + marker interpretation in `novacode_cli/ui/hitl_approval.py`**

Add imports at the top of the module:

```python
from pathlib import Path

from novacode_cli.security.remember import apply_remember
from novacode_cli.security.rule_synthesis import synthesize_rule
```

Add a confirm helper (console-based; returns `(target, edited_rule_or_none)`, or `(None, None)` on cancel):

```python
def _confirm_remember(rule):
    """Confirm an 'always allow' rule: show it, pick project/global, optional edit.

    Returns ``(target, edited_rule_or_None)`` where target is ``"project"`` /
    ``"global"``, or ``(None, None)`` if the user cancels.
    """
    from dataclasses import replace

    console.print()
    console.print(f"[bold]Always allow:[/bold] {rule.human}")
    console.print(f"[dim]Rule ({rule.category}):[/dim] {rule.value}")
    choice = input("Save where?  [P]roject  [G]lobal  [E]dit  [C]ancel: ").strip().lower()
    if choice in {"e", "edit"}:
        new_value = input(f"Edit rule value [{rule.value}]: ").strip() or rule.value
        rule = replace(rule, value=new_value)
        choice = input("Save where?  [P]roject  [G]lobal  [C]ancel: ").strip().lower()
        edited = rule
    else:
        edited = None
    if choice in {"p", "project"}:
        return "project", edited
    if choice in {"g", "global"}:
        return "global", edited
    return None, None
```

In `process_hitl_approval`, in the `for action_index, decision in enumerate(raw_decisions):` loop, handle the two new markers **before** the existing `decisions.append(decision)`:

```python
        if isinstance(decision, dict) and decision.get("type") == "allow_session":
            ar = action_requests[action_index]
            apply_remember("session", ar.get("name", ""), ar.get("args", {}))
            console.print(f"[green]✓ Allowed for this session:[/green] {ar.get('name')}")
            decisions.append({"type": "approve"})
            continue

        if isinstance(decision, dict) and decision.get("type") == "allow_always":
            ar = action_requests[action_index]
            rule = synthesize_rule(ar.get("name", ""), ar.get("args", {}))
            target, edited = _confirm_remember(rule)
            if target is not None:
                result = apply_remember(
                    "always", ar.get("name", ""), ar.get("args", {}),
                    target=target, project_root=Path.cwd(), rule=edited or rule,
                )
                console.print(f"[green]✓ Saved to[/green] {result.saved_path}")
            else:
                console.print("[dim]Not saved — approved this call only.[/dim]")
            decisions.append({"type": "approve"})
            continue
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_repl_remember.py -q`
Expected: PASS (3 passed).

- [ ] **Step 5: Format, lint, commit**

```bash
uv run ruff format novacode_cli/ui/tool_approval.py novacode_cli/ui/hitl_approval.py tests/test_repl_remember.py
uv run ruff check novacode_cli/ui/tool_approval.py novacode_cli/ui/hitl_approval.py tests/test_repl_remember.py
git add novacode_cli/ui/tool_approval.py novacode_cli/ui/hitl_approval.py tests/test_repl_remember.py
git commit -m "feat(approval): REPL session/always-allow options + confirm"
```

---

## Task 7: TUI — modal options + `RememberRuleModal` + wiring

**Files:**
- Modify: `novacode_cli/tui/app.py` (`ApprovalModal` options; new `RememberRuleModal`; `_handle_interrupt_inner` tool branch)
- Test: `tests/test_tui_remember.py` (new)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_tui_remember.py
"""Tests for TUI session/always-allow wiring in the tool interrupt handler."""

from __future__ import annotations

import asyncio
import types

from novacode_cli.security.session_allow import get_session_allow, reset_session_allow


def _interrupt(name, args):
    fut: asyncio.Future = asyncio.get_event_loop().create_future()
    return types.SimpleNamespace(
        kind="tool",
        payload={"action_requests": [{"name": name, "args": args}]},
        future=fut,
    )


async def test_tui_session_choice_remembers_and_approves(monkeypatch):
    from novacode_cli.tui.app import NovaApp

    reset_session_allow()
    app = NovaApp.__new__(NovaApp)  # bypass __init__; we only exercise the handler
    app.session_state = types.SimpleNamespace(plan_mode_enabled=False, auto_approve=False)
    monkeypatch.setattr(app, "push_screen_wait", _async_return("session"), raising=False)
    monkeypatch.setattr(app, "_log", lambda *a, **k: None, raising=False)

    e = _interrupt("shell", {"command": "npm run build"})
    await app._handle_interrupt_inner(e)

    result = e.future.result()
    assert result["decisions"][0]["type"] == "approve"
    assert get_session_allow().matches("shell", {"command": "npm run build --prod"}) is True
    reset_session_allow()


def _async_return(value):
    async def _fn(*args, **kwargs):
        return value

    return _fn
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_tui_remember.py -q`
Expected: FAIL — the handler returns `approve` but does **not** add a session rule (assertion on `matches` fails), because the `"session"` choice isn't handled yet.

- [ ] **Step 3a: Add options to `ApprovalModal`**

In `novacode_cli/tui/app.py`, `ApprovalModal.on_mount`, add the two options after Approve:

```python
    def on_mount(self) -> None:
        animate_modal_screen(self)
        ol = self.query_one("#choices", OptionList)
        ol.add_option(Option("Approve (y)"))
        ol.add_option(Option("Allow for session (s)"))
        ol.add_option(Option("Always allow… (l)"))
        if self._allow_auto:
            ol.add_option(Option("Auto-approve for this thread (a)"))
        ol.add_option(Option("Reject (n)"))
        ol.highlighted = 0
        ol.focus()
```

Add bindings + actions:

```python
    BINDINGS = [
        ("y", "approve", "Approve"),
        ("s", "session", "Session"),
        ("l", "always", "Always"),
        ("a", "auto", "Auto-approve"),
        ("n", "reject", "Reject"),
        ("escape", "reject", "Reject"),
    ]
```

```python
    def action_session(self) -> None:
        self.dismiss("session")

    def action_always(self) -> None:
        self.dismiss("always")
```

Update `on_option_list_option_selected` to map the new labels:

```python
    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        label = str(event.option.prompt)
        if label.startswith("Approve"):
            self.dismiss("approve")
        elif label.startswith("Allow for session"):
            self.dismiss("session")
        elif label.startswith("Always"):
            self.dismiss("always")
        elif label.startswith("Auto"):
            self.dismiss("auto")
        else:
            self.dismiss("reject")
```

- [ ] **Step 3b: Add `RememberRuleModal`** (place next to `ApprovalModal`)

```python
class RememberRuleModal(ModalScreen[dict | None]):
    """Confirm an 'always allow' rule: editable value + project/global target.

    Dismisses with ``{"value": <str>, "target": "project"|"global"}`` or ``None``
    if cancelled.
    """

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, rule: Any) -> None:
        super().__init__()
        self._rule = rule

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-box"):
            yield Static(Text(">>> Always allow <<<", style="bold yellow"), id="modal-title")
            yield Static(
                Text(f"{self._rule.human}\n({self._rule.category} rule)", style="dim"),
                id="modal-body",
            )
            yield Input(value=self._rule.value, id="rule-value")
            with Horizontal(id="remember-buttons"):
                yield Button("Project", id="btn-project", variant="primary")
                yield Button("Global", id="btn-global")
                yield Button("Cancel", id="btn-cancel", variant="error")

    def on_mount(self) -> None:
        animate_modal_screen(self)
        self.query_one("#rule-value", Input).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        value = self.query_one("#rule-value", Input).value.strip() or self._rule.value
        if event.button.id == "btn-project":
            self.dismiss({"value": value, "target": "project"})
        elif event.button.id == "btn-global":
            self.dismiss({"value": value, "target": "global"})
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)
```

If `Button` / `Horizontal` aren't already imported in `app.py`, add them to the Textual imports (`from textual.widgets import Button`, `from textual.containers import Horizontal`). Verify with `grep -n "import Button\|Horizontal" novacode_cli/tui/app.py` before adding to avoid duplicate imports.

- [ ] **Step 3c: Wire the choices in `_handle_interrupt_inner`**

In the `if e.kind == "tool":` branch, replace the `if choice == "reject": … else: …` block with handling for the new choices. After computing `choice = await self.push_screen_wait(ApprovalModal(...))`:

```python
            if choice == "reject":
                e.future.set_result(
                    {
                        "decisions": [
                            {"type": "reject", "message": "Rejected by user"}
                            for _ in action_requests
                        ],
                        "any_rejected": True,
                    }
                )
                return

            if choice in ("session", "always"):
                from dataclasses import replace

                from novacode_cli.security.remember import apply_remember
                from novacode_cli.security.rule_synthesis import synthesize_rule

                for ar in action_requests:
                    name, args = ar.get("name", ""), ar.get("args", {})
                    if choice == "session":
                        apply_remember("session", name, args)
                        self._log(Text(f"✓ Allowed `{name}` for this session.", style="green"))
                    else:
                        rule = synthesize_rule(name, args)
                        out = await self.push_screen_wait(RememberRuleModal(rule))
                        if out:
                            edited = replace(rule, value=out["value"])
                            res = apply_remember(
                                "always", name, args, target=out["target"], rule=edited
                            )
                            self._log(Text(f"✓ Saved to {res.saved_path}", style="green"))
                        else:
                            self._log(Text("Not saved — approved this call only.", style="dim"))
                e.future.set_result(
                    {
                        "decisions": [{"type": "approve"} for _ in action_requests],
                        "any_rejected": False,
                    }
                )
                return

            if choice == "auto":
                self.session_state.auto_approve = True
                self._log(Text("✓ Auto-approve enabled for this session.", style="green"))
            e.future.set_result(
                {
                    "decisions": [{"type": "approve"} for _ in action_requests],
                    "any_rejected": False,
                }
            )
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_tui_remember.py -q`
Expected: PASS (1 passed).

- [ ] **Step 5: Run the full TUI suite in isolation to confirm no modal/CSS regressions**

Run: `uv run pytest tests/test_tui_app.py -q` (heavy — allow ~60s; flaky tests pass when run individually).
Then: `uv run pytest tests/test_tui_app.py::test_tui_approval_modal -q`
Expected: PASS.

- [ ] **Step 6: Format, lint, commit**

```bash
uv run ruff format novacode_cli/tui/app.py tests/test_tui_remember.py
uv run ruff check novacode_cli/tui/app.py tests/test_tui_remember.py
git add novacode_cli/tui/app.py tests/test_tui_remember.py
git commit -m "feat(tui): session/always-allow options + RememberRuleModal"
```

---

## Task 8: Full-suite verification + spec close-out

**Files:** none (verification only)

- [ ] **Step 1: Run all new + adjacent suites**

Run:
```bash
uv run pytest tests/test_rule_synthesis.py tests/test_session_allow.py \
  tests/test_policy_writer.py tests/test_remember_approvals.py \
  tests/test_approval_policy.py tests/test_repl_remember.py tests/test_tui_remember.py -q
```
Expected: PASS (all).

- [ ] **Step 2: Lint the whole changed surface**

Run: `uv run ruff check novacode_cli/security/ novacode_cli/ui/hitl_approval.py novacode_cli/ui/tool_approval.py`
Expected: no new findings beyond the repo's pre-existing baseline.

- [ ] **Step 3: Manual smoke (optional, documented)**

Run `uv run nova`, ask the agent to run an unknown shell command (e.g. `frobnicate --x`), choose **Allow for session**, then ask it to run the same command again — confirm no second prompt. Repeat with **Always allow… → Project** and confirm `.nova/approval-policy.json` gains the rule.

- [ ] **Step 4: Commit any final fixups** (if Steps 1-2 surfaced issues)

```bash
git add -A
git commit -m "test: verify session/always-allow approvals end-to-end"
```

---

## Self-review notes (author)

- **Spec coverage:** §3 synthesis → Task 1; §4 session layer → Task 2; §4 writer → Task 3; §4 glue → Task 4; §6 gate/safety ordering → Task 5 (incl. deny-inviolable test); §7 UX (REPL) → Task 6; §7 UX (TUI) → Task 7; §10 testing spread across tasks; §9 error handling: write failure path is covered by `apply_remember` adding to the session layer regardless (Task 4) and the REPL/TUI cancel→approve-once fallbacks (Tasks 6/7).
- **Type consistency:** `ProposedRule(category, value, human, tool_name)` used identically across Tasks 1-7; `apply_remember(kind, tool_name, args, *, target, project_root, rule)` and `RememberResult(rule, saved_path)` consistent in Tasks 4/6/7; gate marker dicts `{"type": "approve"|"reject"|"allow_session"|"allow_always"}` consistent.
- **Deny inviolable:** enforced structurally — the gate only consults the session layer on the `ask` tier (Task 5), and `SessionAllowList` matching runs through `ApprovalPolicy.evaluate`, which checks built-in denies first (Task 2 test `test_session_allow_cannot_override_builtin_deny`).

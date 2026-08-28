"""Tests for Docker sandbox toolchain provisioning (git/ruff/pytest).

These cover the pure helpers in :mod:`novacode_cli.integrations.sandbox_factory`
that decide the image, whether to provision, the provisioning script, and how a
provisioning result is interpreted — none of which require a Docker daemon.
"""

from types import SimpleNamespace

import pytest

from novacode_cli.integrations import sandbox_factory as sf


def test_default_image_and_override(monkeypatch):
    monkeypatch.delenv("NOVA_SANDBOX_IMAGE", raising=False)
    assert sf._sandbox_image() == sf._DEFAULT_SANDBOX_IMAGE

    monkeypatch.setenv("NOVA_SANDBOX_IMAGE", "ghcr.io/acme/nova-dev:latest")
    assert sf._sandbox_image() == "ghcr.io/acme/nova-dev:latest"

    # Blank/whitespace falls back to the default.
    monkeypatch.setenv("NOVA_SANDBOX_IMAGE", "   ")
    assert sf._sandbox_image() == sf._DEFAULT_SANDBOX_IMAGE


@pytest.mark.parametrize(
    ("value", "expected"),
    [("1", True), ("true", True), ("YES", True), ("on", True),
     ("0", False), ("false", False), ("", False)],
)
def test_skip_provision_parsing(monkeypatch, value, expected):
    monkeypatch.setenv("NOVA_SANDBOX_SKIP_PROVISION", value)
    assert sf._skip_provision() is expected


def test_provision_script_contains_baseline_tools(monkeypatch):
    monkeypatch.delenv("NOVA_SANDBOX_EXTRA_APT", raising=False)
    monkeypatch.delenv("NOVA_SANDBOX_EXTRA_PIP", raising=False)
    script = sf._build_provision_script()
    # Baseline tools the agent needs for vcs / lint / test. Driven off the
    # package tuple itself so a deliberate slim-down (build-essential and other
    # heavy packages were dropped to save ~250MB/container) doesn't read as a
    # regression, while an accidental removal still fails.
    for tool in (*sf._PROVISION_APT_PACKAGES, "ruff", "pytest"):
        assert tool in script
    # Idempotent + best-effort markers.
    assert "command -v git" in script
    assert "nova-provision-summary:" in script
    assert "--no-install-recommends" in script


def test_provision_script_appends_extras(monkeypatch):
    monkeypatch.setenv("NOVA_SANDBOX_EXTRA_APT", "ripgrep jq")
    monkeypatch.setenv("NOVA_SANDBOX_EXTRA_PIP", "mypy")
    script = sf._build_provision_script()
    assert "ripgrep" in script and "jq" in script
    assert "mypy" in script


def _fake_backend(output: str, exit_code: int = 0):
    calls = {}

    def execute(command, *, timeout=None):
        calls["command"] = command
        calls["timeout"] = timeout
        return SimpleNamespace(output=output, exit_code=exit_code, truncated=False)

    return SimpleNamespace(execute=execute), calls


def test_provision_reports_success(monkeypatch):
    summary = "nova-provision-summary: git=/usr/bin/git ruff=/usr/local/bin/ruff pytest=/usr/local/bin/pytest"
    backend, calls = _fake_backend(summary, exit_code=0)
    printed = []
    monkeypatch.setattr(sf.console, "print", lambda *a, **k: printed.append(" ".join(str(x) for x in a)))

    sf._provision_sandbox_tools(backend)

    # Ran under a bounded timeout, and reported a healthy toolchain.
    assert calls["timeout"] == 600
    assert any("toolchain ready" in line for line in printed)
    assert not any("incomplete" in line for line in printed)


def test_provision_warns_when_tool_missing(monkeypatch):
    summary = "nova-provision-summary: git=MISSING ruff=/usr/local/bin/ruff pytest=/usr/local/bin/pytest"
    backend, _ = _fake_backend(summary, exit_code=0)
    printed = []
    monkeypatch.setattr(sf.console, "print", lambda *a, **k: printed.append(" ".join(str(x) for x in a)))

    sf._provision_sandbox_tools(backend)

    assert any("incomplete" in line for line in printed)


def test_provision_survives_execute_exception(monkeypatch):
    def boom(command, *, timeout=None):
        raise RuntimeError("daemon gone")

    backend = SimpleNamespace(execute=boom)
    printed = []
    monkeypatch.setattr(sf.console, "print", lambda *a, **k: printed.append(" ".join(str(x) for x in a)))

    # Must not raise — provisioning is best-effort.
    sf._provision_sandbox_tools(backend)
    assert any("provisioning failed" in line.lower() for line in printed)

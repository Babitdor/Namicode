"""WorkdirSandboxBackend rebases virtual `/` paths onto the sandbox workdir.

Guards the fix for the sandbox path mismatch: the agent uses `/`-rooted virtual
project paths, but a raw sandbox backend resolves `/foo` at the container root
(project lives at e.g. /workspace), so file reads 404. The wrapper rebases onto
the workdir while still registering as a sandbox backend.
"""

from __future__ import annotations

import base64
import re

from deepagents.backends.protocol import (
    ExecuteResponse,
    SandboxBackendProtocol,
)
from deepagents.backends.sandbox import BaseSandbox

from novacode_cli.integrations.workdir_backend import WorkdirSandboxBackend


class _FakeSandbox(BaseSandbox):
    """Minimal BaseSandbox: records the script passed to execute / delegated args."""

    def __init__(self) -> None:
        self.commands: list[str] = []
        self.dl: list[list[str]] = []
        self.ul: list[list[tuple[str, bytes]]] = []

    @property
    def id(self) -> str:
        return "fake"

    def execute(self, command: str, *, timeout=None) -> ExecuteResponse:
        self.commands.append(command)
        return ExecuteResponse(output="", exit_code=0, truncated=False)

    async def aexecute(self, command: str, *, timeout=None) -> ExecuteResponse:
        return self.execute(command, timeout=timeout)

    def download_files(self, paths):
        self.dl.append(list(paths))
        return []

    async def adownload_files(self, paths):
        return self.download_files(paths)

    def upload_files(self, files):
        self.ul.append(list(files))
        return []

    async def aupload_files(self, files):
        return self.upload_files(files)


def _wrap(workdir="/workspace"):
    inner = _FakeSandbox()
    return WorkdirSandboxBackend(inner, workdir=workdir), inner


def test_rebase_logic():
    w, _ = _wrap("/workspace")
    rb = w._rebase
    assert rb("/novacode_cli/x.py") == "/workspace/novacode_cli/x.py"  # virtual abs
    assert rb("rel/y.py") == "/workspace/rel/y.py"                      # relative
    assert rb("/workspace/z.py") == "/workspace/z.py"                   # already rooted
    assert rb("/workspace") == "/workspace"                            # the workdir itself
    assert rb("/") == "/workspace"                                     # root → workdir
    # Idempotent: rebasing an already-rebased path is a no-op.
    assert rb(rb("/a/b")) == rb("/a/b")
    assert w._rebase_opt(None) == "/workspace"                          # grep/glob default


def test_rebase_other_workdir():
    w, _ = _wrap("/home/user")
    assert w._rebase("/pkg/mod.py") == "/home/user/pkg/mod.py"
    assert w._rebase("/home/user/keep") == "/home/user/keep"


def test_registers_as_sandbox_backend():
    # Must still satisfy isinstance so _supports_sandbox_execution() stays True.
    w, _ = _wrap()
    assert isinstance(w, SandboxBackendProtocol)
    assert w.id == "fake"


def test_execute_is_not_rebased():
    # Shell commands run in the workdir already — don't touch them.
    w, inner = _wrap()
    w.execute("ls -la /")
    assert inner.commands[-1] == "ls -la /"


def test_download_upload_rebase_paths():
    w, inner = _wrap()
    w.download_files(["/novacode_cli/a.py", "rel/b.py", "/workspace/c.py"])
    assert inner.dl[-1] == [
        "/workspace/novacode_cli/a.py",
        "/workspace/rel/b.py",
        "/workspace/c.py",
    ]
    w.upload_files([("/out/x.json", b"data")])
    assert inner.ul[-1] == [("/workspace/out/x.json", b"data")]


def test_ls_runs_script_with_rebased_path():
    # ls builds a script that base64-encodes the path and calls self.execute;
    # the rebased path must be what reaches the sandbox.
    w, inner = _wrap()
    w.ls("/novacode_cli/utils")
    cmd = inner.commands[-1]
    m = re.search(r"b64decode\('([^']+)'\)", cmd)
    assert m, cmd
    decoded = base64.b64decode(m.group(1)).decode("utf-8")
    assert decoded == "/workspace/novacode_cli/utils"

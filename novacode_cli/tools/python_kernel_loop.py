"""Kernel-side loop for the persistent Python kernel tool.

This module is the *child* process of :func:`novacode_cli.tools.python_kernel_tool.python_kernel`.
It reads JSONL requests on stdin, executes each snippet in a shared namespace, and
writes JSONL responses on stdout. The namespace persists across requests, so state
built up in one call (imports, variables, dataframes) is visible in the next.

The loop is deliberately kept separate from the tool so it can be unit-tested
without spawning a subprocess, and so the tool can spawn it via ``python -m``.

Protocol (one JSON object per line, both directions):

Request::

    {"op": "exec", "code": "...", "snapshot": null | "save" | "load:<path>"}
    {"op": "reset"}

Response::

    {"ok": true, "output": "...", "error": null}
    {"ok": false, "output": "...", "error": "Traceback..."}

``snapshot`` semantics:
- ``null`` — run ``code`` in the current namespace.
- ``"save"`` — run ``code``, then dump the namespace to ``<cwd>/kernel_snapshot.pkl``
  (or the path in ``snapshot_path``) and return the path.
- ``"load:<path>"`` — restore the namespace from ``<path>`` *before* running ``code``.

The namespace is a plain ``dict`` used as the ``globals`` for ``exec``. Builtins are
injected so ``print``/``len``/etc. work as expected.
"""

from __future__ import annotations

import ast
import io
import json
import sys
import traceback
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any

#: Default snapshot filename written by ``snapshot="save"`` when no path is given.
DEFAULT_SNAPSHOT_NAME = "kernel_snapshot.pkl"


def _load_namespace(path: str) -> dict[str, Any]:
    """Restore a namespace dict from a dill file."""
    import dill

    with Path(path).open("rb") as fh:
        data = dill.load(fh)  # noqa: S301 — the kernel only loads its own snapshots
    if not isinstance(data, dict):
        raise TypeError("snapshot is not a namespace dict")  # noqa: EM101, TRY003
    return data


def _save_namespace(ns: dict[str, Any], path: str) -> None:
    """Dump a namespace dict to a dill file (atomic-ish: write temp then rename)."""
    import dill

    tmp = f"{path}.tmp"
    with Path(tmp).open("wb") as fh:
        dill.dump(ns, fh)
    Path(tmp).replace(path)


def _exec_code(ns: dict[str, Any], code: str) -> tuple[str, str | None]:
    """Execute *code* in *ns*, returning ``(captured_output, error_traceback)``.

    ``error_traceback`` is ``None`` on success. Output is captured from stdout and
    stderr during the exec. A bare expression (e.g. ``x + 1``) is echoed like a
    REPL so the agent sees its value.
    """
    out = io.StringIO()
    err = io.StringIO()
    try:
        with redirect_stdout(out), redirect_stderr(err):
            # REPL-style: if the code is a single bare expression, evaluate and
            # echo its value (unless it's None).
            try:
                tree = ast.parse(code, mode="exec")
            except SyntaxError:
                tree = None
            if tree is not None and len(tree.body) == 1 and isinstance(tree.body[0], ast.Expr):
                expr = ast.Expression(tree.body[0].value)
                value = eval(compile(expr, "<kernel>", "eval"), ns)  # noqa: S307 — kernel's job
                if value is not None:
                    print(repr(value))  # noqa: T201 — this IS the kernel's output channel
            else:
                exec(compile(code, "<kernel>", "exec"), ns)  # noqa: S102 — the kernel's whole job
    except BaseException:  # noqa: BLE001 — report any failure, keep the kernel alive
        tb = traceback.format_exc()
        return out.getvalue() + err.getvalue(), tb
    return out.getvalue() + err.getvalue(), None


def _handle_request(req: dict[str, Any], ns: dict[str, Any], cwd: str) -> dict[str, Any]:
    """Process a single request dict against the shared namespace."""
    op = req.get("op", "exec")
    if op == "reset":
        ns.clear()
        ns["__builtins__"] = __builtins__
        return {"ok": True, "output": "namespace reset", "error": None}

    if op != "exec":
        return {"ok": False, "output": "", "error": f"unknown op: {op!r}"}

    code = str(req.get("code") or "")
    snapshot = req.get("snapshot")
    snapshot_path = str(req.get("snapshot_path") or DEFAULT_SNAPSHOT_NAME)

    # Load a snapshot before running, if requested.
    if isinstance(snapshot, str) and snapshot.startswith("load:"):
        path = snapshot[len("load:") :]
        try:
            loaded = _load_namespace(path)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "output": "", "error": f"load failed: {exc}"}
        ns.clear()
        ns.update(loaded)
        ns["__builtins__"] = __builtins__

    output, error = _exec_code(ns, code)

    # Save a snapshot after running, if requested.
    if isinstance(snapshot, str) and snapshot == "save":
        path = str(Path(cwd) / snapshot_path)
        try:
            _save_namespace(ns, path)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "output": output, "error": f"save failed: {exc}"}
        return {"ok": True, "output": output, "error": None, "snapshot_path": path}

    return {"ok": error is None, "output": output, "error": error}


def run_kernel_loop() -> int:
    """Serve the JSONL protocol on stdin/stdout until EOF. Returns an exit code."""
    ns: dict[str, Any] = {"__builtins__": __builtins__}
    cwd = str(Path.cwd())
    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            sys.stdout.write(
                json.dumps({"ok": False, "output": "", "error": "invalid JSON request"}) + "\n"
            )
            sys.stdout.flush()
            continue
        try:
            resp = _handle_request(req, ns, cwd)
        except Exception as exc:  # noqa: BLE001 — never let one request kill the kernel
            resp = {"ok": False, "output": "", "error": f"{type(exc).__name__}: {exc}"}
        sys.stdout.write(json.dumps(resp) + "\n")
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(run_kernel_loop())

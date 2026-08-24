"""WorkspacePolicy — the Cowork permission broker (the security boundary).

Default-deny. The agent may *request* anything; this module independently
authorizes every filesystem operation against explicit, revocable folder grants.

Enforcement rules (from the plan's §5/§14):
- Canonicalize the requested path (resolve symlinks / junctions / ``..``) BEFORE
  deciding — never a raw string-prefix check.
- The *resolved* target must sit inside a *resolved* granted root; a symlink that
  escapes the root is denied (``SYMLINK_TARGET_NOT_ALLOWED``).
- ``..`` can never climb out of a root (the canonical target is re-checked).
- Fail CLOSED on any canonicalization error.
- Scope is per-grant: read / write / execute.
- rename/move authorizes source (read+write) AND destination (write) — callers
  invoke :meth:`authorize` for each.

Persisted (revocable) to ``~/.nova/cowork_workspaces.json``.
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

Op = str  # "read" | "write" | "execute"
_OPS = frozenset({"read", "write", "execute"})


@dataclass
class Grant:
    """An explicit, revocable folder grant."""

    id: str
    display_path: str          # path as the user granted it
    canonical: str             # resolved at grant time (informational)
    read: bool = True
    write: bool = True
    execute: bool = True
    recursive: bool = True
    created_at: float = field(default_factory=time.time)
    last_used: float | None = None
    revoked: bool = False

    def allows(self, op: Op) -> bool:
        return bool(getattr(self, op, False))

    def public(self) -> dict:
        d = asdict(self)
        return d


@dataclass
class Decision:
    """Result of an authorization check."""

    allowed: bool
    code: str  # "OK" or an error code from the plan's §16
    grant_id: str | None = None
    target: str | None = None
    reason: str = ""


def _canonical(path: str | Path) -> Path | None:
    """Resolve symlinks/junctions/``..`` to an absolute canonical path.

    ``strict=False`` so a not-yet-existing target (a file about to be written)
    still resolves via its existing parent chain. Returns None on any error →
    the caller FAILS CLOSED.
    """
    try:
        return Path(path).resolve(strict=False)
    except Exception:  # noqa: BLE001 — fail closed
        return None


def _within(target: Path, root: Path, recursive: bool) -> bool:
    """True if *target* is *root* itself, or (recursive) inside it — on canonical
    paths, so this is containment, not a string prefix."""
    if target == root:
        return True
    if not recursive:
        return False
    try:
        return target.is_relative_to(root)
    except (ValueError, AttributeError):
        # AttributeError: Python <3.9 (Nova targets 3.11, but stay safe).
        try:
            target.relative_to(root)
            return True
        except ValueError:
            return False


class WorkspacePolicy:
    """Persistent, revocable, default-deny workspace grants + authorization."""

    def __init__(self, store_path: Path | None = None) -> None:
        self._store = store_path or (Path.home() / ".nova" / "cowork_workspaces.json")
        self._lock = threading.RLock()
        self._grants: dict[str, Grant] = {}
        self._load()

    # -- persistence -------------------------------------------------------
    def _load(self) -> None:
        if not self._store.exists():
            return
        try:
            data = json.loads(self._store.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return
        for raw in data.get("grants", []):
            try:
                g = Grant(**{k: raw[k] for k in raw if k in Grant.__dataclass_fields__})
                self._grants[g.id] = g
            except Exception:  # noqa: BLE001 — skip malformed
                continue

    def _save(self) -> None:
        self._store.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._store.with_suffix(".tmp")
        tmp.write_text(
            json.dumps({"grants": [g.public() for g in self._grants.values()]}, indent=2),
            encoding="utf-8",
        )
        tmp.replace(self._store)
        try:
            os.chmod(self._store, 0o600)  # owner-only (no-op on Windows)
        except OSError:
            pass

    # -- grant management --------------------------------------------------
    def grant(
        self,
        path: str | Path,
        *,
        read: bool = True,
        write: bool = True,
        execute: bool = True,
        recursive: bool = True,
    ) -> Grant | None:
        """Grant access to a folder. Returns the Grant, or None if the path can't
        be canonicalized or isn't an existing directory (fail closed)."""
        canon = _canonical(path)
        if canon is None or not canon.is_dir():
            return None
        with self._lock:
            g = Grant(
                id=f"ws_{uuid.uuid4().hex[:8]}",
                display_path=str(path),
                canonical=str(canon),
                read=read,
                write=write,
                execute=execute,
                recursive=recursive,
            )
            self._grants[g.id] = g
            self._save()
        return g

    def revoke(self, grant_id: str) -> bool:
        with self._lock:
            g = self._grants.get(grant_id)
            if g is None or g.revoked:
                return False
            g.revoked = True
            self._save()
        return True

    def active_grants(self) -> list[Grant]:
        with self._lock:
            return [g for g in self._grants.values() if not g.revoked]

    def all_grants(self) -> list[Grant]:
        with self._lock:
            return list(self._grants.values())

    def get(self, grant_id: str) -> Grant | None:
        with self._lock:
            return self._grants.get(grant_id)

    # -- authorization (the boundary) --------------------------------------
    def authorize(self, path: str | Path, op: Op) -> Decision:
        """Authorize an operation on a path. Default-deny; fail closed."""
        if op not in _OPS:
            return Decision(False, "COMMAND_NOT_ALLOWED", reason=f"unknown op {op!r}")
        target = _canonical(path)
        if target is None:
            return Decision(False, "SANDBOX_UNAVAILABLE", reason="canonicalization failed")

        with self._lock:
            grants = [g for g in self._grants.values() if not g.revoked]

        symlink_escape = False
        for g in grants:
            if not g.allows(op):
                continue
            root = _canonical(g.canonical)
            if root is None:
                continue  # a root we can't resolve → skip (fail closed for it)
            if _within(target, root, g.recursive):
                g.last_used = time.time()
                return Decision(True, "OK", grant_id=g.id, target=str(target))
            # Distinguish "symlink pointed out of an otherwise-granted tree" from
            # plain out-of-workspace, for a clearer error. If the requested path
            # is LEXICALLY inside the root but the RESOLVED target isn't, a
            # symlink/junction escaped.
            try:
                lexical = Path(os.path.normpath(str(Path(path))))
                if g.recursive and _within(lexical, root, True) and not _within(target, root, True):
                    symlink_escape = True
            except Exception:  # noqa: BLE001
                pass

        if symlink_escape:
            return Decision(
                False, "SYMLINK_TARGET_NOT_ALLOWED", target=str(target),
                reason="path resolves outside the granted workspace via a symlink/junction",
            )
        return Decision(
            False, "ACCESS_DENIED_OUTSIDE_WORKSPACE", target=str(target),
            reason="no active grant covers this path with the requested access",
        )

    def authorize_move(self, src: str | Path, dst: str | Path) -> Decision:
        """rename/move: source needs read+write, destination needs write."""
        for p, op in ((src, "read"), (src, "write"), (dst, "write")):
            d = self.authorize(p, op)
            if not d.allowed:
                return d
        return Decision(True, "OK", target=str(_canonical(dst)))


_policy: WorkspacePolicy | None = None


def get_policy() -> WorkspacePolicy:
    """Process-global workspace policy."""
    global _policy
    if _policy is None:
        _policy = WorkspacePolicy()
    return _policy


if __name__ == "__main__":
    import tempfile

    d = Path(tempfile.mkdtemp())
    root = d / "proj"
    (root / "src").mkdir(parents=True)
    (root / "src" / "a.py").write_text("x")
    outside = d / "secret"
    outside.mkdir()
    (outside / "creds").write_text("TOP SECRET")

    pol = WorkspacePolicy(store_path=d / "store.json")
    assert pol.authorize(root / "src" / "a.py", "read").allowed is False  # default deny
    g = pol.grant(root, read=True, write=True, execute=False)
    assert g is not None
    assert pol.authorize(root / "src" / "a.py", "read").allowed  # in-workspace read
    assert pol.authorize(root / "src" / "new.py", "write").allowed  # write not-yet-existing
    assert pol.authorize(root / "src", "execute").allowed is False  # scope excludes execute
    # .. traversal cannot escape
    assert pol.authorize(root / ".." / "secret" / "creds", "read").allowed is False
    assert pol.authorize(outside / "creds", "read").code == "ACCESS_DENIED_OUTSIDE_WORKSPACE"
    # symlink escape (skip where the OS/user can't create one)
    link = root / "escape"
    try:
        os.symlink(outside, link, target_is_directory=True)
        d2 = pol.authorize(link / "creds", "read")
        assert d2.allowed is False and d2.code == "SYMLINK_TARGET_NOT_ALLOWED", d2
    except (OSError, NotImplementedError):
        pass
    # revocation
    assert pol.revoke(g.id) is True
    assert pol.authorize(root / "src" / "a.py", "read").allowed is False
    # persistence
    pol2 = WorkspacePolicy(store_path=d / "store.json")
    assert [x.id for x in pol2.all_grants()] == [g.id] and pol2.all_grants()[0].revoked
    print("cowork.policy self-check ok")

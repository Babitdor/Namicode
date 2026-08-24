"""Cowork WorkspacePolicy broker — the security boundary. Covers the plan's §20
unit matrix: canonicalization, grant matching, nested/overlapping roots, ``..``
traversal, symlink escape, rename/move, revocation, default-deny."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from novacode_cli.cowork.policy import WorkspacePolicy


@pytest.fixture
def tree(tmp_path: Path):
    proj = tmp_path / "proj"
    (proj / "src").mkdir(parents=True)
    (proj / "src" / "a.py").write_text("x")
    (proj / "sub").mkdir()
    secret = tmp_path / "secret"
    secret.mkdir()
    (secret / "creds").write_text("TOP SECRET")
    pol = WorkspacePolicy(store_path=tmp_path / "store.json")
    return pol, proj, secret, tmp_path


def test_default_deny(tree):
    pol, proj, _secret, _ = tree
    d = pol.authorize(proj / "src" / "a.py", "read")
    assert not d.allowed and d.code == "ACCESS_DENIED_OUTSIDE_WORKSPACE"


def test_grant_and_scope(tree):
    pol, proj, _secret, _ = tree
    pol.grant(proj, read=True, write=True, execute=False)
    assert pol.authorize(proj / "src" / "a.py", "read").allowed
    assert pol.authorize(proj / "src" / "new.py", "write").allowed  # not-yet-existing target
    assert not pol.authorize(proj / "src", "execute").allowed  # scope excludes execute


def test_dotdot_cannot_escape(tree):
    pol, proj, secret, _ = tree
    pol.grant(proj)
    d = pol.authorize(proj / ".." / "secret" / "creds", "read")
    assert not d.allowed
    assert pol.authorize(secret / "creds", "read").code == "ACCESS_DENIED_OUTSIDE_WORKSPACE"


def test_non_recursive_grant(tree):
    pol, proj, _secret, _ = tree
    pol.grant(proj, recursive=False)
    assert pol.authorize(proj, "read").allowed          # the root itself
    assert not pol.authorize(proj / "src" / "a.py", "read").allowed  # not descendants


def test_nested_and_overlapping_roots(tree):
    pol, proj, _secret, _ = tree
    pol.grant(proj / "src", read=True, write=False)     # inner: read-only
    pol.grant(proj, read=True, write=True)              # outer: read+write (overlaps)
    # A file under both roots: write is allowed via the outer grant.
    assert pol.authorize(proj / "src" / "a.py", "write").allowed
    # A sibling only under the outer grant.
    assert pol.authorize(proj / "sub" / "b.txt", "write").allowed


def test_symlink_escape_denied(tree):
    pol, proj, secret, _ = tree
    pol.grant(proj)
    link = proj / "escape"
    try:
        os.symlink(secret, link, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation not permitted here")
    d = pol.authorize(link / "creds", "read")
    assert not d.allowed and d.code == "SYMLINK_TARGET_NOT_ALLOWED"


def test_move_authorizes_source_and_dest(tree):
    pol, proj, secret, _ = tree
    pol.grant(proj)
    # in-workspace move ok
    assert pol.authorize_move(proj / "src" / "a.py", proj / "sub" / "a.py").allowed
    # moving OUT of the workspace is denied (dest not granted)
    assert not pol.authorize_move(proj / "src" / "a.py", secret / "a.py").allowed
    # moving IN from outside is denied (source not granted)
    assert not pol.authorize_move(secret / "creds", proj / "creds").allowed


def test_revocation_and_persistence(tree):
    pol, proj, _secret, tmp_path = tree
    g = pol.grant(proj)
    assert pol.authorize(proj / "src" / "a.py", "read").allowed
    assert pol.revoke(g.id) is True
    assert not pol.authorize(proj / "src" / "a.py", "read").allowed
    # a fresh policy from the same store remembers the revoked grant
    pol2 = WorkspacePolicy(store_path=tmp_path / "store.json")
    assert pol2.all_grants()[0].revoked
    assert not pol2.authorize(proj / "src" / "a.py", "read").allowed


def test_grant_rejects_nonexistent_dir(tree):
    pol, _proj, _secret, tmp_path = tree
    assert pol.grant(tmp_path / "does-not-exist") is None
    assert pol.grant(_proj / "src" / "a.py") is None  # a file, not a dir

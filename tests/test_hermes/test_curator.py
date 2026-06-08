"""Tests for Phase 3 — the Skill Curator.

Covers archive-unused (with safety guards), overlap flagging (flag-only), and
the curation log. The curator only scans the skills dir it's given, so bundled
skills are inherently out of scope.
"""

from __future__ import annotations

import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from novacode_cli.hermes.curator import run_curation

_DAY = 86400.0


class FakeStore:
    def __init__(self) -> None:
        self.data: dict[tuple, dict] = {}

    async def aget(self, namespace, key):
        ns = self.data.get(tuple(namespace), {})
        return SimpleNamespace(value=dict(ns[key])) if key in ns else None

    async def aput(self, namespace, key, value):
        self.data.setdefault(tuple(namespace), {})[key] = dict(value)

    async def asearch(self, namespace):
        ns = self.data.get(tuple(namespace), {})
        return [SimpleNamespace(key=k, value=dict(v)) for k, v in ns.items()]


def _make_skill(skills_dir: Path, name: str, description: str) -> Path:
    d = skills_dir / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(
        f'---\nname: {name}\ndescription: "{description}"\n---\n\n# {name}\n\nstep\n',
        encoding="utf-8",
    )
    return d


@pytest.fixture
def env(tmp_path):
    return tmp_path / "skills", FakeStore()


async def _seed_created(store, name, ts):
    await store.aput(("nova", "created_skills"), name, {"timestamp": ts})


async def _seed_usage(store, name, invocations):
    await store.aput(("nova", "skill_usage"), name, {"invocations": invocations})


class TestArchiveUnused:
    async def test_archives_old_unused_created(self, env):
        skills_dir, store = env
        _make_skill(skills_dir, "stale", "does a thing")
        now = time.time()
        await _seed_created(store, "stale", now - 30 * _DAY)
        result = await run_curation(store, skills_dir, now=now)
        assert "stale" in result["archived"]
        assert not (skills_dir / "stale").exists()
        assert (skills_dir.parent / "skills-archive").exists()

    async def test_keeps_invoked_skill(self, env):
        skills_dir, store = env
        _make_skill(skills_dir, "useful", "x")
        now = time.time()
        await _seed_created(store, "useful", now - 30 * _DAY)
        await _seed_usage(store, "useful", 3)
        result = await run_curation(store, skills_dir, now=now)
        assert "useful" not in result["archived"]
        assert (skills_dir / "useful").exists()

    async def test_keeps_recent_skill(self, env):
        skills_dir, store = env
        _make_skill(skills_dir, "fresh", "x")
        now = time.time()
        await _seed_created(store, "fresh", now - 1 * _DAY)
        result = await run_curation(store, skills_dir, now=now)
        assert "fresh" not in result["archived"]

    async def test_never_archives_hand_written(self, env):
        # Not in created_skills → user-authored → never auto-archived.
        skills_dir, store = env
        _make_skill(skills_dir, "mine", "x")
        now = time.time()
        result = await run_curation(store, skills_dir, now=now)
        assert "mine" not in result["archived"]
        assert (skills_dir / "mine").exists()


class TestOverlapFlagging:
    async def test_flags_overlapping_pair(self, env):
        skills_dir, store = env
        _make_skill(skills_dir, "deploy-docker", "deploy the app with docker compose")
        _make_skill(skills_dir, "docker-deploy", "deploy the app using docker compose")
        result = await run_curation(store, skills_dir, now=time.time())
        pairs = {frozenset((o["a"], o["b"])) for o in result["overlaps"]}
        assert frozenset(("deploy-docker", "docker-deploy")) in pairs

    async def test_distinct_skills_not_flagged(self, env):
        skills_dir, store = env
        _make_skill(skills_dir, "pdf-export", "render reports to pdf")
        _make_skill(skills_dir, "git-bisect", "find a regression with bisection")
        result = await run_curation(store, skills_dir, now=time.time())
        assert result["overlaps"] == []

    async def test_overlap_never_deletes(self, env):
        skills_dir, store = env
        _make_skill(skills_dir, "a-thing", "same words here now")
        _make_skill(skills_dir, "b-thing", "same words here now")
        await run_curation(store, skills_dir, now=time.time())
        # Flag-only: both skills still on disk.
        assert (skills_dir / "a-thing").exists()
        assert (skills_dir / "b-thing").exists()


class TestCurationLog:
    async def test_log_written_on_action(self, env):
        skills_dir, store = env
        _make_skill(skills_dir, "stale", "x")
        now = time.time()
        await _seed_created(store, "stale", now - 30 * _DAY)
        await run_curation(store, skills_dir, now=now)
        log = store.data.get(("nova", "curation_log"), {})
        assert len(log) == 1
        entry = next(iter(log.values()))
        assert "stale" in entry["archived"]

    async def test_no_log_when_nothing_to_do(self, env):
        skills_dir, store = env
        _make_skill(skills_dir, "fresh", "unique alpha")
        result = await run_curation(store, skills_dir, now=time.time())
        assert result == {"archived": [], "overlaps": []}
        assert ("nova", "curation_log") not in store.data

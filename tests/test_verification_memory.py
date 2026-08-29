"""Tests for per-repo verification memory (hermes/verification_memory.py).

Verification "learns": failing checks and high-risk files are recorded per repo
and surfaced in later rubric prompts.
"""

from __future__ import annotations

from novacode_cli.hermes import config
from novacode_cli.hermes.verification_memory import (
    load_verification_memory,
    record_verification_failure,
)


class _FakeStore:
    """Minimal in-memory stand-in for the durable BaseStore."""

    def __init__(self) -> None:
        self._data: dict[tuple, dict] = {}

    async def aget(self, namespace: tuple, key: str, /) -> _Item | None:
        if (namespace, key) in self._data:
            return _Item(self._data[(namespace, key)])
        return None

    async def aput(self, namespace: tuple, key: str, value: dict, /) -> None:
        self._data[(namespace, key)] = value


class _Item:
    def __init__(self, value: dict) -> None:
        self.value = value


async def test_record_then_load_surfaces_failing_check() -> None:
    store = _FakeStore()
    await record_verification_failure(
        store,
        repo_root="B:/repo",
        failed_checks=["tests_pass"],
        files=["src/math.py"],
        feedback="tests are red",
    )
    summary = await load_verification_memory(store, repo_root="B:/repo")
    assert "tests_pass" in summary
    assert "src/math.py" in summary


async def test_different_repo_is_isolated() -> None:
    store = _FakeStore()
    await record_verification_failure(
        store,
        repo_root="B:/repoA",
        failed_checks=["tests_pass"],
        files=["a.py"],
        feedback="",
    )
    # repoB has no history.
    assert await load_verification_memory(store, repo_root="B:/repoB") == ""


async def test_no_store_returns_empty() -> None:
    assert await load_verification_memory(None, repo_root="B:/repo") == ""
    # Recording with no store is a no-op (never raises).
    await record_verification_failure(
        None, repo_root="B:/repo", failed_checks=[], files=[], feedback=""
    )


async def test_aggregates_recurring_files() -> None:
    store = _FakeStore()
    for _ in range(3):
        await record_verification_failure(
            store,
            repo_root="B:/repo",
            failed_checks=["no_test_gaming"],
            files=["tests/test_math.py"],
            feedback="",
        )
    summary = await load_verification_memory(store, repo_root="B:/repo")
    assert "no_test_gaming (3x)" in summary
    assert "tests/test_math.py (3x)" in summary


async def test_namespace_is_verification_memory() -> None:
    # Sanity: the module uses the declared namespace constant.
    assert config.VERIFICATION_MEMORY_NS == ("nova", "verification_memory")

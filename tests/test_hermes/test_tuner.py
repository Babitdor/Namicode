"""Tests for the threshold auto-tuner (Loop-Engineering Enhancement 4).

Covers the data-gating, directional nudges, damping, clamping, and the
``ReviewRunner`` lazy-load seam that consumes the tuned values.
"""

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from novacode_cli.hermes import config
from novacode_cli.hermes.review import ReviewRunner
from novacode_cli.hermes.tuner import ThresholdTuner, _clamp, _is_substantive


class FakeStore:
    """Minimal async ``BaseStore`` stand-in (same shape as other Hermes tests)."""

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


def _seed(store: FakeStore, *, reviews: int, history: list[tuple[str, bool]]) -> None:
    """Seed review count and a tool-history window into the store."""
    store.data[("nova", "meta")] = {"last_review": {"review_count": reviews}}
    entries = [
        {"tool": tool, "success": ok, "timestamp": float(i)} for i, (tool, ok) in enumerate(history)
    ]
    store.data[("nova", "tool_history")] = {"history": {"entries": entries}}


def _stored_thresholds(store: FakeStore) -> dict | None:
    return store.data.get(config.HARNESS_CONFIG_NS, {}).get(config.HARNESS_CONFIG_KEY)


# ── pure helpers ─────────────────────────────────────────────────────────────


class TestHelpers:
    def test_clamp_bounds(self):
        assert _clamp(3, 5, 50) == 5
        assert _clamp(99, 5, 50) == 50
        assert _clamp(12, 5, 50) == 12

    def test_substantive_predicate(self):
        assert _is_substantive("write_file") is True
        assert _is_substantive("execute") is True
        # A non-builtin (skill / MCP tool) counts as real work.
        assert _is_substantive("some_mcp_tool") is True
        # Read-only builtins do not.
        assert _is_substantive("read_file") is False
        assert _is_substantive("grep") is False
        assert _is_substantive(None) is False


# ── data gating ──────────────────────────────────────────────────────────────


class TestGating:
    async def test_skips_with_too_few_reviews(self):
        store = FakeStore()
        _seed(store, reviews=config.TUNER_MIN_BASIS_REVIEWS - 1, history=[("execute", True)] * 30)
        assert await ThresholdTuner(store).run_tuning_pass() is None
        assert _stored_thresholds(store) is None

    async def test_skips_with_too_little_history(self):
        store = FakeStore()
        _seed(store, reviews=20, history=[("execute", True)] * 5)
        assert await ThresholdTuner(store).run_tuning_pass() is None
        assert _stored_thresholds(store) is None


# ── directional nudges ───────────────────────────────────────────────────────


class TestDirection:
    async def test_substantive_work_lowers_threshold(self):
        store = FakeStore()
        _seed(store, reviews=20, history=[("edit_file", True)] * 30)
        result = await ThresholdTuner(store).run_tuning_pass()
        assert result is not None
        # All real work ⇒ review sooner than the default 10.
        assert result["review_threshold"] < config.REVIEW_THRESHOLD_DEFAULT
        assert result["review_threshold"] >= config.REVIEW_THRESHOLD_FLOOR

    async def test_browsing_raises_threshold(self):
        store = FakeStore()
        _seed(store, reviews=20, history=[("read_file", True)] * 30)
        result = await ThresholdTuner(store).run_tuning_pass()
        assert result is not None
        # All read-only browsing ⇒ defer reviews longer than the default.
        assert result["review_threshold"] > config.REVIEW_THRESHOLD_DEFAULT

    async def test_high_failure_rate_raises_burst(self):
        store = FakeStore()
        _seed(store, reviews=20, history=[("execute", False)] * 30)
        result = await ThresholdTuner(store).run_tuning_pass()
        assert result is not None
        assert result["failure_burst"] > config.FAILURE_BURST_DEFAULT

    async def test_no_failures_keeps_burst_at_default(self):
        store = FakeStore()
        _seed(store, reviews=20, history=[("execute", True)] * 30)
        result = await ThresholdTuner(store).run_tuning_pass()
        assert result is not None
        assert result["failure_burst"] == config.FAILURE_BURST_DEFAULT


# ── damping, clamping, persistence ───────────────────────────────────────────


class TestBlendingAndPersistence:
    async def test_damped_move_is_partial(self):
        store = FakeStore()
        _seed(store, reviews=20, history=[("edit_file", True)] * 30)
        result = await ThresholdTuner(store).run_tuning_pass()
        assert result is not None
        # Suggestion for all-substantive is 5; damping keeps it above 5 after one
        # pass (a single pass never jumps the whole way).
        threshold = result["review_threshold"]
        assert config.REVIEW_THRESHOLD_FLOOR <= threshold < config.REVIEW_THRESHOLD_DEFAULT

    async def test_poisoned_current_value_is_clamped(self):
        store = FakeStore()
        _seed(store, reviews=20, history=[("read_file", True)] * 30)
        # A hand-edited / corrupt stored value far outside the bounds.
        store.data[config.HARNESS_CONFIG_NS] = {
            config.HARNESS_CONFIG_KEY: {"review_threshold": 9999, "failure_burst": 9999}
        }
        result = await ThresholdTuner(store).run_tuning_pass()
        assert result is not None
        assert result["review_threshold"] <= config.REVIEW_THRESHOLD_CEILING
        assert result["failure_burst"] <= config.FAILURE_BURST_CEILING

    async def test_result_persisted_with_metadata(self):
        store = FakeStore()
        _seed(store, reviews=14, history=[("execute", True)] * 25)
        before = time.time()
        result = await ThresholdTuner(store).run_tuning_pass()
        assert result is not None
        stored = _stored_thresholds(store)
        assert stored == result
        assert stored["basis_reviews"] == 14
        assert stored["tuned_at"] >= before


# ── ReviewRunner lazy-load seam ──────────────────────────────────────────────


class TestReviewRunnerSeam:
    def _runner(self, store: FakeStore) -> ReviewRunner:
        # tracker / skill_manager are unused by _ensure_thresholds_loaded.
        return ReviewRunner(store, tracker=None, skill_manager=None)

    async def test_loads_tuned_values(self):
        store = FakeStore()
        store.data[config.HARNESS_CONFIG_NS] = {
            config.HARNESS_CONFIG_KEY: {"review_threshold": 7, "failure_burst": 5}
        }
        runner = self._runner(store)
        await runner._ensure_thresholds_loaded()
        assert runner._review_threshold == 7
        assert runner._failure_burst == 5

    async def test_defaults_when_absent(self):
        runner = self._runner(FakeStore())
        await runner._ensure_thresholds_loaded()
        assert runner._review_threshold == config.REVIEW_THRESHOLD_DEFAULT
        assert runner._failure_burst == config.FAILURE_BURST_DEFAULT

    async def test_clamps_on_read(self):
        store = FakeStore()
        store.data[config.HARNESS_CONFIG_NS] = {
            config.HARNESS_CONFIG_KEY: {"review_threshold": 9999, "failure_burst": 0}
        }
        runner = self._runner(store)
        await runner._ensure_thresholds_loaded()
        assert runner._review_threshold == config.REVIEW_THRESHOLD_CEILING
        assert runner._failure_burst == config.FAILURE_BURST_FLOOR

    async def test_load_is_idempotent(self):
        store = FakeStore()
        runner = self._runner(store)
        await runner._ensure_thresholds_loaded()
        # A value written *after* the first load must not be picked up again.
        store.data[config.HARNESS_CONFIG_NS] = {
            config.HARNESS_CONFIG_KEY: {"review_threshold": 7, "failure_burst": 5}
        }
        await runner._ensure_thresholds_loaded()
        assert runner._review_threshold == config.REVIEW_THRESHOLD_DEFAULT


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

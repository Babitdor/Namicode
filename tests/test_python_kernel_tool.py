"""Persistent Python kernel tool: namespace persistence, snapshots, timeouts."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from novacode_cli.tools.python_kernel_tool import _get_kernel, python_kernel

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from pathlib import Path


@pytest.fixture(autouse=True)
async def _fresh_kernel() -> AsyncIterator[None]:
    """Ensure a clean kernel per test (and close it after)."""
    kernel = await _get_kernel()
    await kernel.request({"op": "reset"}, timeout_secs=10)
    yield
    await kernel.close()


class TestPersistence:
    async def test_state_persists_across_calls(self):
        r1 = await python_kernel.ainvoke({"code": "x = 41"})
        assert "Error" not in r1
        r2 = await python_kernel.ainvoke({"code": "x + 1"})
        assert "42" in r2

    async def test_imports_persist(self):
        await python_kernel.ainvoke({"code": "import math"})
        r = await python_kernel.ainvoke({"code": "math.sqrt(16)"})
        assert "4.0" in r

    async def test_print_captured(self):
        r = await python_kernel.ainvoke({"code": "print('hello kernel')"})
        assert "hello kernel" in r

    async def test_no_output_returns_placeholder(self):
        r = await python_kernel.ainvoke({"code": "x = 1"})
        assert "(no output)" in r


class TestErrors:
    async def test_error_returns_traceback_and_namespace_survives(self):
        r = await python_kernel.ainvoke({"code": "1 / 0"})
        assert "Error" in r
        assert "ZeroDivisionError" in r
        # The namespace survives the error.
        await python_kernel.ainvoke({"code": "y = 5"})
        r2 = await python_kernel.ainvoke({"code": "y * 2"})
        assert "10" in r2

    async def test_reset_clears_namespace(self):
        await python_kernel.ainvoke({"code": "z = 99"})
        await python_kernel.ainvoke({"code": "reset"})
        r = await python_kernel.ainvoke({"code": "z"})
        assert "Error" in r  # NameError: z is gone


class TestSnapshots:
    async def test_save_and_load_roundtrip(self, tmp_path: Path):
        # Save a namespace with a lambda (dill-only, pickle would fail).
        r = await python_kernel.ainvoke(
            {
                "code": "f = lambda n: n * 3",
                "snapshot": "save",
                "snapshot_path": str(tmp_path / "ns.pkl"),
            }
        )
        assert "snapshot saved" in r
        assert (tmp_path / "ns.pkl").exists()

        # Reset, then load the snapshot and use the lambda.
        await python_kernel.ainvoke({"code": "reset"})
        r2 = await python_kernel.ainvoke(
            {
                "code": "f(7)",
                "snapshot": f"load:{tmp_path / 'ns.pkl'}",
            }
        )
        assert "21" in r2

    async def test_load_missing_snapshot_errors(self):
        r = await python_kernel.ainvoke({"code": "x = 1", "snapshot": "load:/nonexistent/ns.pkl"})
        assert "Error" in r
        assert "load failed" in r


class TestTimeout:
    async def test_hung_kernel_times_out_and_respawns(self):
        r = await python_kernel.ainvoke({"code": "import time; time.sleep(999)", "timeout": 1.0})
        assert "timed out" in r
        # Next call works on a fresh kernel.
        r2 = await python_kernel.ainvoke({"code": "1 + 1"})
        assert "2" in r2

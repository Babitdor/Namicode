"""Tests for test-evidence capture in the verification loop.

The loop collects the agent's test-run outputs so the verifier can grade
``tests_pass`` against real evidence rather than the agent's claims.
"""

from __future__ import annotations

from types import SimpleNamespace

from novacode_cli.core.verification_loop import (
    _extract_diffs,
    _extract_test_evidence,
    _looks_like_test_run,
)


def _tool_result(full_output: str) -> SimpleNamespace:
    return SimpleNamespace(full_output=full_output)


def test_pytest_output_is_detected() -> None:
    out = (
        "============================= test session starts =============================\n"
        "3 passed, 0 failed"
    )
    assert _looks_like_test_run(out)


def test_failed_test_output_is_detected() -> None:
    out = "tests/test_math.py::test_add FAILED\n1 failed, 2 passed"
    assert _looks_like_test_run(out)


def test_plain_prose_is_not_detected() -> None:
    out = "I passed the file to the function and it worked fine."
    assert not _looks_like_test_run(out)


def test_empty_output_is_not_detected() -> None:
    assert not _looks_like_test_run("")


def test_extract_test_evidence_collects_test_runs() -> None:
    results = [
        _tool_result("3 passed, 0 failed"),
        _tool_result("just some normal output"),
        _tool_result("1 failed, 2 passed"),
    ]
    evidence = _extract_test_evidence(results)
    assert len(evidence) == 2
    assert "3 passed" in evidence[0]
    assert "1 failed" in evidence[1]


def test_extract_test_evidence_ignores_non_test_output() -> None:
    results = [_tool_result("nothing test-like here")]
    assert _extract_test_evidence(results) == []


def test_extract_diffs_collects_non_empty_diffs() -> None:
    recs = [
        SimpleNamespace(diff="--- a/x\n+++ b/x\n-1\n+2"),
        SimpleNamespace(diff=None),
        SimpleNamespace(diff=""),
    ]
    diffs = _extract_diffs(recs)
    assert len(diffs) == 1
    assert "+++ b/x" in diffs[0]

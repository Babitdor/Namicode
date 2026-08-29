"""Tests for the deterministic test-gaming detector (hermes/test_gaming.py).

The detector flags candidate reward-hacking edits in test files so the LLM
rubric grader can check them under the ``no_test_gaming`` check.
"""

from __future__ import annotations

from novacode_cli.hermes.test_gaming import detect_test_gaming


def _diff(path: str, lines: list[str]) -> str:
    """Build a minimal unified-diff string for a single file."""
    header = f"--- a/{path} (before)\n+++ b/{path} (after)"
    return header + "\n" + "\n".join(lines)


def test_removed_assert_is_flagged() -> None:
    diff = _diff(
        "tests/test_math.py",
        [
            "@@ -1,5 +1,5 @@",
            "-    assert add(2, 2) == 4",
            "+    assert add(2, 2) == 5",
        ],
    )
    report = detect_test_gaming([diff])
    assert report.has_findings
    kinds = {f.kind for f in report.findings}
    assert "removed-assert" in kinds or "changed-expected" in kinds


def test_added_skip_is_flagged() -> None:
    diff = _diff(
        "tests/test_math.py",
        [
            "@@ -1,3 +1,4 @@",
            '+@pytest.mark.skip(reason="flaky")',
            " def test_add():",
        ],
    )
    report = detect_test_gaming([diff])
    assert report.has_findings
    assert any(f.kind == "added-skip" for f in report.findings)


def test_removed_test_function_is_flagged() -> None:
    diff = _diff(
        "tests/test_math.py",
        [
            "@@ -1,4 +1,2 @@",
            "-def test_division_by_zero():",
            "-    with pytest.raises(ZeroDivisionError):",
            "-        divide(1, 0)",
        ],
    )
    report = detect_test_gaming([diff])
    assert report.has_findings
    assert any(f.kind == "removed-test" for f in report.findings)


def test_non_test_file_is_ignored() -> None:
    diff = _diff(
        "src/math.py",
        [
            "@@ -1,3 +1,3 @@",
            "-    return a + b",
            "+    return a - b",
        ],
    )
    report = detect_test_gaming([diff])
    assert not report.has_findings


def test_legitimate_test_edit_is_not_flagged() -> None:
    # Adding a new assertion (not removing/weakening) should not be flagged.
    diff = _diff(
        "tests/test_math.py",
        [
            "@@ -1,3 +1,4 @@",
            "+    assert add(0, 0) == 0",
            "     assert add(1, 1) == 2",
        ],
    )
    report = detect_test_gaming([diff])
    assert not report.has_findings


def test_empty_diffs_produce_no_findings() -> None:
    assert not detect_test_gaming([]).has_findings
    assert not detect_test_gaming(None).has_findings


def test_summarize_renders_findings() -> None:
    diff = _diff(
        "tests/test_math.py",
        [
            "@@ -1,3 +1,3 @@",
            "-    assert add(2, 2) == 4",
            "+    assert add(2, 2) == 5",
        ],
    )
    report = detect_test_gaming([diff])
    summary = report.summarize()
    assert "candidate test-weakening" in summary
    assert "tests/test_math.py" in summary

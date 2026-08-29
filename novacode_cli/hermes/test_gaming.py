"""Deterministic test-gaming detector — Loop-Engineering "Verification that Learns".

The LLM rubric grader (``nova_verify.jinja``) is the final judge of whether an
agent weakened its tests to make them pass. This module gives that grader
*concrete signals* by scanning the agent's diffs for edits to test files that
are classic reward-hacking patterns:

- removed or weakened ``assert`` statements,
- added ``@pytest.mark.skip`` / ``skipif`` / ``xfail``,
- changed expected values to match the (possibly broken) output,
- deleted failing test cases,
- added trivial always-green tests.

The detector is deliberately *conservative*: it only flags candidate lines and
lets the LLM make the call. It never fails a turn on its own.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

#: Paths that look like test files.
_TEST_FILE_RE = re.compile(r"(^|[/\\])(test_|tests?[/\\]|.*_test\.)", re.IGNORECASE)

#: A diff line that *removes* an assertion (leading ``-``).
_REMOVED_ASSERT_RE = re.compile(r"^-\s*(assert|self\.assert|expect\(|\.to(Be|Equal|Throw))")
#: A diff line that *adds* a skip/xfail marker.
_ADDED_SKIP_RE = re.compile(
    r"^\+.*@(pytest\.mark\.(skip|skipif|xfail)|unittest\.skip|@Skip|@Disabled)"
)
#: A diff line that *removes* an assertion carrying an expected value — the
#: "old expected value deleted" signal (e.g. ``- assert add(2,2) == 4``). We
#: only match removed (``-``) lines: *adding* an assertion is legitimate.
_CHANGED_EXPECTED_RE = re.compile(
    r"^-\s*(assert.*(==|!=|in\b|not in\b)|assertEqual|assert.*expected|"
    r"expect\(.*\.to(Be|Equal|Throw)|toEqual|toBe)",
    re.IGNORECASE,
)
#: A diff line that removes a test function entirely.
_REMOVED_TEST_DEF_RE = re.compile(r"^-\s*(def test_|async def test_|@pytest\.mark\.parametrize)")


@dataclass
class TestGamingFinding:
    """One candidate reward-hacking signal found in a diff."""

    path: str
    kind: str
    line: str


@dataclass
class TestGamingReport:
    """Aggregated candidate signals across all changed files."""

    findings: list[TestGamingFinding] = field(default_factory=list)

    @property
    def has_findings(self) -> bool:
        """Whether any candidate test-weakening edits were found."""
        return bool(self.findings)

    def summarize(self, max_lines: int = 12) -> str:
        """Render the findings as short evidence lines for the rubric prompt."""
        if not self.findings:
            return ""
        lines = [f"Detected {len(self.findings)} candidate test-weakening edit(s):"]
        lines.extend(
            f"- {f.path}: {f.kind}: {f.line.strip()[:120]}" for f in self.findings[:max_lines]
        )
        if len(self.findings) > max_lines:
            lines.append(f"... and {len(self.findings) - max_lines} more")
        return "\n".join(lines)


def _is_test_file(path: str) -> bool:
    return bool(_TEST_FILE_RE.search(path))


def detect_test_gaming(diffs: list[str]) -> TestGamingReport:
    """Scan unified diffs for candidate test-weakening edits.

    Args:
        diffs: Unified diff strings (as produced by
            :func:`novacode_cli.file_ops.compute_unified_diff`).

    Returns:
        A :class:`TestGamingReport` of candidate findings. Empty when no test
        files were changed or no suspicious edits were found.
    """
    report = TestGamingReport()
    for diff in diffs or []:
        path = _diff_path(diff)
        if not path or not _is_test_file(path):
            continue
        for line in diff.splitlines():
            if _REMOVED_ASSERT_RE.match(line):
                report.findings.append(
                    TestGamingFinding(path=path, kind="removed-assert", line=line)
                )
            elif _ADDED_SKIP_RE.match(line):
                report.findings.append(TestGamingFinding(path=path, kind="added-skip", line=line))
            elif _REMOVED_TEST_DEF_RE.match(line):
                report.findings.append(TestGamingFinding(path=path, kind="removed-test", line=line))
            elif _CHANGED_EXPECTED_RE.match(line):
                report.findings.append(
                    TestGamingFinding(path=path, kind="changed-expected", line=line)
                )
    return report


def _diff_path(diff: str) -> str | None:
    """Extract the file path from a unified diff header (``+++ b/path``)."""
    for line in diff.splitlines():
        if line.startswith("+++ "):
            # Strip the "a/"/"b/" prefix and any "(before)"/"(after)" suffix.
            return line[4:].split(" (")[0].lstrip("ab/")
    return None

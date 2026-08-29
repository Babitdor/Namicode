"""Per-repo verification memory — "Verification that Learns".

The inline verifier grades each turn against a rubric. This module makes that
grading *learn*: it records which checks fail, which files are involved, and
which failure patterns recur, keyed by repository. Before the next grade it
loads the repo's recent failure history and injects it into the rubric prompt,
so high-risk files and recurring failure patterns get extra scrutiny over time.

Storage is the durable LangGraph ``BaseStore`` (``~/.nova/store.db``) under the
:data:`~novacode_cli.hermes.config.VERIFICATION_MEMORY_NS` namespace. Each repo
holds a single key with a bounded, rolling list of recent failure records, so
the memory never grows unbounded and stale patterns age out.
"""

from __future__ import annotations

import hashlib
import logging
import time
from typing import TYPE_CHECKING, Any

from novacode_cli.hermes import config

if TYPE_CHECKING:
    from langgraph.store.base import BaseStore

logger = logging.getLogger("nova.hermes.verification_memory")

#: How many recent failure records to retain per repo.
_MAX_RECORDS_PER_REPO: int = 20
#: How old a failure record may be before it is dropped (seconds).
_MAX_RECORD_AGE_SECONDS: int = 60 * 60 * 24 * 14  # 14 days
#: How many distinct high-risk files to surface in the rubric prompt.
_MAX_FILES_SURFACED: int = 8


def _repo_key(repo_root: str | None) -> str:
    """Hash the repo root into a stable store key (avoids path chars in keys)."""
    if not repo_root:
        return "unknown"
    return hashlib.sha256(repo_root.encode("utf-8")).hexdigest()[:16]


def _now() -> float:
    return time.time()


async def record_verification_failure(
    store: BaseStore | None,
    *,
    repo_root: str | None,
    failed_checks: list[str],
    files: list[str],
    feedback: str,
) -> None:
    """Record a failing verdict for a repo (best-effort, never raises).

    Args:
        store: Durable store; ``None`` disables recording.
        repo_root: Absolute path of the repo being worked on.
        failed_checks: Names of the rubric checks that failed (e.g.
            ``["tests_pass"]``).
        files: Paths of the files involved in the turn.
        feedback: The verifier's feedback for the failed attempt.
    """
    if store is None:
        return
    try:
        key = _repo_key(repo_root)
        item = await store.aget(config.VERIFICATION_MEMORY_NS, key)
        records: list[dict[str, Any]] = list((item.value or {}).get("records", [])) if item else []

        records.append(
            {
                "ts": _now(),
                "checks": list(failed_checks),
                "files": list(files)[:_MAX_FILES_SURFACED],
                "feedback": (feedback or "")[:200],
            }
        )
        # Drop stale records, then cap the list.
        cutoff = _now() - _MAX_RECORD_AGE_SECONDS
        records = [r for r in records if r.get("ts", 0) >= cutoff][-_MAX_RECORDS_PER_REPO:]

        await store.aput(config.VERIFICATION_MEMORY_NS, key, {"records": records})
    except Exception:
        logger.exception("Failed to record verification failure")


async def load_verification_memory(store: BaseStore | None, *, repo_root: str | None) -> str:
    """Load a repo's recent failure history as a rubric-prompt summary.

    Returns a short human-readable block (or ``""`` when there is nothing
    notable) that the verifier injects into ``nova_verify.jinja`` so it pays
    extra attention to recurring failure patterns.
    """
    if store is None:
        return ""
    try:
        item = await store.aget(config.VERIFICATION_MEMORY_NS, _repo_key(repo_root))
        if item is None:
            return ""
        records: list[dict[str, Any]] = list((item.value or {}).get("records", []))
        if not records:
            return ""

        # Aggregate: which checks fail most, which files recur.
        check_counts: dict[str, int] = {}
        file_counts: dict[str, int] = {}
        for r in records:
            for c in r.get("checks", []):
                check_counts[c] = check_counts.get(c, 0) + 1
            for f in r.get("files", []):
                file_counts[f] = file_counts.get(f, 0) + 1

        top_checks = sorted(check_counts, key=check_counts.get, reverse=True)[:4]
        top_files = sorted(file_counts, key=file_counts.get, reverse=True)[:_MAX_FILES_SURFACED]

        lines = [
            "This repo has a history of verification failures. Pay extra attention to:",
        ]
        if top_checks:
            lines.append(
                "Recurring failing checks: "
                + ", ".join(f"{c} ({check_counts[c]}x)" for c in top_checks)
            )
        if top_files:
            lines.append(
                "High-risk files: " + ", ".join(f"{f} ({file_counts[f]}x)" for f in top_files)
            )
        return "\n".join(lines)
    except Exception:
        logger.exception("Failed to load verification memory")
        return ""

"""Skill discovery — pattern recognition, skill creation, and refinement.

This module implements the "Autonomous Skill Creation" and "Skill Refinement"
pillars of the Nova system. It analyzes tool usage history to detect
repeated workflow patterns, creates reusable SKILL.md files from those
patterns, and refines existing skills when better approaches are found.

Pattern detection approach:
    1. Group tool calls by session (roughly: tools called in sequence)
    2. Look for repeated sequences of 3+ tool calls
    3. Filter out trivial sequences (only read_file, only grep)
    4. Flag sequences that include write_file, edit_file, execute, tests
    5. Consider: did the user approve/praise the result? (tracked via success)
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from langgraph.store.base import BaseStore

logger = logging.getLogger("nova.hermes.skill_discovery")

# Minimum sequence length to consider as a pattern
_MIN_PATTERN_LENGTH = 3
# Minimum number of repetitions to consider as a skill candidate
_MIN_REPETITIONS = 2
# Recent tool calls to analyze
_RECENT_N = 100


# ── TUI Event Emission ─────────────────────────────────────────────────────


def _emit_tui_event(event_type: str, message: str) -> None:
    """Surface a skill-activity notification via the shared Nova event buffer.

    Autonomous skill creation/refinement runs *inside the agent loop* (Hermes),
    so printing to the console here corrupts the Textual TUI (it overlaps the
    input box). Instead we append to ``nova_event_log``, which
    ``iterate_agent_events`` drains into a ``ContextMessage`` rendered by both the
    Rich console REPL and the TUI. Best-effort — never raise from a notification.

    Events include:
    - nova_skill_created: Skill created from pattern
    - nova_skill_refined: Skill improved based on feedback
    - nova_skill_error: Error in skill creation/refinement
    """
    event_config = {
        "nova_skill_created": {"icon": "🧠", "color": "green"},
        "nova_skill_refined": {"icon": "🛠", "color": "yellow"},
        "nova_skill_error": {"icon": "⚠", "color": "red"},
    }
    config = event_config.get(event_type, {"icon": "•", "color": "cyan"})
    try:
        from novacode_cli.hermes.middleware import nova_event_log

        nova_event_log.append(
            (event_type, config["icon"], config["color"], message)
        )
    except Exception:  # noqa: BLE001
        logger.debug("skill event (not surfaced): %s — %s", event_type, message)


# ── Pattern detection ──────────────────────────────────────────────────────


class Pattern:
    """A detected tool usage pattern that may warrant skill creation."""

    def __init__(
        self,
        sequence: list[str],
        frequency: int,
        success_rate: float,
        description: str = "",
    ) -> None:
        self.sequence = sequence
        self.frequency = frequency
        self.success_rate = success_rate
        self.description = description or " | ".join(sequence)

    def to_dict(self) -> dict[str, Any]:
        return {
            "sequence": self.sequence,
            "frequency": self.frequency,
            "success_rate": self.success_rate,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Pattern:
        return cls(
            sequence=data["sequence"],
            frequency=data.get("frequency", 1),
            success_rate=data.get("success_rate", 1.0),
            description=data.get("description", ""),
        )


def _is_trivial(tools: list[str]) -> bool:
    """Check if a tool sequence is too trivial to be a skill."""
    non_trivial = {"execute", "write_file", "edit_file", "run_tests"}
    return not any(t in non_trivial for t in tools)


def _sequence_key(seq: list[str]) -> str:
    """Create a canonical key for a tool sequence."""
    return "→".join(seq)


def detect_patterns(
    history: list[dict[str, Any]], min_length: int = _MIN_PATTERN_LENGTH
) -> list[Pattern]:
    """Detect repeated tool usage patterns from tool history.

    Uses a sliding-window approach: for each subsequence of ``min_length``
    consecutive tools, count how many times it appears. Patterns appearing
    more than once are candidates.

    Args:
        history: List of tool usage records with ``tool`` and ``success`` keys.
        min_length: Minimum sequence length to consider.

    Returns:
        List of detected patterns, sorted by frequency descending.
    """
    if len(history) < min_length:
        return []

    tools = [h["tool"] for h in history]
    sequences: dict[str, list[str]] = {}
    success_map: dict[str, list[bool]] = {}

    for i in range(len(tools) - min_length + 1):
        seq = tools[i : i + min_length]
        key = _sequence_key(seq)

        if key not in sequences:
            sequences[key] = seq

        # Track success for this occurrence
        if key not in success_map:
            success_map[key] = []
        success_map[key].append(
            all(h.get("success", True) for h in history[i : i + min_length])
        )

    patterns: list[Pattern] = []
    for key, seq in sequences.items():
        occurrences = len(success_map[key])
        if occurrences < _MIN_REPETITIONS:
            continue
        if _is_trivial(seq):
            continue

        successes = sum(1 for s in success_map[key] if s)
        success_rate = successes / occurrences if occurrences > 0 else 0.0

        patterns.append(
            Pattern(
                sequence=seq,
                frequency=occurrences,
                success_rate=success_rate,
            )
        )

    patterns.sort(key=lambda p: p.frequency, reverse=True)
    return patterns


def is_skill_candidate(pattern: Pattern) -> bool:
    """Check if a pattern is complex enough and reusable to be a skill.

    Criteria:
    - At least 3 tool calls in the sequence
    - Appeared at least 2 times
    - At least 60% success rate
    - Includes at least one non-trivial tool (write, edit, execute, test)
    """
    if len(pattern.sequence) < _MIN_PATTERN_LENGTH:
        return False
    if pattern.frequency < _MIN_REPETITIONS:
        return False
    if pattern.success_rate < 0.6:
        return False
    if _is_trivial(pattern.sequence):
        return False
    return True


def generate_skill_name(pattern: Pattern) -> str:
    """Derive a skill name from the tool sequence.

    Uses non-trivial tools as hints and appends a hash suffix to avoid collisions.
    """
    tool_hints = {
        "execute": "exec",
        "write_file": "write",
        "edit_file": "edit",
        "run_tests": "test",
    }
    hints: list[str] = []
    for t in pattern.sequence:
        hint = tool_hints.get(t)
        if hint and hint not in hints:
            hints.append(hint)

    if hints:
        base = "-".join(hints[:2])
    else:
        base = "tool"

    # Deterministic hash (stable across processes) so the same pattern always
    # maps to the same skill name — enables dedup. Python's built-in hash() is
    # randomized per process (PYTHONHASHSEED) and must not be used here.
    import hashlib

    seq_hash = hashlib.sha1(_sequence_key(pattern.sequence).encode("utf-8")).hexdigest()[:6]
    return f"nova-{base}-{seq_hash}"


def pattern_to_description(pattern: Pattern) -> str:
    """Generate a human-readable description for a pattern-based skill."""
    tools_str = " → ".join(pattern.sequence)
    return (
        f"Automated workflow detected from repeated tool usage: {tools_str}. "
        f"Appeared {pattern.frequency} times with "
        f"{pattern.success_rate * 100:.0f}% success rate."
    )


# ── Skill creation ─────────────────────────────────────────────────────────


async def create_skill_from_pattern(
    pattern: Pattern,
    skills_dir: Path,
    store: BaseStore | None = None,
) -> str | None:
    """Create a skill from a detected pattern.

    Reuses the existing ``_generate_skill`` from ``novacode_cli.skills.skill_creation``.

    Args:
        pattern: The detected tool usage pattern.
        skills_dir: Directory where skills are stored (``~/.nova/skills/``).
        store: Optional durable store for recording the creation.

    Returns:
        The skill name if created successfully, None otherwise.
    """
    if not is_skill_candidate(pattern):
        return None

    skill_name = generate_skill_name(pattern)
    description = pattern_to_description(pattern)

    try:
        from novacode_cli.skills.skill_creation import _generate_skill

        result = await _generate_skill(skill_name, skills_dir, description)
        if result:
            _emit_tui_event(
                "nova_skill_created",
                f"Nova created skill: {skill_name}\n   Description: {description}\n   Location: {skills_dir / skill_name}/",
            )

            if store:
                await store.aput(
                    ("nova", "created_skills"),
                    skill_name,
                    {
                        "pattern": pattern.to_dict(),
                        "timestamp": time.time(),
                    },
                )
            return skill_name
    except Exception as exc:
        _emit_tui_event(
            "nova_skill_error", f"Nova skill creation failed for '{skill_name}': {exc}"
        )
    return None


# ── Episode-grounded skill creation (from the review LLM) ───────────────────
#
# The review runs an out-of-band model call WITH the full conversation in
# context (see NovaLearningMiddleware._run_review), so it can recognize a real,
# reusable workflow from this session and write a proper skill — a semantic
# name, a "use when…" trigger, and concrete steps. That is far better signal
# than n-grams of tool *names* (which produce opaque `nova-exec-<hash>` skills
# the agent never invokes). The functions below parse that spec and write it.


# Legacy auto-skill names: nova-<hint>[-<hint>]-<6 hex>, e.g. nova-edit-test-5628de.
_LEGACY_SKILL_RE = re.compile(r"^nova-[a-z]+(?:-[a-z]+)?-[0-9a-f]{6}$")

# <skill> … </skill> block in a review response, with name/description/body.
_SKILL_BLOCK_RE = re.compile(r"<skill>(.*?)</skill>", re.DOTALL | re.IGNORECASE)
_SKILL_NAME_RE = re.compile(r"<name>(.*?)</name>", re.DOTALL | re.IGNORECASE)
_SKILL_DESC_RE = re.compile(r"<description>(.*?)</description>", re.DOTALL | re.IGNORECASE)
_SKILL_BODY_RE = re.compile(r"<body>(.*?)</body>", re.DOTALL | re.IGNORECASE)


def _slugify_skill_name(raw: str) -> str:
    """Normalize an LLM-proposed name into a safe kebab-case skill slug."""
    slug = raw.strip().lower()
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"[^a-z0-9-]", "", slug)
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    return slug[:50]


def parse_skill_spec(review_text: str) -> dict[str, str] | None:
    """Extract an episode skill spec from a review response.

    Looks for::

        <skill>
        <name>add-tui-slash-command</name>
        <description>Use when adding a new /command to the Textual TUI.</description>
        <body>… full SKILL.md body (markdown, no frontmatter) …</body>
        </skill>

    Returns:
        ``{"name", "description", "body"}`` with a slugified name, or ``None``
        when no valid block is present (name + body are required).
    """
    block_match = _SKILL_BLOCK_RE.search(review_text or "")
    if not block_match:
        return None
    block = block_match.group(1)

    name_match = _SKILL_NAME_RE.search(block)
    body_match = _SKILL_BODY_RE.search(block)
    desc_match = _SKILL_DESC_RE.search(block)
    if not name_match or not body_match:
        return None

    name = _slugify_skill_name(name_match.group(1))
    body = body_match.group(1).strip()
    description = (desc_match.group(1).strip() if desc_match else "").replace("\n", " ")
    if not name or not body or _LEGACY_SKILL_RE.match(name):
        return None

    return {"name": name, "description": description, "body": body}


async def write_skill_from_spec(
    spec: dict[str, str],
    skills_dir: Path,
    store: BaseStore | None = None,
) -> str | None:
    """Write an episode-grounded skill (name + trigger + body) to disk.

    Unlike ``create_skill_from_pattern`` this does NOT spin up a second LLM to
    invent content — the review already wrote it. We just frame valid YAML
    frontmatter and persist it. Deduped by directory existence + store record.

    Returns:
        The skill name if written, else ``None`` (invalid spec / duplicate).
    """
    name = spec.get("name", "")
    body = spec.get("body", "")
    description = spec.get("description", "") or f"Reusable workflow: {name}"
    if not name or not body:
        return None

    skill_dir = skills_dir / name
    if skill_dir.exists():
        return None  # dedup: skill already exists
    if store is not None:
        try:
            if await store.aget(("nova", "created_skills"), name) is not None:
                return None
        except Exception:  # noqa: BLE001
            pass

    # Escape any double-quotes in the description for the YAML scalar.
    safe_desc = description.replace('"', "'")
    content = f'---\nname: {name}\ndescription: "{safe_desc}"\n---\n\n{body}\n'

    try:
        skill_dir.mkdir(parents=True, exist_ok=True)
        (skill_dir / "SKILL.md").write_text(content, encoding="utf-8")
    except OSError as exc:
        _emit_tui_event("nova_skill_error", f"Could not write skill '{name}': {exc}")
        return None

    _emit_tui_event(
        "nova_skill_created",
        f"Nova learned a skill: {name}\n   {description}\n   {skill_dir}/",
    )
    if store is not None:
        try:
            await store.aput(
                ("nova", "created_skills"),
                name,
                {"description": description, "source": "review", "timestamp": time.time()},
            )
        except Exception:  # noqa: BLE001
            pass
    return name


def cleanup_legacy_pattern_skills(skills_dir: Path) -> list[str]:
    """Delete the old n-gram auto-skills (``nova-<hint>-<hash>``) from disk.

    These were generated from tool-name sequences with opaque names and generic
    bodies the agent never invokes. Only directories matching the exact legacy
    naming are removed — hand-written or episode skills are untouched.

    Returns:
        The list of removed skill names.
    """
    removed: list[str] = []
    if not skills_dir.exists():
        return removed
    try:
        for child in skills_dir.iterdir():
            if child.is_dir() and _LEGACY_SKILL_RE.match(child.name):
                try:
                    shutil.rmtree(child)
                    removed.append(child.name)
                except OSError:
                    logger.debug("Could not remove legacy skill %s", child.name)
    except OSError:
        logger.debug("Could not scan skills dir for legacy cleanup")
    return removed


# ── Skill refinement ───────────────────────────────────────────────────────


async def check_skill_effectiveness(
    store: BaseStore,
) -> list[tuple[str, str]]:
    """Check all tracked skills for effectiveness issues.

    Returns a list of (skill_name, issue) tuples for skills needing attention.

    Issues detected:
    - "high_failure" — success_rate < 0.6 with >5 uses
    - "low_usage" — skill has <2 uses total
    """
    issues: list[tuple[str, str]] = []

    try:
        results = await store.asearch(("nova", "skill_stats"))
        for item in results:
            if not hasattr(item, "key") or not hasattr(item, "value"):
                continue
            # item.key is the store key, item.value is the stats dict
            value = item.value
            if not isinstance(value, dict):
                continue
            uses = value.get("uses", 0)
            successes = value.get("successes", 0)

            # High failure rate
            if uses >= 5:
                success_rate = successes / uses if uses > 0 else 0.0
                if success_rate < 0.6:
                    issues.append((item.key, "high_failure"))

            # Low usage (skill was created but barely used)
            if uses < 2:
                issues.append((item.key, "low_usage"))
    except Exception:  # noqa: BLE001
        pass

    return issues


async def refine_skill(
    skill_name: str,
    skills_dir: Path,
    issue: str,
) -> bool:
    """Refine an existing skill based on detected issues.

    Re-runs skill generation with improvement context.

    Args:
        skill_name: Name of the skill to refine.
        skills_dir: Directory where skills are stored.
        issue: The detected issue (e.g., "high_failure", "low_usage").

    Returns:
        True if refinement was successful, False otherwise.
    """
    skill_path = skills_dir / skill_name / "SKILL.md"
    if not skill_path.exists():
        _emit_tui_event(
            "nova_skill_error", f"Cannot refine '{skill_name}': SKILL.md not found"
        )
        return False

    issue_descriptions = {
        "high_failure": "This skill has a high failure rate. Review and simplify the instructions to make them more reliable.",
        "low_usage": "This skill has low usage. Consider whether the trigger pattern is too narrow or the instructions need clarification.",
    }
    improvement_context = issue_descriptions.get(issue, f"Improvement needed: {issue}")

    try:
        from novacode_cli.skills.skill_creation import _generate_skill

        result = await _generate_skill(
            skill_name,
            skills_dir,
            f"Refinement: {improvement_context}",
        )
        if result:
            _emit_tui_event(
                "nova_skill_refined", f"Nova refined skill: {skill_name} ({issue})"
            )
            return True
    except Exception as exc:
        _emit_tui_event(
            "nova_skill_error",
            f"Nova skill refinement failed for '{skill_name}': {exc}",
        )

    return False


# ── Public analysis API ────────────────────────────────────────────────────


async def analyze_tool_history(
    store: BaseStore,
    recent_n: int = _RECENT_N,
) -> list[Pattern]:
    """Analyze recent tool history for skill-worthy patterns.

    Args:
        store: Durable store with tool history.
        recent_n: Number of recent tool calls to analyze.

    Returns:
        List of detected patterns that are skill candidates.
    """
    try:
        entry = await store.aget(("nova", "tool_history"), "history")
        if entry and isinstance(entry.value, dict):
            history = entry.value.get("entries", [])[-recent_n:]
            patterns = detect_patterns(history)
            return [p for p in patterns if is_skill_candidate(p)]
    except Exception:  # noqa: BLE001
        pass
    return []

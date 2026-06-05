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
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from novacode_cli.config.config import console

if TYPE_CHECKING:
    from langgraph.store.base import BaseStore

# Minimum sequence length to consider as a pattern
_MIN_PATTERN_LENGTH = 3
# Minimum number of repetitions to consider as a skill candidate
_MIN_REPETITIONS = 2
# Recent tool calls to analyze
_RECENT_N = 100


# ── TUI Event Emission ─────────────────────────────────────────────────────


def _emit_tui_event(event_type: str, message: str) -> None:
    """Emit a structured notification for TUI display.

    Uses Rich text with TUI-appropriate styling. Events include:
    - nova_skill_created: Skill created from pattern
    - nova_skill_refined: Skill improved based on feedback
    - nova_skill_error: Error in skill creation/refinement
    """
    try:
        from rich.text import Text

        # Map event types to styling and icons
        event_config = {
            "nova_skill_created": {
                "icon": "🧠",
                "color": "green",
            },
            "nova_skill_refined": {
                "icon": "🛠",
                "color": "yellow",
            },
            "nova_skill_error": {
                "icon": "⚠",
                "color": "red",
            },
        }

        config = event_config.get(event_type, {"icon": "•", "color": "cyan"})
        text = Text(f"{config['icon']}  {message}", style=config["color"])
        console.print(text)
    except Exception:  # noqa: BLE001
        # Fallback: plain console output
        try:
            console.print(message)
        except Exception:  # noqa: BLE001
            pass


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

    seq_hash = hex(hash(_sequence_key(pattern.sequence)) & 0xFFFF)[2:]
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

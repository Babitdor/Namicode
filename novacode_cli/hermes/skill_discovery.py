"""Skill discovery — episode-grounded skill creation and refinement.

This module implements the "Autonomous Skill Creation" and "Skill Refinement"
pillars of the **Procedural memory tier**. Skills are created from the review
engine's ``<skill>`` block — an episode-grounded spec written with the full
conversation in context (semantic name, "use when…" trigger, concrete steps) —
and refined when their attributed outcomes show they're ineffective.

(An earlier n-gram path that synthesized opaque ``nova-<hash>`` skills from tool
*name* sequences was removed; ``cleanup_legacy_pattern_skills`` reclaims any
left on disk.)
"""

from __future__ import annotations

import logging
import re
import shutil
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from langgraph.store.base import BaseStore

logger = logging.getLogger("nova.hermes.skill_discovery")


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
        from novacode_cli.events import nova_event_log

        nova_event_log.append((event_type, config["icon"], config["color"], message))
    except Exception:  # noqa: BLE001
        logger.debug("skill event (not surfaced): %s — %s", event_type, message)


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

    Reads the ``("nova", "skill_usage")`` namespace, which records actual
    SKILL.md invocations and the outcomes attributed to them (see
    ``ToolUsageTracker``). Earlier this read ``skill_stats`` keyed by *tool*
    name, so it could never match a real skill — the refinement loop was inert.

    Returns a list of (skill_name, issue) tuples for skills needing attention.

    Issues detected:
    - "high_failure" — success_rate < 0.6 over >=5 attributed outcomes
    - "low_usage" — skill invoked fewer than 2 times
    """
    issues: list[tuple[str, str]] = []

    try:
        results = await store.asearch(("nova", "skill_usage"))
        for item in results:
            if not hasattr(item, "key") or not hasattr(item, "value"):
                continue
            # item.key is the skill name, item.value is the usage dict
            value = item.value
            if not isinstance(value, dict):
                continue
            # New schema uses "invocations"; fall back to legacy "uses".
            invocations = value.get("invocations", value.get("uses", 0))
            successes = value.get("successes", 0)
            failures = value.get("failures", 0)
            outcomes = successes + failures

            # High failure rate over a meaningful number of attributed outcomes.
            if outcomes >= 5:
                success_rate = successes / outcomes if outcomes > 0 else 0.0
                if success_rate < 0.6:
                    issues.append((item.key, "high_failure"))

            # Low usage (skill was created but barely invoked).
            if invocations < 2:
                issues.append((item.key, "low_usage"))
    except Exception:  # noqa: BLE001
        pass

    return issues


async def refine_skill(
    skill_name: str,
    skills_dir: Path,
    issue: str,
    *,
    failure_samples: list[dict[str, Any]] | None = None,
) -> bool:
    """Refine an existing skill — **grounded in the actual failures**.

    Unlike the old blind regenerate, this reads the current ``SKILL.md`` and
    the captured ``failure_samples`` (tool + error excerpt) and asks the model
    for a *targeted* improvement that addresses those specific failures. The
    prior version is snapshotted first, so a bad refinement can be rolled back.

    Args:
        skill_name: Name of the skill to refine.
        skills_dir: Directory where skills are stored.
        issue: The detected issue (``high_failure`` | ``low_usage``).
        failure_samples: Recent per-skill failure excerpts (from ``skill_usage``).

    Returns:
        True if a refinement was written, False otherwise.
    """
    skill_dir = skills_dir / skill_name
    skill_path = skill_dir / "SKILL.md"
    if not skill_path.exists():
        _emit_tui_event("nova_skill_error", f"Cannot refine '{skill_name}': SKILL.md not found")
        return False

    try:
        current = skill_path.read_text(encoding="utf-8")
    except OSError:
        return False

    issue_descriptions = {
        "high_failure": (
            "This skill has a high failure rate. Diagnose *why* it fails from the "
            "failure samples below and revise the steps so the failures don't recur "
            "(fix wrong commands/paths/assumptions; add missing prerequisites or "
            "guardrails). Keep what works; change only what the evidence implicates."
        ),
        "low_usage": (
            "This skill is rarely invoked. Sharpen the `description` (the trigger) "
            "so it matches the situations it's meant for, and tighten the steps."
        ),
    }
    guidance = issue_descriptions.get(issue, f"Improvement needed: {issue}")

    samples_text = ""
    if failure_samples:
        lines = [
            f"- [{s.get('tool', '?')}] {s.get('excerpt', '').strip()}"
            for s in failure_samples
            if s.get("excerpt")
        ]
        if lines:
            samples_text = "\n\nObserved failures while using this skill:\n" + "\n".join(lines)

    prompt = (
        "You are refining an existing agent skill (a SKILL.md playbook).\n\n"
        f"{guidance}{samples_text}\n\n"
        "Here is the current SKILL.md:\n\n"
        f"{current}\n\n"
        "Return the COMPLETE improved SKILL.md (YAML frontmatter + body). "
        "Do not add commentary outside the file content."
    )

    try:
        from langchain_core.messages import SystemMessage

        from novacode_cli.config.model_create import create_model
        from novacode_cli.skills.skill_creation import (
            _extract_skill_md_from_response,
        )

        model = create_model()
        resp = await model.ainvoke(
            [SystemMessage(content=prompt)],
            config={
                "run_name": "nova_skill_refine",
                "tags": ["nova", "hermes", "skill-refine"],
                "metadata": {
                    # Out-of-band marker: keeps the regenerated SKILL.md from
                    # leaking into the chat as a "Nova" assistant message (this
                    # task inherits the graph's stream callback via contextvars).
                    # See agent_loop's nova_oob filter.
                    "nova_oob": True,
                    "skill": skill_name,
                    "issue": issue,
                    "n_failure_samples": len(failure_samples or []),
                },
            },
        )
        raw = getattr(resp, "content", "")
        text = raw if isinstance(raw, str) else str(raw)
        new_md = _extract_skill_md_from_response(text, skill_name) or (
            text.strip() if text.strip().startswith("---") else None
        )
        if not new_md or new_md.strip() == current.strip():
            return False

        from novacode_cli.skills import versioning

        versioning.snapshot(skill_dir, reason=f"refine:{issue}", source="refine")
        skill_path.write_text(new_md.rstrip() + "\n", encoding="utf-8")
        _emit_tui_event(
            "nova_skill_refined",
            f"Nova refined skill: {skill_name} ({issue}) — previous version saved",
        )
        return True
    except Exception as exc:  # noqa: BLE001
        _emit_tui_event(
            "nova_skill_error",
            f"Nova skill refinement failed for '{skill_name}': {exc}",
        )

    return False

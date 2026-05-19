"""Handler for /<skill-name> direct skill invocation.

When the user types a slash command that doesn't match any built-in
command (like /help, /init, etc.), we check if it matches a skill name.
If it does, we read the skill's SKILL.md and return its content as a
prompt for the agent to follow.

Examples:
    /api-testing          → invoke the "api-testing" skill
    /docker-deploy        → invoke the "docker-deploy" skill
    /code-review fix.py   → invoke "code-review" with "fix.py" as extra args
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from novacode_cli.config.config import COLORS, Settings, console
from novacode_cli.skills.load import list_skills


async def _try_skill_invocation(
    cmd: str,
    cmd_args: str | None,
    session_state: Any,
    assistant_id: str,
) -> str | None:
    """Try to invoke a skill by name.

    Checks if ``cmd`` matches a known skill name (from user-skills or
    project-skills directories).  If found, reads the SKILL.md and
    returns a formatted prompt string that the agent will process.
    If not found, returns ``None`` so the caller can show "unknown command".

    Args:
        cmd: The command name (without the leading ``/``).
        cmd_args: Optional arguments after the skill name.
        session_state: Current session state (for workspace_root).
        assistant_id: Agent identifier (for user skills directory).

    Returns:
        A prompt string if the skill was found, or ``None`` if not.
    """
    settings = Settings.from_environment()
    in_project = settings.project_root is not None

    # Collect skills from all sources
    user_skills_dir = settings.ensure_user_skills_dir(assistant_id)
    project_skills_dir = settings.get_project_skills_dir() if in_project else None

    skills = list_skills(
        user_skills_dir=user_skills_dir,
        project_skills_dir=project_skills_dir,
    )

    if not skills:
        return None

    # Normalize the command to match skill names (hyphens = hyphens)
    # Skill names use hyphens (e.g. "api-testing"), but users might
    # type underscores or spaces.  Normalize to hyphens for matching.
    cmd_normalized = cmd.replace("_", "-").strip().lower()

    # Find matching skill
    matched_skill = None
    for skill in skills:
        skill_name = skill.get("name", "").lower()
        if skill_name == cmd_normalized:
            matched_skill = skill
            break

    if matched_skill is None:
        return None

    # Found a matching skill — read its SKILL.md
    skill_name = matched_skill.get("name", cmd)
    skill_path = matched_skill.get("path", "")

    # The skill's SKILL.md content
    skill_content = _read_skill_content(matched_skill, user_skills_dir, project_skills_dir)
    if not skill_content:
        console.print(f"[yellow]Skill '{skill_name}' found but SKILL.md is empty[/yellow]")
        console.print()
        return None

    # Show feedback to the user
    source = matched_skill.get("source", "unknown")
    source_label = "project" if source == "project" else "global"
    description = matched_skill.get("description", "")
    description_short = description[:80] + "..." if len(description) > 80 else description

    console.print()
    console.print(
        f"[bold {COLORS['primary']}]⚡ Invoking skill: {skill_name}[/bold {COLORS['primary']}]"
    )
    console.print(f"   [dim]{description_short}[/dim]")
    console.print(f"   [dim]Source: {source_label}[/dim]")
    if cmd_args:
        console.print(f"   [dim]Arguments: {cmd_args}[/dim]")
    console.print()

    # Build the prompt that the agent will process
    extra_context = ""
    if cmd_args:
        extra_context = f"\n\nUser provided additional context: {cmd_args}"

    prompt = (
        f"Follow the instructions in the skill below.\n\n"
        f"--- SKILL: {skill_name} ---\n\n"
        f"{skill_content}\n\n"
        f"--- END SKILL: {skill_name} ---"
        f"{extra_context}\n\n"
        f"Execute the skill above. Apply it to the current project and context."
    )

    return prompt


def _read_skill_content(
    skill: dict[str, Any],
    user_skills_dir: Path | None,
    project_skills_dir: Path | None,
) -> str | None:
    """Read a skill's SKILL.md content from disk.

    Tries multiple locations: the skill's path attribute, user skills
    directory, then project skills directory.

    Args:
        skill: Skill metadata dict (must have 'name' key).
        user_skills_dir: Path to user-level skills directory.
        project_skills_dir: Path to project-level skills directory.

    Returns:
        SKILL.md content as string, or None if not found.
    """
    skill_name = skill.get("name", "")

    # Try the skill's path attribute first (may contain the full path)
    skill_path = skill.get("path", "")
    if skill_path:
        skill_md = Path(skill_path)
        if skill_md.is_file():
            try:
                return skill_md.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                pass
        # If path is a directory, look for SKILL.md inside it
        if skill_md.is_dir():
            md_path = skill_md / "SKILL.md"
            if md_path.is_file():
                try:
                    return md_path.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    pass

    # Try user skills directory
    if user_skills_dir and user_skills_dir.exists():
        md_path = user_skills_dir / skill_name / "SKILL.md"
        if md_path.is_file():
            try:
                return md_path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                pass

    # Try project skills directory
    if project_skills_dir and project_skills_dir.exists():
        md_path = project_skills_dir / skill_name / "SKILL.md"
        if md_path.is_file():
            try:
                return md_path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                pass

    return None
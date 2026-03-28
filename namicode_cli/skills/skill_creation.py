import argparse
import re
from pathlib import Path
from typing import Any

from nami_deepagents.backends.filesystem import FilesystemBackend
from nami_deepagents.graph import create_deep_agent

from namicode_cli.config.config import COLORS, Settings, console
from namicode_cli.config.model_create import create_model
from namicode_cli.skills.load import list_skills
from namicode_cli.skills.skill_system_prompt import SKILL_CREATION
from namicode_cli.tools import web_search


def _get_skill_query(
    skill_name: str,
    description: str | None = None,
) -> str:
    """Build a prompt for skill generation.

    Args:
        skill_name: Name of the skill.
        description: Optional user-provided description.
        research_context: Web search results for context.

    Returns:
        Complete prompt string for the LLM.
    """
    description_hint = ""
    if description:
        description_hint = f"""
The user has provided this description: "{description}"
Use this to guide the skill's purpose and content.
"""

    return f"""
    Create a comprehensive, production-ready SKILL.md file for a skill named "{skill_name}".

    {description_hint}
"""


async def _generate_skill(
    skill_name: str,
    base_dir: Path,
    description: str | None = None,
) -> str | None:
    """Generate skill content using the configured LLM and return SKILL.md content."""
    try:
        console.print(
            "[dim]Generating comprehensive skill content...[/dim]",
            style=COLORS["dim"],
        )
        skill_dir = base_dir / skill_name

        skill_query_prompt = _get_skill_query(skill_name, description)

        skill_creation_agent = create_deep_agent(
            name="Skill-Creation-Agent",
            model=create_model(),
            system_prompt=SKILL_CREATION.format(skill_dir=skill_dir),
            tools=[web_search],
            backend=FilesystemBackend(root_dir=skill_dir, virtual_mode=True),
        )

        # Invoke the agent (this writes SKILL.md to disk)
        response = await skill_creation_agent.ainvoke(
            {"messages": [{"role": "user", "content": skill_query_prompt}]}
        )

        responded = str(response["messages"][-1].content).strip()

        if responded:
            # Now read the actual SKILL.md file
            skill_file = skill_dir / "SKILL.md"
            if not skill_file.exists():
                console.print("[yellow]Warning: SKILL.md was not created by the agent.[/yellow]")
                return None

            skill_content = skill_file.read_text(encoding="utf-8").strip()

            # Validate frontmatter
            if not skill_content.startswith("---"):
                console.print(
                    "[yellow]Warning: SKILL.md missing valid frontmatter. Adding defaults.[/yellow]"
                )
                skill_content = f"""---
                name: {skill_name}
                description: {description}
                ---

                {skill_content}
                """
                skill_file.write_text(skill_content, encoding="utf-8")

            console.print(
                "[dim]Skill content generated and normalized successfully.[/dim]",
                style=COLORS["dim"],
            )
            return skill_content

        return "Skill creation failed"

    except Exception as e:
        console.print(
            f"[yellow]Warning: LLM generation failed ({e}), using static template.[/yellow]"
        )
        return None


def _get_static_template(skill_name: str) -> str:
    """Get the static template for skill creation (fallback).

    Args:
        skill_name: Name of the skill.

    Returns:
        Static SKILL.md template content.
    """
    skill_title = skill_name.replace("-", " ").replace("_", " ").title()
    return f"""---
name: {skill_name}
description: [Brief description of what this skill does]
---

# {skill_title} Skill

## Overview

[Provide a detailed explanation of what this skill does and when it should be used.
Explain the key capabilities and what problems it solves.]

## Core Competencies

- **[Competency 1]**: [Description]
- **[Competency 2]**: [Description]
- **[Competency 3]**: [Description]

## When to Use This Skill

### Primary Use Cases
- [Scenario 1: When the user asks...]
- [Scenario 2: When you need to...]
- [Scenario 3: When the task involves...]

### Trigger Phrases
- "[Example request]"
- "[Another example]"

## Detailed Instructions

### Phase 1: Assessment & Planning
1. [First step]
2. [Second step]

### Phase 2: Implementation
1. [Implementation step]
2. [Another step]

### Phase 3: Verification & Refinement
1. [Verification step]
2. [Final polish]

## Technical Reference

### Key Commands & Tools
```bash
# Example command
example-command --flag value
```

### Common Patterns
```python
# Example code pattern
def example():
    pass
```

## Best Practices

### Do's
- [Best practice 1]
- [Best practice 2]
- [Best practice 3]

### Don'ts
- [Mistake to avoid 1]
- [Mistake to avoid 2]

## Troubleshooting Guide

### Common Issues

#### Issue: [Problem description]
**Symptoms:** [What the user might see]
**Solution:** [How to fix it]

## Examples

### Example 1: [Scenario Name]

**User Request:** "[Example user request]"

**Approach:**
1. [Step-by-step breakdown]
2. [Using tools and commands]
3. [Expected outcome]

**Expected Outcome:** [What success looks like]

## Quick Reference Card

| Task | Command/Action |
|------|----------------|
| [Task 1] | `[command]` |
| [Task 2] | `[command]` |

## Notes & Limitations

- [Additional tips, warnings, or context]
- [Known limitations or edge cases]
"""


def _create(
    skill_name: str,
    agent: str,
    project: bool = False,
    global_scope: bool = False,
    ask: bool = True,
) -> None:
    """Create a new skill with a template SKILL.md file.

    Args:
        skill_name: Name of the skill to create.
        agent: Agent identifier for skills
        project: If True, create in project skills directory.
        global_scope: If True, create in global skills directory.
        ask: If True and neither project nor global_scope is specified, prompt user interactively.
    """
    # Validate skill name first
    is_valid, error_msg = _validate_name(skill_name)
    if not is_valid:
        console.print(f"[bold red]Error:[/bold red] Invalid skill name: {error_msg}")
        console.print(
            "[dim]Skill names must only contain letters, numbers, hyphens, and underscores.[/dim]",
            style=COLORS["dim"],
        )
        return

    # Determine scope - either from flags or by asking
    if project and global_scope:
        console.print(
            "[bold red]Error:[/bold red] Cannot specify both --project and --global flags."
        )
        return

    use_project = project
    if not project and not global_scope and ask:
        # Ask user interactively
        scope = _ask_scope("create")
        if scope is None:
            console.print("Cancelled.", style=COLORS["dim"])
            return
        use_project = scope == "project"
    # If global_scope is True, use_project remains False

    # Determine target directory
    settings = Settings.from_environment()
    if use_project:
        if not settings.project_root:
            console.print("[bold red]Error:[/bold red] Not in a project directory.")
            console.print(
                "[dim]Project skills require a .git directory in the project root.[/dim]",
                style=COLORS["dim"],
            )
            return
        skills_dir = settings.ensure_project_skills_dir()
    else:
        skills_dir = settings.ensure_user_skills_dir(agent)

    skill_dir = skills_dir / skill_name  # type: ignore

    # Validate the resolved path is within skills_dir
    is_valid_path, path_error = _validate_skill_path(skill_dir, skills_dir)  # type: ignore
    if not is_valid_path:
        console.print(f"[bold red]Error:[/bold red] {path_error}")
        return

    if skill_dir.exists():
        console.print(
            f"[bold red]Error:[/bold red] Skill '{skill_name}' already exists at {skill_dir}"
        )
        return

    # Create skill directory
    skill_dir.mkdir(parents=True, exist_ok=True)

    # Try to generate content with LLM, fall back to static template.
    # _generate_skill is async; use asyncio.run() since _create is sync.
    # Pass skills_dir (the parent) not skill_dir — _generate_skill appends
    # skill_name internally to build the correct path.
    import asyncio
    content = asyncio.run(_generate_skill(skill_name, skills_dir))
    if content is None:
        content = _get_static_template(skill_name)
        skill_md = skill_dir / "SKILL.md"
        skill_md.write_text(content, encoding="utf-8")
        used_llm = False
    else:
        # _generate_skill already wrote SKILL.md via the agent; no second write needed.
        used_llm = True
    skill_md = skill_dir / "SKILL.md"

    console.print(f"✓ Skill '{skill_name}' created successfully!", style=COLORS["primary"])
    console.print(f"Location: {skill_dir}\n", style=COLORS["dim"])

    if used_llm:
        files_created = ["SKILL.md"]
        console.print(
            f"[dim]Files created: {', '.join(files_created)}\n"
            "\n"
            "The skill was generated using AI. Review and customize as needed:\n"
            f"  nano {skill_md}\n",
            style=COLORS["dim"],
        )

    else:
        console.print(
            "[dim]Edit the SKILL.md file to customize:\n"
            "  1. Update the description in YAML frontmatter\n"
            "  2. Fill in the instructions and examples\n"
            "  3. Add any supporting files (scripts, configs, etc.)\n"
            "\n"
            f"  nano {skill_md}\n",
            style=COLORS["dim"],
        )


def _validate_skill_path(skill_dir: Path, base_dir: Path) -> tuple[bool, str]:
    """Validate that the resolved skill directory is within the base directory.

    Args:
        skill_dir: The skill directory path to validate
        base_dir: The base skills directory that should contain skill_dir

    Returns:
        Tuple of (is_valid, error_message). If valid, error_message is empty.
    """
    try:
        # Resolve both paths to their canonical form
        resolved_skill = skill_dir.resolve()
        resolved_base = base_dir.resolve()

        # Check if skill_dir is within base_dir
        # Use is_relative_to if available (Python 3.9+), otherwise use string comparison
        if hasattr(resolved_skill, "is_relative_to"):
            if not resolved_skill.is_relative_to(resolved_base):
                return False, f"Skill directory must be within {base_dir}"
        else:
            # Fallback for older Python versions
            try:
                resolved_skill.relative_to(resolved_base)
            except ValueError:
                return False, f"Skill directory must be within {base_dir}"

        return True, ""
    except (OSError, RuntimeError) as e:
        return False, f"Invalid path: {e}"


def _ask_scope(operation: str = "use", allow_both: bool = False) -> str | None:
    """Ask user whether to use project or global scope.

    Args:
        operation: The operation being performed (e.g., "create", "use", "list")
        allow_both: If True, add a "both" option (for list/info commands)

    Returns:
        "project", "global", or "both" (if allow_both=True), or None if user cancels
    """
    # Check if we're in a project directory
    settings = Settings.from_environment()
    in_project = settings.project_root is not None

    console.print(f"\nWhere do you want to {operation} skills?", style=COLORS["primary"])

    if in_project:
        console.print("  1. Project-specific (current project only)")
        console.print("  2. Global (all projects)")
        if allow_both:
            console.print("  3. Both (project and global)")
        console.print()

        max_choice = "3" if allow_both else "2"
        default_choice = "3" if allow_both else "1"
        choice = input(f"Choose (1-{max_choice}) [{default_choice}]: ").strip() or default_choice

        if choice == "1":
            return "project"
        if choice == "2":
            return "global"
        if choice == "3" and allow_both:
            return "both"
        return "project" if not allow_both else "both"
    console.print("[yellow]Not in a project directory. Using global skills.[/yellow]")
    console.print(
        "[dim]Project skills require a .git directory in the project root.[/dim]",
        style=COLORS["dim"],
    )
    return "global"


def _validate_name(name: str) -> tuple[bool, str]:
    """Validate name to prevent path traversal attacks.

    Args:
        name: The name to validate

    Returns:
        Tuple of (is_valid, error_message). If valid, error_message is empty.
    """
    # Check for empty or whitespace-only names
    if not name or not name.strip():
        return False, "cannot be empty"

    # Check for path traversal sequences
    if ".." in name:
        return False, "name cannot contain '..' (path traversal)"

    # Check for absolute paths
    if name.startswith(("/", "\\")):
        return False, "name cannot be an absolute path"

    # Check for path separators
    if "/" in name or "\\" in name:
        return False, "name cannot contain path separators"

    # Only allow alphanumeric, hyphens, underscores
    if not re.match(r"^[a-zA-Z0-9_-]+$", name):
        return False, "name can only contain letters, numbers, hyphens, and underscores"

    return True, ""


def _list(
    agent: str, *, project: bool = False, global_scope: bool = False, ask: bool = True
) -> None:
    """List all available skills for the specified agent.

    Args:
        agent: Agent identifier for skills (default: agent).
        project: If True, show only project skills.
        global_scope: If True, show only global skills.
        ask: If True and no flags specified, prompt user interactively.
    """
    settings = Settings.from_environment()
    user_skills_dir = settings.get_user_skills_dir(agent)
    project_skills_dir = settings.get_project_skills_dir()

    # Determine what to show - from flags or by asking
    if project and global_scope:
        console.print(
            "[bold red]Error:[/bold red] Cannot specify both --project and --global flags."
        )
        return

    show_scope = "both"  # Default
    if project:
        show_scope = "project"
    elif global_scope:
        show_scope = "global"
    elif ask:
        # Ask user interactively
        scope = _ask_scope("list", allow_both=True)
        if scope is None:
            console.print("Cancelled.", style=COLORS["dim"])
            return
        show_scope = scope

    # Handle project-only view
    if show_scope == "project":
        if not project_skills_dir:
            console.print("[yellow]Not in a project directory.[/yellow]")
            console.print(
                "[dim]Project skills require a .git directory in the project root.[/dim]",
                style=COLORS["dim"],
            )
            return

        if not project_skills_dir.exists() or not any(project_skills_dir.iterdir()):
            console.print("[yellow]No project skills found.[/yellow]")
            console.print(
                f"[dim]Project skills will be created in {project_skills_dir}/ when you add them.[/dim]",
                style=COLORS["dim"],
            )
            console.print(
                "\n[dim]Create a project skill:\n  nami skills create my-skill --project[/dim]",
                style=COLORS["dim"],
            )
            return

        skills = list_skills(user_skills_dir=None, project_skills_dir=project_skills_dir)
        console.print("\n[bold]Project Skills:[/bold]\n", style=COLORS["primary"])
    elif show_scope == "global":
        # Load only global skills
        skills = list_skills(user_skills_dir=user_skills_dir, project_skills_dir=None)
        console.print("\n[bold]Global Skills:[/bold]\n", style=COLORS["primary"])
    else:
        # Load both user and project skills
        skills = list_skills(user_skills_dir=user_skills_dir, project_skills_dir=project_skills_dir)

        if not skills:
            console.print("[yellow]No skills found.[/yellow]")
            console.print(
                "[dim]Skills will be created in ~/.nami/agent/skills/ when you add them.[/dim]",
                style=COLORS["dim"],
            )
            console.print(
                "\n[dim]Create your first skill:\n  nami skills create my-skill[/dim]",
                style=COLORS["dim"],
            )
            return

        console.print("\n[bold]Available Skills:[/bold]\n", style=COLORS["primary"])

    # Check if we have any skills
    if not skills:
        if show_scope == "global":
            console.print("[yellow]No global skills found.[/yellow]")
            console.print(
                "[dim]Global skills will be created in ~/.nami/skills/ when you add them.[/dim]",
                style=COLORS["dim"],
            )
            console.print(
                "\n[dim]Create a global skill:\n  nami skills create my-skill --global[/dim]",
                style=COLORS["dim"],
            )
        # Project and both cases are handled above
        return

    # Group skills by source
    user_skills = [s for s in skills if s["source"] == "user"]
    project_skills_list = [s for s in skills if s["source"] == "project"]

    # Show user skills (for global-only or both views)
    if user_skills and show_scope in ["global", "both"]:
        console.print("[bold cyan]User Skills:[/bold cyan]", style=COLORS["primary"])
        for skill in user_skills:
            skill_path = Path(skill["path"])
            console.print(f"  • [bold]{skill['name']}[/bold]", style=COLORS["primary"])
            console.print(f"    {skill['description']}", style=COLORS["dim"])
            console.print(f"    Location: {skill_path.parent}/", style=COLORS["dim"])
            console.print()

    # Show project skills (for project-only or both views)
    if project_skills_list and show_scope in ["project", "both"]:
        if show_scope == "both" and user_skills:
            console.print()
        console.print("[bold green]Project Skills:[/bold green]", style=COLORS["primary"])
        for skill in project_skills_list:
            skill_path = Path(skill["path"])
            console.print(f"  • [bold]{skill['name']}[/bold]", style=COLORS["primary"])
            console.print(f"    {skill['description']}", style=COLORS["dim"])
            console.print(f"    Location: {skill_path.parent}/", style=COLORS["dim"])
            console.print()


def _info(
    skill_name: str,
    *,
    agent: str = "agent",
    project: bool = False,
    global_scope: bool = False,
    ask: bool = True,
) -> None:
    """Show detailed information about a specific skill.

    Args:
        skill_name: Name of the skill to show info for.
        agent: Agent identifier for skills (default: agent).
        project: If True, only search in project skills.
        global_scope: If True, only search in global skills.
        ask: If True and no flags specified, prompt user interactively.
    """
    settings = Settings.from_environment()
    user_skills_dir = settings.get_user_skills_dir(agent)
    project_skills_dir = settings.get_project_skills_dir()

    # Determine what to search - from flags or by asking
    if project and global_scope:
        console.print(
            "[bold red]Error:[/bold red] Cannot specify both --project and --global flags."
        )
        return

    search_scope = "both"  # Default
    if project:
        search_scope = "project"
    elif global_scope:
        search_scope = "global"
    elif ask:
        # Ask user interactively
        scope = _ask_scope("search", allow_both=True)
        if scope is None:
            console.print("Cancelled.", style=COLORS["dim"])
            return
        search_scope = scope

    # Load skills based on scope
    if search_scope == "project":
        if not project_skills_dir:
            console.print("[bold red]Error:[/bold red] Not in a project directory.")
            return
        skills = list_skills(user_skills_dir=None, project_skills_dir=project_skills_dir)
    elif search_scope == "global":
        skills = list_skills(user_skills_dir=user_skills_dir, project_skills_dir=None)
    else:
        skills = list_skills(user_skills_dir=user_skills_dir, project_skills_dir=project_skills_dir)

    # Find the skill
    skill = next((s for s in skills if s["name"] == skill_name), None)

    if not skill:
        console.print(f"[bold red]Error:[/bold red] Skill '{skill_name}' not found.")
        console.print("\n[dim]Available skills:[/dim]", style=COLORS["dim"])
        for s in skills:
            console.print(f"  - {s['name']}", style=COLORS["dim"])
        return

    # Read the full SKILL.md file
    skill_path = Path(skill["path"])
    skill_content = skill_path.read_text()

    # Determine source label
    source_label = "Project Skill" if skill["source"] == "project" else "User Skill"
    source_color = "green" if skill["source"] == "project" else "cyan"

    console.print(
        f"\n[bold]Skill: {skill['name']}[/bold] [bold {source_color}]({source_label})[/bold {source_color}]\n",
        style=COLORS["primary"],
    )
    console.print(f"[bold]Description:[/bold] {skill['description']}\n", style=COLORS["dim"])
    console.print(f"[bold]Location:[/bold] {skill_path.parent}/\n", style=COLORS["dim"])

    # List supporting files
    skill_dir = skill_path.parent
    supporting_files = [f for f in skill_dir.iterdir() if f.name != "SKILL.md"]

    if supporting_files:
        console.print("[bold]Supporting Files:[/bold]", style=COLORS["dim"])
        for file in supporting_files:
            console.print(f"  - {file.name}", style=COLORS["dim"])
        console.print()

    # Show the full SKILL.md content
    console.print("[bold]Full SKILL.md Content:[/bold]\n", style=COLORS["primary"])
    console.print(skill_content, style=COLORS["dim"])
    console.print()


def _get_skills_dir(
    agent: str,
    project: bool = False,
    global_scope: bool = False,
    ask: bool = True,
) -> tuple[Path | None, bool]:
    """Get the skills directory based on scope settings.

    Args:
        agent: Agent identifier for skills.
        project: If True, return project skills directory.
        global_scope: If True, return global skills directory.
        ask: If True and neither flag specified, prompt user interactively.

    Returns:
        Tuple of (skills_dir, is_project). is_project indicates if scope is project.
    """
    settings = Settings.from_environment()

    # Validate flags
    if project and global_scope:
        console.print(
            "[bold red]Error:[/bold red] Cannot specify both --project and --global flags."
        )
        return None, False

    use_project = project
    if not project and not global_scope and ask:
        scope = _ask_scope("install")
        if scope is None:
            console.print("Cancelled.", style=COLORS["dim"])
            return None, False
        use_project = scope == "project"

    if use_project:
        if not settings.project_root:
            console.print("[bold red]Error:[/bold red] Not in a project directory.")
            console.print(
                "[dim]Project skills require a .git directory in the project root.[/dim]",
                style=COLORS["dim"],
            )
            return None, False
        return settings.ensure_project_skills_dir(), True
    else:
        return settings.ensure_user_skills_dir(agent), False


def _skill_exists(skill_name: str, skills_dir: Path) -> Path | None:
    """Check if a skill already exists in the given directory.

    Args:
        skill_name: Name of the skill to check.
        skills_dir: Directory to search in.

    Returns:
        Path to existing skill directory if found, None otherwise.
    """
    skill_dir = skills_dir / skill_name
    return skill_dir if skill_dir.exists() else None


def _parse_github_url(url: str) -> tuple[str, str, str, str] | None:
    """Parse a GitHub URL to extract owner, repo, branch, and path.

    Supports URLs like:
    - https://github.com/owner/repo
    - https://github.com/owner/repo/tree/branch
    - https://github.com/owner/repo/blob/branch/path/to/SKILL.md

    Args:
        url: GitHub URL to parse.

    Returns:
        Tuple of (owner, repo, branch, path) or None if invalid.
        path is the directory path within the repo (empty string if not specified).
    """
    import re

    # Handle github.com/owner/repo format
    github_pattern = r"github\.com/([^/]+)/([^/]+?)(?:\.git)?(?:/|$)"
    match = re.search(github_pattern, url)
    if not match:
        return None

    owner, repo = match.groups()
    repo = repo.rstrip("/")

    # Remove .git suffix if present
    repo = re.sub(r"\.git$", "", repo)

    # Extract branch and path
    branch = "main"  # Default branch
    path = ""  # Default empty path

    # Check for /tree/ or /blob/ with branch and path
    path_match = re.search(r"/(?:tree|blob)/([^/]+)(?:/(.+))?$", url)
    if path_match:
        branch = path_match.group(1)
        path = path_match.group(2) or ""

    return owner, repo, branch, path


def _fetch_skill_from_github(owner: str, repo: str, branch: str = "main", path: str = "") -> tuple[str | None, str | None]:
    """Fetch SKILL.md from a GitHub repository.

    Args:
        owner: Repository owner.
        repo: Repository name.
        branch: Branch name (default: main).
        path: Subdirectory path within the repo (e.g., "skills/find-skills").

    Returns:
        Tuple of (skill_content, skill_name) or (None, None) if failed.
    """
    import requests

    api_base = "https://api.github.com"

    # Build the base path for SKILL.md locations
    base_path = path.strip("/") if path else ""

    # If a specific path was provided in the URL (e.g., pointing to a skill directory),
    # try that location first
    if base_path:
        # Check if path points to a specific SKILL.md file
        if base_path.endswith("/SKILL.md"):
            url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{base_path}"
            try:
                response = requests.get(url, timeout=10)
                if response.status_code == 200:
                    content = response.text.strip()
                    skill_name = _extract_skill_name(content)
                    return content, skill_name or repo
            except requests.RequestException:
                pass
        else:
            # Path points to a directory, look for SKILL.md inside
            skill_path = f"{base_path}/SKILL.md"
            url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{skill_path}"
            try:
                response = requests.get(url, timeout=10)
                if response.status_code == 200:
                    content = response.text.strip()
                    skill_name = _extract_skill_name(content)
                    return content, skill_name or repo
            except requests.RequestException:
                pass

    # Try common SKILL.md locations at root level
    possible_paths = [
        "SKILL.md",
        "skills/SKILL.md",
        "skill/SKILL.md",
        ".skills/SKILL.md",
    ]

    for skill_path in possible_paths:
        url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{skill_path}"
        try:
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                content = response.text.strip()
                skill_name = _extract_skill_name(content)
                if skill_name:
                    return content, skill_name
                else:
                    return content, repo
        except requests.RequestException:
            continue

    # If common paths didn't work, try searching in the repo
    search_url = f"{api_base}/repos/{owner}/{repo}/contents"
    try:
        response = requests.get(search_url, params={"ref": branch}, timeout=10)
        if response.status_code == 200:
            items = response.json()
            for item in items:
                if item["name"] in ["SKILL.md", "skills", "skill", ".skills"]:
                    if item["type"] == "file" and item["name"] == "SKILL.md":
                        # Fetch this file
                        file_response = requests.get(item["download_url"], timeout=10)
                        if file_response.status_code == 200:
                            content = file_response.text.strip()
                            skill_name = _extract_skill_name(content)
                            return content, skill_name or repo
                    elif item["type"] == "dir":
                        # Search in directory
                        dir_response = requests.get(item["url"], timeout=10)
                        if dir_response.status_code == 200:
                            dir_items = dir_response.json()
                            for subitem in dir_items:
                                if subitem["name"] == "SKILL.md":
                                    file_response = requests.get(subitem["download_url"], timeout=10)
                                    if file_response.status_code == 200:
                                        content = file_response.text.strip()
                                        skill_name = _extract_skill_name(content)
                                        return content, skill_name or repo
    except requests.RequestException:
        pass

    return None, None


def _extract_skill_name(content: str) -> str | None:
    """Extract skill name from SKILL.md frontmatter.

    Args:
        content: SKILL.md content.

    Returns:
        Skill name if found in frontmatter, None otherwise.
    """
    if not content.startswith("---"):
        return None

    parts = content.split("---", 2)
    if len(parts) < 2:
        return None

    frontmatter = parts[1]

    # Look for name: field
    name_match = re.search(r"^\s*name:\s*(.+?)\s*$", frontmatter, re.MULTILINE)
    if name_match:
        return name_match.group(1).strip()

    return None


def _add(
    url: str,
    agent: str,
    project: bool = False,
    global_scope: bool = False,
    force: bool = False,
) -> None:
    """Add a skill from a GitHub URL.

    Args:
        url: GitHub URL to the skill repository.
        agent: Agent identifier for skills.
        project: If True, install in project skills directory.
        global_scope: If True, install in global skills directory.
        force: If True, overwrite existing skill.
    """
    # Parse GitHub URL
    parsed = _parse_github_url(url)
    if not parsed:
        console.print(f"[bold red]Error:[/bold red] Invalid GitHub URL: {url}")
        console.print(
            "\n[dim]Supported formats:\n"
            "  https://github.com/owner/repo\n"
            "  https://github.com/owner/repo/tree/branch\n"
            "  https://github.com/owner/repo/blob/branch/path/to/SKILL.md[/dim]",
            style=COLORS["dim"],
        )
        return

    owner, repo, branch, path = parsed

    console.print(f"[dim]Fetching skill from {owner}/{repo} (branch: {branch}, path: {path or 'root'})...[/dim]")

    # Fetch skill content
    content, skill_name = _fetch_skill_from_github(owner, repo, branch, path)
    if not content:
        console.print(f"[bold red]Error:[/bold red] Could not find SKILL.md in {owner}/{repo}")
        console.print(
            "[dim]Make sure the repository contains a SKILL.md file.[/dim]",
            style=COLORS["dim"],
        )
        return

    console.print(f"[dim]Found skill: {skill_name}[/dim]")

    # Validate skill name
    is_valid, error_msg = _validate_name(skill_name)
    if not is_valid:
        console.print(f"[bold red]Error:[/bold red] Invalid skill name from repository: {error_msg}")
        console.print(
            "[dim]The 'name' field in SKILL.md frontmatter contains invalid characters.[/dim]",
            style=COLORS["dim"],
        )
        return

    # Get target directory
    skills_dir, is_project = _get_skills_dir(agent, project, global_scope)
    if skills_dir is None:
        return  # User cancelled

    skill_dir = skills_dir / skill_name

    # Validate the resolved path is within skills_dir
    is_valid_path, path_error = _validate_skill_path(skill_dir, skills_dir)
    if not is_valid_path:
        console.print(f"[bold red]Error:[/bold red] {path_error}")
        return

    # Check for existing skill
    existing = _skill_exists(skill_name, skills_dir)
    if existing and not force:
        console.print(f"[bold red]Error:[/bold red] Skill '{skill_name}' already exists.")
        console.print(f"  Location: {existing}")
        console.print("\n[dim]Use --force to overwrite existing skill.[/dim]", style=COLORS["dim"])
        return

    # Create skill directory
    skill_dir.mkdir(parents=True, exist_ok=True)

    # Write SKILL.md
    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text(content, encoding="utf-8")

    scope_label = "project" if is_project else "global"
    console.print(
        f"✓ Skill '{skill_name}' installed successfully!",
        style=COLORS["primary"],
    )
    console.print(f"Location: {skill_dir}", style=COLORS["dim"])
    console.print(f"Scope: {scope_label}", style=COLORS["dim"])
    console.print()


def setup_skills_parser(
    subparsers: Any,
) -> argparse.ArgumentParser:
    """Setup the skills subcommand parser with all its subcommands."""
    skills_parser = subparsers.add_parser(
        "skills",
        help="Manage agent skills",
        description="Manage agent skills - create, list, and view skill information",
    )
    skills_subparsers = skills_parser.add_subparsers(dest="skills_command", help="Skills command")

    # Skills list
    list_parser = skills_subparsers.add_parser(
        "list",
        help="List all available skills",
        description="List all available skills",
    )
    list_parser.add_argument(
        "--agent",
        default="nami-agent",
        help="Agent identifier for skills (default: nami-agent)",
    )
    list_parser.add_argument(
        "--project",
        action="store_true",
        help="Show only project-level skills",
    )
    list_parser.add_argument(
        "--global",
        dest="global_scope",
        action="store_true",
        help="Show only global skills (user-level)",
    )

    # Skills create
    create_parser = skills_subparsers.add_parser(
        "create",
        help="Create a new skill",
        description="Create a new skill with a template SKILL.md file",
    )
    create_parser.add_argument("name", help="Name of the skill to create (e.g., web-research)")
    create_parser.add_argument(
        "--agent",
        default="nami-agent",
        help="Agent identifier for skills (default: nami-agent)",
    )
    create_parser.add_argument(
        "--project",
        action="store_true",
        help="Create skill in project directory instead of user directory",
    )
    create_parser.add_argument(
        "--global",
        dest="global_scope",
        action="store_true",
        help="Create skill in global directory (user-level)",
    )

    # Skills info
    info_parser = skills_subparsers.add_parser(
        "info",
        help="Show detailed information about a skill",
        description="Show detailed information about a specific skill",
    )
    info_parser.add_argument("name", help="Name of the skill to show info for")
    info_parser.add_argument(
        "--agent",
        default="nami-agent",
        help="Agent identifier for skills (default: nami-agent)",
    )
    info_parser.add_argument(
        "--project",
        action="store_true",
        help="Search only in project skills",
    )
    info_parser.add_argument(
        "--global",
        dest="global_scope",
        action="store_true",
        help="Search only in global skills (user-level)",
    )

    # Skills add
    add_parser = skills_subparsers.add_parser(
        "add",
        help="Install a skill from GitHub URL",
        description="Install a skill from a GitHub URL",
    )
    add_parser.add_argument(
        "url",
        help="GitHub URL to install skill from (e.g., https://github.com/owner/repo)",
    )
    add_parser.add_argument(
        "--agent",
        default="nami-agent",
        help="Agent identifier for skills (default: nami-agent)",
    )
    add_parser.add_argument(
        "--project",
        action="store_true",
        help="Install skill in project directory instead of user directory",
    )
    add_parser.add_argument(
        "--global",
        dest="global_scope",
        action="store_true",
        help="Install skill in global directory (user-level)",
    )
    add_parser.add_argument(
        "--force",
        action="store_true",
        help="Force overwrite if skill already exists",
    )
    return skills_parser

"""CLI commands for skill management.

These commands are registered with the CLI via cli.py:
- nami skills list --agent <agent> [--project]
- nami skills create <name>
- nami skills info <name>
"""

import argparse
import json
import re
from pathlib import Path
from typing import Any

from langchain_core.language_models import BaseChatModel

from namicode_cli.config import COLORS, Settings, console
from namicode_cli.skills.load import list_skills


def _get_configured_llm() -> BaseChatModel:
    """Get the LLM configured for the agent.

    Uses the same model configuration as the main agent, falling back to defaults.

    Returns:
        Configured BaseChatModel instance.
    """
    from namicode_cli.config import create_model

    return create_model()


def _search_for_skill_context(skill_name: str, description: str | None = None) -> str:
    """Search the web for relevant information about the skill topic.

    Args:
        skill_name: Name of the skill to research.
        description: Optional description to enhance search query.

    Returns:
        Concatenated search results as context string.
    """
    try:
        from namicode_cli.tools import web_search

        # Convert skill name to search query
        search_query = skill_name.replace("-", " ").replace("_", " ")
        if description:
            search_query = f"{search_query} {description}"

        console.print(
            f"[dim]Researching '{search_query}' for best practices...[/dim]",
            style=COLORS["dim"],
        )

        # Search for documentation, best practices, and implementation patterns
        results = web_search(
            query=f"{search_query} best practices tutorial guide implementation",
            max_results=5,
        )

        if "error" in results:
            console.print(
                f"[yellow]Web search unavailable: {results['error']}[/yellow]"
            )
            return ""

        # Extract relevant content from results
        context_parts = []
        results_list = results.get("results", []) if isinstance(results, dict) else []
        for result in results_list:
            if not isinstance(result, dict):
                continue
            title = result.get("title", "")
            content = result.get("content", "")
            url = result.get("url", "")
            if content:
                context_parts.append(f"### {title}\nSource: {url}\n{content}\n")

        if context_parts:
            console.print(
                f"[dim]Found {len(context_parts)} relevant sources[/dim]",
                style=COLORS["dim"],
            )
            return "\n".join(context_parts)

        return ""

    except Exception as e:
        console.print(f"[yellow]Research skipped: {e}[/yellow]")
        return ""


def _get_comprehensive_skill_prompt(
    skill_name: str,
    description: str | None = None,
    research_context: str = "",
) -> str:
    """Build a comprehensive prompt for skill generation.

    Args:
        skill_name: Name of the skill.
        description: Optional user-provided description.
        research_context: Web search results for context.

    Returns:
        Complete prompt string for the LLM.
    """
    skill_title = skill_name.replace("-", " ").replace("_", " ").title()

    context_section = ""
    if research_context:
        context_section = f"""
## Research Context (Use this to create accurate, up-to-date content)

{research_context}

---
"""

    description_hint = ""
    if description:
        description_hint = f"""
The user has provided this description: "{description}"
Use this to guide the skill's purpose and content.
"""

    return f"""You are an expert AI agent skill designer. Create a comprehensive, production-ready SKILL.md file for a skill named "{skill_name}".

{description_hint}
{context_section}

## Your Task

Generate a complete SKILL.md that makes this skill an **all-rounder expert** at its domain. The skill should:
1. Cover ALL major aspects of the topic comprehensively
2. Include practical, actionable instructions
3. Provide real-world examples with specific code/commands
4. Address common pitfalls and edge cases
5. Be immediately usable by an AI coding agent

## Output Requirements

CRITICAL: Your response must start EXACTLY with "---" (YAML frontmatter) and contain ONLY the SKILL.md content.
Do NOT include any explanations, preamble, markdown code blocks (```), or anything before or after the SKILL.md content.

## Required Structure

---
name: {skill_name}
description: [One comprehensive sentence describing what this skill enables - be specific about capabilities]
---

# {skill_title} Skill

## Overview

[3-4 sentences providing a comprehensive overview. Explain:
- What this skill does and why it's valuable
- The key capabilities it provides
- What problems it solves]

## Core Competencies

[List 5-8 major areas of expertise this skill covers. Be specific and comprehensive.]

- **[Competency 1]**: [Brief description of this capability]
- **[Competency 2]**: [Brief description of this capability]
- **[Competency 3]**: [Brief description of this capability]
- **[Competency 4]**: [Brief description of this capability]
- **[Competency 5]**: [Brief description of this capability]

## When to Use This Skill

### Primary Use Cases
- [Specific scenario 1 with context]
- [Specific scenario 2 with context]
- [Specific scenario 3 with context]

### Trigger Phrases
- "[Example user request that should activate this skill]"
- "[Another example request]"
- "[Third example]"

## Detailed Instructions

### Phase 1: Assessment & Planning
[Detailed instructions for initial assessment]
1. [Step with specific actions]
2. [Step with specific actions]
3. [Step with specific actions]

### Phase 2: Implementation
[Detailed instructions for main implementation work]
1. [Step with specific actions and commands]
2. [Step with specific actions and commands]
3. [Step with specific actions and commands]

### Phase 3: Verification & Refinement
[Detailed instructions for testing and polishing]
1. [Step with specific actions]
2. [Step with specific actions]
3. [Step with specific actions]

## Technical Reference

### Key Commands & Tools
```bash
# [Description of command]
[actual command]

# [Description of another command]
[actual command]
```

### Common Patterns
[Code patterns, configurations, or templates commonly used]

```[appropriate language]
[practical code example]
```

### Configuration Templates
[Provide any relevant config file templates]

## Best Practices

### Do's
- [Specific actionable best practice 1]
- [Specific actionable best practice 2]
- [Specific actionable best practice 3]
- [Specific actionable best practice 4]
- [Specific actionable best practice 5]

### Don'ts
- [Common mistake to avoid 1]
- [Common mistake to avoid 2]
- [Common mistake to avoid 3]

## Troubleshooting Guide

### Common Issues

#### Issue: [Problem description]
**Symptoms:** [What the user might see]
**Cause:** [Why this happens]
**Solution:** [How to fix it]

#### Issue: [Another problem]
**Symptoms:** [What the user might see]
**Cause:** [Why this happens]
**Solution:** [How to fix it]

## Examples

### Example 1: [Realistic Scenario Name]

**User Request:** "[Detailed realistic request]"

**Approach:**
1. [Specific step with actual commands/code]
2. [Next step with actual commands/code]
3. [Verification step]

**Expected Outcome:** [What success looks like]

### Example 2: [Another Realistic Scenario]

**User Request:** "[Different realistic request]"

**Approach:**
1. [Specific step]
2. [Next step]
3. [Final step]

**Expected Outcome:** [What success looks like]

## Integration Notes

### Works Well With
- [Other skill or tool that complements this one]
- [Another complementary skill/tool]

### Prerequisites
- [Required tool, dependency, or knowledge]
- [Another prerequisite]

## Quick Reference Card

| Task | Command/Action |
|------|----------------|
| [Common task 1] | `[command]` |
| [Common task 2] | `[command]` |
| [Common task 3] | `[command]` |

## Notes & Limitations

- [Important consideration or limitation]
- [Version-specific note if applicable]
- [Platform-specific note if applicable]

---

Now generate the complete SKILL.md content following this structure exactly:"""


def _generate_scripts_prompt(skill_name: str, skill_content: str) -> str:
    """Build prompt for generating supporting scripts.

    Args:
        skill_name: Name of the skill.
        skill_content: The generated SKILL.md content.

    Returns:
        Prompt string for script generation.
    """
    return f"""Based on the following skill definition, generate supporting scripts that would be useful for this skill.

## Skill: {skill_name}

{skill_content}

---

## Your Task

Generate 1-3 practical helper scripts that would enhance this skill's capabilities. These scripts should:
1. Be immediately usable
2. Handle common automation tasks related to this skill
3. Include proper error handling
4. Be well-documented with comments

## Output Format

Return a JSON object with this exact structure:
{{
    "scripts": [
        {{
            "filename": "script_name.py",
            "description": "What this script does",
            "content": "#!/usr/bin/env python3\\n# Script content here..."
        }},
        {{
            "filename": "another_script.sh",
            "description": "What this script does",
            "content": "#!/bin/bash\\n# Script content here..."
        }}
    ]
}}

Requirements:
- Use Python (.py) or Bash (.sh) scripts
- Include shebangs (#!/usr/bin/env python3 or #!/bin/bash)
- Add helpful comments explaining key sections
- Handle errors gracefully
- Include usage examples in comments

IMPORTANT: Return ONLY the JSON object, no markdown formatting or explanations.

Generate the scripts JSON now:"""


def _generate_skill_with_scripts(
    skill_name: str,
    description: str | None = None,
) -> tuple[str | None, list[dict[str, str]]]:
    """Generate skill content and supporting scripts using the configured LLM.

    Args:
        skill_name: Name of the skill to generate content for.
        description: Optional user-provided description.

    Returns:
        Tuple of (SKILL.md content, list of script dicts with filename/content).
        Returns (None, []) if generation fails.
    """
    try:
        llm = _get_configured_llm()

        # First, search for relevant context
        research_context = _search_for_skill_context(skill_name, description)

        console.print(
            "[dim]Generating comprehensive skill content...[/dim]",
            style=COLORS["dim"],
        )

        # Generate SKILL.md content
        skill_prompt = _get_comprehensive_skill_prompt(
            skill_name, description, research_context
        )
        response = llm.invoke(skill_prompt)
        skill_content = str(response.content).strip()

        # Clean up response - remove markdown code blocks if present
        if skill_content.startswith("```"):
            lines = skill_content.split("\n")
            # Remove first and last lines if they're code block markers
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            skill_content = "\n".join(lines)

        # Validate the response has proper frontmatter
        if not skill_content.startswith("---"):
            console.print(
                "[yellow]Warning: LLM response doesn't have valid frontmatter.[/yellow]"
            )
            return None, []

        # Check for required fields
        if "name:" not in skill_content or "description:" not in skill_content:
            console.print(
                "[yellow]Warning: LLM response missing required fields.[/yellow]"
            )
            return None, []

        # Now generate supporting scripts
        console.print(
            "[dim]Generating supporting scripts...[/dim]",
            style=COLORS["dim"],
        )

        scripts: list[dict[str, str]] = []
        try:
            scripts_prompt = _generate_scripts_prompt(skill_name, skill_content)
            scripts_response = llm.invoke(scripts_prompt)
            scripts_json = str(scripts_response.content).strip()

            # Clean up JSON response
            if scripts_json.startswith("```"):
                lines = scripts_json.split("\n")
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                scripts_json = "\n".join(lines)

            scripts_data = json.loads(scripts_json)
            if isinstance(scripts_data, dict) and "scripts" in scripts_data:
                scripts = scripts_data["scripts"]
                console.print(
                    f"[dim]Generated {len(scripts)} supporting script(s)[/dim]",
                    style=COLORS["dim"],
                )
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            console.print(f"[yellow]Script generation skipped: {e}[/yellow]")
            scripts = []

        return skill_content, scripts

    except Exception as e:
        console.print(
            f"[yellow]Warning: LLM generation failed ({e}), using static template.[/yellow]"
        )
        return None, []


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


def _ask_scope(operation: str = "use", allow_both: bool = False) -> str | None:
    """Ask user whether to use project or global scope.

    Args:
        operation: The operation being performed (e.g., "create", "use", "list")
        allow_both: If True, add a "both" option (for list/info commands)

    Returns:
        "project", "global", or "both" (if allow_both=True), or None if user cancels
    """
    from prompt_toolkit import prompt

    # Check if we're in a project directory
    settings = Settings.from_environment()
    in_project = settings.project_root is not None

    console.print(
        f"\nWhere do you want to {operation} skills?", style=COLORS["primary"]
    )

    if in_project:
        console.print("  1. Project-specific (current project only)")
        console.print("  2. Global (all projects)")
        if allow_both:
            console.print("  3. Both (project and global)")
        console.print()

        max_choice = "3" if allow_both else "2"
        choice = prompt(
            f"Choose (1-{max_choice}): ", default="3" if allow_both else "1"
        ).strip()

        if choice == "1":
            return "project"
        elif choice == "2":
            return "global"
        elif choice == "3" and allow_both:
            return "both"
        else:
            return "project" if not allow_both else "both"
    else:
        console.print(
            "[yellow]Not in a project directory. Using global skills.[/yellow]"
        )
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

        skills = list_skills(
            user_skills_dir=None, project_skills_dir=project_skills_dir
        )
        console.print("\n[bold]Project Skills:[/bold]\n", style=COLORS["primary"])
    elif show_scope == "global":
        # Load only global skills
        skills = list_skills(user_skills_dir=user_skills_dir, project_skills_dir=None)
        console.print("\n[bold]Global Skills:[/bold]\n", style=COLORS["primary"])
    else:
        # Load both user and project skills
        skills = list_skills(
            user_skills_dir=user_skills_dir, project_skills_dir=project_skills_dir
        )

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
        console.print(
            "[bold green]Project Skills:[/bold green]", style=COLORS["primary"]
        )
        for skill in project_skills_list:
            skill_path = Path(skill["path"])
            console.print(f"  • [bold]{skill['name']}[/bold]", style=COLORS["primary"])
            console.print(f"    {skill['description']}", style=COLORS["dim"])
            console.print(f"    Location: {skill_path.parent}/", style=COLORS["dim"])
            console.print()


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

    skill_dir = skills_dir / skill_name # type: ignore

    # Validate the resolved path is within skills_dir
    is_valid_path, path_error = _validate_skill_path(skill_dir, skills_dir) # type: ignore
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

    # Try to generate content and scripts with LLM, fall back to static template
    content, scripts = _generate_skill_with_scripts(skill_name)
    if content is None:
        content = _get_static_template(skill_name)
        scripts = []
        used_llm = False
    else:
        used_llm = True

    # Write SKILL.md
    skill_md = skill_dir / "SKILL.md"
    skill_md.write_text(content, encoding="utf-8")

    # Write supporting scripts
    scripts_written = []
    for script in scripts:
        if not isinstance(script, dict):
            continue
        filename = script.get("filename", "")
        script_content = script.get("content", "")
        if filename and script_content:
            # Validate filename to prevent path traversal
            if "/" in filename or "\\" in filename or ".." in filename:
                continue
            script_path = skill_dir / filename
            script_path.write_text(script_content, encoding="utf-8")
            scripts_written.append(filename)

    console.print(
        f"✓ Skill '{skill_name}' created successfully!", style=COLORS["primary"]
    )
    console.print(f"Location: {skill_dir}\n", style=COLORS["dim"])

    if used_llm:
        files_created = ["SKILL.md"] + scripts_written
        console.print(
            f"[dim]Files created: {', '.join(files_created)}\n"
            "\n"
            "The skill was generated using AI. Review and customize as needed:\n"
            f"  nano {skill_md}\n",
            style=COLORS["dim"],
        )
        if scripts_written:
            console.print(
                f"[dim]Supporting scripts: {', '.join(scripts_written)}[/dim]",
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
        skills = list_skills(
            user_skills_dir=None, project_skills_dir=project_skills_dir
        )
    elif search_scope == "global":
        skills = list_skills(user_skills_dir=user_skills_dir, project_skills_dir=None)
    else:
        skills = list_skills(
            user_skills_dir=user_skills_dir, project_skills_dir=project_skills_dir
        )

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
    console.print(
        f"[bold]Description:[/bold] {skill['description']}\n", style=COLORS["dim"]
    )
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


def setup_skills_parser(
    subparsers: Any,
) -> argparse.ArgumentParser:
    """Setup the skills subcommand parser with all its subcommands."""
    skills_parser = subparsers.add_parser(
        "skills",
        help="Manage agent skills",
        description="Manage agent skills - create, list, and view skill information",
    )
    skills_subparsers = skills_parser.add_subparsers(
        dest="skills_command", help="Skills command"
    )

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
    create_parser.add_argument(
        "name", help="Name of the skill to create (e.g., web-research)"
    )
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
    return skills_parser


def execute_skills_command(args: argparse.Namespace) -> None:
    """Execute skills subcommands based on parsed arguments.

    Args:
        args: Parsed command line arguments with skills_command attribute
    """
    # validate agent argument
    if args.agent:
        is_valid, error_msg = _validate_name(args.agent)
        if not is_valid:
            console.print(
                f"[bold red]Error:[/bold red] Invalid agent name: {error_msg}"
            )
            console.print(
                "[dim]Agent names must only contain letters, numbers, hyphens, and underscores.[/dim]",
                style=COLORS["dim"],
            )
            return

    if args.skills_command == "list":
        _list(
            agent=args.agent,
            project=args.project,
            global_scope=getattr(args, "global_scope", False),
        )
    elif args.skills_command == "create":
        _create(
            args.name,
            agent=args.agent,
            project=args.project,
            global_scope=getattr(args, "global_scope", False),
        )
    elif args.skills_command == "info":
        _info(
            args.name,
            agent=args.agent,
            project=args.project,
            global_scope=getattr(args, "global_scope", False),
        )
    else:
        # No subcommand provided, show help
        console.print(
            "[yellow]Please specify a skills subcommand: list, create, or info[/yellow]"
        )
        console.print("\n[bold]Usage:[/bold]", style=COLORS["primary"])
        console.print("  nami skills <command> [options]\n")
        console.print("[bold]Available commands:[/bold]", style=COLORS["primary"])
        console.print("  list              List all available skills")
        console.print("  create <name>     Create a new skill")
        console.print("  info <name>       Show detailed information about a skill")
        console.print("\n[bold]Examples:[/bold]", style=COLORS["primary"])
        console.print("  nami skills list")
        console.print("  nami skills create web-research")
        console.print("  nami skills info web-research")
        console.print(
            "\n[dim]For more help on a specific command:[/dim]", style=COLORS["dim"]
        )
        console.print("  nami skills <command> --help", style=COLORS["dim"])


__all__ = [
    "execute_skills_command",
    "setup_skills_parser",
]

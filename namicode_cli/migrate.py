"""Migration utilities for transitioning from old to new directory structure.

OLD STRUCTURE (Pre-2025):
~/.nami/
├── agent/               # Agent as top-level directory
│   ├── agent.md
│   └── skills/          # Per-agent skills
│       └── my-skill/
└── mybot/              # Another agent
    ├── agent.md
    └── skills/

NEW STRUCTURE (Claude Code Compatible):
~/.nami/
├── agents/             # Agents subdirectory
│   ├── default/
│   │   └── agent.md
│   └── mybot/
│       └── agent.md
└── skills/             # Global skills (shared)
    └── my-skill/
        └── SKILL.md
"""

import shutil
from pathlib import Path

from namicode_cli.config import COLORS, console


def detect_old_structure() -> list[Path]:
    """Detect agents using old directory structure.

    Returns:
        List of agent directories in old structure (e.g., ~/.nami/agent/)
    """
    deepagents_dir = Path.home() / ".nami"

    if not deepagents_dir.exists():
        return []

    old_agents = []

    # Look for directories with agent.md at the top level (old structure)
    for item in deepagents_dir.iterdir():
        if not item.is_dir():
            continue

        # Skip new structure directories
        if item.name in ["agents", "skills"]:
            continue

        # Check if it has agent.md (indicates it's an old-style agent)
        agent_md = item / "agent.md"
        if agent_md.exists():
            old_agents.append(item)

    return old_agents


def migrate_agents() -> None:
    """Migrate agents from old structure to new structure.

    Migrates:
    - Agent directories: ~/.nami/{agent}/ → ~/.nami/agents/{agent}/
    - Skills: ~/.nami/{agent}/skills/ → ~/.nami/skills/ (global)
    """
    old_agents = detect_old_structure()

    if not old_agents:
        console.print("[green]✓ No migration needed. Directory structure is up to date.[/green]")
        return

    console.print(f"\n[yellow]⚠ Found {len(old_agents)} agent(s) using old directory structure:[/yellow]\n")

    for old_agent_dir in old_agents:
        agent_name = old_agent_dir.name
        console.print(f"  • {agent_name} ({old_agent_dir})", style=COLORS["dim"])

    console.print("\n[bold]Migration Plan:[/bold]")
    console.print("  1. Move agents to ~/.nami/agents/{agent_name}/")
    console.print("  2. Move per-agent skills to global ~/.nami/skills/")
    console.print("  3. Preserve all agent.md files and configurations")
    console.print()

    # Ask for confirmation
    from prompt_toolkit import prompt

    confirm = prompt("Proceed with migration? (yes/no): ", default="yes").strip().lower()

    if confirm not in ["yes", "y"]:
        console.print("[yellow]Migration cancelled.[/yellow]")
        return

    console.print()

    # Create new directories
    agents_root = Path.home() / ".nami" / "agents"
    global_skills_dir = Path.home() / ".nami" / "skills"

    agents_root.mkdir(parents=True, exist_ok=True)
    global_skills_dir.mkdir(parents=True, exist_ok=True)

    # Track skills conflicts
    skills_conflicts = []

    # Migrate each agent
    for old_agent_dir in old_agents:
        agent_name = old_agent_dir.name
        console.print(f"[bold]Migrating agent:[/bold] {agent_name}", style=COLORS["primary"])

        # 1. Move agent.md
        new_agent_dir = agents_root / agent_name
        new_agent_dir.mkdir(parents=True, exist_ok=True)

        old_agent_md = old_agent_dir / "agent.md"
        new_agent_md = new_agent_dir / "agent.md"

        if old_agent_md.exists():
            shutil.copy2(old_agent_md, new_agent_md)
            console.print(f"  ✓ Copied agent.md to {new_agent_md}", style=COLORS["dim"])

        # 2. Migrate skills from per-agent to global
        old_skills_dir = old_agent_dir / "skills"

        if old_skills_dir.exists() and old_skills_dir.is_dir():
            for skill_dir in old_skills_dir.iterdir():
                if not skill_dir.is_dir():
                    continue

                skill_name = skill_dir.name
                global_skill_dir = global_skills_dir / skill_name

                # Check for conflicts
                if global_skill_dir.exists():
                    console.print(
                        f"  ⚠ Skill '{skill_name}' already exists in global skills. Skipping.",
                        style=COLORS["tool"]
                    )
                    skills_conflicts.append((agent_name, skill_name))
                    continue

                # Move skill to global
                shutil.copytree(skill_dir, global_skill_dir)
                console.print(f"  ✓ Moved skill '{skill_name}' to global skills", style=COLORS["dim"])

        # 3. Remove old agent directory (after confirming everything is copied)
        console.print(f"  ✓ Cleaning up old directory: {old_agent_dir}", style=COLORS["dim"])
        shutil.rmtree(old_agent_dir)
        console.print()

    # Summary
    console.print("[bold green]✓ Migration completed successfully![/bold green]\n")
    console.print("[bold]New Structure:[/bold]")
    console.print(f"  • Agents: {agents_root}/")
    console.print(f"  • Skills: {global_skills_dir}/")
    console.print()

    if skills_conflicts:
        console.print("[yellow]⚠ Skills Conflicts Detected:[/yellow]")
        console.print("The following skills were skipped because they already exist in global skills:")
        for agent_name, skill_name in skills_conflicts:
            console.print(f"  • {skill_name} (from agent '{agent_name}')")
        console.print()
        console.print("To manually migrate these skills:")
        console.print(f"  1. Review the existing skill in {global_skills_dir}/{skill_name}/") # type: ignore
        console.print(f"  2. Manually merge or rename conflicting skills as needed")
        console.print()


def check_migration_status() -> None:
    """Check if migration is needed and display status."""
    old_agents = detect_old_structure()

    if not old_agents:
        console.print("[green]✓ Directory structure is up to date.[/green]")
        console.print("[dim]Using new Claude Code-compatible structure.[/dim]")
        return

    console.print(f"[yellow]⚠ Migration needed for {len(old_agents)} agent(s)[/yellow]\n")
    console.print("Run 'nami migrate' to upgrade to the new directory structure.")

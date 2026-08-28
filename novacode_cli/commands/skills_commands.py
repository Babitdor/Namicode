"""Handlers for /skills command - skill management."""

from prompt_toolkit import PromptSession

from novacode_cli.commands import CommandContext
from novacode_cli.commands.menu_helper import MenuOption, run_interactive_menu
from novacode_cli.config.config import COLORS, Settings, console
from novacode_cli.skills.skill_creation import (
    _generate_skill,
    _validate_name,
)


async def handle_skills_command(cmd_args: str | None, assistant_id: str) -> bool:
    """Handle the /skills command."""
    ps = PromptSession()

    console.print()
    console.print("[bold]Skills Manager[/bold]", style=COLORS["primary"])
    console.print()

    action = None
    extra_args = None

    if cmd_args:
        parts = cmd_args.strip().split(maxsplit=1)
        first_arg = parts[0].lower()
        extra_args = parts[1] if len(parts) > 1 else None

        if first_arg in ("create", "new", "add"):
            action = "create"
        elif first_arg in ("list", "ls", "show"):
            action = "list"
        elif first_arg in ("toggle", "manage", "curate", "enable", "disable"):
            action = "toggle"
        else:
            action = "create"
            extra_args = cmd_args.strip()

    if not action:
        ctx = CommandContext(cmd="skills", cmd_args=cmd_args,
                             agent=None, token_tracker=None,
                             session_state=None, assistant_id=assistant_id)
        options = [
            MenuOption("Create a new skill", _menu_create_skill),
            MenuOption("List available skills", _menu_list_skills),
            MenuOption("Toggle skills on/off", _menu_toggle_skills),
        ]
        return await run_interactive_menu("Skills Manager", options, ctx)

    if action == "list":
        return await _skills_list_interactive(ps, Settings.from_environment(), assistant_id)

    if action == "toggle":
        return await _skills_toggle_interactive(ps, Settings.from_environment(), assistant_id)

    return await _skills_create_interactive(ps, Settings.from_environment(), assistant_id, extra_args)


async def _menu_create_skill(ctx: CommandContext, session: PromptSession) -> bool:
    return await _skills_create_interactive(
        session, Settings.from_environment(), ctx.assistant_id, None,
    )


async def _menu_list_skills(ctx: CommandContext, session: PromptSession) -> bool:
    return await _skills_list_interactive(
        session, Settings.from_environment(), ctx.assistant_id,
    )


async def _menu_toggle_skills(ctx: CommandContext, session: PromptSession) -> bool:
    return await _skills_toggle_interactive(
        session, Settings.from_environment(), ctx.assistant_id,
    )


async def _skills_list_interactive(ps, settings: Settings, assistant_id: str) -> bool:
    """List skills interactively with scope selection.

    Args:
        ps: PromptSession instance
        settings: Settings instance
        assistant_id: Agent identifier

    Returns:
        True (always handled)
    """
    from novacode_cli.skills.load import list_skills

    console.print()
    console.print("[bold]List Skills[/bold]", style=COLORS["primary"])
    console.print()

    # Ask for scope
    in_project = settings.project_root is not None

    if in_project:
        console.print("  1. Global skills (shared across projects)")
        console.print("  2. Project skills (current project only)")
        console.print("  3. Both")
        console.print()

        choice = (await ps.prompt_async("Choose (1-3, default=3): ")).strip() or "3"

        if choice == "1":
            scope = "global"
        elif choice == "2":
            scope = "project"
        else:
            scope = "both"
    else:
        scope = "global"
        console.print("[dim]Not in a project directory. Showing global skills.[/dim]")

    console.print()

    # Get skills based on scope
    user_skills_dir = settings.ensure_user_skills_dir(assistant_id)
    project_skills_dir = settings.get_project_skills_dir() if in_project else None
    claude_skills_dir = Settings.get_global_claude_skills_dir()
    claude_skills_dir_arg = claude_skills_dir if claude_skills_dir.exists() else None

    if scope == "global":
        skills = list_skills(
            user_skills_dir=user_skills_dir,
            claude_skills_dir=claude_skills_dir_arg,
            project_skills_dir=None,
        )
    elif scope == "project":
        skills = list_skills(
            user_skills_dir=None,
            claude_skills_dir=None,
            project_skills_dir=project_skills_dir,
        )
    else:
        skills = list_skills(
            user_skills_dir=user_skills_dir,
            claude_skills_dir=claude_skills_dir_arg,
            project_skills_dir=project_skills_dir,
        )

    if not skills:
        console.print("[yellow]No skills found.[/yellow]")
        console.print(
            "[dim]Use '/skills create' or '/skills' → 1 to create a new skill.[/dim]"
        )
        console.print()
        return True

    # Group by source
    nova_skills = [s for s in skills if s["source"] == "user"]
    claude_skills = [s for s in skills if s["source"] == "claude"]
    project_skills = [s for s in skills if s["source"] == "project"]

    if nova_skills and scope in ("global", "both"):
        console.print("[bold cyan]Nova Global Skills:[/bold cyan]")
        for skill in nova_skills:
            console.print(f"  • [bold]{skill['name']}[/bold]")
            console.print(f"    [dim]{skill['description']}[/dim]")
        console.print()

    if claude_skills and scope in ("global", "both"):
        console.print("[bold yellow]Claude Global Skills:[/bold yellow]")
        for skill in claude_skills:
            console.print(f"  • [bold]{skill['name']}[/bold]")
            console.print(f"    [dim]{skill['description']}[/dim]")
        console.print()

    if project_skills and scope in ("project", "both"):
        console.print("[bold green]Project Skills:[/bold green]")
        for skill in project_skills:
            console.print(f"  • [bold]{skill['name']}[/bold]")
            console.print(f"    [dim]{skill['description']}[/dim]")
        console.print()

    total = len(nova_skills) + len(claude_skills) + len(project_skills)
    console.print(f"[dim]Total: {total} skill(s)[/dim]")
    console.print()
    return True


def _render_toggle_board(
    skills: list[dict], disabled: set[str], scope: str
) -> None:
    """Print the numbered skill list with [x]/[ ] markers for the edited scope."""
    source_label = {"user": "Nova", "claude": "Claude", "project": "Project"}
    console.print(
        f"[bold]Toggle skills[/bold]  [dim](editing {scope} preferences)[/dim]"
    )
    console.print(
        "[dim]A skill is hidden from the agent if it is off here OR in the other "
        "scope. Toggling here writes to the "
        f"{scope} file only.[/dim]"
    )
    console.print()
    for i, skill in enumerate(skills, 1):
        on = skill["name"] not in disabled
        mark = "[green][x][/green]" if on else "[red][ ][/red]"
        src = source_label.get(skill["source"], skill["source"])
        console.print(f"  {i:2}. {mark} [bold]{skill['name']}[/bold] [dim]({src})[/dim]")
        console.print(f"        [dim]{skill['description']}[/dim]")
    console.print()
    enabled_count = sum(1 for s in skills if s["name"] not in disabled)
    console.print(
        f"[dim]{enabled_count}/{len(skills)} enabled. "
        "Enter numbers to toggle (e.g. '1 3 5'), 'a' all on, 'n' all off, "
        "'s' to save, 'q' to cancel.[/dim]"
    )


def _apply_index_toggles(raw: str, skills: list[dict], disabled: set[str]) -> None:
    """Flip the skills named by the space/comma-separated indices in ``raw``."""
    flipped_any = False
    for token in raw.replace(",", " ").split():
        if not token.isdigit():
            console.print(f"[yellow]Ignored '{token}' — not a number.[/yellow]")
            continue
        idx = int(token) - 1
        if not 0 <= idx < len(skills):
            console.print(f"[yellow]Ignored '{token}' — out of range.[/yellow]")
            continue
        name = skills[idx]["name"]
        if name in disabled:
            disabled.discard(name)
        else:
            disabled.add(name)
        flipped_any = True
    if not flipped_any and raw:
        console.print("[yellow]Nothing toggled.[/yellow]")


async def _skills_toggle_interactive(ps, settings: Settings, assistant_id: str) -> bool:
    """Interactively toggle skills on/off, persisting to a chosen scope file.

    Args:
        ps: PromptSession instance
        settings: Settings instance
        assistant_id: Agent identifier

    Returns:
        True (always handled)
    """
    from novacode_cli.skills import skills_prefs
    from novacode_cli.skills.load import list_skills

    console.print()
    console.print("[bold]Toggle Skills[/bold]", style=COLORS["primary"])
    console.print()

    in_project = settings.project_root is not None

    # Choose which scope's preference file to edit.
    if in_project:
        console.print("Which preferences do you want to edit?")
        console.print("  1. Global (~/.nova/skills_prefs.json)")
        console.print("  2. Project (.nova/skills_prefs.json, committable)")
        console.print()
        choice = (await ps.prompt_async("Choose (1-2, default=1): ")).strip() or "1"
        scope = "project" if choice == "2" else "global"
    else:
        scope = "global"

    # Load the full skill set (both scopes' skills are listed regardless of
    # which scope we edit — you may want to disable a global skill per-project).
    user_skills_dir = settings.ensure_user_skills_dir(assistant_id)
    project_skills_dir = settings.get_project_skills_dir() if in_project else None
    claude_skills_dir = Settings.get_global_claude_skills_dir()
    skills = list_skills(
        user_skills_dir=user_skills_dir,
        claude_skills_dir=claude_skills_dir if claude_skills_dir.exists() else None,
        project_skills_dir=project_skills_dir,
    )
    if not skills:
        console.print("[yellow]No skills found to toggle.[/yellow]")
        console.print("[dim]Create one with '/skills create'.[/dim]")
        console.print()
        return True

    skills.sort(key=lambda s: (s["source"], s["name"]))

    # Working copy of the chosen scope's disabled set; persisted only on save.
    scope_path = skills_prefs.scope_path(scope)
    disabled = skills_prefs.load_disabled(scope_path)
    names = {s["name"] for s in skills}

    while True:
        console.print()
        _render_toggle_board(skills, disabled, scope)
        console.print()
        raw = (await ps.prompt_async("> ")).strip().lower()

        if raw in ("q", "cancel", "c"):
            console.print("[dim]Cancelled — no changes saved.[/dim]")
            console.print()
            return True
        if raw == "s":
            # `disabled` keeps any entries for skills not currently installed
            # (loaded from the file, never touched) plus the toggles made here.
            skills_prefs.save_disabled(scope_path, disabled)
            on = sum(1 for s in skills if s["name"] not in disabled)
            console.print(
                f"[green]✓ Saved.[/green] {on}/{len(skills)} skills enabled in "
                f"{scope}. [dim]Takes effect on the next turn.[/dim]"
            )
            console.print()
            return True
        if raw == "a":
            disabled -= names
            continue
        if raw == "n":
            disabled |= names
            continue
        _apply_index_toggles(raw, skills, disabled)


async def _skills_create_interactive(
    ps, settings: Settings, assistant_id: str, skill_name: str | None
) -> bool:
    """Create a skill interactively.

    Args:
        ps: PromptSession instance
        settings: Settings instance
        assistant_id: Agent identifier
        skill_name: Optional pre-provided skill name

    Returns:
        True (always handled)
    """
    console.print()
    console.print("[bold]Create New Skill[/bold]", style=COLORS["primary"])
    console.print()

    # Get skill name if not provided
    if not skill_name:
        console.print(
            "[dim]Skills are reusable workflows that guide the agent for specific tasks.[/dim]"
        )
        console.print(
            "[dim]Examples: web-research, code-review, docker-deploy, api-testing[/dim]"
        )
        console.print()
        skill_name = (await ps.prompt_async("Skill name: ")).strip()

    if not skill_name:
        console.print("[yellow]Cancelled - no skill name provided[/yellow]")
        console.print()
        return True

    # Validate skill name
    is_valid, error_msg = _validate_name(skill_name)
    if not is_valid:
        console.print(f"[red]Invalid skill name: {error_msg}[/red]")
        console.print("[dim]Use only letters, numbers, hyphens, and underscores.[/dim]")
        console.print()
        return True

    # Ask for description
    console.print()
    console.print(
        "[dim]Describe what this skill should do (or press Enter to auto-generate):[/dim]"
    )
    description = (await ps.prompt_async("Description: ")).strip()

    # Ask for scope
    in_project = settings.project_root is not None
    if in_project:
        console.print()
        console.print("  1. Global (available in all projects)")
        console.print("  2. Project (only in this project)")
        console.print()
        scope_choice = (
            await ps.prompt_async("Scope (1-2, default=1): ")
        ).strip() or "1"
        use_project = scope_choice == "2"
    else:
        use_project = False

    # Determine target directory
    if use_project:
        base_dir = settings.ensure_project_skills_dir()
        if not base_dir:
            console.print("[red]Error: Not in a project directory.[/red]")
            console.print()
            return True
    else:
        base_dir = settings.ensure_user_skills_dir(assistant_id)

    skill_dir = base_dir / skill_name

    if skill_dir.exists():
        console.print(
            f"[yellow]Skill '{skill_name}' already exists at {skill_dir}[/yellow]"
        )
        console.print()
        return True

    # Create skill directory
    skill_dir.mkdir(parents=True, exist_ok=True)

    # Generate content with LLM
    console.print()
    content = await _generate_skill(
        skill_name,
        base_dir=base_dir,
        description=description if description else None,
    )
    if content is None:
        console.print(
            f"[red]✗ Failed to generate skill '{skill_name}' using AI. Please try again.[/red]"
        )
        console.print()
        return True

    # Success message
    scope_label = "project" if use_project else "global"
    console.print(
        f"[green]✓ Skill '{skill_name}' created successfully! ({scope_label})[/green]"
    )
    console.print(f"[dim]Location: {skill_dir}[/dim]")
    console.print()

    # Since the agent already created SKILL.md and any supporting files,
    # we just confirm success without listing files.
    console.print(
        "[dim]The skill was generated using AI. Review and customize as needed.[/dim]"
    )
    console.print()

    return True


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

def register_commands(registry) -> None:
    from novacode_cli.commands import CommandContext

    async def _handle(ctx: CommandContext) -> bool:
        return await handle_skills_command(cmd_args=ctx.cmd_args, assistant_id=ctx.assistant_id)

    registry.register("skills", _handle)

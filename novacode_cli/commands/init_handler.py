"""Handler for the /init command to create Nova.md documentation."""

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from novacode_cli.config.config import COLORS, Settings, console
from novacode_cli.prompts import render_template
from novacode_cli.ui.ui_elements import TokenTracker


async def handle_init_command(
    agent, session_state, assistant_id: str, token_tracker: TokenTracker
) -> None:
    """Handle the /init command to explore codebase and create Nova.md file.
    
    Args:
        agent: The LangGraph agent
        session_state: Current session state
        assistant_id: Agent identifier
        token_tracker: Token tracker instance
    """
    from novacode_cli.ui.execution import execute_task
    
    console.print()

    # Create a nice header
    header = Text()
    header.append("🔍 ", style="bold")
    header.append("Nova.md Initialization", style=f"bold {COLORS['primary']}")

    panel = Panel(
        Text(
            "Exploring your codebase to create comprehensive documentation for AI assistants",
            style="dim",
        ),
        title=header,
        border_style=COLORS["primary"],
        padding=(1, 2),
    )
    console.print(panel)
    console.print()

    # Check if we're in a project directory
    settings = Settings.from_environment()
    project_root = settings.project_root

    if not project_root:
        console.print("❌ ", style="red", end="")
        console.print("[bold red]Not in a project directory[/bold red]")
        console.print(
            "   [dim]The /init command requires a .git directory in the project root.[/dim]"
        )
        console.print()
        return

    # Show project info
    console.print("📁 ", style=COLORS["primary"], end="")
    console.print(f"[bold]Project:[/bold] {project_root.name}")
    console.print(f"   [dim]{project_root}[/dim]")
    console.print()

    # Check if NOVA.md already exists
    Nova_md_path = project_root / ".nova" / "NOVA.md"
    if Nova_md_path.exists():
        console.print("⚠️  ", style="yellow", end="")
        console.print("[yellow]NOVA.md already exists[/yellow]")
        console.print("   [dim]It will be updated with fresh analysis[/dim]")
        console.print()

    # Create the exploration prompt using Jinja template
    exploration_prompt = render_template(
        "init_exploration.jinja",
        project_root=str(project_root),
        Nova_md_path=str(Nova_md_path),
    )

    # Show status
    console.print("🤖 ", style=COLORS["primary"], end="")
    console.print("[bold]Starting AI exploration...[/bold]")
    console.print(
        "   [dim]The agent will automatically explore and document your codebase[/dim]"
    )
    console.print()

    # Temporarily enable auto-approve for this operation since user explicitly requested /init
    original_auto_approve = session_state.auto_approve
    session_state.auto_approve = True

    try:
        # Use the existing execute_task function to handle the exploration
        # This properly handles all tool calls, approvals, streaming, etc.
        await execute_task(
            exploration_prompt,
            agent,
            assistant_id,
            session_state,
            token_tracker,
        )

        console.print()

        # Check if file was created and show appropriate message
        if Nova_md_path.exists():
            # Read the file to show a preview
            try:
                content = Nova_md_path.read_text()
                lines = content.split("\n")
                file_size = len(content)
                line_count = len(lines)

                # Create success panel
                success_text = Text()
                success_text.append("✓ ", style="bold green")
                success_text.append("NOVA.md Created Successfully", style="bold green")

                info_lines = [
                    f"📍 Location: {Nova_md_path}",
                    f"📄 Size: {file_size:,} characters, {line_count} lines",
                    "",
                    "📋 Preview:",
                ]

                # Add first few lines as preview
                preview_lines = [line for line in lines[:10] if line.strip()][:5]
                for line in preview_lines:
                    info_lines.append(f"   {line[:80]}")
                if line_count > 10:
                    info_lines.append("   ...")

                info_lines.append("")
                info_lines.append(
                    "💡 Tip: The Nova.md file helps AI assistants understand your project"
                )
                info_lines.append(
                    "   It will be automatically loaded in future sessions"
                )

                panel = Panel(
                    "\n".join(info_lines),
                    title=success_text,
                    border_style="green",
                    padding=(1, 2),
                )
                console.print(panel)
            except Exception:
                # Fallback to simple message if we can't read the file
                console.print("✅ ", style="bold green", end="")
                console.print("[bold green]NOVA.md created successfully![/bold green]")
                console.print(f"   [dim]Location: {Nova_md_path}[/dim]")
        else:
            console.print("⚠️  ", style="yellow", end="")
            console.print("[bold yellow]NOVA.md was not created[/bold yellow]")
            console.print(
                "   [dim]The agent may need additional guidance. Try running /init again.[/dim]"
            )
        console.print()

    except Exception as e:
        console.print()
        console.print("❌ ", style="red", end="")
        console.print(f"[bold red]Error during exploration:[/bold red] {e}")
        import traceback

        console.print()
        console.print("[dim]Traceback:[/dim]")
        console.print(f"[dim]{traceback.format_exc()}[/dim]")
        console.print()
    finally:
        # Restore original auto-approve setting
        session_state.auto_approve = original_auto_approve

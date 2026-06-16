"""Handler for the /effort command to manage reasoning effort configuration."""

from novacode_cli.commands import CommandContext
from novacode_cli.config.config import COLORS, console
from novacode_cli.config.nova_config import NovaConfig
from novacode_cli.config.model_create import create_model

async def handle_effort_command(ctx: CommandContext) -> bool:
    """Handle the /effort command."""
    args = ctx.cmd_args
    nova_config = NovaConfig()
    current_effort = nova_config.get("reasoning_effort", "off")

    if not args:
        console.print()
        console.print(f"[bold]Reasoning Effort Configuration[/bold]", style=COLORS["primary"])
        console.print(f"Current reasoning effort: [bold cyan]{current_effort}[/bold cyan]")
        console.print()
        console.print("[bold]Usage:[/bold]")
        console.print("  /effort <low|medium|high|off>   - Set the reasoning effort level")
        console.print()
        console.print("[bold]Supported Providers:[/bold]")
        console.print("  • [bold]OpenAI[/bold] (o1, o3-mini models): supports low, medium, high")
        console.print("  • [bold]Google Gemini[/bold] (Gemini 2.5/3 models): supports low, medium, high")
        console.print("  • [bold]Anthropic Claude[/bold] (Claude 3.7 Sonnet): maps to token budget")
        console.print("  • [bold]Ollama[/bold]: Local models (like DeepSeek-R1) generate reasoning automatically")
        console.print()
        return True

    val = args.strip().lower()
    if val not in ("low", "medium", "high", "off", "none", "default"):
        console.print(f"[red]Error: Invalid effort level '{args}'.[/red]")
        console.print("Choose one of: low, medium, high, off")
        return True

    # Normalize none / default to off
    if val in ("none", "default"):
        val = "off"

    # Save configuration
    nova_config.set("reasoning_effort", val)
    console.print()
    console.print(f"[green]✓ Reasoning effort set to '{val}' and saved to config.[/green]")

    # Trigger hot-swap
    session_state = ctx.session_state
    if session_state is not None:
        try:
            new_model = create_model()
            await session_state.switch_model(new_model)
            console.print("[green]✓ Model recreated with new reasoning effort dynamically![/green]")
        except Exception as e:
            console.print(f"[yellow]⚠ Could not recreate model dynamically: {e}[/yellow]")
            console.print("[dim]The change will take effect on next model switch or restart.[/dim]")
    else:
        console.print("[dim]The change will take effect on restart.[/dim]")

    console.print()
    return True

def register_commands(registry) -> None:
    async def _handle(ctx: CommandContext) -> bool:
        return await handle_effort_command(ctx)

    registry.register("effort", _handle)

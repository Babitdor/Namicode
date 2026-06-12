"""Legacy (rich + prompt_toolkit) renderer for the /init command.

The pipeline in :mod:`novacode_cli.commands.init_handler` is pure logic: it emits
UI-agnostic :mod:`novacode_cli.init.events` and returns an :class:`~novacode_cli.init.events.InitResult`.
This module is the legacy REPL's *renderer* — it owns all the rich presentation
(intro panel, per-step progress, success summary) and the prompt-based fallback
flow. The Textual TUI provides its own renderer (``NovaApp._run_init``) and does
not use this module.
"""

from __future__ import annotations

from pathlib import Path

from rich.panel import Panel
from rich.text import Text

from novacode_cli.config.config import COLORS, console
from novacode_cli.init import events as ev
from novacode_cli.prompts import render_template
from novacode_cli.ui.ui_elements import TokenTracker


class LegacyInitRenderer:
    """Renders the /init pipeline's events and result to the rich console."""

    def __init__(self) -> None:
        # The pipeline forwards this to graphify internals (detect/extract/build)
        # for their own tree-sitter/Leiden progress bars.
        self.console = console

    # ── Pre-pipeline notices ────────────────────────────────────────────

    def no_project(self) -> None:
        """No project root — /init needs a .git directory."""
        c = self.console
        c.print()
        c.print("❌ ", style="red", end="")
        c.print("[bold red]Not in a project directory[/bold red]")
        c.print(
            "   [dim]The /init command requires a .git directory in the project root.[/dim]"
        )
        c.print()

    def intro(self, project_root: Path, flags, nova_md_path: Path) -> None:
        """Header panel, project info, active flags, and the overwrite notice."""
        c = self.console
        c.print()

        header = Text()
        header.append("🔍 ", style="bold")
        header.append("NOVA.md Initialization", style=f"bold {COLORS['primary']}")

        c.print(
            Panel(
                Text(
                    "Exploring your codebase to create comprehensive documentation "
                    "for AI assistants",
                    style="dim",
                ),
                title=header,
                border_style=COLORS["primary"],
                padding=(1, 2),
            )
        )
        c.print()

        c.print("📁 ", style=COLORS["primary"], end="")
        c.print(f"[bold]Project:[/bold] {project_root.name}")
        c.print(f"   [dim]{project_root}[/dim]")

        flag_parts = flags.as_list()
        if flag_parts:
            c.print(f"   [dim]Flags: {' '.join(flag_parts)}[/dim]")
        c.print()

        if nova_md_path.exists():
            c.print("⚠️  ", style="yellow", end="")
            c.print("[yellow]NOVA.md already exists[/yellow]")
            if flags.update:
                c.print(
                    "   [dim]Incremental update — only changed files will be re-analyzed[/dim]"
                )
            else:
                c.print("   [dim]It will be updated with fresh analysis[/dim]")
            c.print()

    def graphify_unavailable(self) -> None:
        """graphify is not installed — explain the fallback."""
        c = self.console
        c.print()
        c.print("💡 ", style="yellow", end="")
        c.print(
            "[yellow]graphify not installed — using fallback exploration mode[/yellow]"
        )
        c.print(
            "   [dim]Install with: [bold]pip install novacode-cli[graphify][/bold] "
            "for richer output (NOVA.md + AGENTS.md + project graph + HTML "
            "visualization)[/dim]"
        )
        c.print()

    # ── Pipeline events ─────────────────────────────────────────────────

    def emit(self, event) -> None:
        """Render a single pipeline progress event."""
        c = self.console
        if isinstance(event, ev.StepStarted):
            c.print()
            c.print(
                f"[bold {COLORS['primary']}]Step {event.index}/{event.total}: "
                f"{event.label}...[/bold {COLORS['primary']}]"
            )
        elif isinstance(event, ev.StepDetail):
            c.print(f"  [dim]{event.text}[/dim]")
        elif isinstance(event, ev.Notice):
            style = {
                "warn": "yellow",
                "error": "red",
                "success": "green",
                "dim": "dim",
            }.get(event.level, "")
            if event.level == "error":
                c.print(f"[red]❌ {event.text}[/red]")
            elif style:
                c.print(f"[{style}]{event.text}[/{style}]")
            else:
                c.print(event.text)

    # ── Final result ────────────────────────────────────────────────────

    def result(self, result, flags) -> None:
        """Render the pipeline outcome — success panel or a failure notice."""
        c = self.console
        if not result.ok:
            if result.message:
                c.print()
                c.print(f"[yellow]{result.message}[/yellow]")
                c.print()
            return

        lines = []
        for art in result.artifacts:
            if art.ok:
                lines.append(f"[green]✓[/green] {art.name} ({art.size:,} bytes)")
            else:
                lines.append(f"[red]✗[/red] {art.name} (not created)")

        success_text = Text()
        success_text.append("✓ ", style="bold green")
        success_text.append("Project Documentation Generated", style="bold green")

        c.print()
        c.print(
            Panel(
                "\n".join(lines),
                title=success_text,
                border_style="green",
                padding=(1, 2),
            )
        )

        c.print()
        c.print("💡 ", style="dim", end="")
        c.print(
            "[dim]Run [bold]/init --update[/bold] to re-analyze only changed files[/dim]"
        )
        c.print()

    # ── Fallback (no graphify) ──────────────────────────────────────────

    async def run_fallback(
        self,
        project_root: Path,
        nova_md_path: Path,
        agent,
        session_state,
        assistant_id: str,
        token_tracker: TokenTracker,
    ) -> None:
        """Prompt-based exploration: stream the agent and report the outcome.

        Uses the init_exploration.jinja template to send an exploration prompt to
        the main agent, which uses its tools to explore and write NOVA.md.
        """
        from novacode_cli.ui.execution import execute_task

        c = self.console

        exploration_prompt = render_template(
            "init_exploration.jinja",
            project_root=str(project_root),
            Nova_md_path=str(nova_md_path),
        )

        c.print("🤖 ", style=COLORS["primary"], end="")
        c.print("[bold]Starting AI exploration (fallback mode)...[/bold]")
        c.print(
            "   [dim]The agent will automatically explore and document your codebase[/dim]"
        )
        c.print()

        original_auto_approve = session_state.auto_approve
        session_state.auto_approve = True
        try:
            await execute_task(
                exploration_prompt,
                agent,
                assistant_id,
                session_state,
                token_tracker,
            )

            c.print()

            if nova_md_path.exists():
                try:
                    content = nova_md_path.read_text(encoding="utf-8")
                    file_size = len(content)
                    line_count = len(content.split("\n"))

                    success_text = Text()
                    success_text.append("✓ ", style="bold green")
                    success_text.append(
                        "NOVA.md Created Successfully", style="bold green"
                    )

                    info_lines = [
                        f"Location: {nova_md_path}",
                        f"Size: {file_size:,} characters, {line_count} lines",
                        "",
                    ]
                    c.print(
                        Panel(
                            "\n".join(info_lines),
                            title=success_text,
                            border_style="green",
                            padding=(1, 2),
                        )
                    )
                except Exception:  # noqa: BLE001
                    c.print("✅ ", style="bold green", end="")
                    c.print("[bold green]NOVA.md created successfully![/bold green]")
                    c.print(f"   [dim]Location: {nova_md_path}[/dim]")
            else:
                c.print("⚠️  ", style="yellow", end="")
                c.print("[bold yellow]NOVA.md was not created[/bold yellow]")
                c.print(
                    "   [dim]The agent may need additional guidance. "
                    "Try running /init again.[/dim]"
                )
            c.print()

        except Exception as e:  # noqa: BLE001
            import traceback

            c.print()
            c.print("❌ ", style="red", end="")
            c.print(f"[bold red]Error during exploration:[/bold red] {e}")
            c.print()
            c.print("[dim]Traceback:[/dim]")
            c.print(f"[dim]{traceback.format_exc()}[/dim]")
            c.print()
        finally:
            session_state.auto_approve = original_auto_approve

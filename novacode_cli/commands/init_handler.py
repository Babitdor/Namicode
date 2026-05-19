"""Handler for the /init command to create project documentation.

Supports two modes:
1. **Graphify mode** (default, when graphify is installed): Multi-step pipeline
   that detects, extracts, clusters, analyzes, and generates structured output
   including NOVA.md, AGENTS.md, project graph JSON, and HTML visualization.
2. **Fallback mode** (when graphify is not installed): Sends an exploration
   prompt to the main agent, which uses its tools to explore and write NOVA.md.

Flags:
    --update    Incremental re-run — only re-extract changed files
    --deep      Extract all files (no limit) — slower but more thorough
    --no-viz    Skip HTML visualization generation
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from novacode_cli.config.config import COLORS, Settings, console
from novacode_cli.prompts import render_template
from novacode_cli.ui.ui_elements import TokenTracker


class InitFlags:
    """Parsed flags for the /init command."""

    def __init__(self, args: str | None = None) -> None:
        """Parse init command flags from argument string.

        Args:
            args: Raw argument string from the command (e.g., "--update --deep").
        """
        self.update = False
        self.deep = False
        self.no_viz = False

        if args:
            parts = args.lower().split()
            self.update = "--update" in parts
            self.deep = "--deep" in parts
            self.no_viz = "--no-viz" in parts


async def handle_init_command(
    agent,
    session_state,
    assistant_id: str,
    token_tracker: TokenTracker,
    cmd_args: str | None = None,
) -> None:
    """Handle the /init command to explore codebase and create documentation.

    When graphify is installed, runs a multi-step pipeline:
    1. Detect — scan project files
    2. Extract — AST analysis of code files
    3. Build & Cluster — knowledge graph with community detection
    4. Analyze — find god nodes, surprising connections
    5. Generate — NOVA.md, AGENTS.md, graph JSON, HTML

    When graphify is not installed, falls back to the prompt-based
    exploration approach using the init_exploration.jinja template.

    Args:
        agent: The LangGraph agent.
        session_state: Current session state.
        assistant_id: Agent identifier.
        token_tracker: Token tracker instance.
        cmd_args: Optional command arguments (e.g., "--update --deep").
    """
    flags = InitFlags(cmd_args)

    console.print()

    # Create header
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

    # Show flags
    flag_parts = []
    if flags.update:
        flag_parts.append("--update")
    if flags.deep:
        flag_parts.append("--deep")
    if flags.no_viz:
        flag_parts.append("--no-viz")
    if flag_parts:
        console.print(f"   [dim]Flags: {' '.join(flag_parts)}[/dim]")
    console.print()

    # Check if NOVA.md already exists
    nova_dir = project_root / ".nova"
    nova_md_path = nova_dir / "NOVA.md"
    agents_md_path = nova_dir / "AGENTS.md"

    if nova_md_path.exists():
        console.print("⚠️  ", style="yellow", end="")
        console.print("[yellow]NOVA.md already exists[/yellow]")
        if flags.update:
            console.print(
                "   [dim]Incremental update — only changed files will be re-analyzed[/dim]"
            )
        else:
            console.print("   [dim]It will be updated with fresh analysis[/dim]")
        console.print()

    # Try graphify pipeline first
    from novacode_cli.init.detect import is_graphify_available

    if is_graphify_available():
        await _run_graphify_pipeline(
            project_root=project_root,
            nova_dir=nova_dir,
            nova_md_path=nova_md_path,
            agents_md_path=agents_md_path,
            flags=flags,
            console=console,
        )
    else:
        _show_graphify_unavailable(console)
        await _run_fallback_pipeline(
            project_root=project_root,
            nova_md_path=nova_md_path,
            agent=agent,
            session_state=session_state,
            assistant_id=assistant_id,
            token_tracker=token_tracker,
        )


async def _run_graphify_pipeline(
    project_root: Path,
    nova_dir: Path,
    nova_md_path: Path,
    agents_md_path: Path,
    flags: InitFlags,
    console: Console,
) -> None:
    """Run the graphify-powered multi-step /init pipeline.

    Steps: detect → extract → build & cluster → analyze → generate → export.

    Heavy synchronous graphify calls are dispatched to a worker thread via
    ``asyncio.to_thread()`` so they don't freeze the event loop.  Rich
    console prints happen on the main thread between steps.

    Args:
        project_root: Path to the project root.
        nova_dir: Path to the .nova directory.
        nova_md_path: Path to the NOVA.md file.
        agents_md_path: Path to the AGENTS.md file.
        flags: Parsed command flags.
        console: Rich console for output.
    """
    import asyncio

    from novacode_cli.init.detect import (
        detect_project,
        detect_project_incremental,
        save_manifest,
    )
    from novacode_cli.init.extract import (
        extract_project,
        extract_project_incremental,
        load_extraction_cache,
        save_extraction_cache,
    )
    from novacode_cli.init.graph import (
        analyze_project_graph,
        build_project_graph,
        cluster_project_graph,
        export_project_graph,
    )
    from novacode_cli.init.generate import generate_agents_md, generate_nova_md

    # ── Step 1: Detect ──────────────────────────────────────────
    console.print(
        f"[bold {COLORS['primary']}]Step 1/5: Detecting project files...[/bold {COLORS['primary']}]"
    )
    # graphify.detect scans the filesystem — fast (IO-bound), run in thread
    if flags.update:
        detection = await asyncio.to_thread(
            detect_project_incremental, project_root, console
        )
        # If no changes, use full detection as fallback
        if not detection:
            detection = await asyncio.to_thread(
                detect_project, project_root, console
            )
    else:
        detection = await asyncio.to_thread(
            detect_project, project_root, console
        )

    if not detection:
        console.print("[red]❌ Detection failed — no files found[/red]")
        return

    # ── Step 2: Extract ────────────────────────────────────────────
    console.print()
    console.print(
        f"[bold {COLORS['primary']}]Step 2/5: Extracting entities (AST analysis)...[/bold {COLORS['primary']}]"
    )
    # graphify.extract runs tree-sitter on every file — CPU-intensive, must run
    # in a thread to avoid freezing the event loop for large codebases.
    if flags.update:
        cached = await asyncio.to_thread(load_extraction_cache, project_root)
        extraction = await asyncio.to_thread(
            extract_project_incremental, project_root, detection, cached, console,
        )
    else:
        extraction = await asyncio.to_thread(
            extract_project, project_root, detection, console, flags.deep
        )

    if not extraction or not extraction.get("nodes"):
        console.print(
            "[yellow]⚠ No entities extracted — falling back to prompt-based exploration[/yellow]"
        )
        return

    # Save extraction cache for future incremental updates
    await asyncio.to_thread(save_extraction_cache, project_root, extraction)

    # ── Step 3: Build & Cluster ─────────────────────────────────
    console.print()
    console.print(
        f"[bold {COLORS['primary']}]Step 3/5: Building knowledge graph...[/bold {COLORS['primary']}]"
    )
    # graphify.build + Leiden clustering — CPU-intensive for large graphs
    G = await asyncio.to_thread(build_project_graph, extraction, console)
    if G is None:
        console.print("[red]❌ Graph building failed[/red]")
        return

    communities = await asyncio.to_thread(cluster_project_graph, G, console)

    # ── Step 4: Analyze ─────────────────────────────────────────
    console.print()
    console.print(
        f"[bold {COLORS['primary']}]Step 4/5: Analyzing project structure...[/bold {COLORS['primary']}]"
    )
    # graphify.analyze — includes betweenness centrality, O(V*E) worst case
    analysis = await asyncio.to_thread(analyze_project_graph, G, communities, console)

    # ── Step 5: Generate & Export ────────────────────────────────────
    console.print()
    console.print(
        f"[bold {COLORS['primary']}]Step 5/5: Generating documentation...[/bold {COLORS['primary']}]"
    )

    # Generate NOVA.md (template rendering + file write — I/O bound, run in thread)
    nova_md_content = await asyncio.to_thread(
        generate_nova_md,
        project_root=project_root,
        detection=detection,
        extraction=extraction,
        analysis=analysis,
        communities=communities,
        console=console,
    )

    # Write files
    nova_dir.mkdir(parents=True, exist_ok=True)
    nova_md_path.write_text(nova_md_content, encoding="utf-8")

    # Export graph (JSON + HTML generation — I/O bound, run in thread)
    await asyncio.to_thread(
        export_project_graph,
        G=G,
        communities=communities,
        analysis=analysis,
        output_dir=nova_dir,
        console=console,
        include_html=not flags.no_viz,
    )

    # Save detection manifest for incremental updates
    await asyncio.to_thread(save_manifest, project_root, detection)
    save_manifest(project_root, detection)

    # ── Show final results ───────────────────────────────────────────
    console.print()
    _show_success_panel(nova_md_path, nova_dir, flags, console)


async def _run_fallback_pipeline(
    project_root: Path,
    nova_md_path: Path,
    agent,
    session_state,
    assistant_id: str,
    token_tracker: TokenTracker,
) -> None:
    """Run the fallback prompt-based /init pipeline.

    Uses the init_exploration.jinja template to send an exploration
    prompt to the main agent, which uses its tools to explore and
    write NOVA.md.

    Args:
        project_root: Path to the project root.
        nova_md_path: Path to the NOVA.md file.
        agent: The LangGraph agent.
        session_state: Current session state.
        assistant_id: Agent identifier.
        token_tracker: Token tracker instance.
    """
    from novacode_cli.ui.execution import execute_task

    # Create the exploration prompt using Jinja template
    exploration_prompt = render_template(
        "init_exploration.jinja",
        project_root=str(project_root),
        Nova_md_path=str(nova_md_path),
    )

    # Show status
    console.print("🤖 ", style=COLORS["primary"], end="")
    console.print("[bold]Starting AI exploration (fallback mode)...[/bold]")
    console.print(
        "   [dim]The agent will automatically explore and document your codebase[/dim]"
    )
    console.print()

    # Temporarily enable auto-approve for this operation
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

        console.print()

        # Check if file was created
        if nova_md_path.exists():
            try:
                content = nova_md_path.read_text(encoding="utf-8")
                file_size = len(content)
                line_count = len(content.split("\n"))

                success_text = Text()
                success_text.append("✓ ", style="bold green")
                success_text.append("NOVA.md Created Successfully", style="bold green")

                info_lines = [
                    f"Location: {nova_md_path}",
                    f"Size: {file_size:,} characters, {line_count} lines",
                    "",
                ]
                panel = Panel(
                    "\n".join(info_lines),
                    title=success_text,
                    border_style="green",
                    padding=(1, 2),
                )
                console.print(panel)
            except Exception:
                console.print("✅ ", style="bold green", end="")
                console.print("[bold green]NOVA.md created successfully![/bold green]")
                console.print(f"   [dim]Location: {nova_md_path}[/dim]")
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
        session_state.auto_approve = original_auto_approve


def _show_graphify_unavailable(console: Console) -> None:
    """Show a message when graphify is not installed.

    Args:
        console: Rich console for output.
    """
    console.print()
    console.print("💡 ", style="yellow", end="")
    console.print(
        "[yellow]graphify not installed — using fallback exploration mode[/yellow]"
    )
    console.print(
        "   [dim]Install with: [bold]pip install novacode-cli[graphify][/bold] "
        "for richer output (NOVA.md + AGENTS.md + project graph + HTML visualization)[/dim]"
    )
    console.print()


def _show_success_panel(
    nova_md_path: Path,
    nova_dir: Path,
    flags: InitFlags,
    console: Console,
) -> None:
    """Show a success panel with all generated files.

    Args:
        nova_md_path: Path to the NOVA.md file.
        agents_md_path: Path to the AGENTS.md file.
        nova_dir: Path to the .nova directory.
        flags: Parsed command flags.
        console: Rich console for output.
    """
    lines = []

    # NOVA.md
    if nova_md_path.exists():
        size = nova_md_path.stat().st_size
        lines.append(f"[green]✓[/green] NOVA.md ({size:,} bytes)")
    else:
        lines.append("[red]✗[/red] NOVA.md (not created)")

    # Graph JSON
    graph_json = nova_dir / "project-graph.json"
    if graph_json.exists():
        size = graph_json.stat().st_size
        lines.append(f"[green]✓[/green] project-graph.json ({size:,} bytes)")

    # Graph HTML
    if not flags.no_viz:
        graph_html = nova_dir / "project-graph.html"
        if graph_html.exists():
            size = graph_html.stat().st_size
            lines.append(f"[green]✓[/green] project-graph.html ({size:,} bytes)")

    # Manifest
    manifest = nova_dir / "manifest.json"
    if manifest.exists():
        lines.append("[green]✓[/green] manifest.json (for incremental updates)")

    success_text = Text()
    success_text.append("✓ ", style="bold green")
    success_text.append("Project Documentation Generated", style="bold green")

    panel = Panel(
        "\n".join(lines),
        title=success_text,
        border_style="green",
        padding=(1, 2),
    )
    console.print(panel)

    # Show tip for incremental updates
    console.print()
    console.print("💡 ", style="dim", end="")
    console.print(
        "[dim]Run [bold]/init --update[/bold] to re-analyze only changed files[/dim]"
    )
    console.print()

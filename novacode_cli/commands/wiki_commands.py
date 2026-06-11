"""REPL command handlers for wiki operations: /ingest, /ask, /file.

These handlers bridge the slash command system to the wiki engine modules.
"""

from __future__ import annotations

from novacode_cli.wiki.ask import WikiAskEngine
from novacode_cli.wiki.file import WikiFileEngine
from novacode_cli.wiki.ingest import IngestEngine


async def handle_ingest(
    ctx,
    execute_fn=None,
) -> bool:
    """/ingest [<path>] — Ingest a captured source into synthesized wiki pages.

    Sources live in the wiki's ``Clipping/`` inbox (Obsidian Web Clipper) or the
    legacy ``raw/`` tree; both are scanned. ``<path>`` may be a bare filename
    (found anywhere) or a relative path. With no argument, lists what's available.

    ``execute_fn`` lets callers (e.g. the Textual TUI) substitute their own
    renderer for the agent run; defaults to the classic ``execute_task``.
    """
    from novacode_cli.config.config import console

    args = (ctx.cmd_args or "").strip()

    # No argument → auto-discover and list whatever's in the local wiki's raw/
    # folder, so the user can see exactly what's available to ingest.
    if not args:
        try:
            engine = IngestEngine()
            sources = engine.list_raw_sources()
            clipping_dir = engine._mgr.root / "Clippings"
        except Exception as ex:  # noqa: BLE001
            console.print(f"[red]/ingest error: {ex}[/red]")
            return True
        console.print()
        console.print("[yellow]Usage: /ingest <path>[/yellow]")
        console.print(f"[dim]Web Clipper inbox: {clipping_dir}[/dim]")
        if sources:
            console.print("[bold]Available sources:[/bold]")
            for s in sources:
                console.print(f"  • {s}")
            console.print(
                "[dim]Tip: pass just the filename — it's found anywhere in Clipping/ or raw/.[/dim]"
            )
        else:
            console.print(
                "[dim]No sources yet — save web clips into the inbox above "
                "(Obsidian Web Clipper), then re-run /ingest.[/dim]"
            )
        console.print()
        return True

    if execute_fn is None:
        from novacode_cli.ui.execution import execute_task

        execute_fn = execute_task

    try:
        engine = IngestEngine()
        await engine.ingest_source(
            source_path=args,
            agent=ctx.agent,
            session_state=ctx.session_state,
            execute_fn=execute_fn,
            token_tracker=ctx.token_tracker,
            assistant_id=ctx.assistant_id,
        )
    except (FileNotFoundError, ValueError) as ex:
        console.print(f"[red]Error: {ex}[/red]")
    except Exception as ex:  # noqa: BLE001
        console.print(f"[red]/ingest error: {ex}[/red]")
    return True


async def handle_ask(
    ctx,
    execute_fn=None,
) -> bool:
    """/ask <question> — Ask a question informed by wiki context.

    Searches the wiki for relevant pages and prepends their content
    before sending to the agent.
    """
    question = (ctx.cmd_args or "").strip()
    if not question:
        from novacode_cli.config.config import console

        console.print()
        console.print("[yellow]Usage: /ask <question>[/yellow]")
        console.print("[dim]Searches wiki context and answers with relevant knowledge.[/dim]")
        console.print()
        return True

    if execute_fn is None:
        from novacode_cli.ui.execution import execute_task

        execute_fn = execute_task

    engine = WikiAskEngine()
    prompt = await engine.build_prompt(question)

    backend = getattr(ctx.agent, "backend", None)
    await execute_fn(
        prompt,
        ctx.agent,
        ctx.assistant_id,
        ctx.session_state,
        token_tracker=ctx.token_tracker,
        backend=backend,
    )
    return True


async def handle_file(
    ctx,
    execute_fn=None,
) -> bool:
    """/file <topic> — File recent conversation knowledge as a wiki page.

    <topic> should be a path like ``patterns/MultiAgentPatterns`` or
    ``comparisons/CrewAI-vs-LangGraph``.
    """
    topic = (ctx.cmd_args or "").strip()
    if not topic:
        from novacode_cli.config.config import console

        console.print()
        console.print("[yellow]Usage: /file <topic>[/yellow]")
        console.print(
            "[dim]Topic is a wiki path (e.g. patterns/MultiAgentPatterns, comparisons/CrewAI-vs-LangGraph)[/dim]"
        )
        console.print()
        return True

    if execute_fn is None:
        from novacode_cli.ui.execution import execute_task

        execute_fn = execute_task

    try:
        engine = WikiFileEngine()
        await engine.file_knowledge(
            topic=topic,
            agent=ctx.agent,
            session_state=ctx.session_state,
            execute_fn=execute_fn,
            token_tracker=ctx.token_tracker,
            assistant_id=ctx.assistant_id,
        )
    except Exception as ex:  # noqa: BLE001
        from novacode_cli.config.config import console

        console.print(f"[red]/file error: {ex}[/red]")
    return True


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def register_commands(registry) -> None:
    """Register wiki commands with the command registry."""
    from novacode_cli.commands import CommandContext

    async def _ingest(ctx: CommandContext) -> bool:
        return await handle_ingest(ctx)

    async def _ask(ctx: CommandContext) -> bool:
        return await handle_ask(ctx)

    async def _file(ctx: CommandContext) -> bool:
        return await handle_file(ctx)

    registry.register("ingest", _ingest)
    registry.register("ask", _ask)
    registry.register("file", _file)

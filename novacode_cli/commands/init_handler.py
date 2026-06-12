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

Presentation is **decoupled** from the pipeline. :func:`_run_graphify_pipeline`
is pure logic: it reports progress through an injected ``emit`` callback (see
:mod:`novacode_cli.init.events`) and returns an :class:`InitResult`. It never
imports ``rich`` or touches a console. The Textual TUI renders those events into
its native step tracker; the legacy REPL renders them via
:mod:`novacode_cli.commands.init_renderer`.

``progress_console`` is an *opaque* sink the renderer owns and forwards to the
graphify internals (detect/extract/build), whose own tree-sitter/Leiden progress
bars still draw through a rich ``Console``. The pipeline never reads or writes it
itself — it only passes it through.
"""

from __future__ import annotations

from pathlib import Path

from novacode_cli.commands import CommandContext, CommandRegistry
from novacode_cli.config.config import Settings
from novacode_cli.init.events import (
    Artifact,
    EmitFn,
    InitResult,
    Notice,
    StepDetail,
    StepStarted,
    null_emit,
)
from novacode_cli.ui.ui_elements import TokenTracker

_TOTAL_STEPS = 5


class InitRenderer:
    """Protocol that a renderer must satisfy to work with InitOrchestrator.

    Each entry point (legacy REPL, Textual TUI) provides its own implementation
    so the orchestrator stays renderer-agnostic.
    """

    def emit(self, event) -> None:
        """Forward a pipeline progress event (StepStarted / StepDetail / Notice)."""
        ...

    def result(self, result, flags) -> None:
        """Render the final pipeline outcome."""
        ...

    def graphify_unavailable(self) -> None:
        """Notify the user that graphify is not installed (optional)."""
        ...

    async def run_fallback(
        self,
        project_root: Path,
        nova_md_path: Path,
        agent,
        session_state,
        assistant_id: str,
        token_tracker: TokenTracker,
    ) -> None:
        """Run the prompt-based fallback when graphify is not available."""
        ...


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
        # By default the graphify pipeline now has the LLM author a narrative
        # NOVA.md grounded in the computed facts. --no-llm (or --template) forces
        # the deterministic template render instead.
        self.no_llm = False

        if args:
            parts = args.lower().split()
            self.update = "--update" in parts
            self.deep = "--deep" in parts
            self.no_viz = "--no-viz" in parts
            self.no_llm = "--no-llm" in parts or "--template" in parts

    def as_list(self) -> list[str]:
        """The active flags as CLI tokens, for display."""
        out = []
        if self.update:
            out.append("--update")
        if self.deep:
            out.append("--deep")
        if self.no_viz:
            out.append("--no-viz")
        if self.no_llm:
            out.append("--no-llm")
        return out


class InitOrchestrator:
    """Encapsulates the shared /init orchestration for both REPL and TUI paths.

    Owns the graphify-availability check, agent-building, pipeline dispatch, and
    fallback routing so both entry points share one authoritative sequence.
    """

    def __init__(
        self,
        *,
        project_root: Path,
        nova_dir: Path,
        nova_md_path: Path,
        agents_md_path: Path,
        flags: InitFlags,
        renderer: InitRenderer,
        agent,
        session_state,
        assistant_id: str,
        token_tracker: TokenTracker,
        session_id: str = "",
        progress_console=None,
        execute_fn=None,
    ) -> None:
        self._project_root = project_root
        self._nova_dir = nova_dir
        self._nova_md_path = nova_md_path
        self._agents_md_path = agents_md_path
        self._flags = flags
        self._renderer = renderer
        self._agent = agent
        self._session_state = session_state
        self._assistant_id = assistant_id
        self._token_tracker = token_tracker
        self._session_id = session_id
        self._progress_console = progress_console
        self._execute_fn = execute_fn

    async def run(self) -> InitResult:
        """Run the /init pipeline (graphify) or fall back to agent exploration."""
        from novacode_cli.init.detect import is_graphify_available

        if is_graphify_available():
            if self._execute_fn is None:
                self._execute_fn = build_init_execute_fn(
                    self._agent,
                    self._session_state,
                    self._assistant_id,
                    self._token_tracker,
                    self._flags,
                )
            result = await _run_graphify_pipeline(
                project_root=self._project_root,
                nova_dir=self._nova_dir,
                nova_md_path=self._nova_md_path,
                agents_md_path=self._agents_md_path,
                flags=self._flags,
                emit=self._renderer.emit,
                progress_console=self._progress_console,
                agent=self._agent,
                execute_fn=self._execute_fn,
                session_id=self._session_id,
            )
            self._renderer.result(result, self._flags)
            return result
        else:
            self._renderer.graphify_unavailable()
            await self._renderer.run_fallback(
                project_root=self._project_root,
                nova_md_path=self._nova_md_path,
                agent=self._agent,
                session_state=self._session_state,
                assistant_id=self._assistant_id,
                token_tracker=self._token_tracker,
            )
            return _make_empty_result(self._nova_dir, self._nova_md_path)


def _make_empty_result(nova_dir: Path, nova_md_path: Path) -> InitResult:
    """Return an InitResult for the fallback path (graphify not available)."""
    return InitResult(
        ok=nova_md_path.exists(),
        nova_dir=nova_dir,
        nova_md_path=nova_md_path,
    )


def build_init_execute_fn(
    agent,
    session_state,
    assistant_id: str,
    token_tracker: TokenTracker,
    flags: InitFlags,
):
    """Build the ``execute_fn`` that runs the LLM-bearing stages through the agent.

    The semantic-extraction and NOVA.md-authoring stages run through the Nova
    agent itself — its tools and ``task`` subagents — grounded in the graph,
    instead of stateless model calls. The agent reads/writes files unattended
    here, so auto-approve is enabled for the duration of each call.

    Returns ``None`` when no agent is available or ``--no-llm`` is set, in which
    case the pipeline falls back to a single model call / deterministic template.
    """
    if agent is None or flags.no_llm:
        return None

    from novacode_cli.ui.execution import execute_task

    # Prefer a dedicated NO-HITL, LOCAL-filesystem agent for /init:
    # - auto_approve=True → interrupt_on={} → no approval prompts on the
    #   main agent OR its `task` subagents (a subagent's HITL interrupt is
    #   unresolvable — it bubbles out of `task`'s ainvoke as a
    #   GraphInterrupt and crashes the run).
    # - sandbox=None → a LOCAL FilesystemBackend rooted at the project.
    #   /init reads local files and must write graph fragments to the
    #   local .nova/; through a sandbox backend, `/`-prefixed virtual
    #   paths hit the container root (project is at /workspace → reads
    #   404) and any writes land inside the sandbox.
    # Fall back to the shared agent if we can't build one.
    init_agent = agent
    try:
        from novacode_cli.agents.core_agent import create_agent_with_config

        _model = getattr(session_state, "_model", None)
        if _model is not None:
            init_agent, _ = create_agent_with_config(
                model=_model,
                assistant_id=getattr(session_state, "_assistant_id", None)
                or assistant_id,
                tools=getattr(session_state, "_tools", None) or [],
                sandbox=None,        # LOCAL filesystem (see comment)
                sandbox_type=None,
                store=getattr(session_state, "_store", None),
                checkpointer=getattr(session_state, "_checkpointer", None),
                auto_approve=True,
                is_continuation=True,
            )
    except Exception:  # noqa: BLE001
        init_agent = agent

    async def execute_fn(prompt: str) -> None:
        original_auto_approve = session_state.auto_approve
        session_state.auto_approve = True
        try:
            await execute_task(
                prompt,
                init_agent,
                assistant_id,
                session_state,
                token_tracker,
            )
        finally:
            session_state.auto_approve = original_auto_approve

    return execute_fn


async def handle_init_command(
    agent,
    session_state,
    assistant_id: str,
    token_tracker: TokenTracker,
    cmd_args: str | None = None,
) -> None:
    """Handle the /init command (legacy REPL entry point).

    Thin wrapper that delegates orchestration to :class:`InitOrchestrator`.
    The **legacy Rich renderer** (:mod:`novacode_cli.commands.init_renderer`)
    provides progress display and fallback execution.

    Args:
        agent: The LangGraph agent.
        session_state: Current session state.
        assistant_id: Agent identifier.
        token_tracker: Token tracker instance.
        cmd_args: Optional command arguments (e.g., "--update --deep").
    """
    from novacode_cli.commands.init_renderer import LegacyInitRenderer

    flags = InitFlags(cmd_args)
    renderer = LegacyInitRenderer()

    settings = Settings.from_environment()
    project_root = settings.project_root
    if not project_root:
        renderer.no_project()
        return

    nova_dir = project_root / ".nova"
    nova_md_path = nova_dir / "NOVA.md"

    renderer.intro(project_root, flags, nova_md_path)

    orchestrator = InitOrchestrator(
        project_root=project_root,
        nova_dir=nova_dir,
        nova_md_path=nova_md_path,
        agents_md_path=nova_dir / "AGENTS.md",
        flags=flags,
        renderer=renderer,
        agent=agent,
        session_state=session_state,
        assistant_id=assistant_id,
        token_tracker=token_tracker,
        session_id=getattr(session_state, "session_id", ""),
        progress_console=renderer.console,
    )
    await orchestrator.run()


async def _run_graphify_pipeline(
    project_root: Path,
    nova_dir: Path,
    nova_md_path: Path,
    agents_md_path: Path,
    flags: InitFlags,
    emit: EmitFn | None = None,
    progress_console=None,
    agent=None,
    execute_fn=None,
    session_id: str = "",
) -> InitResult:
    """Run the graphify-powered multi-step /init pipeline (pure logic).

    Steps: detect → extract (AST) → semantic extract → build & cluster →
    analyze → author NOVA.md → export.

    graphify computes the **graph and facts** (deterministic). The two
    LLM-bearing stages — semantic extraction and NOVA.md authoring — are run
    through the **Nova agent itself** (``execute_fn`` + its ``task`` subagents
    and tools) so they can read files, follow imports, look things up, and stay
    grounded in the graph. They fall back to a single model call / deterministic
    template only when no agent is available (e.g. non-interactive, or --no-llm).

    Progress is reported through ``emit`` (UI-agnostic events); the final outcome
    is the returned :class:`InitResult`. This function never imports ``rich`` or
    writes to a console.

    Args:
        project_root: Path to the project root.
        nova_dir: Path to the .nova directory.
        nova_md_path: Path to the NOVA.md file.
        agents_md_path: Path to the AGENTS.md file.
        flags: Parsed command flags.
        emit: Callback fed UI-agnostic progress events (defaults to a no-op).
        progress_console: Opaque rich sink forwarded to graphify internals for
            their own tree-sitter/Leiden progress bars. Renderer-owned; the
            pipeline only passes it through.
        agent: The Nova agent (for tool/subagent-driven stages).
        execute_fn: Runs a prompt through the agent (TUI stream / execute_task).
        session_id: Current session id, for the init.complete hook.

    Returns:
        An :class:`InitResult` describing the outcome and generated files.
    """
    import asyncio

    if emit is None:
        emit = null_emit
    pc = progress_console  # opaque sink forwarded to graphify internals

    from novacode_cli.init.detect import (
        detect_project,
        detect_project_incremental,
        save_manifest,
    )
    from novacode_cli.init.extract import (
        extract_project,
        extract_project_incremental,
        load_extraction_cache,
        normalize_source_paths,
        save_extraction_cache,
    )
    from novacode_cli.init.graph import (
        analyze_project_graph,
        build_project_graph,
        cluster_project_graph,
        export_project_graph,
        sanitize_graph_extraction,
    )
    from novacode_cli.init.generate import (
        generate_nova_md,
        generate_nova_md_llm,
    )

    # ── Step 1: Detect ──────────────────────────────────────────
    emit(StepStarted(1, _TOTAL_STEPS, "Detecting project files"))
    # graphify.detect scans the filesystem — fast (IO-bound), run in thread.
    # NOTE: detect_project_incremental's 2nd positional is `manifest_path`, so the
    # console MUST be passed by keyword (passing it positionally silently routed
    # all output to the global console — the TUI's incremental-detection leak).
    if flags.update:
        detection = await asyncio.to_thread(
            detect_project_incremental, project_root, console=pc
        )
        # If no changes, use full detection as fallback
        if not detection:
            detection = await asyncio.to_thread(detect_project, project_root, pc)
    else:
        detection = await asyncio.to_thread(detect_project, project_root, pc)

    if not detection:
        emit(Notice("Detection failed — no files found", "error"))
        return InitResult(
            ok=False,
            nova_dir=nova_dir,
            nova_md_path=nova_md_path,
            message="Detection failed — no files found",
        )

    # Surface detection stats natively (the graphify panel is suppressed in TUI).
    if "new_files" in detection:
        _nf = detection.get("new_files", {})
        _uf = detection.get("unchanged_files", {})
        _new = sum(len(v) for v in _nf.values()) if isinstance(_nf, dict) else len(_nf)
        _unchanged = (
            sum(len(v) for v in _uf.values()) if isinstance(_uf, dict) else len(_uf)
        )
        emit(StepDetail(f"{_new} new · {_unchanged} unchanged files"))
    else:
        emit(
            StepDetail(
                f"{detection.get('total_files', 0)} files · "
                f"{detection.get('total_words', 0):,} words"
            )
        )

    # ── Step 2: Extract ────────────────────────────────────────────
    emit(StepStarted(2, _TOTAL_STEPS, "Extracting entities (AST analysis)"))
    # graphify.extract runs tree-sitter on every file — CPU-intensive, must run
    # in a thread to avoid freezing the event loop for large codebases.
    if flags.update:
        cached = await asyncio.to_thread(load_extraction_cache, project_root)
        extraction = await asyncio.to_thread(
            extract_project_incremental,
            project_root,
            detection,
            cached,
            pc,
        )
    else:
        extraction = await asyncio.to_thread(
            extract_project, project_root, detection, pc, flags.deep
        )

    if not extraction or not extraction.get("nodes"):
        emit(
            Notice(
                "No entities extracted — falling back to prompt-based exploration",
                "warn",
            )
        )
        return InitResult(
            ok=False,
            nova_dir=nova_dir,
            nova_md_path=nova_md_path,
            message="No entities extracted",
            fell_back=True,
        )

    emit(
        StepDetail(
            f"{len(extraction.get('nodes', []))} entities · "
            f"{len(extraction.get('edges', []))} relations (AST)"
        )
    )

    # ── Step 2b: Semantic extraction ────────────────────────────────
    # AST only captures code structure. The semantic stage adds document
    # concepts and the call/data/architecture edges AST can't see, grounding a
    # much richer graph. Run through the Nova AGENT (tools + subagents) when
    # available so extractors can read files / follow imports / look things up;
    # fall back to a stateless model call otherwise. Skipped on --no-llm/--update.
    if not flags.no_llm and not flags.update:
        from novacode_cli.init.extract import (
            merge_ast_semantic,
            semantic_extract_project,
            semantic_extract_via_agent,
        )

        emit(StepDetail("Semantic extraction (agent concepts + relationships)…"))
        if execute_fn is not None:
            semantic = await semantic_extract_via_agent(
                project_root=project_root,
                detection=detection,
                execute_fn=execute_fn,
                console=pc,
                deep=flags.deep,
            )
        else:
            semantic = await semantic_extract_project(
                project_root=project_root,
                detection=detection,
                console=pc,
                deep=flags.deep,
            )
        if semantic.get("nodes") or semantic.get("edges"):
            extraction = merge_ast_semantic(extraction, semantic)
            emit(
                StepDetail(
                    f"Merged graph: {len(extraction.get('nodes', []))} nodes, "
                    f"{len(extraction.get('edges', []))} edges"
                )
            )

    # Normalize OS-native (Windows backslash) source paths to forward slashes so
    # they don't leak into NOVA.md / the graph JSON and break later edit_file
    # matches (the agent loops on "String not found"). Done once here so the
    # graph, cache, facts, and docs all inherit slash paths.
    extraction = normalize_source_paths(extraction)

    # Sanitize BEFORE caching so a malformed LLM fragment (dict weight, None
    # label/id) can't poison the cache — otherwise a later `/init --update`
    # reloads the bad data and crashes ('>' float/dict, regex on NoneType).
    # build_project_graph re-sanitizes as a catch-all.
    extraction = sanitize_graph_extraction(extraction)

    # Save extraction cache for future incremental updates
    await asyncio.to_thread(save_extraction_cache, project_root, extraction)

    # ── Step 3: Build & Cluster ─────────────────────────────────
    emit(StepStarted(3, _TOTAL_STEPS, "Building knowledge graph"))
    # graphify.build + Leiden clustering — CPU-intensive for large graphs
    G = await asyncio.to_thread(build_project_graph, extraction, pc)
    if G is None:
        emit(Notice("Graph building failed", "error"))
        return InitResult(
            ok=False,
            nova_dir=nova_dir,
            nova_md_path=nova_md_path,
            message="Graph building failed",
        )

    communities = await asyncio.to_thread(cluster_project_graph, G, pc)
    try:
        emit(
            StepDetail(
                f"{G.number_of_nodes()} nodes · {G.number_of_edges()} edges · "
                f"{len(communities or {})} communities"
            )
        )
    except Exception:  # noqa: BLE001
        pass

    # ── Step 4: Analyze ─────────────────────────────────────────
    emit(StepStarted(4, _TOTAL_STEPS, "Analyzing project structure"))
    # graphify.analyze — includes betweenness centrality, O(V*E) worst case
    analysis = await asyncio.to_thread(analyze_project_graph, G, communities, pc)
    emit(
        StepDetail(
            f"{len(analysis.get('god_nodes', []))} hubs · "
            f"{len(analysis.get('surprising_connections', []))} surprising links"
        )
    )

    # ── Step 5: Export graph + author docs ───────────────────────────
    emit(StepStarted(5, _TOTAL_STEPS, "Generating documentation"))

    # Export the graph FIRST so NOVA.md authoring can query it live
    # (query_project_graph reads .nova/project-graph.json) and the agent can
    # open it directly. Guarded: a graphify export edge case must degrade to a
    # notice, not abort /init — NOVA.md authoring can still proceed without it.
    nova_dir.mkdir(parents=True, exist_ok=True)
    try:
        await asyncio.to_thread(
            export_project_graph,
            G=G,
            communities=communities,
            analysis=analysis,
            output_dir=nova_dir,
            console=pc,
            include_html=not flags.no_viz,
        )
        emit(
            StepDetail(
                "Exported project-graph.json"
                + ("" if flags.no_viz else " + project-graph.html")
            )
        )
    except Exception as ex:  # noqa: BLE001
        emit(Notice(f"Graph export skipped ({ex})", "warn"))

    # Author NOVA.md. Preferred: the Nova AGENT writes a rich, grounded doc using
    # its tools (query_project_graph / read_file). Fallbacks: a single grounded
    # model call, then the deterministic template — used only when no agent is
    # available, --no-llm is set, or the agent didn't produce a file.
    authored = False
    if execute_fn is not None and not flags.no_llm:
        from novacode_cli.init.generate import build_nova_md_author_prompt

        emit(StepDetail("Authoring NOVA.md with the Nova agent (grounded in the graph)…"))
        prompt = build_nova_md_author_prompt(
            project_root=project_root,
            detection=detection,
            extraction=extraction,
            analysis=analysis,
            communities=communities,
        )
        try:
            await execute_fn(prompt)
            authored = (
                nova_md_path.exists()
                and len(nova_md_path.read_text(encoding="utf-8").strip()) > 200
            )
        except Exception as ex:  # noqa: BLE001
            emit(Notice(f"Agent authoring failed ({ex}); using fallback.", "warn"))
            authored = False

    if not authored:
        nova_md_content = None
        if not flags.no_llm:
            nova_md_content = await generate_nova_md_llm(
                project_root=project_root,
                detection=detection,
                extraction=extraction,
                analysis=analysis,
                communities=communities,
                console=pc,
            )
        if not nova_md_content:
            nova_md_content = await asyncio.to_thread(
                generate_nova_md,
                project_root=project_root,
                detection=detection,
                extraction=extraction,
                analysis=analysis,
                communities=communities,
                console=pc,
            )
        nova_md_path.write_text(nova_md_content, encoding="utf-8")

    # Save detection manifest for incremental updates
    await asyncio.to_thread(save_manifest, project_root, detection)

    _fire_init_complete_hook(project_root, session_id)

    return InitResult(
        ok=nova_md_path.exists(),
        nova_dir=nova_dir,
        nova_md_path=nova_md_path,
        artifacts=_collect_artifacts(nova_md_path, nova_dir, flags),
    )


def _collect_artifacts(
    nova_md_path: Path, nova_dir: Path, flags: InitFlags
) -> list[Artifact]:
    """Stat the files the pipeline writes, for the final summary."""
    artifacts: list[Artifact] = []

    if nova_md_path.exists():
        artifacts.append(
            Artifact("NOVA.md", nova_md_path, nova_md_path.stat().st_size)
        )
    else:
        artifacts.append(Artifact("NOVA.md", nova_md_path, 0, ok=False))

    graph_json = nova_dir / "project-graph.json"
    if graph_json.exists():
        artifacts.append(
            Artifact("project-graph.json", graph_json, graph_json.stat().st_size)
        )

    if not flags.no_viz:
        graph_html = nova_dir / "project-graph.html"
        if graph_html.exists():
            artifacts.append(
                Artifact("project-graph.html", graph_html, graph_html.stat().st_size)
            )

    manifest = nova_dir / "manifest.json"
    if manifest.exists():
        artifacts.append(
            Artifact("manifest.json", manifest, manifest.stat().st_size)
        )

    return artifacts


def _fire_init_complete_hook(project_root: Path, session_id: str) -> None:
    """Fire the init.complete hook (best-effort)."""
    try:
        from novacode_cli.hooks import HookEvent, dispatch_hook_fire_and_forget

        dispatch_hook_fire_and_forget(
            HookEvent.INIT_COMPLETE,
            {
                "project_root": str(project_root),
                "session_id": session_id,
            },
        )
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def register_commands(registry: "CommandRegistry") -> None:
    """Register /init command."""

    async def _handle(ctx: CommandContext) -> bool:
        await handle_init_command(
            agent=ctx.agent,
            session_state=ctx.session_state,
            assistant_id=ctx.assistant_id,
            token_tracker=ctx.token_tracker,
            cmd_args=ctx.cmd_args,
        )
        return True

    registry.register("init", _handle)

"""Project extraction module for /init pipeline.

Two complementary stages, matching graphify's design:

- ``extract_project`` — **structural** extraction via ``graphify.extract``
  (tree-sitter AST) over **code files only**. Captures imports/defs/classes.
- ``semantic_extract_project`` — **semantic** extraction via the LLM over docs,
  papers, and (optionally) code. Captures the edges AST can't: call/data/
  architecture relationships, document concepts, and cross-file links, with
  INFERRED/AMBIGUOUS tags. Merged with the AST result before graph building.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

from novacode_cli.config.config import COLORS


def _make_console() -> Console:
    """Create a Console that handles Unicode on Windows.

    On Windows, the default console encoding (cp1252) cannot represent
    characters like emojis and special symbols that Rich renders in panel
    titles. Wrapping stdout with UTF-8 avoids UnicodeEncodeError.
    """
    from novacode_cli.config.config import console as _global_console
    return _global_console


def extract_project(
    project_root: Path,
    detection: dict[str, Any],
    console: Console | None = None,
    deep: bool = False,
) -> dict[str, Any]:
    """Structural (AST) extraction over **code files only**.

    Uses graphify.extract (tree-sitter) on code files. Doc/paper concepts are
    NOT handled here — tree-sitter can't parse prose; they are captured by
    :func:`semantic_extract_project` and merged before graph building.

    Args:
        project_root: Path to the project root directory.
        detection: Detection result from detect_project().
        console: Rich console for output.
        deep: If True, extract from all files. If False, limit to
            a reasonable subset for large projects.

    Returns:
        Extraction result dict with keys: nodes, edges, input_tokens,
        output_tokens. Returns empty dict if graphify is not available.
    """
    if console is None:
        console = _make_console()

    try:
        from graphify.extract import extract
    except ImportError:
        console.print(
            "[yellow]graphify not installed — install with: "
            "pip install novacode-cli[graphify][/yellow]"
        )
        return {}

    files_dict = detection.get("files", {})
    code_files = files_dict.get("code", [])

    # AST extraction is for CODE only (docs/papers go to semantic extraction).
    paths = []
    for rel_path in code_files:
        full_path = project_root / rel_path
        if full_path.exists():
            paths.append(full_path)

    # Limit for very large projects (unless --deep)
    max_files = len(paths) if deep else min(len(paths), 200)
    if len(paths) > max_files:
        console.print(
            f"[yellow]⚠ Large project ({len(paths)} files) — "
            f"extracting {max_files} most relevant. Use --deep for all.[/yellow]"
        )
        paths = paths[:max_files]

    if not paths:
        console.print("[yellow]⚠ No files found to extract[/yellow]")
        return {}

    # Run extraction with progress indicator
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task(
            f"Extracting {len(paths)} files (AST analysis)...", total=None
        )
        result = extract(paths)
        progress.update(task, completed=True)

    # Show extraction results
    nodes = result.get("nodes", [])
    edges = result.get("edges", [])
    _show_extraction_panel(nodes, edges, console)

    return result


# Semantic extraction tuning.
_SEM_CHUNK_SIZE = 12          # files per LLM call
_SEM_MAX_FILES = 60          # cap (non-deep) to bound cost
_SEM_MAX_CHUNKS = 6          # cap (non-deep) concurrent LLM calls
_SEM_MAX_BYTES_PER_FILE = 8000  # truncate large files in the prompt

# Agent-driven path: each chunk becomes one parallel `task` subagent. We want a
# healthy fan-out, but the subagents fire concurrently and share the API rate
# limit — too many at once → HTTP 429. So the subagent count is HARD-CAPPED
# (always, deep included) and the per-chunk size grows to cover all files within
# that cap. _SEM_AGENT_MIN_CHUNK keeps small projects from over-splitting.
_SEM_AGENT_MIN_CHUNK = 4       # min files per subagent (avoid tiny chunks)
_SEM_AGENT_MAX_SUBAGENTS = 6   # hard cap on concurrent subagents (rate-limit safe)

# Canonical onboarding docs, most-important first. Plain (non-deep) /init orders
# its document targets by this priority so the high-signal files (README,
# CHANGELOG, …) always lead and are never dropped by the file cap. Matched
# case-insensitively against the file's stem, then anywhere in its path.
_DOC_PRIORITY: tuple[str, ...] = (
    "readme",
    "changelog", "history", "news", "releases",
    "contributing",
    "architecture", "design",
    "agents", "claude", "nova",
    "roadmap", "todo",
    "adr", "decision",
    "security", "code_of_conduct", "governance",
)


def _doc_priority_rank(path: str) -> int:
    """Rank a document path by :data:`_DOC_PRIORITY` (lower = more important).

    Matches the file stem first (so ``README.md`` beats ``docs/x/readme-notes``),
    then falls back to a substring match anywhere in the path. Unmatched docs
    sort last (kept, just after the canonical ones).
    """
    from pathlib import PurePosixPath

    p = path.replace("\\", "/").lower()
    stem = PurePosixPath(p).stem
    for rank, key in enumerate(_DOC_PRIORITY):
        if stem == key or stem.startswith(key):
            return rank
    for rank, key in enumerate(_DOC_PRIORITY):
        if key in p:
            return rank + len(_DOC_PRIORITY)  # weaker (substring) match
    return 2 * len(_DOC_PRIORITY)


def _prioritize_docs(paths: list[str]) -> list[str]:
    """Order document paths canonical-first (stable within the same rank)."""
    return sorted(paths, key=lambda p: (_doc_priority_rank(p), p.lower()))


def _build_chunk_listing(project_root: Path, paths: list[Path]) -> str:
    """Render a chunk of files (path + bounded contents) for the LLM prompt."""
    parts: list[str] = []
    for p in paths:
        try:
            rel = p.relative_to(project_root).as_posix()
        except ValueError:
            rel = p.name
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            continue
        if len(text) > _SEM_MAX_BYTES_PER_FILE:
            text = text[:_SEM_MAX_BYTES_PER_FILE] + "\n…(truncated)…"
        parts.append(f"### FILE: {rel}\n```\n{text}\n```")
    return "\n\n".join(parts)


def _parse_extraction_json(text: str) -> dict[str, Any] | None:
    """Parse a graph-fragment JSON written by a subagent — defensively.

    Weak models mangle the fragment in predictable ways; this recovers all of
    them so a malformed write doesn't lose the whole chunk:
      • markdown code fences (```json … ```)
      • the whole JSON wrapped in surrounding quotes ('…' or "…")
      • double-encoded JSON (a JSON *string* whose value is the JSON object)
      • trailing "Extra data" after the object (decode just the first value)
      • leading/trailing prose around the object
      • a Python-repr dict (single quotes) — via ast.literal_eval

    Returns the dict, or None if nothing parseable is found.
    """
    import ast
    import json
    import re

    s = (text or "").strip()
    if not s:
        return None
    # 1) strip code fences
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\n?", "", s)
        s = re.sub(r"\n?```$", "", s).strip()
    # 2) direct / double-encoded JSON (model sometimes json.dumps() the string)
    probe = s
    for _ in range(2):
        try:
            v = json.loads(probe)
        except Exception:  # noqa: BLE001
            break
        if isinstance(v, dict):
            return v
        if isinstance(v, str):  # double-encoded → decode the inner string again
            probe = v.strip()
            continue
        break
    # 3) strip a single layer of surrounding quotes the model may have added
    if len(s) >= 2 and s[0] in "'\"" and s[-1] == s[0] and s[1:-1].lstrip().startswith("{"):
        s = s[1:-1].strip()
    # 4) decode the first JSON object, ignoring any trailing "Extra data"
    start = s.find("{")
    if start == -1:
        return None
    try:
        obj, _ = json.JSONDecoder().raw_decode(s[start:])
        if isinstance(obj, dict):
            return obj
    except Exception:  # noqa: BLE001
        pass
    # 5) last resort: greedy braces, JSON then Python-repr (single quotes)
    m = re.search(r"\{.*\}", s[start:], re.S)
    if m:
        frag = m.group(0)
        try:
            return json.loads(frag)
        except Exception:  # noqa: BLE001
            pass
        try:
            v = ast.literal_eval(frag)
            return v if isinstance(v, dict) else None
        except Exception:  # noqa: BLE001
            return None
    return None


async def semantic_extract_project(
    project_root: Path,
    detection: dict[str, Any],
    console: Console | None = None,
    deep: bool = False,
) -> dict[str, Any]:
    """LLM semantic extraction over docs/papers (+ code when ``deep``).

    Captures the relationships AST cannot — document concepts, call/data/
    architecture edges, cross-file links — using graphify's extraction schema.
    Runs chunks concurrently and is bounded by ``_SEM_MAX_*`` unless ``deep``.

    Returns ``{nodes, edges, hyperedges, input_tokens, output_tokens}`` (empty
    on any failure — the caller proceeds with the AST result alone).
    """
    import asyncio

    empty = {"nodes": [], "edges": [], "hyperedges": [], "input_tokens": 0, "output_tokens": 0}
    if console is None:
        console = _make_console()
    try:
        from langchain_core.messages import HumanMessage

        from novacode_cli.config.model_create import create_model
        from novacode_cli.prompts import render_template
    except Exception:  # noqa: BLE001
        return empty

    files_dict = detection.get("files", {})
    # Canonical-first ordering (README, CHANGELOG, …) so the high-signal docs lead.
    docs = _prioritize_docs(
        list(files_dict.get("document", [])) + list(files_dict.get("paper", []))
    )
    targets = docs + (list(files_dict.get("code", [])) if deep else [])
    paths = [project_root / p for p in targets if (project_root / p).exists()]
    if not paths:
        return empty

    if not deep and len(paths) > _SEM_MAX_FILES:
        paths = paths[:_SEM_MAX_FILES]

    chunks = [paths[i : i + _SEM_CHUNK_SIZE] for i in range(0, len(paths), _SEM_CHUNK_SIZE)]
    if not deep and len(chunks) > _SEM_MAX_CHUNKS:
        chunks = chunks[:_SEM_MAX_CHUNKS]

    try:
        model = create_model()
    except Exception as exc:  # noqa: BLE001
        console.print(f"[yellow]⚠ Semantic extraction skipped (no model: {exc})[/yellow]")
        return empty

    console.print(
        f"  [dim]Semantic extraction: {len(paths)} file(s) → {len(chunks)} LLM chunk(s)…[/dim]"
    )

    async def _do_chunk(chunk: list[Path]) -> dict[str, Any] | None:
        listing = _build_chunk_listing(project_root, chunk)
        if not listing.strip():
            return None
        prompt = render_template("init_semantic_extract.jinja", files_block=listing)
        try:
            resp = await model.ainvoke([HumanMessage(content=prompt)])
            text = resp.content if isinstance(resp.content, str) else str(resp.content)
            return _parse_extraction_json(text)
        except Exception:  # noqa: BLE001
            return None

    results = await asyncio.gather(
        *[_do_chunk(c) for c in chunks], return_exceptions=True
    )

    nodes: list[dict] = []
    edges: list[dict] = []
    hyperedges: list[dict] = []
    for r in results:
        if isinstance(r, dict):
            nodes.extend(r.get("nodes") or [])
            edges.extend(r.get("edges") or [])
            hyperedges.extend(r.get("hyperedges") or [])

    seen: set = set()
    deduped: list[dict] = []
    for n in nodes:
        nid = n.get("id")
        if nid and nid not in seen:
            seen.add(nid)
            deduped.append(n)

    console.print(
        f"  [cyan]Semantic:[/cyan] {len(deduped)} nodes, {len(edges)} edges, "
        f"{len(hyperedges)} hyperedges"
    )
    return {
        "nodes": deduped,
        "edges": edges,
        "hyperedges": hyperedges,
        "input_tokens": 0,
        "output_tokens": 0,
    }


def _read_and_merge_fragments(
    frag_dir: Path, console: Console | None = None
) -> dict[str, Any]:
    """Read every `chunk_*.json` graph fragment the agent wrote, dedup, merge."""
    out = {"nodes": [], "edges": [], "hyperedges": [], "input_tokens": 0, "output_tokens": 0}
    if not frag_dir.exists():
        return out
    nodes: list[dict] = []
    edges: list[dict] = []
    hyper: list[dict] = []
    for f in sorted(frag_dir.glob("chunk_*.json")):
        try:
            data = _parse_extraction_json(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            data = None
        if isinstance(data, dict):
            nodes.extend(data.get("nodes") or [])
            edges.extend(data.get("edges") or [])
            hyper.extend(data.get("hyperedges") or [])
    seen: set = set()
    deduped: list[dict] = []
    for n in nodes:
        nid = n.get("id")
        if nid and nid not in seen:
            seen.add(nid)
            deduped.append(n)
    if console is not None:
        console.print(
            f"  [cyan]Semantic:[/cyan] {len(deduped)} nodes, {len(edges)} edges "
            f"from agent fragments"
        )
    out["nodes"], out["edges"], out["hyperedges"] = deduped, edges, hyper
    return out


async def semantic_extract_via_agent(
    project_root: Path,
    detection: dict[str, Any],
    execute_fn,
    console: Console | None = None,
    deep: bool = False,
) -> dict[str, Any]:
    """Semantic extraction driven by the **Nova agent** (tools + subagents).

    Instead of a stateless model call, this dispatches the work through the agent
    (``execute_fn(prompt)``): the agent reads the chunked files (and may follow
    imports / fetch paper URLs), extracts graph fragments, and writes each to
    ``.nova/graph_fragments/chunk_N.json``. We then read + merge those fragments.

    Returns ``{nodes, edges, hyperedges, ...}`` (empty on failure → AST-only).
    """
    import asyncio
    empty = {"nodes": [], "edges": [], "hyperedges": [], "input_tokens": 0, "output_tokens": 0}
    if console is None:
        console = _make_console()
    if execute_fn is None:
        return empty
    try:
        from novacode_cli.prompts import render_template
    except Exception:  # noqa: BLE001
        return empty

    files_dict = detection.get("files", {})
    # Docs/papers first, ordered canonical-first (README, CHANGELOG, …) so the
    # high-signal onboarding files always lead. --deep additionally feeds the
    # code through the semantic pass; without it, plain /init focuses on the docs.
    docs = _prioritize_docs(
        list(files_dict.get("document", [])) + list(files_dict.get("paper", []))
    )
    targets = docs + (list(files_dict.get("code", [])) if deep else [])

    # graphify may return absolute paths; the agent's filesystem backend rejects
    # absolute (esp. Windows) paths and wants workspace-relative ones. Normalize
    # every target to a relative POSIX path (forward slashes) before listing it
    # in the prompt — the agent then reads it via the virtual filesystem.
    norm: list[str] = []
    for p in targets:
        path = Path(p)
        if not path.is_absolute():
            path = project_root / path
        if not path.exists():
            continue
        try:
            rel = path.resolve().relative_to(project_root.resolve())
        except ValueError:
            continue  # outside the workspace — skip (backend can't reach it)
        norm.append(rel.as_posix())
    targets = norm
    if not targets:
        return empty
    if not deep and len(targets) > _SEM_MAX_FILES:
        targets = targets[:_SEM_MAX_FILES]

    # Bound concurrent subagents: derive a chunk size so the number of chunks
    # (= subagents fired in parallel) never exceeds _SEM_AGENT_MAX_SUBAGENTS,
    # even in deep mode. Keeps fan-out healthy without tripping the API rate
    # limit (429). MIN_CHUNK stops small projects from over-splitting.
    import math

    chunk_size = max(
        _SEM_AGENT_MIN_CHUNK,
        math.ceil(len(targets) / _SEM_AGENT_MAX_SUBAGENTS),
    )
    chunks = [
        targets[i : i + chunk_size] for i in range(0, len(targets), chunk_size)
    ]

    # Fresh fragment dir (clear stale fragments from a prior run).
    frag_dir = project_root / ".nova" / "graph_fragments"
    try:
        if frag_dir.exists():
            for f in frag_dir.glob("chunk_*.json"):
                f.unlink()
        frag_dir.mkdir(parents=True, exist_ok=True)
    except Exception:  # noqa: BLE001
        pass

    chunk_specs = [
        {"n": i + 1, "files": list(c), "out": f".nova/graph_fragments/chunk_{i + 1}.json"}
        for i, c in enumerate(chunks)
    ]
    prompt = render_template(
        "init_semantic_orchestrate.jinja", chunks=chunk_specs, total=len(chunk_specs)
    )
    console.print(
        f"  [dim]Semantic extraction via the agent: {len(targets)} file(s) → "
        f"{len(chunk_specs)} task(s)…[/dim]"
    )
    try:
        await execute_fn(prompt)
    except Exception as exc:  # noqa: BLE001
        console.print(f"[yellow]⚠ Agent semantic extraction failed ({exc})[/yellow]")
        return empty

    return await asyncio.to_thread(_read_and_merge_fragments, frag_dir, console)


def normalize_source_paths(extraction: dict[str, Any]) -> dict[str, Any]:
    """Rewrite Windows backslash paths in ``source_file`` fields to forward slashes.

    graphify emits OS-native paths on Windows (e.g. ``novacode_cli\\ui\\x.py``).
    Those leak into NOVA.md prose, the graph JSON, and ``query_project_graph``
    output — and the ``\\u``/``\\t`` escape sequences make a later ``edit_file``
    match fail ("String not found"), which sends the authoring agent into a retry
    loop. Forward slashes (which the prompts already mandate) avoid all of that.

    Only path fields are touched: node ``id``s are already slash-free, so edge
    references stay valid; node ``label``s are left alone (their backslashes are
    code content like ``\\n``, not paths). Mutates and returns ``extraction``.
    """
    def _fix(v: Any) -> Any:
        return v.replace("\\", "/") if isinstance(v, str) else v

    for n in extraction.get("nodes") or []:
        if isinstance(n, dict) and isinstance(n.get("source_file"), str):
            n["source_file"] = _fix(n["source_file"])
    for e in extraction.get("edges") or []:
        if not isinstance(e, dict):
            continue
        if isinstance(e.get("source_file"), str):
            e["source_file"] = _fix(e["source_file"])
        sf = e.get("source_files")
        if isinstance(sf, list):
            e["source_files"] = [_fix(x) for x in sf]
    return extraction


def merge_ast_semantic(ast: dict[str, Any], semantic: dict[str, Any]) -> dict[str, Any]:
    """Merge the AST and semantic extraction results into one extraction dict.

    Nodes dedup by id (AST wins on conflict), edges dedup by
    (source, target, relation), hyperedges concatenated.
    """
    # Coerce LLM-authored semantic edge weights to numbers BEFORE merge, so the
    # extraction cache (saved right after this) is clean and malformed weights
    # never reach the graph. build_project_graph re-sanitizes as a catch-all.
    from novacode_cli.init.graph import sanitize_graph_extraction

    semantic = sanitize_graph_extraction(semantic)

    # base=semantic, new=ast → on an id/edge conflict the AST (authoritative for
    # code structure) wins, since merge_extractions lets `new` override `base`.
    merged = merge_extractions(semantic, ast)
    merged["hyperedges"] = (ast.get("hyperedges") or []) + (
        semantic.get("hyperedges") or []
    )
    return sanitize_graph_extraction(merged)


def extract_project_incremental(
    project_root: Path,
    detection: dict[str, Any],
    cached_extraction: dict[str, Any] | None = None,
    console: Console | None = None,
) -> dict[str, Any]:
    """Extract entities incrementally, only processing changed files.

    Checks the semantic cache for unchanged files and only re-extracts
    files that have been modified since the last extraction.

    Args:
        project_root: Path to the project root directory.
        detection: Incremental detection result.
        cached_extraction: Previously cached extraction result to merge with.
        console: Rich console for output.

    Returns:
        Merged extraction result with cached + new nodes/edges.
    """
    if console is None:
        console = _make_console()

    try:
        from graphify.extract import extract
        from graphify.cache import check_semantic_cache, load_cached, save_cached
    except ImportError:
        console.print(
            "[yellow]graphify not installed — install with: "
            "pip install novacode-cli[graphify][/yellow]"
        )
        return {}

    # new_files is a dict of file-type categories (e.g. {"code": [...], "document": [...]})
    # Flatten all file paths across categories
    new_files_raw = detection.get("new_files", {})
    new_paths = []
    if isinstance(new_files_raw, dict):
        for file_list in new_files_raw.values():
            if isinstance(file_list, list):
                new_paths.extend(file_list)
    elif isinstance(new_files_raw, list):
        new_paths = new_files_raw

    paths = []
    for rel_path in new_paths:
        full_path = project_root / rel_path
        if full_path.exists():
            paths.append(full_path)

    if not paths:
        console.print("[green]✓ No files need re-extraction[/green]")
        return cached_extraction or {}

    # Extract only changed/new files
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task(
            f"Re-extracting {len(paths)} changed files...", total=None
        )
        new_result = extract(paths)
        progress.update(task, completed=True)

    # Merge with cached extraction
    if cached_extraction:
        merged = merge_extractions(cached_extraction, new_result)
    else:
        merged = new_result

    # Show results
    nodes = merged.get("nodes", [])
    edges = merged.get("edges", [])
    _show_extraction_panel(nodes, edges, console, incremental=True)

    return merged


def merge_extractions(
    base: dict[str, Any], new: dict[str, Any]
) -> dict[str, Any]:
    """Merge two extraction results, deduplicating nodes and edges.

    New nodes/edges override existing ones with the same ID. This
    allows incremental updates to replace stale data.

    Args:
        base: Base extraction result (e.g., cached).
        new: New extraction result to merge in.

    Returns:
        Merged extraction result.
    """
    # Deduplicate nodes by ID
    existing_nodes = {n["id"]: n for n in base.get("nodes", [])}
    for node in new.get("nodes", []):
        existing_nodes[node["id"]] = node

    # Deduplicate edges by (source, target, relation) tuple
    existing_edges = {}
    for edge in base.get("edges", []):
        key = (edge["source"], edge["target"], edge.get("relation", ""))
        existing_edges[key] = edge
    for edge in new.get("edges", []):
        key = (edge["source"], edge["target"], edge.get("relation", ""))
        existing_edges[key] = edge

    return {
        "nodes": list(existing_nodes.values()),
        "edges": list(existing_edges.values()),
        "input_tokens": base.get("input_tokens", 0) + new.get("input_tokens", 0),
        "output_tokens": base.get("output_tokens", 0) + new.get("output_tokens", 0),
    }


def save_extraction_cache(
    project_root: Path, extraction: dict[str, Any]
) -> None:
    """Save extraction result to cache for incremental updates.

    Args:
        project_root: Path to the project root directory.
        extraction: Extraction result to cache.
    """
    cache_path = project_root / ".nova" / "extraction_cache.json"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(extraction, indent=2, default=str), encoding="utf-8")


def load_extraction_cache(project_root: Path) -> dict[str, Any] | None:
    """Load cached extraction result for incremental updates.

    Args:
        project_root: Path to the project root directory.

    Returns:
        Cached extraction result, or None if no cache exists.
    """
    cache_path = project_root / ".nova" / "extraction_cache.json"
    if cache_path.exists():
        try:
            return json.loads(cache_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
    return None


def _show_extraction_panel(
    nodes: list[dict], edges: list[dict], console: Console, *, incremental: bool = False
) -> None:
    """Show a Rich panel with extraction results.

    Args:
        nodes: List of extracted nodes.
        edges: List of extracted edges.
        console: Rich console for output.
        incremental: Whether this was an incremental extraction.
    """
    # Count node types
    node_types: dict[str, int] = {}
    for node in nodes:
        ft = node.get("file_type", "unknown")
        node_types[ft] = node_types.get(ft, 0) + 1

    type_lines = []
    for ft, count in sorted(node_types.items()):
        type_lines.append(f"  {ft}: {count} nodes")

    label = "Incremental Extraction" if incremental else "Extraction"
    content = "\n".join([
        f"[cyan]Nodes:[/cyan] {len(nodes)}",
        f"[cyan]Edges:[/cyan] {len(edges)}",
        "",
        "[dim]Node types:[/dim]",
        *type_lines,
    ])

    panel = Panel(
        content,
        title=f"[bold {COLORS['primary']}]🔬 {label}[/bold {COLORS['primary']}]",
        border_style=COLORS["primary"],
        padding=(1, 2),
    )
    console.print(panel)
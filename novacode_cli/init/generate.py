"""Output generation for /init pipeline.

Generates NOVA.md and AGENTS.md from extraction and analysis results.
Uses Jinja templates for consistent formatting and character limits.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel

from novacode_cli.config.config import COLORS
from novacode_cli.prompts import render_template


def _make_console() -> Console:
    """Create a Console that handles Unicode on Windows.

    On Windows, the default console encoding (cp1252) cannot represent
    characters like emojis and special symbols that Rich renders in panel
    titles. Wrapping stdout with UTF-8 avoids UnicodeEncodeError.
    """
    from novacode_cli.config.config import console as _global_console
    return _global_console

# Character limits for generated files
NOVA_MD_MAX_CHARS = 10_000
AGENTS_MD_MAX_CHARS = 5_000


def generate_nova_md(
    project_root: Path,
    detection: dict[str, Any],
    extraction: dict[str, Any],
    analysis: dict[str, Any],
    communities: dict[int, list[str]],
    console: Console | None = None,
) -> str:
    """Generate NOVA.md content from extraction and analysis results.

    Uses the init_generate.jinja template to produce a structured
    NOVA.md file that tells a coding agent everything it needs to
    work effectively in the project.

    Args:
        project_root: Path to the project root directory.
        detection: Detection result from detect_project().
        extraction: Extraction result from extract_project().
        analysis: Analysis result from analyze_project_graph().
        communities: Community assignments from cluster_project_graph().
        console: Rich console for output.

    Returns:
        Generated NOVA.md content as a string.
    """
    if console is None:
        console = _make_console()

    # Build template context from extraction data
    context = _build_nova_md_context(project_root, detection, extraction, analysis, communities)

    # Render template
    content = render_template("init_generate.jinja", **context)

    # Trim if over character limit
    if len(content) > NOVA_MD_MAX_CHARS:
        content = _trim_to_limit(content, NOVA_MD_MAX_CHARS)
        console.print(
            f"[yellow]⚠ NOVA.md trimmed to {NOVA_MD_MAX_CHARS:,} characters[/yellow]"
        )

    return content


def _strip_doc_fence(text: str) -> str:
    """Drop a code fence wrapping the WHOLE document, if the model added one."""
    s = text.strip()
    if not s.startswith("```"):
        return text
    lines = s.split("\n")
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines)


def _build_facts_brief(context: dict[str, Any]) -> str:
    """Flatten the graphify-derived NOVA.md context into a ground-truth brief.

    This is the verified data the LLM must write from (and not contradict).
    """
    out: list[str] = []
    out.append(f"PROJECT: {context.get('project_name')}")
    if context.get("project_description"):
        out.append(f"DESCRIPTION: {context['project_description']}")
    out.append(
        f"SCALE: {context.get('total_files', 0)} files, "
        f"{context.get('total_words', 0)} words; "
        f"{context.get('community_count', 0)} module communities"
    )

    def _section(title: str, items, fmt) -> None:
        items = items or []
        if not items:
            return
        out.append(f"{title}:")
        for it in items:
            out.append(f"  - {fmt(it)}")

    _section("COMMANDS", context.get("commands"),
             lambda c: f"{c.get('task')}: {c.get('command')}")
    _section("ARCHITECTURE INSIGHTS", context.get("architecture"),
             lambda a: f"{a.get('insight')} — {a.get('detail')}")
    _section(
        "CENTRAL HUBS (god nodes)", context.get("god_nodes"),
        lambda g: f"{g.get('label') or g.get('id')} "
        f"({g.get('edges') or g.get('degree') or 0} connections)"
        + (f" — {g.get('source_file')}" if g.get("source_file") else ""),
    )
    _section(
        "CROSS-MODULE CONNECTIONS", context.get("surprising_connections"),
        lambda s: f"{(s.get('source_files') or [s.get('source')])[0]} <-> {s.get('target')}",
    )
    _section("KEY FILES", context.get("key_files"),
             lambda f: f"{f.get('path')}: {f.get('purpose')}")
    _section("CONVENTIONS", context.get("conventions"),
             lambda c: f"{c.get('rule')} — {c.get('detail')}")
    _section("GUARDRAILS", context.get("guardrails"),
             lambda g: f"{g.get('rule')} — {g.get('reason')}")
    _section(
        "SUGGESTED QUESTIONS", context.get("suggested_questions"),
        lambda q: q.get("question") if isinstance(q, dict) else q,
    )
    return "\n".join(out)


def build_nova_md_author_prompt(
    project_root: Path,
    detection: dict[str, Any],
    extraction: dict[str, Any],
    analysis: dict[str, Any],
    communities: dict[int, list[str]],
    nova_md_rel_path: str = ".nova/NOVA.md",
) -> str:
    """Build the prompt that has the Nova *agent* author NOVA.md.

    Unlike :func:`generate_nova_md_llm` (a single stateless model call), this is
    run through the agent so it can use tools (`query_project_graph`, `read_file`)
    and write the file itself — richer and grounded in the live graph.
    """
    context = _build_nova_md_context(
        project_root, detection, extraction, analysis, communities
    )
    facts = _build_facts_brief(context)
    return render_template(
        "init_nova_md_author.jinja",
        facts=facts,
        nova_md_path=nova_md_rel_path,
        max_chars=NOVA_MD_MAX_CHARS,
    )


async def generate_nova_md_llm(
    project_root: Path,
    detection: dict[str, Any],
    extraction: dict[str, Any],
    analysis: dict[str, Any],
    communities: dict[int, list[str]],
    console: Console | None = None,
) -> str | None:
    """Author a narrative NOVA.md with the LLM, grounded in graphify facts.

    Hybrid generation: graphify computes the graph + facts (communities, god
    nodes, connections, commands, conventions…), then the model writes a rich,
    readable NOVA.md constrained to those facts.

    Returns the generated markdown, or ``None`` if the model is unavailable or
    the call fails / looks invalid — the caller then falls back to the
    deterministic template (:func:`generate_nova_md`).
    """
    if console is None:
        console = _make_console()
    try:
        from langchain_core.messages import HumanMessage

        from novacode_cli.config.model_create import create_model
    except Exception:  # noqa: BLE001
        return None

    context = _build_nova_md_context(
        project_root, detection, extraction, analysis, communities
    )
    facts = _build_facts_brief(context)
    prompt = render_template(
        "init_nova_md_llm.jinja",
        facts=facts,
        max_chars=NOVA_MD_MAX_CHARS,
        **context,
    )

    try:
        console.print(
            "[dim]Authoring NOVA.md with the model (grounded in the graph)…[/dim]"
        )
        model = create_model()
        resp = await model.ainvoke([HumanMessage(content=prompt)])
        content = resp.content if isinstance(resp.content, str) else str(resp.content)
        content = _strip_doc_fence(content).strip()
    except Exception as exc:  # noqa: BLE001
        console.print(
            f"[yellow]⚠ LLM NOVA.md authoring failed ({exc}); using template.[/yellow]"
        )
        return None

    # Sanity: a real document is substantial and looks like markdown.
    if len(content) < 200 or not content.lstrip().startswith("#"):
        return None
    if len(content) > NOVA_MD_MAX_CHARS:
        content = _trim_to_limit(content, NOVA_MD_MAX_CHARS)
    return content


def generate_agents_md(
    project_root: Path,
    detection: dict[str, Any],
    extraction: dict[str, Any],
    analysis: dict[str, Any],
    communities: dict[int, list[str]],
    console: Console | None = None,
) -> str:
    """Generate AGENTS.md content from extraction and analysis results.

    Uses the init_agents_md.jinja template to produce a structured
    AGENTS.md file with project conventions and architecture notes.

    Args:
        project_root: Path to the project root directory.
        detection: Detection result from detect_project().
        extraction: Extraction result from extract_project().
        analysis: Analysis result from analyze_project_graph().
        communities: Community assignments from cluster_project_graph().
        console: Rich console for output.

    Returns:
        Generated AGENTS.md content as a string.
    """
    if console is None:
        console = _make_console()

    # Build template context
    context = _build_agents_md_context(project_root, detection, extraction, analysis, communities)

    # Render template
    content = render_template("init_agents_md.jinja", **context)

    # Trim if over character limit
    if len(content) > AGENTS_MD_MAX_CHARS:
        content = _trim_to_limit(content, AGENTS_MD_MAX_CHARS)
        console.print(
            f"[yellow]⚠ AGENTS.md trimmed to {AGENTS_MD_MAX_CHARS:,} characters[/yellow]"
        )

    return content


def _build_nova_md_context(
    project_root: Path,
    detection: dict[str, Any],
    extraction: dict[str, Any],
    analysis: dict[str, Any],
    communities: dict[int, list[str]],
) -> dict[str, Any]:
    """Build template context for NOVA.md generation.

    Args:
        project_root: Path to the project root.
        detection: Detection result.
        extraction: Extraction result.
        analysis: Analysis result.
        communities: Community assignments.

    Returns:
        Dict of template variables.
    """
    # Extract project identity
    project_name = project_root.name
    project_description = _infer_project_description(detection, extraction)

    # Extract commands from detection
    commands = _extract_commands(project_root)

    # Extract architecture from communities
    architecture = _extract_architecture(extraction, analysis, communities)

    # Extract conventions from extraction
    conventions = _extract_conventions(extraction, project_root)

    # Extract key files from god nodes
    key_files = _extract_key_files(extraction, analysis)

    # Extract guardrails
    guardrails = _extract_guardrails(detection, project_root)

    return {
        "project_name": project_name,
        "project_description": project_description,
        "total_files": detection.get("total_files", 0),
        "total_words": detection.get("total_words", 0),
        "commands": commands,
        "architecture": architecture,
        "conventions": conventions,
        "guardrails": guardrails,
        "key_files": key_files,
        "community_count": len(communities),
        "god_nodes": analysis.get("god_nodes", [])[:5],
        "surprising_connections": analysis.get("surprising_connections", [])[:3],
        "suggested_questions": analysis.get("suggested_questions", [])[:3],
    }


def _build_agents_md_context(
    project_root: Path,
    detection: dict[str, Any],
    extraction: dict[str, Any],
    analysis: dict[str, Any],
    communities: dict[int, list[str]],
) -> dict[str, Any]:
    """Build template context for AGENTS.md generation.

    Args:
        project_root: Path to the project root.
        detection: Detection result.
        extraction: Extraction result.
        analysis: Analysis result.
        communities: Community assignments.

    Returns:
        Dict of template variables.
    """
    project_name = project_root.name

    # Extract conventions
    conventions = _extract_conventions(extraction, project_root)

    # Extract architecture from communities
    architecture = _extract_architecture(extraction, analysis, communities)

    # Extract build/test commands
    commands = _extract_commands(project_root)

    # Extract key directories from communities
    key_directories = _extract_key_directories(extraction, communities)

    # Extract guardrails
    guardrails = _extract_guardrails(detection, project_root)

    return {
        "project_name": project_name,
        "conventions": conventions,
        "architecture": architecture,
        "commands": commands,
        "key_directories": key_directories,
        "guardrails": guardrails,
        "community_count": len(communities),
        "god_nodes": analysis.get("god_nodes", [])[:5],
    }


def _infer_project_description(
    detection: dict[str, Any], extraction: dict[str, Any]
) -> str:
    """Infer a one-line project description from extraction data.

    Args:
        detection: Detection result.
        extraction: Extraction result.

    Returns:
        One-line project description string.
    """
    # Try to find a description from node labels
    nodes = extraction.get("nodes", [])
    for node in nodes:
        label = node.get("label", "")
        source = node.get("source_file", "")
        # Look for main entry points
        if "main" in label.lower() or "app" in label.lower():
            return f"Project with entry point: {label}"

    # Fallback to file type summary
    files = detection.get("files", {})
    code_count = len(files.get("code", []))
    doc_count = len(files.get("document", []))
    return f"Project with {code_count} code files and {doc_count} documents"


def _extract_commands(project_root: Path) -> list[dict[str, str]]:
    """Extract runnable commands from project config files.

    Looks for Makefile, pyproject.toml, package.json, etc.

    Args:
        project_root: Path to the project root.

    Returns:
        List of dicts with 'task' and 'command' keys.
    """
    commands: list[dict[str, str]] = []

    # Check Makefile
    makefile = project_root / "Makefile"
    if makefile.exists():
        try:
            content = makefile.read_text(encoding="utf-8")
            for line in content.splitlines():
                if line and not line.startswith("#") and ":" in line:
                    target = line.split(":")[0].strip()
                    if target and not target.startswith("."):
                        commands.append({
                            "task": target.capitalize(),
                            "command": f"make {target}",
                        })
        except OSError:
            pass

    # Check pyproject.toml for scripts
    pyproject = project_root / "pyproject.toml"
    if pyproject.exists():
        try:
            content = pyproject.read_text(encoding="utf-8")
            if "[project.scripts]" in content:
                # Simple extraction — look for script entries
                in_scripts = False
                for line in content.splitlines():
                    if "[project.scripts]" in line:
                        in_scripts = True
                        continue
                    if in_scripts and line.startswith("["):
                        break
                    if in_scripts and "=" in line:
                        name = line.split("=")[0].strip()
                        commands.append({
                            "task": f"Run {name}",
                            "command": name,
                        })
        except OSError:
            pass

    # Check package.json for scripts
    package_json = project_root / "package.json"
    if package_json.exists():
        try:
            import json
            data = json.loads(package_json.read_text(encoding="utf-8"))
            scripts = data.get("scripts", {})
            for name, cmd in scripts.items():
                commands.append({
                    "task": name.capitalize(),
                    "command": f"npm run {name}",
                })
        except (OSError, json.JSONDecodeError):
            pass

    return commands[:10]  # Limit to 10 commands


def _extract_architecture(
    extraction: dict[str, Any],
    analysis: dict[str, Any],
    communities: dict[int, list[str]],
) -> list[dict[str, str]]:
    """Extract architecture insights from communities and god nodes.

    Args:
        extraction: Extraction result.
        analysis: Analysis result.
        communities: Community assignments.

    Returns:
        List of dicts with 'insight' and 'detail' keys.
    """
    architecture: list[dict[str, str]] = []

    # Add community-based insights
    community_labels = analysis.get("community_labels", {})
    for cid in sorted(communities.keys()):
        nodes = communities[cid]
        label = community_labels.get(cid, f"Community {cid}")
        n_nodes = len(nodes)
        if n_nodes >= 3:
            architecture.append({
                "insight": f"{label} module",
                "detail": f"{n_nodes} interconnected components",
            })

    # Add god node insights
    for gn in analysis.get("god_nodes", [])[:3]:
        architecture.append({
            "insight": f"{gn.get('label', gn.get('id', '?'))} is a central hub",
            "detail": f"{gn.get('edges', gn.get('degree', 0))} connections — changes here affect many modules",
        })

    return architecture[:8]  # Limit to 8 insights


def _extract_conventions(
    extraction: dict[str, Any], project_root: Path
) -> list[dict[str, str]]:
    """Extract code conventions from extraction data and config files.

    Args:
        extraction: Extraction result.
        project_root: Path to the project root.

    Returns:
        List of dicts with 'rule' and 'detail' keys.
    """
    conventions: list[dict[str, str]] = []

    # Check for linter/formatter configs
    ruff_toml = project_root / "ruff.toml"
    pyproject = project_root / "pyproject.toml"

    if ruff_toml.exists():
        conventions.append({
            "rule": "Lint with ruff",
            "detail": "ruff.toml configuration found",
        })

    if pyproject.exists():
        try:
            content = pyproject.read_text(encoding="utf-8")
            if "[tool.ruff]" in content:
                conventions.append({
                    "rule": "Lint with ruff",
                    "detail": "Configured in pyproject.toml [tool.ruff]",
                })
            if "[tool.ruff.lint.pydocstyle]" in content:
                conventions.append({
                    "rule": "Use Google-style docstrings",
                    "detail": "Configured in pyproject.toml",
                })
        except OSError:
            pass

    # Check for type checking config
    pyrightconfig = project_root / "pyrightconfig.json"
    if pyrightconfig.exists():
        conventions.append({
            "rule": "Type-check with pyright",
            "detail": "pyrightconfig.json found",
        })

    # Infer from node types
    nodes = extraction.get("nodes", [])
    has_async = any("async" in n.get("label", "").lower() for n in nodes)
    if has_async:
        conventions.append({
            "rule": "Use async patterns",
            "detail": "Async functions detected in codebase",
        })

    return conventions[:8]


def _extract_key_files(
    extraction: dict[str, Any], analysis: dict[str, Any]
) -> list[dict[str, str]]:
    """Extract key files from god nodes and entry points.

    Args:
        extraction: Extraction result.
        analysis: Analysis result.

    Returns:
        List of dicts with 'path' and 'purpose' keys.
    """
    key_files: list[dict[str, str]] = []

    # Use god nodes as key files
    seen_sources: set[str] = set()
    for gn in analysis.get("god_nodes", [])[:8]:
        source = gn.get("source_file", "")
        if source and source not in seen_sources:
            seen_sources.add(source)
            label = gn.get("label", gn.get("id", "?"))
            key_files.append({
                "path": source,
                "purpose": f"Central hub: {label}",
            })

    # Add entry points from nodes
    for node in extraction.get("nodes", []):
        label = node.get("label", "").lower()
        source = node.get("source_file", "")
        if source and source not in seen_sources:
            if any(kw in label for kw in ["main", "cli", "app", "entry"]):
                seen_sources.add(source)
                key_files.append({
                    "path": source,
                    "purpose": f"Entry point: {node.get('label', '')}",
                })

    return key_files[:8]


def _extract_key_directories(
    extraction: dict[str, Any], communities: dict[int, list[str]]
) -> list[dict[str, str]]:
    """Extract key directories from community structure.

    Args:
        extraction: Extraction result.
        communities: Community assignments.

    Returns:
        List of dicts with 'directory' and 'purpose' keys.
    """
    directories: list[dict[str, str]] = []
    seen_dirs: set[str] = set()

    # Extract directory names from node source files
    for node in extraction.get("nodes", []):
        source = node.get("source_file", "")
        if source and "/" in source:
            parts = source.rsplit("/", 1)
            if len(parts) == 2:
                dir_name = parts[0]
                if dir_name not in seen_dirs and not dir_name.startswith("."):
                    seen_dirs.add(dir_name)
                    directories.append({
                        "directory": dir_name,
                        "purpose": f"Contains {parts[1]}",
                    })

    return directories[:10]


def _extract_guardrails(
    detection: dict[str, Any], project_root: Path
) -> list[dict[str, str]]:
    """Extract guardrails from project structure.

    Args:
        detection: Detection result.
        project_root: Path to the project root.

    Returns:
        List of dicts with 'rule' and 'reason' keys.
    """
    guardrails: list[dict[str, str]] = []

    # Check for common auto-generated directories
    auto_gen_dirs = ["migrations", "generated", "dist", "build", "__pycache__"]
    for d in auto_gen_dirs:
        if (project_root / d).exists():
            guardrails.append({
                "rule": f"NEVER modify {d}/",
                "reason": "Auto-generated directory",
            })

    # Check for sensitive files
    sensitive_files = [".env", ".env.local", "credentials.json", "secrets.json"]
    for f in sensitive_files:
        if (project_root / f).exists():
            guardrails.append({
                "rule": f"NEVER commit {f}",
                "reason": "Contains secrets",
            })

    # Check skipped sensitive files from detection
    for f in detection.get("skipped_sensitive", []):
        guardrails.append({
            "rule": f"NEVER modify {f}",
            "reason": "Sensitive file",
        })

    return guardrails[:6]


def _trim_to_limit(content: str, limit: int) -> str:
    """Trim content to fit within a character limit.

    Removes sections from the end of Key Files, then Conventions,
    then Architecture until the content fits within the limit.

    Args:
        content: The content to trim.
        limit: Maximum character count.

    Returns:
        Trimmed content.
    """
    if len(content) <= limit:
        return content

    # Remove sections from least important to most important
    section_order = ["## Key Files", "## Conventions", "## Architecture"]
    for section in section_order:
        if len(content) <= limit:
            break
        # Find and remove the section
        idx = content.find(section)
        if idx != -1:
            # Find the next section
            next_section_idx = len(content)
            for next_marker in ["## ", "\n# "]:
                ns = content.find(next_marker, idx + len(section))
                if ns != -1 and ns < next_section_idx:
                    next_section_idx = ns
            content = content[:idx] + content[next_section_idx:]

    # Final truncation if still too long
    if len(content) > limit:
        content = content[: limit - 3] + "..."

    return content
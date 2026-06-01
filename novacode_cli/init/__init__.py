"""Graphify-powered project initialization for Nova Code CLI.

This module provides a multi-step pipeline for exploring and documenting
codebases, inspired by the graphify package. The pipeline:

1. **Detect** — scan project files, count words, classify file types
2. **Extract** — AST extraction for code files, semantic extraction via subagents
3. **Build & Cluster** — build a knowledge graph, detect communities
4. **Analyze** — find god nodes, surprising connections, suggested questions
5. **Generate** — produce NOVA.md, AGENTS.md, project graph JSON, HTML visualization

When graphify is not installed, falls back to the prompt-based exploration
approach using the init_exploration.jinja template.
"""

from novacode_cli.init.detect import detect_project, detect_project_incremental
from novacode_cli.init.extract import extract_project
from novacode_cli.init.generate import generate_agents_md, generate_nova_md

# Lazy imports — graph module depends on networkx (optional)
def build_project_graph(*args, **kwargs):
    from novacode_cli.init.graph import build_project_graph as _fn
    return _fn(*args, **kwargs)


def cluster_project_graph(*args, **kwargs):
    from novacode_cli.init.graph import cluster_project_graph as _fn
    return _fn(*args, **kwargs)


def analyze_project_graph(*args, **kwargs):
    from novacode_cli.init.graph import analyze_project_graph as _fn
    return _fn(*args, **kwargs)


def export_project_graph(*args, **kwargs):
    from novacode_cli.init.graph import export_project_graph as _fn
    return _fn(*args, **kwargs)


__all__ = [
    "detect_project",
    "detect_project_incremental",
    "extract_project",
    "build_project_graph",
    "cluster_project_graph",
    "analyze_project_graph",
    "export_project_graph",
    "generate_nova_md",
    "generate_agents_md",
]
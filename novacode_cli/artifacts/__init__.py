"""Artifacts: turn session outputs into live, shareable web pages.

- ``registry``: the in-memory, session-scoped artifact store (+ change observers).
- ``server``: a lightweight local HTTP server that renders artifacts (sandboxed).
- tools live in ``novacode_cli.tools.artifact_tools``.
"""

from novacode_cli.artifacts.registry import Artifact, get_registry

__all__ = ["Artifact", "get_registry"]

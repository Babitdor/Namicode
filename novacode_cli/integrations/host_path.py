"""Host-path → virtual-path normalization for filesystem tools.

## Why this exists

Nova's agents are told to address files with **virtual paths starting with
``/``** rooted at the project (``/novacode_cli/x`` → ``<project>/novacode_cli/x``).
But the model constantly *sees* real host paths — in the IDE's open-file context,
in ``@file`` mentions, in prior tool output, in error traces — and so it very
often passes a real **host absolute path** to a file tool, e.g.::

    read_file("B:/Summer Project 2026/Nova-Code/nova-code-cli/novacode_cli/prompts/plan_agent.jinja")

deepagents' ``validate_path`` (called by ``FilesystemMiddleware`` before the
backend) then rejects it hard::

    Error: Windows absolute paths are not supported: B:/… Please use virtual
    paths starting with / (e.g., /workspace/file.txt)

Telling the agent "don't do that" in the prompt isn't enough — it slips up
constantly. :func:`host_path_to_virtual` rewrites any host absolute path **that
points inside the project** into the equivalent ``/``-rooted virtual path, so the
mistake becomes harmless. It is applied by monkey-patching ``validate_path`` (see
:func:`novacode_cli.utils.backend_patches.apply_filesystem_host_path_patch`).

Paths that are already virtual, relative, or outside the project are returned
unchanged, so genuinely-invalid paths still surface deepagents' helpful error.
Handles Windows (``B:\\…`` / ``B:/…``, case-insensitive) and POSIX
(``/home/user/project/…``) host paths.
"""

from __future__ import annotations

import os
import posixpath


def host_path_to_virtual(path: str, workspace_root: str) -> str:
    """Rewrite a host absolute path inside ``workspace_root`` to a virtual path.

    Args:
        path: The path the agent passed to a file tool.
        workspace_root: The project root on the host (e.g.
            ``B:\\Summer Project 2026\\Nova-Code\\nova-code-cli``).

    Returns:
        A ``/``-rooted virtual path when ``path`` is at or under the project
        root; otherwise ``path`` unchanged (already virtual/relative, or outside
        the project).
    """
    if not isinstance(path, str) or not path or not workspace_root:
        return path

    root = str(workspace_root).replace("\\", "/").rstrip("/")
    if not root:
        return path

    norm = path.replace("\\", "/")
    # Host filesystems are case-insensitive on Windows; compare accordingly.
    ci = os.name == "nt"
    a, b = (norm.lower(), root.lower()) if ci else (norm, root)

    if a == b:
        return "/"
    if a.startswith(b + "/"):
        # Strip the project-root prefix; keep the original casing of the rest.
        rel = norm[len(root):].lstrip("/")
        return "/" + posixpath.normpath(rel) if rel else "/"
    return path


__all__ = ["host_path_to_virtual"]

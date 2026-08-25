"""Parallel Nova sessions: worktree-isolated child processes and their wire protocol.

A spawned session runs as a separate OS process bound to its own git worktree, so
the process-global state Nova relies on (``config.settings`` frozen at import from
``Path.cwd()``, the ``validate_path`` monkeypatch, the shell job registry, the
session allow-list) stays correctly scoped to exactly one workspace.

The child streams :mod:`novacode_cli.ui_events` dataclasses to its parent as JSONL;
the parent decodes them back into the *same* dataclasses and feeds them to the
existing TUI renderer, so no rendering code is duplicated.
"""

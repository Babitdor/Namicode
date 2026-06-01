"""Textual TUI front-end for NovaCode (experimental, behind ``--tui``).

Phase 1 of the migration: a chat screen that consumes the UI-agnostic
:func:`novacode_cli.agent_stream.run_agent_stream` and renders its events.
The legacy ``rich`` + ``prompt_toolkit`` REPL remains the default.
"""

from novacode_cli.tui.app import run_tui

__all__ = ["run_tui"]

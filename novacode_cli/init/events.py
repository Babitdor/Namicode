"""UI-agnostic progress events for the ``/init`` pipeline.

The graphify pipeline (:func:`novacode_cli.commands.init_handler._run_graphify_pipeline`)
is pure logic: it reports progress by calling an injected ``emit`` callback with
these dataclasses and returns an :class:`InitResult`. Renderers decide how to
present them — the Textual TUI drives its native step tracker, while the legacy
REPL renders rich panels — so the pipeline itself never imports ``rich`` or
touches a console.

Events flow one-way (pipeline -> renderer). The final outcome is the returned
:class:`InitResult`, not an event, so callers can branch on it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Union


@dataclass
class StepStarted:
    """A top-level pipeline step began. ``index`` is 1-based out of ``total``."""

    index: int
    total: int
    label: str


@dataclass
class StepDetail:
    """A sub-progress line attached to the step currently in flight."""

    text: str


@dataclass
class Notice:
    """A standalone message not tied to a step.

    ``level`` is one of ``"info" | "warn" | "error" | "success" | "dim"``.
    """

    text: str
    level: str = "info"


# Anything the pipeline may hand to ``emit``.
InitEvent = Union[StepStarted, StepDetail, Notice]
EmitFn = Callable[[InitEvent], None]


@dataclass
class Artifact:
    """A file produced by the pipeline, for the final summary."""

    name: str
    path: Path
    size: int
    ok: bool = True


@dataclass
class InitResult:
    """Outcome of an ``/init`` run, returned to the caller for final rendering.

    ``ok`` is True only when NOVA.md was generated. ``fell_back`` marks the case
    where graphify produced nothing usable (no entities) and the caller may want
    to drop to prompt-based exploration. ``artifacts`` lists the files written.
    """

    ok: bool
    nova_dir: Path
    nova_md_path: Path
    artifacts: list[Artifact] = field(default_factory=list)
    message: str = ""
    fell_back: bool = False


def null_emit(event: InitEvent) -> None:
    """No-op emitter for callers that don't want to render progress."""

"""UI-agnostic progress events for the ``/init`` pipeline.

The /init pipeline is a single-step agent exploration that writes NOVA.md.
Progress is minimal — just a final result. Renderers decide how to present it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass
class Notice:
    """A standalone message not tied to a step.

    ``level`` is one of ``"info" | "warn" | "error" | "success" | "dim"``.
    """

    text: str
    level: str = "info"


# Anything the pipeline may hand to ``emit``.
InitEvent = Notice
EmitFn = Callable[[InitEvent], None]


@dataclass
class InitResult:
    """Outcome of an ``/init`` run, returned to the caller for final rendering.

    ``ok`` is True only when NOVA.md was generated.
    """

    ok: bool
    nova_md_path: Path
    message: str = ""


def null_emit(event: InitEvent) -> None:
    """No-op emitter for callers that don't want to render progress."""

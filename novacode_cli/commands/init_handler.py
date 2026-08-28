"""Handler for the /init command to create project documentation.

The /init command explores the codebase using the Nova agent's tools
(read_file, glob, grep, code_search) and writes a NOVA.md file at the
project root — a concise guide that tells an AI agent everything it needs
to work effectively in the project.

The pipeline is simple:
1. Check project root exists
2. Send an exploration prompt to the agent
3. The agent explores and writes NOVA.md
4. Report the result

Presentation is **decoupled** from the pipeline. :func:`_run_exploration`
is pure logic: it sends the prompt and returns an :class:`InitResult`.
It never imports ``rich`` or touches a console. The Textual TUI streams
the prompt through its native chat; the legacy REPL renders via
:mod:`novacode_cli.commands.init_renderer`.
"""

from __future__ import annotations
from pathlib import Path
from typing import TYPE_CHECKING
from novacode_cli.init.events import InitResult
if TYPE_CHECKING:
    from novacode_cli.ui.ui_elements import TokenTracker

from novacode_cli.commands import CommandContext, CommandRegistry


class InitRenderer:
    """Protocol that a renderer must satisfy to work with InitOrchestrator.

    Each entry point (legacy REPL, Textual TUI) provides its own implementation
    so the orchestrator stays renderer-agnostic.
    """

    def emit(self, event) -> None:
        """Forward a pipeline progress event (Notice)."""
        ...

    def result(self, result) -> None:
        """Render the final pipeline outcome."""
        ...

    async def run_exploration(
        self,
        project_root: Path,
        nova_md_path: Path,
        agent,
        session_state,
        assistant_id: str,
        token_tracker: TokenTracker,
    ) -> None:
        """Run the agent exploration that writes NOVA.md."""
        ...


class InitFlags:
    """Parsed flags for the /init command."""

    def __init__(self, args: str | None = None) -> None:
        """Parse init command flags from argument string.

        Args:
            args: Raw argument string from the command.
        """
        self.help = False
        if args:
            parts = args.lower().split()
            self.help = "--help" in parts or "-h" in parts

    def as_list(self) -> list[str]:
        """The active flags as CLI tokens, for display."""
        return []


class InitOrchestrator:
    """Encapsulates the shared /init orchestration for both REPL and TUI paths.

    Owns the project-root check, exploration dispatch, and result routing
    so both entry points share one authoritative sequence.
    """

    def __init__(
        self,
        *,
        project_root: Path,
        nova_md_path: Path,
        flags: InitFlags,
        renderer: InitRenderer,
        agent,
        session_state,
        assistant_id: str,
        token_tracker: TokenTracker,
    ) -> None:
        self._project_root = project_root
        self._nova_md_path = nova_md_path
        self._flags = flags
        self._renderer = renderer
        self._agent = agent
        self._session_state = session_state
        self._assistant_id = assistant_id
        self._token_tracker = token_tracker

    async def run(self) -> InitResult:
        """Run the /init exploration."""
        prev_plan = getattr(self._session_state, "plan_mode_enabled", False)
        if hasattr(self._session_state, "plan_mode_enabled"):
            self._session_state.plan_mode_enabled = False

        try:
            await self._renderer.run_exploration(
                project_root=self._project_root,
                nova_md_path=self._nova_md_path,
                agent=self._agent,
                session_state=self._session_state,
                assistant_id=self._assistant_id,
                token_tracker=self._token_tracker,
            )

            result = InitResult(
                ok=self._nova_md_path.exists(),
                nova_md_path=self._nova_md_path,
            )
            self._renderer.result(result)
            return result
        finally:
            if hasattr(self._session_state, "plan_mode_enabled"):
                self._session_state.plan_mode_enabled = prev_plan


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def register_commands(registry: "CommandRegistry") -> None:
    """Register /init command (passthrough to TUI-native handler)."""

    async def _handle(ctx: CommandContext) -> bool:
        # The TUI handles /init natively via _run_init. This passthrough
        # is a no-op for the REPL path (which no longer exists).
        return True

    registry.register("init", _handle)

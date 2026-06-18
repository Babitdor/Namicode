"""``/voice`` command — control local voice I/O (STT + VAD + TTS).

Subcommands::

    /voice                 show status (availability + current settings)
    /voice status
    /voice on | off        enable/disable voice (persisted default)
    /voice mode ptt|listen push-to-talk vs always-listening
    /voice test            synthesize + play a phrase to verify the pipeline

Live capture is driven from the TUI keybindings (ctrl+g push-to-talk,
ctrl+shift+v toggle listening); this command manages the persisted preferences
and a quick end-to-end test. Persisted to ``~/.nova/Nova.config.json``.
"""

from __future__ import annotations

import shlex
from typing import TYPE_CHECKING

from novacode_cli import audio

if TYPE_CHECKING:
    from rich.console import Console

    from novacode_cli.config.nova_config import NovaConfig
    from novacode_cli.states.Session import SessionState

_MODE_ALIASES = {"ptt": "push_to_talk", "push_to_talk": "push_to_talk", "listen": "listen"}
_MIN_MODE_TOKENS = 2


async def handle_voice_command(  # noqa: PLR0911 — command dispatcher, one return per subcommand
    cmd_args: str | None,
    session_state: SessionState,  # noqa: ARG001 — uniform command-handler signature
    console: Console,
) -> bool:
    """Dispatch a ``/voice`` subcommand. Returns ``True`` (command handled)."""
    from novacode_cli.config.nova_config import NovaConfig

    config = NovaConfig()
    try:
        tokens = shlex.split((cmd_args or "").strip())
    except ValueError as exc:
        console.print(f"[red]Could not parse arguments: {exc}[/red]")
        return True

    action = tokens[0].lower() if tokens else "status"

    if action == "status":
        _print_status(config, console)
        return True

    if action in ("on", "off"):
        cfg = config.set_voice_config(enabled=action == "on")
        state = "[green]on[/green]" if cfg["enabled"] else "[dim]off[/dim]"
        console.print(f"  Voice is now {state}.")
        if action == "on" and not audio.is_voice_available():
            console.print(f"  [yellow]{audio.install_hint()}[/yellow]")
        return True

    if action == "mode":
        if len(tokens) < _MIN_MODE_TOKENS or tokens[1].lower() not in _MODE_ALIASES:
            console.print("[yellow]Usage:[/yellow] /voice mode ptt|listen")
            return True
        mode = _MODE_ALIASES[tokens[1].lower()]
        config.set_voice_config(mode=mode)
        console.print(f"  [green]✓[/green] Voice mode set to [cyan]{mode}[/cyan].")
        return True

    if action == "test":
        await _run_test(config, console)
        return True

    console.print(f"[yellow]Unknown /voice subcommand:[/yellow] {action}")
    return True


def _print_status(config: NovaConfig, console: Console) -> None:
    """Render availability + current voice settings."""
    cfg = config.get_voice_config()
    if audio.is_voice_available():
        console.print("  [green]●[/green] Local voice stack installed.")
    else:
        console.print(f"  [yellow]○ {audio.install_hint()}[/yellow]")
    console.print(
        f"  enabled=[cyan]{cfg['enabled']}[/cyan] mode=[cyan]{cfg['mode']}[/cyan] "
        f"speak_responses=[cyan]{cfg['speak_responses']}[/cyan]"
    )
    console.print(f"  stt={cfg['stt_model']}@{cfg['stt_device']} tts_voice={cfg['tts_voice']}")
    console.print(
        "  [dim]In the TUI: ctrl+g = push-to-talk, ctrl+shift+v = toggle listening.[/dim]"
    )


async def _run_test(config: NovaConfig, console: Console) -> None:
    """Speak a test phrase to verify synthesis + playback end-to-end."""
    if not audio.is_voice_available():
        console.print(f"  [yellow]{audio.install_hint()}[/yellow]")
        return
    from novacode_cli.audio.pipeline import VoicePipeline

    cfg = config.get_voice_config()
    console.print("  [dim]Synthesizing test phrase…[/dim]")
    try:
        pipeline = VoicePipeline(tts_voice=cfg["tts_voice"])
        await pipeline.speak("Nova voice output is working.")
        console.print("  [green]✓[/green] Heard it? Voice output is working.")
    except Exception as exc:  # noqa: BLE001 — surface any audio/device error to the user
        console.print(f"  [red]Voice test failed:[/red] {exc}")

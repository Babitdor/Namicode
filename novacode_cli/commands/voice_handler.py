"""``/voice`` command — control local voice I/O (STT + VAD + TTS).

Subcommands::

    /voice                       show status (availability + current settings)
    /voice status
    /voice on | off              enable/disable voice (persisted default)
    /voice mode ptt|listen       push-to-talk vs always-listening
    /voice speak on|off          enable/disable spoken replies
    /voice test                  synthesize + play a phrase to verify the pipeline
    /voice settings              show all voice settings with available providers
    /voice settings stt          choose STT provider (faster-whisper / deepgram)
    /voice settings tts          choose TTS provider (piper / elevenlabs / none)
    /voice settings stt deepgram  configure Deepgram API key + model
    /voice settings tts elevenlabs  configure ElevenLabs API key + voice ID

Live capture is driven from the TUI keybindings (ctrl+g push-to-talk,
ctrl+l toggle listening); this command manages the persisted preferences
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
_ON_OFF = {"on": True, "off": False}
_MIN_MODE_TOKENS = 2
_SETTINGS_PROVIDER_TOKENS = 3


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

    if action == "speak":
        if len(tokens) < _MIN_MODE_TOKENS or tokens[1].lower() not in _ON_OFF:
            console.print("[yellow]Usage:[/yellow] /voice speak on|off")
            return True
        enabled = _ON_OFF[tokens[1].lower()]
        config.set_voice_config(speak_responses=enabled)
        state = "[green]on[/green]" if enabled else "[dim]off[/dim]"
        console.print(f"  Spoken responses are now {state}.")
        return True

    if action == "settings":
        if len(tokens) < _SETTINGS_PROVIDER_TOKENS:
            _print_settings(config, console)
            return True
        await _handle_settings(tokens[1:], config, console)
        return True

    if action == "test":
        await _run_test(config, console)
        return True

    console.print(f"[yellow]Unknown /voice subcommand:[/yellow] {action}")
    return True


# ── Status ────────────────────────────────────────────────────────────────────


def _print_status(config: NovaConfig, console: Console) -> None:
    """Render availability + current voice settings."""
    cfg = config.get_voice_config()
    if audio.is_voice_available():
        console.print("  [green]●[/green] Local voice stack installed.")
    else:
        console.print(f"  [yellow]○ {audio.install_hint()}[/yellow]")
    console.print(
        f"  enabled=[cyan]{cfg['enabled']}[/cyan] mode=[cyan]{cfg['mode']}[/cyan] "
        f"speak=[cyan]{cfg['speak_responses']}[/cyan]"
    )
    console.print(
        f"  stt=[cyan]{cfg['stt_provider']}[/cyan] tts=[cyan]{cfg['tts_provider']}[/cyan]"
    )
    console.print("  [dim]In the TUI: ctrl+g = push-to-talk, ctrl+l = toggle listening.[/dim]")


# ── Settings ──────────────────────────────────────────────────────────────────


def _print_settings(config: NovaConfig, console: Console) -> None:
    """Show detailed settings with available providers."""
    cfg = config.get_voice_config()
    from novacode_cli.audio.providers import STT_PROVIDERS, TTS_PROVIDERS

    console.print("[bold]Voice settings[/bold]")
    console.print(f"  enabled:      [cyan]{cfg['enabled']}[/cyan]")
    console.print(f"  mode:         [cyan]{cfg['mode']}[/cyan]")
    console.print(f"  speak:        [cyan]{cfg['speak_responses']}[/cyan]")
    console.print(f"  STT provider: [cyan]{cfg['stt_provider']}[/cyan]")
    _show_provider_options(STT_PROVIDERS, cfg["stt_provider"], config, console)
    console.print(f"  TTS provider: [cyan]{cfg['tts_provider']}[/cyan]")
    _show_provider_options(TTS_PROVIDERS, cfg["tts_provider"], config, console)


def _show_provider_options(
    providers: dict,
    current: str,
    config: NovaConfig,
    console: Console,
) -> None:
    """List available providers for STT or TTS, flagged with current + key status."""
    for key, meta in sorted(providers.items()):
        marker = "●" if key == current else "○"
        name = meta.get("name", key)
        desc = meta.get("description", "")
        if meta.get("requires_key"):
            pcfg = config.get_voice_provider_config(key)
            key_ok = bool(pcfg.get("api_key"))
            key_status = " [green](key set)[/green]" if key_ok else " [yellow](no key)[/yellow]"
        else:
            key_status = ""
        console.print(f"    {marker} {name} — {desc}{key_status}")


async def _handle_settings(  # noqa: PLR0912 — settings sub-dispatch
    tokens: list[str],
    config: NovaConfig,
    console: Console,
) -> None:
    """Handle /voice settings <stt|tts> [provider] [--key x] [--model y] etc."""
    from novacode_cli.audio.providers import STT_PROVIDERS, TTS_PROVIDERS

    action = tokens[0].lower()
    rest = tokens[1:] if len(tokens) > 1 else []

    if action == "stt":
        if not rest:
            console.print(
                f"  Current STT: [cyan]{config.get_voice_config()['stt_provider']}[/cyan]"
            )
            console.print("  Available: " + ", ".join(STT_PROVIDERS))
            return
        provider = rest[0].lower()
        if provider not in STT_PROVIDERS:
            console.print(f"  [red]Unknown STT provider:[/red] {provider}")
            return
        meta = STT_PROVIDERS[provider]
        if len(rest) > 1:
            # Configure — parse --key, --model
            flags = _parse_flags(rest[1:])
            config.set_voice_provider_config(provider, **flags)
            console.print(f"  [green]✓[/green] {meta['name']} configured.")
        else:
            # Switch provider
            config.set_voice_config(stt_provider=provider)
            console.print(f"  [green]✓[/green] STT provider set to [cyan]{meta['name']}[/cyan].")
            if meta.get("requires_key"):
                pcfg = config.get_voice_provider_config(provider)
                if not pcfg.get("api_key"):
                    console.print(
                        f"  [yellow]Set key:[/yellow] /voice settings stt {provider} --key <key>"
                    )
    elif action == "tts":
        if not rest:
            console.print(
                f"  Current TTS: [cyan]{config.get_voice_config()['tts_provider']}[/cyan]"
            )
            console.print("  Available: " + ", ".join(TTS_PROVIDERS))
            return
        provider = rest[0].lower()
        if provider not in TTS_PROVIDERS:
            console.print(f"  [red]Unknown TTS provider:[/red] {provider}")
            return
        meta = TTS_PROVIDERS[provider]
        if len(rest) > 1:
            flags = _parse_flags(rest[1:])
            config.set_voice_provider_config(provider, **flags)
            console.print(f"  [green]✓[/green] {meta['name']} configured.")
        else:
            config.set_voice_config(tts_provider=provider)
            console.print(f"  [green]✓[/green] TTS provider set to [cyan]{meta['name']}[/cyan].")
            if meta.get("requires_key"):
                pcfg = config.get_voice_provider_config(provider)
                if not pcfg.get("api_key"):
                    console.print(
                        f"  [yellow]Set key:[/yellow] /voice settings tts {provider} --key <key>"
                    )
    else:
        console.print(f"[yellow]Unknown settings category:[/yellow] {action}. Use stt or tts.")


# ── Test ─────────────────────────────────────────────────────────────────────


async def _run_test(config: NovaConfig, console: Console) -> None:
    """Speak a test phrase to verify synthesis + playback end-to-end."""
    if not audio.is_voice_available():
        console.print(f"  [yellow]{audio.install_hint()}[/yellow]")
        return
    from novacode_cli.audio.pipeline import VoicePipeline

    cfg = config.get_voice_config()
    console.print("  [dim]Synthesizing test phrase…[/dim]")
    try:
        pipeline = VoicePipeline(
            stt_provider=cfg.get("stt_provider", "faster-whisper"),
            tts_provider=cfg.get("tts_provider", "piper"),
            provider_configs=cfg.get("providers", {}),
        )
        await pipeline.speak("Nova voice output is working.")
        console.print("  [green]✓[/green] Heard it? Voice output is working.")
    except Exception as exc:  # noqa: BLE001 — surface any audio/device error to the user
        console.print(f"  [red]Voice test failed:[/red] {exc}")


# ── Helpers ───────────────────────────────────────────────────────────────────


def _parse_flags(tokens: list[str]) -> dict[str, str]:
    """Parse ``--key value`` flag pairs from a token list."""
    flags: dict[str, str] = {}
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok.startswith("--") and i + 1 < len(tokens):
            flags[tok[2:]] = tokens[i + 1]
            i += 2
        else:
            i += 1
    return flags

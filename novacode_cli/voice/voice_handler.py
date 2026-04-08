"""CLI handler for 'nova voice' command.

This module provides the command-line interface for starting voice
sessions with Nova, the coding assistant.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from rich.console import Console

if TYPE_CHECKING:
    import argparse

console = Console()


def setup_voice_parser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    """Add voice subcommand to CLI.

    Args:
        subparsers: Subparsers action from main argument parser.

    Returns:
        Configured voice parser.
    """
    voice_parser = subparsers.add_parser(
        "voice",
        help="Start interactive voice session with Nova",
        description=(
            "Launch a voice conversation with Nova, your cute coding assistant. "
            "Say 'Hey Nova' to activate, then ask questions or plan tasks. "
            "Implementation tasks are delegated to the text agent."
        ),
    )

    voice_parser.add_argument(
        "--model", "-m",
        default="gemini",
        choices=["gemini", "gpt-4o"],
        help="LLM model for voice agent (default: gemini)",
    )

    voice_parser.add_argument(
        "--stt",
        default="deepgram",
        choices=["deepgram", "elevenlabs"],
        help="Speech-to-text provider (default: deepgram)",
    )

    voice_parser.add_argument(
        "--tts",
        default="elevenlabs",
        choices=["elevenlabs", "deepgram", "cartesia"],
        help="Text-to-speech provider (default: elevenlabs)",
    )

    voice_parser.add_argument(
        "--working-dir", "-d",
        type=Path,
        default=None,
        help="Working directory for file operations (default: current directory)",
    )

    voice_parser.add_argument(
        "--no-wake-word",
        action="store_true",
        help="Disable wake word detection (always listen mode)",
    )

    voice_parser.add_argument(
        "--voice",
        default="Rachel",
        help="Voice name for TTS (default: Rachel - ElevenLabs)",
    )

    return voice_parser


def handle_voice_command(args: argparse.Namespace) -> None:
    """Run the voice agent.

    Args:
        args: Parsed command line arguments.
    """
    # Check for required dependencies
    try:
        from vision_agents.core import AgentLauncher, Runner
    except ImportError:
        _msg = (
            "\n❌ Voice dependencies not installed!\n\n"
            "To use voice features, install with:\n"
            "  uv add 'novacode-cli[voice]'\n\n"
            "Or:\n"
            "  pip install novacode-cli[voice]"
        )
        console.print(_msg)
        sys.exit(1)

    # Check for required API keys
    _check_api_keys(args)

    # Set working directory
    working_dir = args.working_dir or Path.cwd()

    console.print("\n🎤 Starting voice session with Nova...")
    console.print(f"   Model: {args.model}")
    console.print(f"   STT: {args.stt}")
    console.print(f"   TTS: {args.tts}")
    console.print(f"   Working directory: {working_dir}")
    console.print("\n💡 Say 'Hey Nova' to activate, then speak your request.")
    console.print("   Press Ctrl+C to exit.\n")

    # Import and run the voice agent
    from vision_agents.core import AgentLauncher, Runner

    from novacode_cli.voice.agent import create_agent, join_call

    runner = Runner(
        AgentLauncher(
            create_agent=lambda: asyncio.run(
                create_agent(
                    model=args.model,
                    stt_provider=args.stt,
                    tts_provider=args.tts,
                    working_dir=working_dir,
                    voice=args.voice,
                    use_wake_word=not args.no_wake_word,
                )
            ),
            join_call=join_call
        )
    )

    try:
        runner.cli()
    except KeyboardInterrupt:
        console.print("\n\n👋 Voice session ended. Goodbye!")
    except (OSError, RuntimeError, ValueError) as e:
        _err_msg = f"\n❌ Error in voice session: {e}"
        console.print(_err_msg)
        sys.exit(1)


def _check_api_keys(args: argparse.Namespace) -> None:
    """Check for required API keys based on selected providers.

    Args:
        args: Parsed command line arguments.
    """
    import os

    missing_keys: list[str] = []

    # Stream API key (required for all voice sessions)
    if not os.getenv("STREAM_API_KEY") or not os.getenv("STREAM_API_SECRET"):
        missing_keys.append("STREAM_API_KEY, STREAM_API_SECRET (from getstream.io)")

    # Model-specific keys
    if args.model == "gemini" and not os.getenv("GOOGLE_API_KEY"):
        missing_keys.append("GOOGLE_API_KEY (from aistudio.google.com)")
    if args.model == "gpt-4o" and not os.getenv("OPENAI_API_KEY"):
        missing_keys.append("OPENAI_API_KEY (from platform.openai.com)")

    # STT/TTS keys
    if args.stt == "deepgram" and not os.getenv("DEEPGRAM_API_KEY"):
        missing_keys.append("DEEPGRAM_API_KEY (from deepgram.com)")
    if args.tts == "elevenlabs" and not os.getenv("ELEVENLABS_API_KEY"):
        missing_keys.append("ELEVENLABS_API_KEY (from elevenlabs.io)")

    if missing_keys:
        console.print("\n❌ Missing required API keys!")
        console.print("\nPlease set the following environment variables:")
        for key in missing_keys:
            console.print(f"  - {key}")
        console.print("\nYou can set them in your .env file or environment.")
        sys.exit(1)

"""Voice agent module for Nova CLI.

This module provides voice-based interaction with Nova, a cute female coding assistant.
The voice agent can help with planning and exploration, then delegate implementation
to the text-based agent.

Usage:
    nova voice                    # Start voice session with defaults
    nova voice --model gpt-4o     # Use GPT-4o as LLM
    nova voice --voice Bella      # Use different TTS voice
"""

from novacode_cli.voice.agent import create_agent, join_call
from novacode_cli.voice.voice_handler import handle_voice_command, setup_voice_parser

__all__ = [
    "create_agent",
    "handle_voice_command",
    "join_call",
    "setup_voice_parser",
]

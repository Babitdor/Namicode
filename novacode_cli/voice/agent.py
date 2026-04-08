"""Voice agent using Vision Agents framework.

This module wraps the Vision Agents framework to provide voice-based
interaction with Nova, a cute female coding assistant.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from dotenv import load_dotenv

if TYPE_CHECKING:
    from vision_agents.core import Agent
    from vision_agents.plugins import LLM, STT, TTS

# Load environment variables
load_dotenv()

# Nova's personality prompt
NOVA_SYSTEM_PROMPT = """You are Nova, a cute and friendly female coding assistant. 😊

Your personality:
- Warm, cheerful, and encouraging
- Uses friendly expressions like "Great question!" and "Let me help you with that!"
- Explains technical concepts in a simple, approachable way
- Patient and supportive when helping users learn
- Occasionally uses emojis in a natural way

Your capabilities:
- You can READ files to understand the codebase
- You can LIST directories to explore project structure
- You can SEARCH for code patterns
- You can help PLAN tasks and break them into steps
- You CANNOT write code or modify files - that's handled by the text agent

When users want to implement something:
1. Help them plan the approach
2. Explore relevant files together
3. Explain what needs to be done
4. Offer to hand off to the text agent for implementation

Wake word: Users say "Hey Nova" to get your attention.

Be concise in your responses - this is a voice conversation, so keep it natural and conversational.
Always be helpful and make coding feel fun and approachable!"""


async def create_agent(
    model: str = "gemini",
    stt_provider: str = "deepgram",
    tts_provider: str = "elevenlabs",
    working_dir: Path | None = None,
    voice: str = "Rachel",
    *,
    use_wake_word: bool = True,
) -> Agent:
    """Create voice agent with specified providers.

    Args:
        model: LLM model to use ('gemini' or 'gpt-4o').
        stt_provider: Speech-to-text provider.
        tts_provider: Text-to-speech provider.
        working_dir: Working directory for file operations.
        voice: Voice name for TTS.
        use_wake_word: Whether to use wake word detection.

    Returns:
        Configured Agent instance.

    Raises:
        ImportError: If vision-agents is not installed.
        ValueError: If required API keys are missing.
    """
    # Import Vision Agents (will fail if not installed)
    _import_err = (
        "vision-agents is not installed. "
        "Install it with: pip install 'novacode-cli[voice]'"
    )
    try:
        from vision_agents.core import Agent, User
        from vision_agents.plugins import getstream
    except ImportError as e:
        raise ImportError(_import_err) from e

    # Get LLM
    llm = _get_llm(model)

    # Register file operation tools
    llm = _register_file_tools(llm, working_dir or Path.cwd())

    # Get STT
    stt = _get_stt(stt_provider, use_wake_word=use_wake_word)

    # Get TTS
    tts = _get_tts(tts_provider, voice=voice)

    # Create agent
    return Agent(
        edge=getstream.Edge(),
        agent_user=User(name="Nova", id="nova-assistant"),
        instructions=NOVA_SYSTEM_PROMPT,
        llm=llm,
        stt=stt,
        tts=tts,
    )


async def join_call(agent: Agent, call_type: str, call_id: str) -> None:
    """Handle incoming call - greet user.

    Args:
        agent: The voice agent instance.
        call_type: Type of call.
        call_id: Call identifier.
    """
    call = await agent.create_call(call_type, call_id)
    async with agent.join(call):
        await agent.simple_response(
            "Hey there! I'm Nova, your coding assistant. 😊 "
            "Say 'Hey Nova' whenever you need me. "
            "What would you like to work on today?"
        )
        await agent.finish()


def _get_llm(model: str) -> LLM:
    """Get LLM provider based on model name.

    Args:
        model: Model name string.

    Returns:
        LLM instance.

    Raises:
        ImportError: If required package is not installed.
        ValueError: If API key is missing.
    """
    _err_import = (
        f"Required package not installed for model '{model}'. "
        f"Install with: pip install 'novacode-cli[voice]'"
    )
    _err_gemini_key = "GOOGLE_API_KEY is required for Gemini model"
    _err_openai_key = "OPENAI_API_KEY is required for GPT-4o model"
    try:
        if model in ["gemini", "gemini-pro", "gemini-2.0-flash"]:
            from vision_agents.plugins import gemini

            if not os.getenv("GOOGLE_API_KEY"):
                raise ValueError(_err_gemini_key)
            return gemini.LLM()

        if model in ["gpt-4o", "openai", "gpt-4"]:
            from vision_agents.plugins import openai

            if not os.getenv("OPENAI_API_KEY"):
                raise ValueError(_err_openai_key)
            return openai.LLM()

        # Default to Gemini for speed
        from vision_agents.plugins import gemini

        return gemini.LLM()
    except ImportError as e:
        raise ImportError(_err_import) from e


def _get_stt(provider: str, *, use_wake_word: bool = True) -> STT:
    """Get speech-to-text provider.

    Args:
        provider: Provider name.
        use_wake_word: Whether to enable wake word detection.

    Returns:
        STT instance.

    Raises:
        ImportError: If required package is not installed.
        ValueError: If API key is missing.
    """
    _err_import = (
        f"Required package not installed for STT '{provider}'. "
        f"Install with: pip install 'novacode-cli[voice]'"
    )
    _err_deepgram_key = "DEEPGRAM_API_KEY is required for Deepgram STT"
    _err_elevenlabs_key = "ELEVENLABS_API_KEY is required for ElevenLabs STT"
    try:
        if provider == "deepgram":
            from vision_agents.plugins import deepgram

            if not os.getenv("DEEPGRAM_API_KEY"):
                raise ValueError(_err_deepgram_key)
            return deepgram.STT(
                eager_turn_detection=True,
                wake_word="Hey Nova" if use_wake_word else None,
            )

        if provider == "elevenlabs":
            from vision_agents.plugins import elevenlabs

            if not os.getenv("ELEVENLABS_API_KEY"):
                raise ValueError(_err_elevenlabs_key)
            return elevenlabs.STT()

        # Default to Deepgram
        from vision_agents.plugins import deepgram

        return deepgram.STT(eager_turn_detection=True)
    except ImportError as e:
        raise ImportError(_err_import) from e


def _get_tts(provider: str, *, voice: str = "Rachel") -> TTS:
    """Get text-to-speech provider.

    Args:
        provider: Provider name.
        voice: Voice name to use.

    Returns:
        TTS instance.

    Raises:
        ImportError: If required package is not installed.
        ValueError: If API key is missing.
    """
    _err_import = (
        f"Required package not installed for TTS '{provider}'. "
        f"Install with: pip install 'novacode-cli[voice]'"
    )
    _err_elevenlabs_key = "ELEVENLABS_API_KEY is required for ElevenLabs TTS"
    _err_deepgram_key = "DEEPGRAM_API_KEY is required for Deepgram TTS"
    _err_cartesia_key = "CARTESIA_API_KEY is required for Cartesia TTS"
    try:
        if provider == "elevenlabs":
            from vision_agents.plugins import elevenlabs

            if not os.getenv("ELEVENLABS_API_KEY"):
                raise ValueError(_err_elevenlabs_key)
            return elevenlabs.TTS(voice=voice)

        if provider == "deepgram":
            from vision_agents.plugins import deepgram

            if not os.getenv("DEEPGRAM_API_KEY"):
                raise ValueError(_err_deepgram_key)
            return deepgram.TTS()

        if provider == "cartesia":
            from vision_agents.plugins import cartesia

            if not os.getenv("CARTESIA_API_KEY"):
                raise ValueError(_err_cartesia_key)
            return cartesia.TTS()

        # Default to ElevenLabs
        from vision_agents.plugins import elevenlabs

        return elevenlabs.TTS(voice=voice)
    except ImportError as e:
        raise ImportError(_err_import) from e


def _register_file_tools(llm: LLM, working_dir: Path) -> LLM:
    """Register file operation tools with the LLM.

    Args:
        llm: LLM instance.
        working_dir: Working directory for file operations.

    Returns:
        LLM with registered tools.
    """
    from novacode_cli.voice.tools import (
        get_project_structure,
        list_directory,
        read_file,
        search_files,
    )

    @llm.register_function(description="Read a file's contents")  # type: ignore[untyped-decorator]
    async def read_file_tool(file_path: str) -> dict[str, Any]:
        """Read file contents."""
        return await read_file(file_path, working_dir)

    @llm.register_function(description="List files in a directory")  # type: ignore[untyped-decorator]
    async def list_directory_tool(directory: str = ".") -> dict[str, Any]:
        """List directory contents."""
        return await list_directory(directory, working_dir)

    @llm.register_function(description="Search for files matching a pattern")  # type: ignore[untyped-decorator]
    async def search_files_tool(pattern: str) -> dict[str, Any]:
        """Search for files."""
        return await search_files(pattern, working_dir)

    @llm.register_function(description="Get the project structure overview")  # type: ignore[untyped-decorator]
    async def get_project_structure_tool() -> dict[str, Any]:
        """Get project structure."""
        return await get_project_structure(working_dir)

    return llm

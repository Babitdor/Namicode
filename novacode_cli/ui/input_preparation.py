"""Input preparation and message content building.

This module handles:
- Parsing file mentions from user input
- Building multimodal content with images
- Preparing messages for the agent
"""

import asyncio
from pathlib import Path

from novacode_cli.config.config import console
from novacode_cli.config.model_create import get_current_model_name
from novacode_cli.errors.handlers import ErrorHandler
from novacode_cli.image_utils import create_multimodal_content
from novacode_cli.input import ImageTracker, parse_file_mentions


async def prepare_input_content(
    user_input: str,
    image_tracker: ImageTracker | None = None,
    *,
    skip_file_mentions: bool = False,
) -> str | list:
    """Prepare input content with file mentions and images.

    Args:
        user_input: The raw user input string
        image_tracker: Optional image tracker for multimodal content
        skip_file_mentions: If True, skip @file mention parsing. Use this
            for programmatic prompts (e.g., skill invocations) that contain
            @ symbols which should not be interpreted as file references.

    Returns:
        Either a string or a multimodal content list
    """
    error_handler = ErrorHandler()

    if skip_file_mentions:
        prompt_text = user_input
        mentioned_files = []
    else:
        prompt_text, mentioned_files = parse_file_mentions(user_input)

    if mentioned_files:
        context_parts = [prompt_text, "\n\n## Referenced Files\n"]
        for file_path in mentioned_files:
            try:
                content = await asyncio.to_thread(file_path.read_text)
                if len(content) > 50000:
                    content = content[:50000] + "\n... (file truncated)"
                context_parts.append(
                    f"\n### {file_path.name}\nPath: `{file_path}`\n```\n{content}\n```"
                )
            except Exception as e:
                recovery = await error_handler.handle(
                    e,
                    context={"file_name": str(file_path), "file_path": str(file_path)},
                )
                error_msg = f"\n### {file_path.name}\n[{recovery.message}]"
                if recovery.suggestion:
                    error_msg += f"\n{recovery.suggestion}"
                context_parts.append(error_msg)
        final_input = "\n".join(context_parts)
    else:
        final_input = prompt_text

    images_to_send = []
    if image_tracker:
        images_to_send = image_tracker.get_images()

    return final_input


def get_agent_display_name(assistant_id: str | None) -> str:
    """Get the display name for an agent.

    Args:
        assistant_id: The assistant ID

    Returns:
        Human-readable display name
    """
    if assistant_id == "nova-agent":
        return "Nova"
    if assistant_id == "ralph":
        return "Ralph"
    return assistant_id or "Agent"


def build_agent_config(
    thread_id: str,
    assistant_id: str | None,
) -> dict:
    """Build the agent configuration dict.

    Args:
        thread_id: The thread ID for this conversation
        assistant_id: Optional assistant ID

    Returns:
        Configuration dict for the agent
    """
    return {
        "configurable": {"thread_id": thread_id},
        "metadata": {
            "thread_id": thread_id,
            **({"assistant_id": assistant_id} if assistant_id else {}),
        },
        "run_name": assistant_id or "nova-agent",
        "tags": ["Nova", assistant_id] if assistant_id else ["Nova"],
    }

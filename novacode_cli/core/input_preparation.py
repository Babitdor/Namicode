"""Input preparation and message content building.

This module handles:
- Building agent config for task execution
- Getting agent display names
- Preparing messages for the agent

Shared between the TUI, headless mode, and server mode.
"""

from __future__ import annotations


from novacode_cli.input_utils import ImageTracker, parse_file_mentions


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
        Prepared content as string or list of content blocks
    """
    if skip_file_mentions:
        cleaned_input = user_input
    else:
        # Parse @file mentions
        cleaned_input, mentioned_files = parse_file_mentions(user_input)

    if image_tracker:
        try:
            images = image_tracker.get_images()
        except Exception:  # noqa: BLE001
            images = []
        if images:
            try:
                from novacode_cli.bootstrap.vision_router import caption_images

                captions = await caption_images(images)
                if captions:
                    return f"{cleaned_input}\n\n[Attached image: {captions}]"
            except Exception:  # noqa: BLE001
                pass
            # Fallback: include image content blocks
            content: list = []
            content.append({"type": "text", "text": cleaned_input})
            for img in images:
                if hasattr(img, 'to_content_block'):
                    content.append(img.to_content_block())
                elif hasattr(img, 'to_message_content'):
                    content.append(img.to_message_content())
            return content

    return cleaned_input


def build_agent_config(
    thread_id: str,
    model: str | None = None,
    **kwargs: object,
) -> dict:
    """Build the standard agent configuration dict.

    Args:
        thread_id: The conversation thread ID
        model: Optional model name override
        **kwargs: Additional config keys

    Returns:
        Configuration dict for the agent
    """
    config: dict = {"configurable": {"thread_id": thread_id}}
    if model:
        config["configurable"]["model"] = model
    config.update(kwargs)
    return config


def get_agent_display_name(agent_name: str | None) -> str:
    """Get a human-readable display name for an agent.

    Args:
        agent_name: The agent's identifier name

    Returns:
        Display name string
    """
    if not agent_name:
        return "Nova"
    return agent_name.replace("-", " ").title()

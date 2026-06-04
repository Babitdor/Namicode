"""Handler for /vision command to describe images using vision models.

This module provides the handle_vision_command function that:
1. Parses @file references to load images
2. Uses vision-capable models to describe image content
3. Returns descriptions for use by the Nova agent
"""

import re
from pathlib import Path
from typing import TYPE_CHECKING

from rich.panel import Panel
from rich.text import Text

from novacode_cli.config.config import COLORS, console
from novacode_cli.config.model_create import (
    create_model,
    get_current_model_name,
    get_vision_model_suggestion,
    model_supports_vision,
)
from novacode_cli.image_utils import ImageData, load_image_from_path

if TYPE_CHECKING:
    from novacode_cli.input import ImageTracker

# Pattern to match @file references
AT_REFERENCE_RE = re.compile(r"@(?P<path>(?:[^\s@]|(?<=\\)\s)+)")


def parse_image_references(args: str | None) -> list[tuple[str, Path | None]]:
    """Parse @file references from command arguments.

    Args:
        args: Command arguments string

    Returns:
        List of tuples (original_match, resolved_path or None if invalid)
    """
    if not args:
        return []

    references = []
    for match in AT_REFERENCE_RE.finditer(args):
        original = match.group(0)  # @path
        path_str = match.group("path")  # path without @

        # Handle escaped spaces
        path_str = path_str.replace("\\ ", " ")

        # Resolve path
        try:
            path = Path(path_str).expanduser().resolve()
            references.append((original, path))
        except (OSError, ValueError):
            references.append((original, None))

    return references


async def handle_vision_command(
    args: str | None,
    image_tracker: "ImageTracker | None",
) -> bool:
    """Handle /vision command to describe images using vision models.

    Usage:
        /vision @path/to/image.png [optional prompt]
        /vision @image1.png @image2.png  (multiple images)

    The command:
    1. Parses @file references to load images
    2. Checks if current model supports vision (suggests alternative if not)
    3. Sends images to vision model for description
    4. Outputs description for use by Nova agent

    Args:
        args: Command arguments containing @file references and optional prompt
        image_tracker: ImageTracker instance for managing images

    Returns:
        True (always handled)
    """
    from langchain_core.messages import HumanMessage

    console.print()

    # Parse @file references
    references = parse_image_references(args)

    if not references:
        console.print(
            Panel(
                "[yellow]No image references found.[/yellow]\n\n"
                "Usage: [cyan]/vision @path/to/image.png[/cyan]\n"
                "       [cyan]/vision @image1.png @image2.png[/cyan]\n\n"
                "Use [cyan]@[/cyan] followed by a file path to reference an image.",
                title="[bold]Vision Command",
                border_style=COLORS["primary"],
            )
        )
        return True

    # Load images
    images: list[ImageData] = []
    failed_loads: list[tuple[str, str]] = []  # (path, error)

    for original, path in references:
        if path is None:
            failed_loads.append((original, "Invalid path"))
            continue

        if not path.exists():
            failed_loads.append((str(path), "File not found"))
            continue

        try:
            image_data = load_image_from_path(path)
            images.append(image_data)
            console.print(f"[green]✓[/green] Loaded: [cyan]{path.name}[/cyan]")
        except (OSError, ValueError, RuntimeError) as e:
            failed_loads.append((str(path), str(e)))

    # Report failures
    if failed_loads:
        console.print()
        console.print("[yellow]Failed to load some images:[/yellow]")
        for path, error in failed_loads:
            console.print(f"  [red]✗[/red] {path}: {error}")

    if not images:
        console.print()
        console.print("[red]No valid images to process.[/red]")
        return True

    # Check current model's vision capability
    current_model = get_current_model_name()
    vision_capable = model_supports_vision(current_model)

    if not vision_capable:
        suggestion = get_vision_model_suggestion(current_model)
        console.print()
        console.print(
            f"[yellow]⚠ Current model '{current_model}' "
            "does not support vision.[/yellow]"
        )
        if suggestion:
            msg = f"[dim]Suggestion: Switch to '{suggestion}' with /model {suggestion}[/dim]"
            console.print(msg)
        console.print()

    # Extract optional prompt (text after @references)
    prompt_text = "Describe this image in detail."
    if args:
        # Remove @references from args to get remaining text
        remaining = args
        for original, _ in references:
            remaining = remaining.replace(original, "", 1)
        remaining = remaining.strip()
        if remaining:
            prompt_text = remaining

    # Create multimodal content
    content_blocks = [{"type": "text", "text": prompt_text}]
    content_blocks.extend(image.to_message_content() for image in images)

    # Get description from vision model
    console.print()
    console.print(f"[dim]Analyzing {len(images)} image(s) with {current_model}...[/dim]")

    try:
        model = create_model()
        message = HumanMessage(content=content_blocks)
        response = await model.ainvoke([message])

        # Extract text from response
        content = response.content
        description = content if isinstance(content, str) else str(content)

        # Display result
        console.print()
        result_header = Text()
        result_header.append("🖼️ ", style="bold")
        result_header.append("Image Description", style=f"bold {COLORS['primary']}")

        console.print(Panel(result_header, border_style=COLORS["primary"]))
        console.print()
        console.print(description)
        console.print()

        # Store in image_tracker for reference
        if image_tracker and hasattr(image_tracker, "add_vision_result"):
            image_tracker.add_vision_result(images, description)

        return True

    except (OSError, ValueError, RuntimeError) as e:
        console.print()
        console.print(f"[red]Error analyzing image: {e}[/red]")
        console.print()
        return True


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

def register_commands(registry) -> None:
    from novacode_cli.commands import CommandContext

    async def _handle(ctx: CommandContext) -> bool:
        return await handle_vision_command(ctx.cmd_args, ctx.image_tracker)

    registry.register("vision", _handle)
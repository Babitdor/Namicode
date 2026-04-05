"""Jinja template loader for Nova_deepagents prompts."""

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader

# Get the directory containing this file
_PROMPTS_DIR = Path(__file__).parent

# Create Jinja environment
_env = Environment(
    loader=FileSystemLoader(_PROMPTS_DIR),
    # Keep whitespace as-is for prompts
    trim_blocks=False,
    lstrip_blocks=False,
    keep_trailing_newline=True,
)


def render_template(template_name: str, **kwargs: Any) -> str:
    """Render a Jinja template from the prompts directory.

    Args:
        template_name: Name of the template file (e.g., "filesystem.jinja")
        **kwargs: Template variables

    Returns:
        Rendered template string
    """
    template = _env.get_template(template_name)
    return template.render(**kwargs)

"""Prompt templates for Nova CLI using Jinja2."""

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

# Template directory
TEMPLATES_DIR = Path(__file__).parent

# Create Jinja environment
_env = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=select_autoescape(default=False),
    trim_blocks=True,
    lstrip_blocks=True,
)


def get_template(name: str) -> Any:
    """Load a Jinja template by name.

    Args:
        name: Template filename (e.g., 'ralph_iteration.jinja')

    Returns:
        Jinja template object
    """
    return _env.get_template(name)


def render_template(name: str, **kwargs: Any) -> str:
    """Render a Jinja template with the given context.

    Args:
        name: Template filename
        **kwargs: Template context variables

    Returns:
        Rendered template string
    """
    template = get_template(name)
    return template.render(**kwargs)

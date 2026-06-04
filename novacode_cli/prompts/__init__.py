"""Prompt templates for Nova CLI using Jinja2."""

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

# Template directory
TEMPLATES_DIR = Path(__file__).parent

# Jinja environment — FileSystemLoader auto-reloads templates when mtime
# changes (auto_reload=True by default), so no manual cache is needed.
_env = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=select_autoescape(default=False),
    trim_blocks=True,
    lstrip_blocks=True,
)


def render_template(name: str, **kwargs: Any) -> str:
    """Render a Jinja template with the given context.

    Args:
        name: Template filename (e.g., 'core_agent_system.jinja')
        **kwargs: Template context variables

    Returns:
        Rendered template string
    """
    template = _env.get_template(name)
    return template.render(**kwargs)

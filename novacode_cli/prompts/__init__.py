"""Prompt templates for Nova CLI using Jinja2."""

import time
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

# Template cache: maps name -> (cached_at, file_mtime, template)
_template_cache: dict[str, tuple[float, float, Any]] = {}
_TEMPLATE_CACHE_TTL = 60.0  # seconds


def get_template(name: str) -> Any:
    """Load a Jinja template by name with caching.

    The cache is invalidated when the template file's mtime changes, so
    edits to .jinja files take effect immediately without restarting.

    Args:
        name: Template filename (e.g., 'core_agent_system.jinja')

    Returns:
        Jinja template object
    """
    current_time = time.time()
    template_path = TEMPLATES_DIR / name

    try:
        current_mtime = template_path.stat().st_mtime
    except OSError:
        current_mtime = 0.0

    if name in _template_cache:
        cached_time, cached_mtime, template = _template_cache[name]
        if (
            current_time - cached_time < _TEMPLATE_CACHE_TTL
            and cached_mtime == current_mtime
        ):
            # Sliding window: reset timer on access
            _template_cache[name] = (current_time, cached_mtime, template)
            return template

    # Load and cache template
    template = _env.get_template(name)
    _template_cache[name] = (current_time, current_mtime, template)
    return template


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

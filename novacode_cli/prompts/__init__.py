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

# Template cache with TTL to avoid re-parsing templates on every request
_template_cache: dict[str, tuple[float, Any]] = {}
_TEMPLATE_CACHE_TTL = 60.0  # seconds


def get_template(name: str) -> Any:
    """Load a Jinja template by name with caching.

    Args:
        name: Template filename (e.g., 'ralph_iteration.jinja')

    Returns:
        Jinja template object
    """
    current_time = time.time()
    
    # Check cache (sliding window: refreshes on access)
    if name in _template_cache:
        cached_time, template = _template_cache[name]
        if current_time - cached_time < _TEMPLATE_CACHE_TTL:
            # Sliding window: reset timer on access to keep cache alive during active use
            _template_cache[name] = (current_time, template)
            return template
    
    # Load and cache template
    template = _env.get_template(name)
    _template_cache[name] = (current_time, template)
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

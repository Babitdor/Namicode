"""Skill creation system prompt.

Loaded from the Jinja template at prompts/skill_creation.jinja.
Use render_skill_creation_prompt() to get the rendered prompt string.
"""

from novacode_cli.prompts import render_template


def render_skill_creation_prompt() -> str:
    """Render the skill creation system prompt from the Jinja template.

    Returns:
        The rendered system prompt string for the Skill-Creation-Agent.
    """
    return render_template("skill_creation.jinja")
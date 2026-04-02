from __future__ import annotations

from namicode_cli.config.config import console
from namicode_cli.prompts import render_template


async def _generate_agent_system_prompt(agent_name: str, description: str) -> str | None:
    """Generate a full system prompt for a custom agent using the configured LLM.

    Args:
        agent_name: Name of the agent
        description: Description of what the agent specializes in

    Returns:
        Generated system prompt, or None if generation failed
    """
    from namicode_cli.config.model_create import create_model

    try:
        model = create_model()

        # Use Jinja template for generation prompt
        generation_prompt = render_template(
            "agent_generation.jinja",
            agent_name=agent_name,
            description=description,
        )

        response = await model.ainvoke(generation_prompt)

        if hasattr(response, "content"):
            content = response.content
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                # Handle list of content blocks
                return "".join(str(c) for c in content)
        return str(response)

    except Exception as e:
        console.print(f"[red]Error generating system prompt: {e}[/red]")
        return None

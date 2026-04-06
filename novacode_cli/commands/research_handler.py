"""Handler for the /research command - agent swarm research.

This module provides the handle_research_command function that orchestrates
multi-agent research swarms for comprehensive research tasks.
"""

from pathlib import Path
from typing import Literal

from novacode_cli.config.config import COLORS, console
from novacode_cli.prompts import render_template


ResearchMode = Literal[
    "academic",      # Academic papers, literature review
    "market",        # Market research, competitive analysis
    "stocks",        # Stock analysis, financial research
    "technical",     # Technical documentation, API research
    "general",       # General-purpose research
]


async def handle_research_command(
    session_state,
    research_query: str | None = None,
    mode: ResearchMode = "general",
    agent_count: int = 3,
    output_dir: Path | None = None,
) -> str | bool:
    """Handle the /research command - run agent swarm research.

    This command orchestrates a multi-agent research swarm:
    1. Planning - Break down research question into sub-questions
    2. Parallel Investigation - Each agent investigates assigned aspect
    3. Cross-Pollination - Agents share findings and adjust focus
    4. Synthesis - Combine all findings into comprehensive report
    5. Quality Assurance - Fact-check and validate conclusions

    Args:
        session_state: Current session state
        research_query: Optional research query (if not provided, will prompt)
        mode: Research mode (academic, market, stocks, technical, general)
        agent_count: Number of agents to spawn (default: 3)
        output_dir: Optional output directory for research report

    Returns:
        True (command always handled) or prompt string for agent
    """
    from novacode_cli.memory.agent_memory import AgentMemoryMiddleware

    # Determine output directory
    if output_dir is None:
        output_dir = Path.cwd() / ".nova" / "research"
    
    # Ensure output directory exists
    output_dir.mkdir(parents=True, exist_ok=True)

    # Mode-specific configurations
    mode_configs = {
        "academic": {
            "description": "Academic literature review and paper analysis",
            "agents": ["literature_reviewer", "methodology_analyst", "citation_tracker"],
            "focus": "peer-reviewed sources, methodology quality, citation networks",
            "output_format": "literature review with bibliography",
        },
        "market": {
            "description": "Market research and competitive analysis",
            "agents": ["market_analyst", "competitor_researcher", "trend_tracker"],
            "focus": "market size, growth trends, competitive landscape",
            "output_format": "market analysis report with data visualizations",
        },
        "stocks": {
            "description": "Stock analysis and financial research",
            "agents": ["financial_analyst", "news_researcher", "technical_analyst"],
            "focus": "financial statements, news sentiment, technical indicators",
            "output_format": "investment research report with recommendations",
        },
        "technical": {
            "description": "Technical documentation and API research",
            "agents": ["doc_researcher", "api_analyst", "implementation_specialist"],
            "focus": "official documentation, API references, implementation guides",
            "output_format": "technical summary with code examples",
        },
        "general": {
            "description": "General-purpose research",
            "agents": ["primary_researcher", "secondary_researcher", "fact_checker"],
            "focus": "comprehensive coverage from multiple angles",
            "output_format": "research report with sources",
        },
    }

    config = mode_configs.get(mode, mode_configs["general"])

    console.print()
    console.print("[bold]Agent Swarm Research[/bold]", style=COLORS["primary"])
    console.print()
    console.print(f"[dim]Mode: {mode} - {config['description']}[/dim]")
    console.print(f"[dim]Agents: {agent_count} specialized agents[/dim]")
    console.print(f"[dim]Output: {output_dir}[/dim]")
    console.print()

    # If no query provided, prompt for it
    if not research_query:
        console.print("[bold]Enter your research query:[/bold]", style=COLORS["primary"])
        console.print("[dim]Example: 'What are the latest advances in quantum computing?'[/dim]")
        console.print("[dim]Press Enter to skip and provide query in chat[/dim]")
        console.print()
        return "research_mode"  # Signal to prompt user in chat

    console.print("[bold]Phase 1: Planning[/bold]", style=COLORS["primary"])
    console.print(f"[dim]  Breaking down research question...[/dim]")
    console.print(f"[dim]  Query: {research_query[:100]}{'...' if len(research_query) > 100 else ''}[/dim]")

    console.print()
    console.print("[bold]Phase 2: Agent Assignment[/bold]", style=COLORS["primary"])
    console.print(f"[dim]  Spawning {agent_count} specialized agents:[/dim]")
    
    # Assign agents based on mode
    selected_agents = config["agents"][:agent_count]
    for i, agent in enumerate(selected_agents, 1):
        console.print(f"[dim]    {i}. {agent.replace('_', ' ').title()}[/dim]")

    console.print()
    console.print("[bold]Phase 3: Parallel Investigation[/bold]", style=COLORS["primary"])
    console.print("[dim]  Each agent will investigate their assigned aspect[/dim]")
    console.print(f"[dim]  Focus: {config['focus']}[/dim]")

    console.print()
    console.print("[bold]Phase 4: Cross-Pollination[/bold]", style=COLORS["primary"])
    console.print("[dim]  Agents will share findings and adjust focus[/dim]")

    console.print()
    console.print("[bold]Phase 5: Synthesis[/bold]", style=COLORS["primary"])
    console.print(f"[dim]  Combining findings into {config['output_format']}[/dim]")

    console.print()
    console.print("[bold]Phase 6: Quality Assurance[/bold]", style=COLORS["primary"])
    console.print("[dim]  Fact-checking and validating conclusions[/dim]")

    console.print()
    console.print("[bold]Research Swarm Prompt Generated[/bold]", style=COLORS["primary"])
    console.print()
    console.print("[dim]The research swarm is ready to begin.[/dim]")
    console.print("[dim]To complete research, the agent will:[/dim]")
    console.print("[dim]  1. Decompose the research question into sub-questions[/dim]")
    console.print("[dim]  2. Assign each sub-question to a specialized agent[/dim]")
    console.print("[dim]  3. Execute parallel investigations[/dim]")
    console.print("[dim]  4. Share findings between agents[/dim]")
    console.print("[dim]  5. Synthesize into comprehensive report[/dim]")
    console.print("[dim]  6. Validate and fact-check conclusions[/dim]")
    console.print()

    # Render the research swarm prompt
    prompt = render_template(
        "research_swarm.jinja",
        research_query=research_query,
        mode=mode,
        mode_description=config["description"],
        agent_count=agent_count,
        agents=selected_agents,
        focus=config["focus"],
        output_format=config["output_format"],
        output_dir=str(output_dir),
    )

    return prompt


def get_research_prompt(
    research_query: str,
    mode: ResearchMode = "general",
    agent_count: int = 3,
    output_dir: Path | None = None,
) -> str:
    """Generate a research swarm prompt without executing.

    Args:
        research_query: The research question to investigate
        mode: Research mode (academic, market, stocks, technical, general)
        agent_count: Number of agents to spawn
        output_dir: Optional output directory for research report

    Returns:
        The research swarm prompt string
    """
    mode_configs = {
        "academic": {
            "description": "Academic literature review and paper analysis",
            "agents": ["literature_reviewer", "methodology_analyst", "citation_tracker"],
            "focus": "peer-reviewed sources, methodology quality, citation networks",
            "output_format": "literature review with bibliography",
        },
        "market": {
            "description": "Market research and competitive analysis",
            "agents": ["market_analyst", "competitor_researcher", "trend_tracker"],
            "focus": "market size, growth trends, competitive landscape",
            "output_format": "market analysis report with data visualizations",
        },
        "stocks": {
            "description": "Stock analysis and financial research",
            "agents": ["financial_analyst", "news_researcher", "technical_analyst"],
            "focus": "financial statements, news sentiment, technical indicators",
            "output_format": "investment research report with recommendations",
        },
        "technical": {
            "description": "Technical documentation and API research",
            "agents": ["doc_researcher", "api_analyst", "implementation_specialist"],
            "focus": "official documentation, API references, implementation guides",
            "output_format": "technical summary with code examples",
        },
        "general": {
            "description": "General-purpose research",
            "agents": ["primary_researcher", "secondary_researcher", "fact_checker"],
            "focus": "comprehensive coverage from multiple angles",
            "output_format": "research report with sources",
        },
    }

    config = mode_configs.get(mode, mode_configs["general"])
    selected_agents = config["agents"][:agent_count]

    if output_dir is None:
        output_dir = Path.cwd() / ".nova" / "research"

    return render_template(
        "research_swarm.jinja",
        research_query=research_query,
        mode=mode,
        mode_description=config["description"],
        agent_count=agent_count,
        agents=selected_agents,
        focus=config["focus"],
        output_format=config["output_format"],
        output_dir=str(output_dir),
    )
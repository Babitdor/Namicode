"""Handler for the /dream command - memory consolidation.

This module provides the handle_dream_command function that runs
a memory consolidation pass to organize and clean up memory files.
"""

from pathlib import Path

from novacode_cli.config.config import COLORS, console
from novacode_cli.prompts import render_template


async def handle_dream_command(
    session_state,
    agent_dir: Path | None = None,
) -> bool:
    """Handle the /dream command - run memory consolidation.

    This command performs a multi-phase memory consolidation pass:
    1. Orient - Review existing memory files
    2. Gather - Collect recent signal from logs/transcripts
    3. Consolidate - Merge updates into topic files
    4. Prune - Clean up the index

    Args:
        session_state: Current session state
        agent_dir: Optional agent directory path (defaults to ~/.nova/)

    Returns:
        True (command always handled)
    """
    from novacode_cli.memory.agent_memory import AgentMemoryMiddleware

    # Determine agent directory
    if agent_dir is None:
        agent_dir = Path.home() / ".nova"

    # Check for memory structures (support both simple and advanced)
    # Simple: agent.md file in agent directory
    # Advanced: memories/ directory with topic files
    agent_md = agent_dir / "agent.md"
    memory_dir = agent_dir / "memories"
    
    has_simple_memory = agent_md.exists()
    has_advanced_memory = memory_dir.exists()
    
    if not has_simple_memory and not has_advanced_memory:
        console.print()
        console.print("[yellow]No memory files found.[/yellow]")
        console.print(f"[dim]Expected: {agent_md} or {memory_dir}[/dim]")
        console.print()
        console.print("[dim]Memory files are created when you use the memory system.[/dim]")
        console.print("[dim]Try asking the agent to remember something first.[/dim]")
        console.print()
        console.print("[dim]Quick start: Ask me to 'save this to memory' or 'remember this for next time'[/dim]")
        console.print()
        return True

    # Determine which memory structure to use
    if has_advanced_memory:
        # Advanced: memories/ directory with topic files
        memory_path = memory_dir
        index_file = memory_dir / "INDEX.md"
        memory_type = "advanced"
    else:
        # Simple: agent.md file
        memory_path = agent_dir
        index_file = agent_md
        memory_type = "simple"
    
    transcripts_dir = agent_dir / "transcripts"

    console.print()
    console.print("[bold]Memory Consolidation (Dream)[/bold]", style=COLORS["primary"])
    console.print()
    console.print(f"[dim]Memory type: {memory_type}[/dim]")
    console.print(f"[dim]Memory path: {memory_path}[/dim]")
    console.print("[dim]Running multi-phase memory consolidation...[/dim]")
    console.print()

    # Render the consolidation prompt
    prompt = render_template(
        "memory_consolidation.jinja",
        memory_dir=str(memory_path),
        memory_dir_context=f"Memory files are stored in {memory_path}" + 
                          (f" (single file: {agent_md.name})" if memory_type == "simple" else ""),
        index_file=index_file.name if memory_type == "advanced" else "agent.md",
        index_max_lines=100,
        transcripts_dir=str(transcripts_dir) if transcripts_dir.exists() else None,
    )

    console.print("[bold]Phase 1: Orient[/bold]", style=COLORS["primary"])
    console.print(f"[dim]  Memory path: {memory_path}[/dim]")
    console.print(f"[dim]  Index file: {index_file}[/dim]")

    # List existing memory files
    if memory_type == "advanced":
        memory_files = list(memory_dir.glob("*.md"))
    else:
        memory_files = [agent_md] if agent_md.exists() else []
    
    if memory_files:
        console.print(f"[dim]  Found {len(memory_files)} memory file(s)[/dim]")
        for mf in sorted(memory_files)[:5]:  # Show first 5
            console.print(f"[dim]    - {mf.name}[/dim]")
        if len(memory_files) > 5:
            console.print(f"[dim]    ... and {len(memory_files) - 5} more[/dim]")
    else:
        console.print("[dim]  No memory files found[/dim]")

    console.print()
    console.print("[bold]Phase 2: Gather[/bold]", style=COLORS["primary"])

    # Check for transcripts
    if transcripts_dir.exists():
        transcript_files = list(transcripts_dir.glob("*.jsonl"))
        console.print(f"[dim]  Found {len(transcript_files)} transcript files[/dim]")
    else:
        console.print("[dim]  No transcripts directory[/dim]")

    console.print()
    console.print("[bold]Phase 3: Consolidate[/bold]", style=COLORS["primary"])
    console.print("[dim]  Merging new signal into existing topic files...[/dim]")

    console.print()
    console.print("[bold]Phase 4: Prune[/bold]", style=COLORS["primary"])
    console.print(f"[dim]  Updating index: {index_file}[/dim]")

    console.print()
    console.print("[bold]Consolidation Prompt Generated[/bold]", style=COLORS["primary"])
    console.print()
    console.print("[dim]The consolidation prompt is ready to be sent to the model.[/dim]")
    console.print("[dim]To complete consolidation, the agent will:[/dim]")
    console.print("[dim]  1. Review all memory files[/dim]")
    console.print("[dim]  2. Identify outdated or duplicate information[/dim]")
    console.print("[dim]  3. Merge related memories[/dim]")
    console.print("[dim]  4. Update the index file[/dim]")
    console.print()

    # Return the prompt for the agent to process
    # The caller should send this prompt to the model
    return prompt


def get_dream_prompt(
    memory_dir: Path,
    transcripts_dir: Path | None = None,
    index_file: str = "INDEX.md",
    index_max_lines: int = 100,
) -> str:
    """Generate the memory consolidation prompt.

    Args:
        memory_dir: Path to the memory directory
        transcripts_dir: Optional path to transcripts directory
        index_file: Name of the index file (default: INDEX.md)
        index_max_lines: Maximum lines for the index (default: 100)

    Returns:
        The rendered prompt string
    """
    return render_template(
        "memory_consolidation.jinja",
        memory_dir=str(memory_dir),
        memory_dir_context=f"Memory files are stored in {memory_dir}",
        index_file=index_file,
        index_max_lines=index_max_lines,
        transcripts_dir=str(transcripts_dir) if transcripts_dir else None,
    )
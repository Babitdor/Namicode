#!/usr/bin/env python3
"""
Ralph Agent System

A flexible autonomous agent system that supports multiple agent profiles
and iterative task execution.
"""
import asyncio
import logging
import tempfile
from pathlib import Path
from typing import Optional, Dict, Any
from dataclasses import dataclass, field

import yaml

# Suppress Pydantic warnings
import warnings
warnings.filterwarnings("ignore", message="Core Pydantic V1 functionality")

from namicode_cli.agents.core_agent import create_agent_with_config
from namicode_cli.config.config import console, COLORS
from namicode_cli.states.Session import SessionState
from namicode_cli.config.model_create import create_model
from namicode_cli.ui.execution import execute_task
from namicode_cli.ui.ui_elements import TokenTracker

from checkpoint import CheckpointManager


@dataclass
class AgentConfig:
    """Configuration for a single agent."""
    name: str
    description: str
    color: str
    system_prompt: str


@dataclass
class SystemConfig:
    """Configuration for the Ralph agent system."""
    default_settings: Dict[str, Any] = field(default_factory=dict)
    agents: Dict[str, AgentConfig] = field(default_factory=dict)
    task_categories: Dict[str, str] = field(default_factory=dict)


class RalphAgentSystem:
    """
    Main agent system for managing autonomous Ralph agents.
    
    Supports:
    - Multiple agent profiles with different capabilities
    - Iterative task execution
    - Configuration management
    - Workspace management
    """
    
    def __init__(self, config_path: Optional[str] = None, checkpoint_dir: str = "./checkpoints"):
        """
        Initialize the Ralph agent system.
        
        Args:
            config_path: Path to configuration file (default: ./config.yaml)
            checkpoint_dir: Directory for checkpoint storage
        """
        self.config_path = config_path or "./config.yaml"
        self.config: Optional[SystemConfig] = None
        self.work_dir: Optional[str] = None
        self.logger = self._setup_logging()
        
        # Initialize checkpoint manager
        self.checkpoint_manager = CheckpointManager(checkpoint_dir)
        
        # Load configuration
        self._load_config()
    
    def _setup_logging(self) -> logging.Logger:
        """Set up logging for the agent system."""
        logger = logging.getLogger("ralph")
        logger.setLevel(logging.INFO)
        
        # Console handler
        handler = logging.StreamHandler()
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        
        return logger
    
    def _load_config(self):
        """Load configuration from YAML file."""
        try:
            config_path = Path(self.config_path)
            if config_path.exists():
                with open(config_path, 'r') as f:
                    config_data = yaml.safe_load(f)
                
                # Parse agents
                agents = {}
                for name, agent_data in config_data.get('agents', {}).items():
                    agents[name] = AgentConfig(**agent_data)
                
                self.config = SystemConfig(
                    default_settings=config_data.get('default_settings', {}),
                    agents=agents,
                    task_categories=config_data.get('task_categories', {})
                )
                
                self.logger.info(f"Loaded configuration with {len(agents)} agents")
            else:
                self.logger.warning(f"Config file not found: {config_path}")
                self.config = SystemConfig()
        except Exception as e:
            self.logger.error(f"Error loading config: {e}")
            self.config = SystemConfig()
    
    def _get_agent_profile(self, agent_name: str = "ralph") -> AgentConfig:
        """
        Get an agent profile by name.
        
        Args:
            agent_name: Name of the agent profile (default: "ralph")
            
        Returns:
            AgentConfig object for the requested agent
        """
        if self.config and agent_name in self.config.agents:
            return self.config.agents[agent_name]
        
        # Fallback to default ralph agent
        self.logger.warning(f"Agent '{agent_name}' not found, using default")
        return AgentConfig(
            name="Ralph",
            description="Default autonomous agent",
            color="#ef4444",
            system_prompt="You are an autonomous agent working on iterative tasks."
        )
    
    def _setup_workspace(self) -> str:
        """
        Set up workspace directory.
        
        Returns:
            Path to workspace directory
        """
        default_dir = "./workspace"
        
        if self.config and 'work_dir' in self.config.default_settings:
            work_dir = self.config.default_settings['work_dir']
            if work_dir != "./workspace":
                # Use custom work directory
                Path(work_dir).mkdir(parents=True, exist_ok=True)
                self.work_dir = work_dir
                return work_dir
        
        # Use temp directory
        work_dir = tempfile.mkdtemp(prefix="ralph-")
        self.work_dir = work_dir
        return work_dir
    
    async def run_task(
        self,
        task: str,
        agent_name: str = "ralph",
        max_iterations: int = 0,
        work_dir: Optional[str] = None,
        enable_checkpoints: bool = False,
        checkpoint_interval: int = 1,
        resume_from: Optional[str] = None
    ):
        """
        Run a task with an autonomous agent.
        
        Args:
            task: The task description
            agent_name: Name of the agent profile to use
            max_iterations: Maximum iterations (0 = unlimited)
            work_dir: Custom working directory (optional)
            enable_checkpoints: Enable periodic checkpointing
            checkpoint_interval: Save checkpoint every N iterations
            resume_from: Checkpoint ID to resume from
        """
        # Get agent profile
        agent_profile = self._get_agent_profile(agent_name)
        
        # Setup workspace
        if work_dir:
            self.work_dir = work_dir
            Path(work_dir).mkdir(parents=True, exist_ok=True)
        else:
            work_dir = self._setup_workspace()
        
        # Get model configuration
        model = create_model()
        
        # Create agent
        agent, backend = create_agent_with_config(
            model=model,
            assistant_id=agent_name,
            tools=[],
            auto_approve=True,
        )
        
        # Setup session
        session_state = SessionState(auto_approve=True)
        token_tracker = TokenTracker()
        
        # Handle resume from checkpoint
        start_iteration = 1
        if resume_from:
            checkpoint = self.checkpoint_manager.load_checkpoint(resume_from)
            if checkpoint:
                console.print(f"[bold green]Resumed from checkpoint {resume_from}[/bold green]")
                console.print(f"[dim]Previous iteration: {checkpoint.metadata.iteration}[/dim]")
                start_iteration = checkpoint.metadata.iteration + 1
            else:
                console.print(f"[bold yellow]Checkpoint {resume_from} not found, starting fresh[/bold yellow]")
        
        # Display header
        console.print(f"\n[bold {agent_profile.color}]{agent_profile.name.upper()}[/bold {agent_profile.color}]")
        console.print(f"[dim]{agent_profile.description}[/dim]")
        console.print(f"[dim]Task: {task}[/dim]")
        console.print(
            f"[dim]Iterations: {'unlimited (Ctrl+C to stop)' if max_iterations == 0 else max_iterations}[/dim]"
        )
        console.print(f"[dim]Working directory: {work_dir}[/dim]\n")
        
        # Run iterations
        iteration = start_iteration
        try:
            while max_iterations == 0 or iteration <= max_iterations:
                # Create checkpoint if enabled
                if enable_checkpoints and iteration % checkpoint_interval == 0:
                    checkpoint_id = self.checkpoint_manager.create_checkpoint(
                        agent_name=agent_name,
                        task=task,
                        iteration=iteration,
                        workspace_path=work_dir,
                        state={"iteration": iteration},
                        tokens_used=token_tracker.total_tokens if hasattr(token_tracker, 'total_tokens') else 0
                    )
                    console.print(f"[dim]Checkpoint saved: {checkpoint_id}[/dim]")
                console.print(f"\n[bold cyan]{'='*60}[/bold cyan]")
                console.print(f"[bold cyan]{agent_profile.name.upper()} ITERATION {iteration}[/bold cyan]")
                console.print(f"[bold cyan]{'='*60}[/bold cyan]\n")
                
                iter_display = (
                    f"{iteration}/{max_iterations}"
                    if max_iterations > 0
                    else str(iteration)
                )
                
                # Build prompt with iteration context
                prompt = f"""## Iteration {iter_display}

{agent_profile.system_prompt}

Your previous work is in the filesystem. Check what exists and keep building.

TASK:
{task}

Make progress. You'll be called again."""
                
                # Execute task
                await execute_task(
                    prompt,
                    agent,
                    agent_name,
                    session_state,
                    token_tracker,
                    backend=backend,
                )
                
                console.print(f"\n[dim]...continuing to iteration {iteration + 1}[/dim]")
                iteration += 1
        
        except KeyboardInterrupt:
            console.print(
                f"\n[bold yellow]Stopped after {iteration} iterations[/bold yellow]"
            )
        
        # Show created files
        self._show_workspace_summary()
    
    def _show_workspace_summary(self):
        """Display summary of files created in workspace."""
        if not self.work_dir:
            return
        
        console.print(f"\n[bold]Files created in {self.work_dir}:[/bold]")
        
        workspace_path = Path(self.work_dir)
        files = sorted(workspace_path.rglob("*"))
        
        for f in files:
            if f.is_file() and ".git" not in str(f):
                console.print(f"  {f.relative_to(workspace_path)}", style="dim")
    
    def list_agents(self):
        """List all available agent profiles."""
        console.print("\n[bold]Available Agents:[/bold]")
        
        if not self.config or not self.config.agents:
            console.print("[dim]No agents configured[/dim]")
            return
        
        for name, agent in self.config.agents.items():
            console.print(
                f"  [{agent.color}]•[/] {name}: {agent.description}"
            )
        
        # Show task categories
        if self.config.task_categories:
            console.print("\n[bold]Task Categories:[/bold]")
            for category, agent_name in self.config.task_categories.items():
                color = self.config.agents.get(agent_name, AgentConfig("", "", "#ffffff", "")).color
                console.print(f"  [{color}]•[/] {category} → {agent_name}")
    
    def list_checkpoints(self):
        """List all available checkpoints."""
        console.print(self.checkpoint_manager.get_checkpoint_summary())
    
    def resume_from_checkpoint(self, checkpoint_id: str, task: str):
        """
        Resume a task from a checkpoint.
        
        Args:
            checkpoint_id: Checkpoint ID to resume from
            task: Task to continue
        """
        asyncio.run(self.run_task(
            task=task,
            resume_from=checkpoint_id
        ))


def main():
    """Simple CLI for testing the agent system."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Ralph Agent System - Autonomous agent management"
    )
    parser.add_argument("--list", action="store_true", help="List available agents")
    parser.add_argument("--list-checkpoints", action="store_true", help="List all checkpoints")
    parser.add_argument("--agent", default="ralph", help="Agent profile to use")
    parser.add_argument("--iterations", type=int, default=0, help="Max iterations")
    parser.add_argument("--workdir", help="Custom working directory")
    parser.add_argument("--enable-checkpoints", action="store_true", help="Enable periodic checkpointing")
    parser.add_argument("--checkpoint-interval", type=int, default=1, help="Save checkpoint every N iterations")
    parser.add_argument("--resume", help="Resume from checkpoint ID")
    parser.add_argument("task", nargs="?", help="Task to execute")
    
    args = parser.parse_args()
    
    system = RalphAgentSystem()
    
    if args.list:
        system.list_agents()
    elif args.list_checkpoints:
        system.list_checkpoints()
    elif args.task:
        asyncio.run(system.run_task(
            args.task,
            agent_name=args.agent,
            max_iterations=args.iterations,
            work_dir=args.workdir,
            enable_checkpoints=args.enable_checkpoints,
            checkpoint_interval=args.checkpoint_interval,
            resume_from=args.resume
        ))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
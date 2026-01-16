#!/usr/bin/env python3
"""
Comprehensive CLI Interface for Ralph Agents

Provides a unified command-line interface for all Ralph Agents features.
"""
import argparse
import asyncio
import sys
from pathlib import Path
from typing import Optional

from agent_system import RalphAgentSystem
from checkpoint import CheckpointManager
from metrics import MetricsCollector
from collaboration import AgentCollaborator, CollaborationTask
from workflow import WorkflowOrchestrator, WorkflowDefinition, WorkflowStep


class RalphCLI:
    """Main CLI handler for Ralph Agents."""
    
    def __init__(self):
        self.agent_system = RalphAgentSystem()
        self.collaborator = AgentCollaborator(self.agent_system)
        self.metrics = MetricsCollector()
        self.orchestrator = WorkflowOrchestrator(
            self.agent_system,
            self.collaborator,
            self.metrics
        )
        self.checkpoint_manager = CheckpointManager()
    
    async def cmd_run(self, args):
        """Run a single task with an agent."""
        print(f"\n[bold yellow]Running task: {args.task}[/bold yellow]")
        print(f"Agent: {args.agent}")
        print(f"Iterations: {args.iterations or 'unlimited'}\n")
        
        await self.agent_system.run_task(
            task=args.task,
            agent_name=args.agent,
            max_iterations=args.iterations or 0,
            work_dir=args.workdir,
            enable_checkpoints=args.checkpoints,
            checkpoint_interval=args.checkpoint_interval,
            resume_from=args.resume
        )
    
    async def cmd_collaborate(self, args):
        """Run a collaboration task."""
        print(f"\n[bold yellow]Collaboration Mode: {args.mode}[/bold yellow]\n")
        
        if args.mode == "sequential":
            # Parse tasks from file or command line
            tasks = self._parse_tasks(args.tasks)
            results = await self.collaborator.execute_sequential(tasks, args.workdir)
        
        elif args.mode == "parallel":
            tasks = self._parse_tasks(args.tasks)
            results = await self.collaborator.execute_parallel(tasks, args.workdir)
        
        elif args.mode == "peer_review":
            result = await self.collaborator.peer_review(
                task=args.task,
                primary_agent=args.primary,
                reviewer_agents=args.reviewers.split(","),
                workspace=args.workdir
            )
            print(f"\n[bold green]Peer review completed[/bold green]")
            print(f"Total time: {result['total_duration']:.2f}s")
            return
        
        else:
            print(f"[bold red]Unknown collaboration mode: {args.mode}[/bold red]")
            return
        
        print(self.collaborator.generate_summary())
    
    async def cmd_workflow(self, args):
        """Execute or manage workflows."""
        if args.list:
            self._list_workflows()
        elif args.create:
            workflow = self.orchestrator.create_template_workflow(
                workflow_id=args.create,
                name=args.name or args.create,
                description=args.description or "Template workflow"
            )
            path = self.orchestrator.save_workflow(workflow)
            print(f"[bold green]Workflow created: {path}[/bold green]")
        
        elif args.execute:
            workflow = self.orchestrator.load_workflow(args.execute)
            execution = await self.orchestrator.execute_workflow(
                workflow,
                workspace=args.workdir,
                resume_from=args.resume
            )
            print(self.orchestrator.generate_report(execution))
        
        elif args.show:
            workflow = self.orchestrator.load_workflow(args.show)
            self._show_workflow(workflow)
    
    def cmd_checkpoint(self, args):
        """Manage checkpoints."""
        if args.list:
            print(self.checkpoint_manager.get_checkpoint_summary())
        
        elif args.delete:
            if self.checkpoint_manager.delete_checkpoint(args.delete):
                print(f"[bold green]Checkpoint {args.delete} deleted[/bold green]")
            else:
                print(f"[bold red]Checkpoint {args.delete} not found[/bold red]")
        
        elif args.clear:
            self.checkpoint_manager.clear_all_checkpoints()
            print("[bold green]All checkpoints cleared[/bold green]")
        
        elif args.info:
            checkpoint = self.checkpoint_manager.load_checkpoint(args.info)
            if checkpoint:
                self._show_checkpoint_info(checkpoint)
            else:
                print(f"[bold red]Checkpoint {args.info} not found[/bold red]")
    
    def cmd_metrics(self, args):
        """Manage metrics."""
        if args.list:
            self._list_metrics()
        
        elif args.show:
            self._show_metrics(args.show)
        
        elif args.export:
            self._export_metrics(args.export, args.format)
    
    def cmd_agents(self, args):
        """List available agents."""
        self.agent_system.list_agents()
    
    async def cmd_interactive(self, args):
        """Interactive mode for agent interaction."""
        print("\n[bold yellow]Interactive Mode[/bold yellow]")
        print("Type your tasks and agents will work on them.")
        print("Commands: /agents, /exit, /help\n")
        
        while True:
            try:
                task = input("Task (or /exit): ").strip()
                
                if task.lower() == "/exit":
                    break
                elif task.lower() == "/agents":
                    self.agent_system.list_agents()
                    continue
                elif task.lower() == "/help":
                    self._print_interactive_help()
                    continue
                elif not task:
                    continue
                
                # Ask for agent
                agent = input("Agent (default: ralph): ").strip() or "ralph"
                
                # Ask for iterations
                iterations_input = input("Iterations (default: 1): ").strip()
                iterations = int(iterations_input) if iterations_input else 1
                
                await self.agent_system.run_task(
                    task=task,
                    agent_name=agent,
                    max_iterations=iterations
                )
                
            except KeyboardInterrupt:
                print("\n\n[bold yellow]Interrupted. Use /exit to quit.[/bold yellow]")
            except Exception as e:
                print(f"[bold red]Error: {e}[/bold red]")
        
        print("\n[bold yellow]Goodbye![/bold yellow]")
    
    def _parse_tasks(self, tasks_str: str) -> list:
        """Parse tasks from string format."""
        tasks = []
        for task_str in tasks_str.split(";"):
            if ":" in task_str:
                agent, task = task_str.split(":", 1)
                tasks.append({
                    "agent": agent.strip(),
                    "task": task.strip(),
                    "iterations": 1
                })
        return tasks
    
    def _list_workflows(self):
        """List all available workflows."""
        workflow_dir = Path("./workflows")
        if not workflow_dir.exists():
            print("[dim]No workflows found[/dim]")
            return
        
        workflows = list(workflow_dir.glob("*.json"))
        if not workflows:
            print("[dim]No workflows found[/dim]")
            return
        
        print("\n[bold]Available Workflows:[/bold]\n")
        for workflow_path in workflows:
            workflow = self.orchestrator.load_workflow(str(workflow_path))
            print(f"  • {workflow.workflow_id}: {workflow.name}")
            print(f"    {workflow.description}")
            print(f"    Steps: {len(workflow.steps)}\n")
    
    def _show_workflow(self, workflow: WorkflowDefinition):
        """Display workflow details."""
        print(f"\n[bold]Workflow: {workflow.workflow_id}[/bold]")
        print(f"Name: {workflow.name}")
        print(f"Description: {workflow.description}")
        print(f"\n[bold]Steps:[/bold]\n")
        
        for i, step in enumerate(workflow.steps, 1):
            deps = f" (depends on: {', '.join(step.dependencies)})" if step.dependencies else ""
            print(f"{i}. {step.name} ({step.agent}){deps}")
            print(f"   Task: {step.task[:80]}...")
            print(f"   Iterations: {step.iterations}")
            print(f"   On failure: {step.on_failure}\n")
    
    def _show_checkpoint_info(self, checkpoint):
        """Display detailed checkpoint information."""
        print(f"\n[bold]Checkpoint Information[/bold]")
        print(f"Timestamp: {checkpoint.metadata.timestamp}")
        print(f"Agent: {checkpoint.metadata.agent_name}")
        print(f"Task: {checkpoint.metadata.task}")
        print(f"Iteration: {checkpoint.metadata.iteration}")
        print(f"Files Created: {checkpoint.metadata.files_created}")
        print(f"Tokens Used: {checkpoint.metadata.tokens_used:,}")
        print(f"Workspace: {checkpoint.metadata.workspace_path}")
    
    def _list_metrics(self):
        """List all saved metrics."""
        metrics_dir = Path("./metrics")
        if not metrics_dir.exists():
            print("[dim]No metrics found[/dim]")
            return
        
        metrics_files = list(metrics_dir.glob("*.json"))
        if not metrics_files:
            print("[dim]No metrics found[/dim]")
            return
        
        print("\n[bold]Available Metrics:[/bold]\n")
        for metrics_path in sorted(metrics_files, reverse=True)[:10]:
            print(f"  • {metrics_path.name}")
    
    def _show_metrics(self, filename: str):
        """Show metrics from a file."""
        import json
        metrics_path = Path("./metrics") / filename
        
        if not metrics_path.exists():
            print(f"[bold red]Metrics file not found: {filename}[/bold red]")
            return
        
        with open(metrics_path, 'r') as f:
            data = json.load(f)
        
        print(f"\n[bold]Metrics: {filename}[/bold]")
        print(f"Task: {data['task']}")
        print(f"Agent: {data['agent_name']}")
        print(f"Status: {'SUCCESS' if data['success'] else 'FAILED'}")
        print(f"Duration: {data['total_duration_seconds']:.2f}s")
        print(f"Iterations: {data['total_iterations']}")
        print(f"Files Created: {data['total_files_created']}")
        print(f"Tokens Used: {data['total_tokens_used']:,}")
    
    def _export_metrics(self, filename: str, format: str):
        """Export metrics to different format."""
        print(f"[bold yellow]Exporting metrics to {format}...[/bold yellow]")
        print(f"[dim]Feature coming soon![/dim]")
    
    def _print_interactive_help(self):
        """Print interactive mode help."""
        print("\n[bold]Interactive Mode Commands:[/bold]")
        print("  /agents   - List available agents")
        print("  /exit     - Exit interactive mode")
        print("  /help     - Show this help")
        print("\n[bold]Usage:[/bold]")
        print("  1. Enter your task description")
        print("  2. Specify an agent (or press Enter for default)")
        print("  3. Specify iterations (or press Enter for 1)")
        print("  4. Agent will execute the task")
        print()


def create_parser():
    """Create the main argument parser."""
    parser = argparse.ArgumentParser(
        description="Ralph Agents - Autonomous Multi-Agent System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run a single task
  python cli.py run "Create a Python CLI tool" --agent coder --iterations 3
  
  # Sequential collaboration
  python cli.py collaborate --mode sequential --tasks "coder:Implement;tester:Test"
  
  # Parallel collaboration
  python cli.py collaborate --mode parallel --tasks "tester:Test A;tester:Test B"
  
  # Peer review
  python cli.py collaborate --mode peer_review --task "Build API" --primary coder --reviewers tester,ralph
  
  # Execute workflow
  python cli.py workflow --execute my_workflow.json
  
  # List checkpoints
  python cli.py checkpoint --list
  
  # Interactive mode
  python cli.py interactive
        """
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # Run command
    run_parser = subparsers.add_parser('run', help='Run a single task')
    run_parser.add_argument('task', help='Task description')
    run_parser.add_argument('--agent', default='ralph', help='Agent to use')
    run_parser.add_argument('--iterations', type=int, help='Max iterations')
    run_parser.add_argument('--workdir', help='Working directory')
    run_parser.add_argument('--checkpoints', action='store_true', help='Enable checkpoints')
    run_parser.add_argument('--checkpoint-interval', type=int, default=1, help='Checkpoint interval')
    run_parser.add_argument('--resume', help='Resume from checkpoint')
    
    # Collaborate command
    collab_parser = subparsers.add_parser('collaborate', help='Run collaboration tasks')
    collab_parser.add_argument('--mode', choices=['sequential', 'parallel', 'peer_review'],
                             required=True, help='Collaboration mode')
    collab_parser.add_argument('--tasks', help='Tasks (format: agent1:task1;agent2:task2)')
    collab_parser.add_argument('--task', help='Task for peer review mode')
    collab_parser.add_argument('--primary', default='coder', help='Primary agent for peer review')
    collab_parser.add_argument('--reviewers', default='tester', help='Comma-separated reviewers')
    collab_parser.add_argument('--workdir', help='Working directory')
    
    # Workflow command
    workflow_parser = subparsers.add_parser('workflow', help='Manage workflows')
    workflow_parser.add_argument('--list', action='store_true', help='List workflows')
    workflow_parser.add_argument('--create', help='Create new workflow template')
    workflow_parser.add_argument('--name', help='Workflow name')
    workflow_parser.add_argument('--description', help='Workflow description')
    workflow_parser.add_argument('--execute', help='Execute workflow file')
    workflow_parser.add_argument('--show', help='Show workflow details')
    workflow_parser.add_argument('--resume', help='Resume from step')
    workflow_parser.add_argument('--workdir', help='Working directory')
    
    # Checkpoint command
    checkpoint_parser = subparsers.add_parser('checkpoint', help='Manage checkpoints')
    checkpoint_parser.add_argument('--list', action='store_true', help='List checkpoints')
    checkpoint_parser.add_argument('--delete', help='Delete checkpoint by ID')
    checkpoint_parser.add_argument('--clear', action='store_true', help='Clear all checkpoints')
    checkpoint_parser.add_argument('--info', help='Show checkpoint details')
    
    # Metrics command
    metrics_parser = subparsers.add_parser('metrics', help='Manage metrics')
    metrics_parser.add_argument('--list', action='store_true', help='List metrics')
    metrics_parser.add_argument('--show', help='Show metrics from file')
    metrics_parser.add_argument('--export', help='Export metrics to file')
    metrics_parser.add_argument('--format', choices=['json', 'csv'], default='json', help='Export format')
    
    # Agents command
    agents_parser = subparsers.add_parser('agents', help='List available agents')
    
    # Interactive command
    interactive_parser = subparsers.add_parser('interactive', help='Interactive mode')
    
    return parser


async def main():
    """Main entry point."""
    parser = create_parser()
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    cli = RalphCLI()
    
    try:
        if args.command == 'run':
            await cli.cmd_run(args)
        elif args.command == 'collaborate':
            await cli.cmd_collaborate(args)
        elif args.command == 'workflow':
            await cli.cmd_workflow(args)
        elif args.command == 'checkpoint':
            cli.cmd_checkpoint(args)
        elif args.command == 'metrics':
            cli.cmd_metrics(args)
        elif args.command == 'agents':
            cli.cmd_agents(args)
        elif args.command == 'interactive':
            await cli.cmd_interactive(args)
    except KeyboardInterrupt:
        print("\n\n[bold yellow]Interrupted by user[/bold yellow]")
    except Exception as e:
        print(f"\n[bold red]Error: {e}[/bold red]")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
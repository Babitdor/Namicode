#!/usr/bin/env python3
"""
Agent Collaboration System for Ralph Agents

Enables multiple agents to work together on complex tasks.
"""
import asyncio
from typing import List, Dict, Optional, Callable, Any
from dataclasses import dataclass
from enum import Enum

from agent_system import RalphAgentSystem, AgentConfig


class CollaborationMode(Enum):
    """Different collaboration patterns."""
    SEQUENTIAL = "sequential"  # Agents work one after another
    PARALLEL = "parallel"  # Agents work simultaneously
    HIERARCHICAL = "hierarchical"  # Manager agent delegates to specialists
    PEER_REVIEW = "peer_review"  # Agents review each other's work


@dataclass
class CollaborationTask:
    """A task assigned to a specific agent."""
    agent_name: str
    task_description: str
    dependencies: List[str]  # Other tasks this depends on
    priority: int  # Lower = higher priority


@dataclass
class CollaborationResult:
    """Result from a collaboration task."""
    agent_name: str
    task: str
    success: bool
    output: str
    metrics: Dict[str, Any]
    duration_seconds: float


class AgentCollaborator:
    """
    Manages collaboration between multiple agents.
    
    Features:
    - Sequential task execution
    - Parallel execution of independent tasks
    - Hierarchical agent management
    - Peer review workflows
    - Task dependency resolution
    """
    
    def __init__(self, agent_system: RalphAgentSystem):
        """
        Initialize agent collaborator.
        
        Args:
            agent_system: RalphAgentSystem instance to use
        """
        self.agent_system = agent_system
        self.results: List[CollaborationResult] = []
        self.task_queue: List[CollaborationTask] = []
    
    async def execute_sequential(
        self,
        tasks: List[Dict[str, str]],
        workspace: Optional[str] = None
    ) -> List[CollaborationResult]:
        """
        Execute tasks sequentially, one agent at a time.
        
        Args:
            tasks: List of {"agent": "name", "task": "description"} dicts
            workspace: Shared workspace directory
            
        Returns:
            List of collaboration results
        """
        self.results = []
        
        console.print("\n[bold yellow]Starting Sequential Collaboration[/bold yellow]")
        console.print(f"[dim]Tasks: {len(tasks)}[/dim]\n")
        
        for i, task_def in enumerate(tasks):
            agent_name = task_def["agent"]
            task = task_def["task"]
            
            console.print(f"\n[bold cyan]Task {i+1}/{len(tasks)}: {agent_name}[/bold cyan]")
            
            try:
                start_time = asyncio.get_event_loop().time()
                
                await self.agent_system.run_task(
                    task=task,
                    agent_name=agent_name,
                    max_iterations=task_def.get("iterations", 1),
                    work_dir=workspace
                )
                
                end_time = asyncio.get_event_loop().time()
                duration = end_time - start_time
                
                result = CollaborationResult(
                    agent_name=agent_name,
                    task=task,
                    success=True,
                    output="Task completed",
                    metrics={},
                    duration_seconds=duration
                )
                
                self.results.append(result)
                console.print(f"[bold green]✓[/bold green] {agent_name} completed ({duration:.1f}s)")
                
            except Exception as e:
                result = CollaborationResult(
                    agent_name=agent_name,
                    task=task,
                    success=False,
                    output=str(e),
                    metrics={},
                    duration_seconds=0
                )
                self.results.append(result)
                console.print(f"[bold red]✗[/bold red] {agent_name} failed: {e}")
        
        return self.results
    
    async def execute_parallel(
        self,
        tasks: List[Dict[str, str]],
        workspace: Optional[str] = None
    ) -> List[CollaborationResult]:
        """
        Execute tasks in parallel where possible.
        
        Args:
            tasks: List of {"agent": "name", "task": "description"} dicts
            workspace: Shared workspace directory
            
        Returns:
            List of collaboration results
        """
        self.results = []
        
        console.print("\n[bold yellow]Starting Parallel Collaboration[/bold yellow]")
        console.print(f"[dim]Tasks: {len(tasks)}[/dim]\n")
        
        # Create coroutines for all tasks
        async def run_single_task(task_def, index):
            agent_name = task_def["agent"]
            task = task_def["task"]
            
            console.print(f"\n[bold cyan]Starting Task {index+1}: {agent_name}[/bold cyan]")
            
            try:
                start_time = asyncio.get_event_loop().time()
                
                await self.agent_system.run_task(
                    task=task,
                    agent_name=agent_name,
                    max_iterations=task_def.get("iterations", 1),
                    work_dir=workspace
                )
                
                end_time = asyncio.get_event_loop().time()
                duration = end_time - start_time
                
                console.print(f"[bold green]✓[/bold green] {agent_name} completed ({duration:.1f}s)")
                
                return CollaborationResult(
                    agent_name=agent_name,
                    task=task,
                    success=True,
                    output="Task completed",
                    metrics={},
                    duration_seconds=duration
                )
                
            except Exception as e:
                console.print(f"[bold red]✗[/bold red] {agent_name} failed: {e}")
                
                return CollaborationResult(
                    agent_name=agent_name,
                    task=task,
                    success=False,
                    output=str(e),
                    metrics={},
                    duration_seconds=0
                )
        
        # Run all tasks concurrently
        coroutines = [run_single_task(task, i) for i, task in enumerate(tasks)]
        self.results = await asyncio.gather(*coroutines)
        
        return self.results
    
    async def execute_with_dependencies(
        self,
        tasks: List[CollaborationTask],
        workspace: Optional[str] = None
    ) -> List[CollaborationResult]:
        """
        Execute tasks respecting dependencies.
        
        Args:
            tasks: List of CollaborationTask objects
            workspace: Shared workspace directory
            
        Returns:
            List of collaboration results
        """
        self.results = []
        
        console.print("\n[bold yellow]Starting Dependency-Aware Collaboration[/bold yellow]")
        console.print(f"[dim]Tasks: {len(tasks)}[/dim]\n")
        
        completed_tasks = set()
        task_map = {task.task_description: task for task in tasks}
        
        while len(completed_tasks) < len(tasks):
            # Find tasks that can be executed (all dependencies met)
            ready_tasks = [
                task for task in tasks
                if task.task_description not in completed_tasks
                and all(dep in completed_tasks for dep in task.dependencies)
            ]
            
            if not ready_tasks:
                # Circular dependency or missing dependency
                console.print("[bold red]Error: Circular dependency detected[/bold red]")
                break
            
            # Sort by priority
            ready_tasks.sort(key=lambda t: t.priority)
            
            # Execute ready tasks in parallel
            task_defs = [
                {"agent": task.agent_name, "task": task.task_description, "iterations": 1}
                for task in ready_tasks
            ]
            
            batch_results = await self.execute_parallel(task_defs, workspace)
            
            # Mark tasks as completed
            for result in batch_results:
                completed_tasks.add(result.task)
        
        return self.results
    
    async def peer_review(
        self,
        task: str,
        primary_agent: str,
        reviewer_agents: List[str],
        workspace: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Execute a task with peer review.
        
        Args:
            task: Task to execute
            primary_agent: Agent that does the work
            reviewer_agents: Agents that review the work
            workspace: Workspace directory
            
        Returns:
            Dictionary with results and feedback
        """
        console.print(f"\n[bold yellow]Starting Peer Review[/bold yellow]")
        console.print(f"[dim]Primary: {primary_agent}[/dim]")
        console.print(f"[dim]Reviewers: {', '.join(reviewer_agents)}[/dim]\n")
        
        # Step 1: Primary agent does the work
        console.print(f"[bold cyan]Step 1: {primary_agent} executing task[/bold cyan]\n")
        
        primary_start = asyncio.get_event_loop().time()
        await self.agent_system.run_task(
            task=task,
            agent_name=primary_agent,
            max_iterations=3,
            work_dir=workspace
        )
        primary_duration = asyncio.get_event_loop().time() - primary_start
        
        # Step 2: Each reviewer provides feedback
        review_tasks = []
        for i, reviewer in enumerate(reviewer_agents):
            review_task = (
                f"Review the work in the workspace. "
                f"Provide feedback on code quality, correctness, and potential improvements. "
                f"Focus on: {task}"
            )
            review_tasks.append({
                "agent": reviewer,
                "task": review_task,
                "iterations": 1
            })
        
        console.print(f"\n[bold cyan]Step 2: Peer review[/bold cyan]\n")
        review_results = await self.execute_parallel(review_tasks, workspace)
        
        # Step 3: Primary agent incorporates feedback
        console.print(f"\n[bold cyan]Step 3: {primary_agent} incorporating feedback[/bold cyan]\n")
        
        incorporation_task = (
            f"Review the feedback from peer reviewers and make improvements to the work. "
            f"Address the issues raised in the review. Task: {task}"
        )
        
        incorporation_start = asyncio.get_event_loop().time()
        await self.agent_system.run_task(
            task=incorporation_task,
            agent_name=primary_agent,
            max_iterations=2,
            work_dir=workspace
        )
        incorporation_duration = asyncio.get_event_loop().time() - incorporation_start
        
        return {
            "primary_duration": primary_duration,
            "review_results": [r.__dict__ for r in review_results],
            "incorporation_duration": incorporation_duration,
            "total_duration": primary_duration + incorporation_duration,
            "total_reviewers": len(reviewer_agents)
        }
    
    def generate_summary(self) -> str:
        """
        Generate a summary of collaboration results.
        
        Returns:
            Formatted summary string
        """
        if not self.results:
            return "No collaboration results available."
        
        total_duration = sum(r.duration_seconds for r in self.results)
        successful = sum(1 for r in self.results if r.success)
        
        lines = [
            "\n" + "=" * 80,
            "COLLABORATION SUMMARY",
            "=" * 80,
            f"\nTotal Tasks: {len(self.results)}",
            f"Successful: {successful}",
            f"Failed: {len(self.results) - successful}",
            f"\nTotal Duration: {total_duration:.2f}s",
            f"Average per Task: {total_duration / len(self.results):.2f}s",
            "\n" + "-" * 80,
            "Task Details",
            "-" * 80,
        ]
        
        for result in self.results:
            status = "✓" if result.success else "✗"
            lines.append(
                f"\n{status} {result.agent_name}: {result.task[:50]}..."
                f"\n   Duration: {result.duration_seconds:.2f}s"
            )
            if not result.success:
                lines.append(f"   Error: {result.output}")
        
        lines.append("\n" + "=" * 80 + "\n")
        return "\n".join(lines)
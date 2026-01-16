#!/usr/bin/env python3
"""
Workflow Orchestration for Ralph Agents

Provides high-level workflow management and task orchestration.
"""
import asyncio
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass
from enum import Enum
import json
from pathlib import Path

from agent_system import RalphAgentSystem
from collaboration import AgentCollaborator, CollaborationTask
from metrics import MetricsCollector, TaskMetrics


class WorkflowStatus(Enum):
    """Workflow execution status."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"


@dataclass
class WorkflowStep:
    """A single step in a workflow."""
    step_id: str
    name: str
    agent: str
    task: str
    dependencies: List[str]
    condition: Optional[str]  # Conditional expression
    iterations: int = 1
    on_failure: Optional[str] = "stop"  # stop, continue, retry


@dataclass
class WorkflowDefinition:
    """Definition of a complete workflow."""
    workflow_id: str
    name: str
    description: str
    steps: List[WorkflowStep]
    default_workspace: str = "./workspace"


@dataclass
class WorkflowExecution:
    """Execution state of a workflow."""
    workflow_id: str
    status: WorkflowStatus
    current_step: Optional[str]
    completed_steps: List[str]
    failed_steps: List[str]
    results: Dict[str, Any]
    start_time: str
    end_time: Optional[str]


class WorkflowOrchestrator:
    """
    Orchestrates complex workflows with multiple steps and agents.
    
    Features:
    - Multi-step workflow definition
    - Conditional execution
    - Error handling strategies
    - Workflow persistence
    - Progress tracking
    - Dynamic workflow generation
    """
    
    def __init__(
        self,
        agent_system: RalphAgentSystem,
        collaborator: AgentCollaborator,
        metrics: Optional[MetricsCollector] = None,
        workflow_dir: str = "./workflows"
    ):
        """
        Initialize workflow orchestrator.
        
        Args:
            agent_system: RalphAgentSystem instance
            collaborator: AgentCollaborator instance
            metrics: MetricsCollector instance (optional)
            workflow_dir: Directory for workflow definitions and state
        """
        self.agent_system = agent_system
        self.collaborator = collaborator
        self.metrics = metrics or MetricsCollector()
        self.workflow_dir = Path(workflow_dir)
        self.workflow_dir.mkdir(parents=True, exist_ok=True)
        
        self.current_execution: Optional[WorkflowExecution] = None
    
    def load_workflow(self, workflow_path: str) -> WorkflowDefinition:
        """
        Load workflow from JSON file.
        
        Args:
            workflow_path: Path to workflow JSON file
            
        Returns:
            WorkflowDefinition object
        """
        with open(workflow_path, 'r') as f:
            data = json.load(f)
        
        steps = [
            WorkflowStep(**step_data)
            for step_data in data['steps']
        ]
        
        return WorkflowDefinition(
            workflow_id=data['workflow_id'],
            name=data['name'],
            description=data['description'],
            steps=steps,
            default_workspace=data.get('default_workspace', './workspace')
        )
    
    def save_workflow(self, workflow: WorkflowDefinition, filename: Optional[str] = None):
        """
        Save workflow to JSON file.
        
        Args:
            workflow: WorkflowDefinition to save
            filename: Optional filename (default: workflow_id.json)
        """
        if filename is None:
            filename = f"{workflow.workflow_id}.json"
        
        filepath = self.workflow_dir / filename
        
        data = {
            'workflow_id': workflow.workflow_id,
            'name': workflow.name,
            'description': workflow.description,
            'default_workspace': workflow.default_workspace,
            'steps': [
                {
                    'step_id': step.step_id,
                    'name': step.name,
                    'agent': step.agent,
                    'task': step.task,
                    'dependencies': step.dependencies,
                    'condition': step.condition,
                    'iterations': step.iterations,
                    'on_failure': step.on_failure
                }
                for step in workflow.steps
            ]
        }
        
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)
        
        return filepath
    
    async def execute_workflow(
        self,
        workflow: WorkflowDefinition,
        workspace: Optional[str] = None,
        resume_from: Optional[str] = None
    ) -> WorkflowExecution:
        """
        Execute a workflow.
        
        Args:
            workflow: WorkflowDefinition to execute
            workspace: Workspace directory (optional)
            resume_from: Step ID to resume from
            
        Returns:
            WorkflowExecution object with results
        """
        from datetime import datetime
        
        workspace = workspace or workflow.default_workspace
        
        # Initialize execution
        execution = WorkflowExecution(
            workflow_id=workflow.workflow_id,
            status=WorkflowStatus.RUNNING,
            current_step=None,
            completed_steps=[],
            failed_steps=[],
            results={},
            start_time=datetime.now().isoformat(),
            end_time=None
        )
        
        self.current_execution = execution
        self.metrics.start_task(
            task=workflow.name,
            agent_name="workflow_orchestrator"
        )
        
        console.print(f"\n[bold yellow]Executing Workflow: {workflow.name}[/bold yellow]")
        console.print(f"[dim]{workflow.description}[/dim]")
        console.print(f"[dim]Steps: {len(workflow.steps)}[/dim]\n")
        
        try:
            # Execute steps in dependency order
            remaining_steps = workflow.steps.copy()
            
            if resume_from:
                # Skip steps before resume point
                remaining_steps = [
                    step for step in remaining_steps
                    if step.step_id == resume_from or any(
                        d in resume_from for d in step.dependencies
                    )
                ]
            
            while remaining_steps:
                # Find executable steps (all dependencies met)
                executable_steps = [
                    step for step in remaining_steps
                    if all(dep in execution.completed_steps for dep in step.dependencies)
                ]
                
                if not executable_steps:
                    # Circular dependency
                    raise RuntimeError("Circular dependency detected in workflow")
                
                # Execute each executable step
                for step in executable_steps:
                    # Check condition if specified
                    if step.condition and not self._evaluate_condition(
                        step.condition, execution.results
                    ):
                        console.print(f"[dim]Skipping {step.name} (condition not met)[/dim]")
                        remaining_steps.remove(step)
                        continue
                    
                    execution.current_step = step.step_id
                    console.print(f"\n[bold cyan]Step: {step.name}[/bold cyan]")
                    console.print(f"[dim]Agent: {step.agent}[/dim]")
                    console.print(f"[dim]Task: {step.task[:80]}...[/dim]\n")
                    
                    try:
                        self.metrics.start_iteration(len(execution.completed_steps) + 1)
                        
                        await self.agent_system.run_task(
                            task=step.task,
                            agent_name=step.agent,
                            max_iterations=step.iterations,
                            work_dir=workspace
                        )
                        
                        execution.completed_steps.append(step.step_id)
                        remaining_steps.remove(step)
                        
                        console.print(f"[bold green]✓[/bold green] {step.name} completed")
                        
                        self.metrics.end_iteration(len(execution.completed_steps), success=True)
                        
                    except Exception as e:
                        console.print(f"[bold red]✗[/bold red] {step.name} failed: {e}")
                        
                        execution.failed_steps.append(step.step_id)
                        self.metrics.end_iteration(len(execution.completed_steps) + 1, success=False, error_message=str(e))
                        
                        # Handle failure
                        if step.on_failure == "stop":
                            raise RuntimeError(f"Workflow stopped at {step.name}: {e}")
                        elif step.on_failure == "retry":
                            console.print(f"[yellow]Retrying {step.name}...[/yellow]")
                            # Will retry in next loop iteration
                        elif step.on_failure == "continue":
                            remaining_steps.remove(step)
                        else:
                            raise
            
            execution.status = WorkflowStatus.COMPLETED
            console.print(f"\n[bold green]Workflow completed successfully![/bold green]")
        
        except Exception as e:
            execution.status = WorkflowStatus.FAILED
            console.print(f"\n[bold red]Workflow failed: {e}[/bold red]")
        
        finally:
            execution.end_time = datetime.now().isoformat()
            self.current_execution = None
            
            # Collect and save metrics
            task_metrics = self.metrics.end_task(success=execution.status == WorkflowStatus.COMPLETED)
            self.metrics.save_metrics(task_metrics)
            
            # Save execution state
            self._save_execution(execution)
        
        return execution
    
    def _evaluate_condition(self, condition: str, results: Dict[str, Any]) -> bool:
        """
        Evaluate a conditional expression.
        
        Args:
            condition: Conditional expression string
            results: Results from previous steps
            
        Returns:
            True if condition is met, False otherwise
        """
        # Simple implementation: check if condition is in results
        # Can be extended with more complex expression evaluation
        return condition in results
    
    def _save_execution(self, execution: WorkflowExecution):
        """Save execution state to file."""
        filename = f"execution_{execution.workflow_id}_{execution.start_time.replace(':', '-')}.json"
        filepath = self.workflow_dir / filename
        
        data = {
            'workflow_id': execution.workflow_id,
            'status': execution.status.value,
            'current_step': execution.current_step,
            'completed_steps': execution.completed_steps,
            'failed_steps': execution.failed_steps,
            'results': execution.results,
            'start_time': execution.start_time,
            'end_time': execution.end_time
        }
        
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)
    
    def generate_report(self, execution: WorkflowExecution) -> str:
        """
        Generate a report for workflow execution.
        
        Args:
            execution: WorkflowExecution to report on
            
        Returns:
            Formatted report string
        """
        lines = [
            "\n" + "=" * 80,
            "WORKFLOW EXECUTION REPORT",
            "=" * 80,
            f"\nWorkflow: {execution.workflow_id}",
            f"Status: {execution.status.value.upper()}",
            f"\nStart Time: {execution.start_time}",
            f"End Time: {execution.end_time or 'Running...'}",
            f"\nCompleted Steps: {len(execution.completed_steps)}",
            f"Failed Steps: {len(execution.failed_steps)}",
        ]
        
        if execution.completed_steps:
            lines.extend([
                "\n" + "-" * 80,
                "Completed Steps",
                "-" * 80,
            ])
            for step in execution.completed_steps:
                lines.append(f"  ✓ {step}")
        
        if execution.failed_steps:
            lines.extend([
                "\n" + "-" * 80,
                "Failed Steps",
                "-" * 80,
            ])
            for step in execution.failed_steps:
                lines.append(f"  ✗ {step}")
        
        lines.append("\n" + "=" * 80 + "\n")
        return "\n".join(lines)
    
    def create_template_workflow(
        self,
        workflow_id: str,
        name: str,
        description: str
    ) -> WorkflowDefinition:
        """
        Create a template workflow structure.
        
        Args:
            workflow_id: Unique workflow identifier
            name: Workflow name
            description: Workflow description
            
        Returns:
            WorkflowDefinition with template structure
        """
        return WorkflowDefinition(
            workflow_id=workflow_id,
            name=name,
            description=description,
            steps=[
                WorkflowStep(
                    step_id="step1",
                    name="Initial Setup",
                    agent="ralph",
                    task="Set up the project structure and initial files",
                    dependencies=[],
                    iterations=2
                ),
                WorkflowStep(
                    step_id="step2",
                    name="Implementation",
                    agent="coder",
                    task="Implement the core functionality",
                    dependencies=["step1"],
                    iterations=5
                ),
                WorkflowStep(
                    step_id="step3",
                    name="Testing",
                    agent="tester",
                    task="Write tests and validate the implementation",
                    dependencies=["step2"],
                    iterations=3
                ),
            ]
        )
#!/usr/bin/env python3
"""
Advanced Examples for Ralph Agents

Demonstrates advanced features including:
- Checkpoints and resume
- Metrics collection
- Agent collaboration
- Workflow orchestration
"""
import asyncio
from agent_system import RalphAgentSystem
from collaboration import AgentCollaborator, CollaborationTask
from workflow import WorkflowOrchestrator, WorkflowDefinition, WorkflowStep


async def example_checkpoints():
    """Example 1: Using checkpoints for long-running tasks."""
    print("\n" + "=" * 60)
    print("Example 1: Checkpoints and Resume")
    print("=" * 60)
    
    system = RalphAgentSystem()
    
    # Run a task with checkpoints enabled
    await system.run_task(
        task="Create a Python web application with Flask",
        agent_name="coder",
        max_iterations=5,
        enable_checkpoints=True,
        checkpoint_interval=2  # Save every 2 iterations
    )
    
    # List all checkpoints
    print("\nAvailable checkpoints:")
    system.list_checkpoints()


async def example_metrics():
    """Example 2: Collecting and reporting metrics."""
    print("\n" + "=" * 60)
    print("Example 2: Metrics Collection")
    print("=" * 60)
    
    from metrics import MetricsCollector
    
    system = RalphAgentSystem()
    collector = MetricsCollector()
    
    # Start task tracking
    collector.start_task("Build a CLI tool", "coder")
    
    # Simulate some work
    for i in range(3):
        collector.start_iteration(i + 1)
        # Do work...
        collector.track_file_created()
        collector.track_file_modified()
        collector.track_tool_call("write_file")
        collector.end_iteration(i + 1, tokens_used=1000 + i * 200)
    
    # End task and get metrics
    metrics = collector.end_task(success=True)
    
    # Generate report
    print(collector.generate_report(metrics))
    
    # Save metrics to file
    filepath = collector.save_metrics(metrics)
    print(f"Metrics saved to: {filepath}")


async def example_sequential_collaboration():
    """Example 3: Sequential agent collaboration."""
    print("\n" + "=" * 60)
    print("Example 3: Sequential Collaboration")
    print("=" * 60)
    
    system = RalphAgentSystem()
    collaborator = AgentCollaborator(system)
    
    # Define tasks for different agents
    tasks = [
        {"agent": "ralph", "task": "Set up project structure and README", "iterations": 2},
        {"agent": "coder", "task": "Implement core functionality", "iterations": 3},
        {"agent": "tester", "task": "Write tests and documentation", "iterations": 2},
    ]
    
    # Execute sequentially
    results = await collaborator.execute_sequential(tasks, workspace="./collab_workspace")
    
    # Show summary
    print(collaborator.generate_summary())


async def example_parallel_collaboration():
    """Example 4: Parallel agent collaboration."""
    print("\n" + "=" * 60)
    print("Example 4: Parallel Collaboration")
    print("=" * 60)
    
    system = RalphAgentSystem()
    collaborator = AgentCollaborator(system)
    
    # Define independent tasks that can run in parallel
    tasks = [
        {"agent": "tester", "task": "Write unit tests for module A", "iterations": 2},
        {"agent": "tester", "task": "Write unit tests for module B", "iterations": 2},
        {"agent": "tester", "task": "Write integration tests", "iterations": 2},
    ]
    
    # Execute in parallel
    results = await collaborator.execute_parallel(tasks, workspace="./parallel_workspace")
    
    # Show summary
    print(collaborator.generate_summary())


async def example_dependency_aware():
    """Example 5: Collaboration with dependencies."""
    print("\n" + "=" * 60)
    print("Example 5: Dependency-Aware Collaboration")
    print("=" * 60)
    
    system = RalphAgentSystem()
    collaborator = AgentCollaborator(system)
    
    # Define tasks with dependencies
    tasks = [
        CollaborationTask(
            agent_name="coder",
            task_description="Create database models",
            dependencies=[],
            priority=1
        ),
        CollaborationTask(
            agent_name="coder",
            task_description="Implement API endpoints",
            dependencies=["Create database models"],
            priority=2
        ),
        CollaborationTask(
            agent_name="tester",
            task_description="Write tests for API endpoints",
            dependencies=["Implement API endpoints"],
            priority=3
        ),
        CollaborationTask(
            agent_name="tester",
            task_description="Write tests for database models",
            dependencies=["Create database models"],
            priority=2
        ),
    ]
    
    # Execute with dependency resolution
    results = await collaborator.execute_with_dependencies(tasks, workspace="./dep_workspace")
    
    # Show summary
    print(collaborator.generate_summary())


async def example_peer_review():
    """Example 6: Peer review workflow."""
    print("\n" + "=" * 60)
    print("Example 6: Peer Review Workflow")
    print("=" * 60)
    
    system = RalphAgentSystem()
    collaborator = AgentCollaborator(system)
    
    # Run task with peer review
    result = await collaborator.peer_review(
        task="Create a REST API for user management",
        primary_agent="coder",
        reviewer_agents=["tester", "ralph"],
        workspace="./peer_review_workspace"
    )
    
    print(f"\nPeer Review Results:")
    print(f"  Primary execution time: {result['primary_duration']:.2f}s")
    print(f"  Reviewers: {result['total_reviewers']}")
    print(f"  Feedback incorporation: {result['incorporation_duration']:.2f}s")
    print(f"  Total time: {result['total_duration']:.2f}s")


async def example_simple_workflow():
    """Example 7: Simple workflow orchestration."""
    print("\n" + "=" * 60)
    print("Example 7: Simple Workflow")
    print("=" * 60)
    
    system = RalphAgentSystem()
    collaborator = AgentCollaborator(system)
    from metrics import MetricsCollector
    
    metrics = MetricsCollector()
    orchestrator = WorkflowOrchestrator(system, collaborator, metrics)
    
    # Create a template workflow
    workflow = orchestrator.create_template_workflow(
        workflow_id="simple_app",
        name="Simple Application Build",
        description="Build a simple application with testing"
    )
    
    # Save workflow
    workflow_path = orchestrator.save_workflow(workflow)
    print(f"Workflow saved to: {workflow_path}")
    
    # Execute workflow
    execution = await orchestrator.execute_workflow(workflow, workspace="./workflow_workspace")
    
    # Show report
    print(orchestrator.generate_report(execution))


async def example_custom_workflow():
    """Example 8: Custom workflow with advanced features."""
    print("\n" + "=" * 60)
    print("Example 8: Custom Workflow")
    print("=" * 60)
    
    system = RalphAgentSystem()
    collaborator = AgentCollaborator(system)
    from metrics import MetricsCollector
    
    metrics = MetricsCollector()
    orchestrator = WorkflowOrchestrator(system, collaborator, metrics)
    
    # Create custom workflow
    workflow = WorkflowDefinition(
        workflow_id="full_stack",
        name="Full-Stack Application",
        description="Build a complete full-stack application",
        steps=[
            WorkflowStep(
                step_id="setup",
                name="Project Setup",
                agent="ralph",
                task="Set up project structure, configuration files, and documentation",
                dependencies=[],
                iterations=2,
                on_failure="stop"
            ),
            WorkflowStep(
                step_id="backend",
                name="Backend Development",
                agent="coder",
                task="Implement backend API with database integration",
                dependencies=["setup"],
                iterations=5,
                on_failure="continue"
            ),
            WorkflowStep(
                step_id="frontend",
                name="Frontend Development",
                agent="coder",
                task="Implement frontend user interface",
                dependencies=["setup"],
                iterations=5,
                on_failure="continue"
            ),
            WorkflowStep(
                step_id="integration",
                name="Integration Testing",
                agent="tester",
                task="Write integration tests and validate end-to-end functionality",
                dependencies=["backend", "frontend"],
                iterations=3,
                on_failure="continue"
            ),
            WorkflowStep(
                step_id="docs",
                name="Documentation",
                agent="ralph",
                task="Write comprehensive documentation and deployment guides",
                dependencies=["integration"],
                iterations=2,
                on_failure="continue"
            ),
        ]
    )
    
    # Save workflow
    workflow_path = orchestrator.save_workflow(workflow)
    print(f"Workflow saved to: {workflow_path}")
    
    # Execute workflow
    execution = await orchestrator.execute_workflow(workflow, workspace="./fullstack_workspace")
    
    # Show report
    print(orchestrator.generate_report(execution))


async def main():
    """Run all examples."""
    print("\n" + "=" * 80)
    print("Ralph Agents - Advanced Examples")
    print("=" * 80)
    print("\nThese examples demonstrate advanced features:")
    print("  1. Checkpoints and resume")
    print("  2. Metrics collection")
    print("  3. Sequential collaboration")
    print("  4. Parallel collaboration")
    print("  5. Dependency-aware collaboration")
    print("  6. Peer review workflow")
    print("  7. Simple workflow")
    print("  8. Custom workflow")
    print("\n" + "=" * 80)
    print("\nTo run a specific example, uncomment the desired function call below:")
    print("=" * 80 + "\n")
    
    # Uncomment the example you want to run:
    
    # await example_checkpoints()
    # await example_metrics()
    # await example_sequential_collaboration()
    # await example_parallel_collaboration()
    # await example_dependency_aware()
    # await example_peer_review()
    # await example_simple_workflow()
    # await example_custom_workflow()
    
    print("\n[bold yellow]No examples run. Please uncomment the desired example in main()[/bold yellow]")


if __name__ == "__main__":
    asyncio.run(main())
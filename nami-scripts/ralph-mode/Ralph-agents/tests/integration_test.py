#!/usr/bin/env python3
"""
Integration Tests for Ralph Agents

Comprehensive integration tests for all Ralph Agents features.
"""
import asyncio
import tempfile
import shutil
from pathlib import Path
import pytest
import json

from agent_system import RalphAgentSystem
from checkpoint import CheckpointManager, CheckpointMetadata
from metrics import MetricsCollector, TaskMetrics
from collaboration import AgentCollaborator, CollaborationTask
from workflow import WorkflowOrchestrator, WorkflowDefinition, WorkflowStep


class TestRalphAgentSystem:
    """Integration tests for Ralph Agent System."""
    
    @pytest.fixture
    def temp_workspace(self):
        """Create temporary workspace for tests."""
        workspace = tempfile.mkdtemp(prefix="ralph_test_")
        yield workspace
        shutil.rmtree(workspace, ignore_errors=True)
    
    @pytest.fixture
    def agent_system(self, temp_workspace):
        """Create agent system for testing."""
        return RalphAgentSystem(work_dir=temp_workspace)
    
    def test_system_initialization(self, agent_system):
        """Test that agent system initializes correctly."""
        assert agent_system is not None
        assert agent_system.config is not None
        assert len(agent_system.config.agents) >= 3  # ralph, coder, tester
    
    def test_agent_profile_loading(self, agent_system):
        """Test that agent profiles load correctly."""
        ralph = agent_system._get_agent_profile("ralph")
        assert ralph.name == "Ralph"
        assert ralph.color == "#ef4444"
        assert "autonomous" in ralph.system_prompt.lower()
        
        coder = agent_system._get_agent_profile("coder")
        assert coder.name == "Coder"
        assert coder.color == "#3b82f6"
        assert "code" in coder.system_prompt.lower()


class TestCheckpointSystem:
    """Integration tests for checkpoint system."""
    
    @pytest.fixture
    def temp_checkpoint_dir(self):
        """Create temporary checkpoint directory."""
        checkpoint_dir = tempfile.mkdtemp(prefix="ralph_checkpoints_")
        yield checkpoint_dir
        shutil.rmtree(checkpoint_dir, ignore_errors=True)
    
    @pytest.fixture
    def checkpoint_manager(self, temp_checkpoint_dir):
        """Create checkpoint manager for testing."""
        return CheckpointManager(temp_checkpoint_dir)
    
    def test_checkpoint_creation(self, checkpoint_manager, temp_checkpoint_dir):
        """Test creating a checkpoint."""
        checkpoint_id = checkpoint_manager.create_checkpoint(
            agent_name="coder",
            task="Build API",
            iteration=5,
            workspace_path=temp_checkpoint_dir,
            state={"iteration": 5},
            tokens_used=10000
        )
        
        assert checkpoint_id is not None
        assert checkpoint_id.endswith("pkl")
    
    def test_checkpoint_loading(self, checkpoint_manager, temp_checkpoint_dir):
        """Test loading a checkpoint."""
        # Create checkpoint
        checkpoint_id = checkpoint_manager.create_checkpoint(
            agent_name="coder",
            task="Build API",
            iteration=5,
            workspace_path=temp_checkpoint_dir,
            state={"test": "data"},
            tokens_used=10000
        )
        
        # Load checkpoint
        checkpoint = checkpoint_manager.load_checkpoint(checkpoint_id.replace(".pkl", ""))
        
        assert checkpoint is not None
        assert checkpoint.metadata.agent_name == "coder"
        assert checkpoint.metadata.iteration == 5
        assert checkpoint.state["test"] == "data"
    
    def test_checkpoint_listing(self, checkpoint_manager, temp_checkpoint_dir):
        """Test listing checkpoints."""
        # Create multiple checkpoints
        for i in range(3):
            checkpoint_manager.create_checkpoint(
                agent_name="coder",
                task=f"Task {i}",
                iteration=i,
                workspace_path=temp_checkpoint_dir,
                state={"iteration": i},
                tokens_used=1000 * i
            )
        
        # List checkpoints
        checkpoints = checkpoint_manager.list_checkpoints()
        
        assert len(checkpoints) == 3
        assert all(isinstance(cp, tuple) for cp in checkpoints)
        assert all(len(cp) == 2 for cp in checkpoints)
    
    def test_checkpoint_rotation(self, checkpoint_manager, temp_checkpoint_dir):
        """Test automatic checkpoint rotation."""
        # Create more checkpoints than max_checkpoints
        max_checkpoints = 10
        checkpoint_manager.max_checkpoints = max_checkpoints
        
        for i in range(max_checkpoints + 5):
            checkpoint_manager.create_checkpoint(
                agent_name="coder",
                task=f"Task {i}",
                iteration=i,
                workspace_path=temp_checkpoint_dir,
                state={"iteration": i},
                tokens_used=1000
            )
        
        # Check that only max_checkpoints remain
        checkpoints = checkpoint_manager.list_checkpoints()
        assert len(checkpoints) <= max_checkpoints


class TestMetricsSystem:
    """Integration tests for metrics system."""
    
    @pytest.fixture
    def temp_metrics_dir(self):
        """Create temporary metrics directory."""
        metrics_dir = tempfile.mkdtemp(prefix="ralph_metrics_")
        yield metrics_dir
        shutil.rmtree(metrics_dir, ignore_errors=True)
    
    @pytest.fixture
    def metrics_collector(self, temp_metrics_dir):
        """Create metrics collector for testing."""
        return MetricsCollector(temp_metrics_dir)
    
    def test_task_tracking(self, metrics_collector):
        """Test tracking a complete task."""
        metrics_collector.start_task("Build API", "coder")
        
        # Simulate iterations
        for i in range(3):
            metrics_collector.start_iteration(i + 1)
            metrics_collector.track_file_created()
            metrics_collector.track_file_modified()
            metrics_collector.track_tool_call("write_file")
            metrics_collector.end_iteration(i + 1, tokens_used=1000 + i * 200)
        
        # End task
        metrics = metrics_collector.end_task(success=True)
        
        assert metrics.task == "Build API"
        assert metrics.agent_name == "coder"
        assert metrics.total_iterations == 3
        assert metrics.total_files_created == 3
        assert metrics.total_files_modified == 3
        assert metrics.total_tokens_used == 3600
        assert metrics.success is True
    
    def test_metrics_saving(self, metrics_collector, temp_metrics_dir):
        """Test saving metrics to file."""
        metrics_collector.start_task("Test Task", "tester")
        metrics_collector.start_iteration(1)
        metrics_collector.end_iteration(1, tokens_used=1000)
        metrics = metrics_collector.end_task(success=True)
        
        # Save metrics
        filepath = metrics_collector.save_metrics(metrics, "test_metrics.json")
        
        assert Path(filepath).exists()
        assert filepath.name == "test_metrics.json"
        
        # Verify file content
        with open(filepath, 'r') as f:
            data = json.load(f)
        
        assert data["task"] == "Test Task"
        assert data["agent_name"] == "tester"
    
    def test_metrics_report_generation(self, metrics_collector):
        """Test generating metrics reports."""
        metrics_collector.start_task("Test Task", "tester")
        metrics_collector.start_iteration(1)
        metrics_collector.end_iteration(1, tokens_used=1000)
        metrics = metrics_collector.end_task(success=True)
        
        # Generate report
        report = metrics_collector.generate_report(metrics)
        
        assert "TASK EXECUTION REPORT" in report
        assert "Test Task" in report
        assert "tester" in report
        assert "SUCCESS" in report


class TestCollaborationSystem:
    """Integration tests for collaboration system."""
    
    @pytest.fixture
    def temp_workspace(self):
        """Create temporary workspace for tests."""
        workspace = tempfile.mkdtemp(prefix="ralph_collab_")
        yield workspace
        shutil.rmtree(workspace, ignore_errors=True)
    
    @pytest.fixture
    def collaboration_system(self, temp_workspace):
        """Create collaboration system for testing."""
        agent_system = RalphAgentSystem(work_dir=temp_workspace)
        collaborator = AgentCollaborator(agent_system)
        return collaborator
    
    def test_collaboration_task_creation(self):
        """Test creating collaboration tasks."""
        task = CollaborationTask(
            agent_name="coder",
            task_description="Build API",
            dependencies=[],
            priority=1
        )
        
        assert task.agent_name == "coder"
        assert task.task_description == "Build API"
        assert task.dependencies == []
        assert task.priority == 1
    
    def test_task_dependency_resolution(self):
        """Test that tasks with dependencies are resolved correctly."""
        tasks = [
            CollaborationTask("coder", "Task 1", [], 1),
            CollaborationTask("coder", "Task 2", ["Task 1"], 2),
            CollaborationTask("tester", "Task 3", ["Task 1"], 2),
        ]
        
        # Task 1 should be executable first (no dependencies)
        executable_first = [t for t in tasks if not t.dependencies]
        assert len(executable_first) == 1
        assert executable_first[0].task_description == "Task 1"
        
        # Tasks 2 and 3 should depend on Task 1
        dependent_on_task1 = [t for t in tasks if "Task 1" in t.dependencies]
        assert len(dependent_on_task1) == 2


class TestWorkflowSystem:
    """Integration tests for workflow system."""
    
    @pytest.fixture
    def temp_workflow_dir(self):
        """Create temporary workflow directory."""
        workflow_dir = tempfile.mkdtemp(prefix="ralph_workflows_")
        yield workflow_dir
        shutil.rmtree(workflow_dir, ignore_errors=True)
    
    @pytest.fixture
    def workflow_orchestrator(self, temp_workflow_dir):
        """Create workflow orchestrator for testing."""
        agent_system = RalphAgentSystem()
        collaborator = AgentCollaborator(agent_system)
        metrics = MetricsCollector()
        return WorkflowOrchestrator(agent_system, collaborator, metrics, temp_workflow_dir)
    
    def test_workflow_creation(self, workflow_orchestrator, temp_workflow_dir):
        """Test creating a workflow."""
        workflow = workflow_orchestrator.create_template_workflow(
            workflow_id="test_workflow",
            name="Test Workflow",
            description="A test workflow"
        )
        
        assert workflow.workflow_id == "test_workflow"
        assert workflow.name == "Test Workflow"
        assert len(workflow.steps) == 3
    
    def test_workflow_saving_and_loading(self, workflow_orchestrator, temp_workflow_dir):
        """Test saving and loading workflows."""
        # Create workflow
        workflow = workflow_orchestrator.create_template_workflow(
            workflow_id="test_workflow",
            name="Test Workflow",
            description="A test workflow"
        )
        
        # Save workflow
        filepath = workflow_orchestrator.save_workflow(workflow, "test.json")
        
        assert Path(filepath).exists()
        assert filepath.name == "test.json"
        
        # Load workflow
        loaded_workflow = workflow_orchestrator.load_workflow(str(filepath))
        
        assert loaded_workflow.workflow_id == workflow.workflow_id
        assert loaded_workflow.name == workflow.name
        assert len(loaded_workflow.steps) == len(workflow.steps)
    
    def test_workflow_step_dependencies(self):
        """Test that workflow steps have correct dependencies."""
        workflow = WorkflowDefinition(
            workflow_id="test",
            name="Test",
            description="Test workflow",
            steps=[
                WorkflowStep("step1", "Step 1", "ralph", "Task 1", [], iterations=1),
                WorkflowStep("step2", "Step 2", "coder", "Task 2", ["step1"], iterations=1),
                WorkflowStep("step3", "Step 3", "tester", "Task 3", ["step2"], iterations=1),
            ]
        )
        
        # Check dependencies
        assert workflow.steps[1].dependencies == ["step1"]
        assert workflow.steps[2].dependencies == ["step2"]
        
        # Check that step1 has no dependencies
        assert workflow.steps[0].dependencies == []


class TestVisualizer:
    """Integration tests for workflow visualizer."""
    
    def test_mermaid_generation(self):
        """Test generating Mermaid diagrams."""
        from visualizer import WorkflowVisualizer
        
        workflow = WorkflowDefinition(
            workflow_id="test",
            name="Test Workflow",
            description="Test",
            steps=[
                WorkflowStep("step1", "Step 1", "ralph", "Task 1", [], iterations=1),
                WorkflowStep("step2", "Step 2", "coder", "Task 2", ["step1"], iterations=1),
            ]
        )
        
        visualizer = WorkflowVisualizer(tempfile.mkdtemp())
        mermaid = visualizer.generate_mermaid(workflow)
        
        assert "```mermaid" in mermaid
        assert "graph TD" in mermaid
        assert "Step 1" in mermaid
        assert "Step 2" in mermaid
    
    def test_ascii_generation(self):
        """Test generating ASCII visualizations."""
        from visualizer import WorkflowVisualizer
        
        workflow = WorkflowDefinition(
            workflow_id="test",
            name="Test Workflow",
            description="Test",
            steps=[
                WorkflowStep("step1", "Step 1", "ralph", "Task 1", [], iterations=1),
            ]
        )
        
        visualizer = WorkflowVisualizer(tempfile.mkdtemp())
        ascii = visualizer.generate_ascii(workflow)
        
        assert "WORKFLOW: Test Workflow" in ascii
        assert "Step 1" in ascii
        assert "ralph" in ascii


# Run tests
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
#!/usr/bin/env python3
"""
Progress Tracking and Metrics for Ralph Agents

Provides comprehensive metrics collection, tracking, and reporting.
"""
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from collections import defaultdict


@dataclass
class IterationMetrics:
    """Metrics for a single iteration."""
    iteration_number: int
    start_time: str
    end_time: str
    duration_seconds: float
    files_created: int
    files_modified: int
    tokens_used: int
    tools_called: Dict[str, int]
    success: bool
    error_message: Optional[str] = None


@dataclass
class TaskMetrics:
    """Complete metrics for a task execution."""
    task: str
    agent_name: str
    start_time: str
    end_time: str
    total_duration_seconds: float
    total_iterations: int
    total_files_created: int
    total_files_modified: int
    total_tokens_used: int
    iterations: List[IterationMetrics]
    success: bool


class MetricsCollector:
    """
    Collects and manages metrics for agent execution.
    
    Features:
    - Track iteration-level metrics
    - Aggregate task-level metrics
    - Export to JSON/CSV
    - Generate reports
    """
    
    def __init__(self, metrics_dir: str = "./metrics"):
        """
        Initialize metrics collector.
        
        Args:
            metrics_dir: Directory to store metrics
        """
        self.metrics_dir = Path(metrics_dir)
        self.metrics_dir.mkdir(parents=True, exist_ok=True)
        
        self.current_task: Optional[str] = None
        self.current_agent: Optional[str] = None
        self.task_start_time: Optional[datetime] = None
        
        self.iterations: List[IterationMetrics] = []
        self.current_iteration_start: Optional[datetime] = None
        
        self.files_created: int = 0
        self.files_modified: int = 0
        
        self.tool_calls: Dict[str, int] = defaultdict(int)
    
    def start_task(self, task: str, agent_name: str):
        """
        Start tracking a new task.
        
        Args:
            task: Task description
            agent_name: Name of the agent
        """
        self.current_task = task
        self.current_agent = agent_name
        self.task_start_time = datetime.now()
        self.iterations = []
        self.files_created = 0
        self.files_modified = 0
        self.tool_calls = defaultdict(int)
    
    def start_iteration(self, iteration_number: int):
        """
        Start tracking a new iteration.
        
        Args:
            iteration_number: Current iteration number
        """
        self.current_iteration_start = datetime.now()
    
    def end_iteration(
        self,
        iteration_number: int,
        tokens_used: int = 0,
        success: bool = True,
        error_message: Optional[str] = None
    ):
        """
        End tracking for current iteration.
        
        Args:
            iteration_number: Current iteration number
            tokens_used: Tokens used in this iteration
            success: Whether iteration completed successfully
            error_message: Error message if iteration failed
        """
        if self.current_iteration_start is None:
            return
        
        end_time = datetime.now()
        duration = (end_time - self.current_iteration_start).total_seconds()
        
        metrics = IterationMetrics(
            iteration_number=iteration_number,
            start_time=self.current_iteration_start.isoformat(),
            end_time=end_time.isoformat(),
            duration_seconds=duration,
            files_created=self.files_created,
            files_modified=self.files_modified,
            tokens_used=tokens_used,
            tools_called=dict(self.tool_calls),
            success=success,
            error_message=error_message
        )
        
        self.iterations.append(metrics)
        
        # Reset counters for next iteration
        self.files_created = 0
        self.files_modified = 0
        self.tool_calls = defaultdict(int)
        self.current_iteration_start = None
    
    def end_task(self, success: bool = True) -> TaskMetrics:
        """
        End tracking for the current task.
        
        Args:
            success: Whether task completed successfully
            
        Returns:
            Complete task metrics
        """
        if self.task_start_time is None:
            raise RuntimeError("No task started")
        
        end_time = datetime.now()
        
        # Aggregate metrics
        total_files_created = sum(iteration.files_created for iteration in self.iterations)
        total_files_modified = sum(iteration.files_modified for iteration in self.iterations)
        total_tokens = sum(iteration.tokens_used for iteration in self.iterations)
        
        metrics = TaskMetrics(
            task=self.current_task or "",
            agent_name=self.current_agent or "unknown",
            start_time=self.task_start_time.isoformat(),
            end_time=end_time.isoformat(),
            total_duration_seconds=(end_time - self.task_start_time).total_seconds(),
            total_iterations=len(self.iterations),
            total_files_created=total_files_created,
            total_files_modified=total_files_modified,
            total_tokens_used=total_tokens,
            iterations=self.iterations,
            success=success
        )
        
        return metrics
    
    def track_file_created(self):
        """Track a file creation event."""
        self.files_created += 1
    
    def track_file_modified(self):
        """Track a file modification event."""
        self.files_modified += 1
    
    def track_tool_call(self, tool_name: str):
        """
        Track a tool usage event.
        
        Args:
            tool_name: Name of the tool called
        """
        self.tool_calls[tool_name] += 1
    
    def save_metrics(self, metrics: TaskMetrics, filename: Optional[str] = None):
        """
        Save metrics to file.
        
        Args:
            metrics: Task metrics to save
            filename: Optional filename (default: auto-generated)
        """
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"metrics_{timestamp}.json"
        
        filepath = self.metrics_dir / filename
        
        # Convert to dict (handle nested dataclasses)
        metrics_dict = {
            "task": metrics.task,
            "agent_name": metrics.agent_name,
            "start_time": metrics.start_time,
            "end_time": metrics.end_time,
            "total_duration_seconds": metrics.total_duration_seconds,
            "total_iterations": metrics.total_iterations,
            "total_files_created": metrics.total_files_created,
            "total_files_modified": metrics.total_files_modified,
            "total_tokens_used": metrics.total_tokens_used,
            "success": metrics.success,
            "iterations": [asdict(iteration) for iteration in metrics.iterations]
        }
        
        with open(filepath, 'w') as f:
            json.dump(metrics_dict, f, indent=2)
        
        return filepath
    
    def generate_report(self, metrics: TaskMetrics) -> str:
        """
        Generate a human-readable metrics report.
        
        Args:
            metrics: Task metrics to report on
            
        Returns:
            Formatted report string
        """
        lines = [
            "\n" + "=" * 80,
            "TASK EXECUTION REPORT",
            "=" * 80,
            f"\nTask: {metrics.task[:60]}...",
            f"Agent: {metrics.agent_name}",
            f"Status: {'SUCCESS' if metrics.success else 'FAILED'}",
            f"\nDuration: {metrics.total_duration_seconds:.2f} seconds",
            f"Total Iterations: {metrics.total_iterations}",
            f"\nFiles Created: {metrics.total_files_created}",
            f"Files Modified: {metrics.total_files_modified}",
            f"Total Tokens Used: {metrics.total_tokens_used:,}",
            f"Average Tokens per Iteration: {metrics.total_tokens_used // max(metrics.total_iterations, 1):,}",
        ]
        
        if metrics.iterations:
            lines.extend([
                "\n" + "-" * 80,
                "ITERATION DETAILS",
                "-" * 80,
            ])
            
            for iteration in metrics.iterations:
                status = "✓" if iteration.success else "✗"
                lines.append(
                    f"\n{status} Iteration {iteration.iteration_number}: "
                    f"{iteration.duration_seconds:.2f}s, "
                    f"{iteration.tokens_used:,} tokens, "
                    f"{iteration.files_created} files"
                )
                
                if iteration.tools_called:
                    lines.append(f"   Tools: {', '.join(iteration.tools_called.keys())}")
                
                if iteration.error_message:
                    lines.append(f"   Error: {iteration.error_message}")
        
        lines.append("\n" + "=" * 80 + "\n")
        return "\n".join(lines)
    
    def get_summary(self) -> str:
        """
        Get a summary of current metrics state.
        
        Returns:
            Formatted summary string
        """
        if not self.iterations:
            return "No iterations tracked yet."
        
        total_duration = sum(iteration.duration_seconds for iteration in self.iterations)
        avg_duration = total_duration / len(self.iterations)
        total_tokens = sum(iteration.tokens_used for iteration in self.iterations)
        
        lines = [
            f"Iterations completed: {len(self.iterations)}",
            f"Total duration: {total_duration:.2f}s",
            f"Average iteration duration: {avg_duration:.2f}s",
            f"Total tokens used: {total_tokens:,}",
            f"Files created: {self.files_created}",
            f"Files modified: {self.files_modified}",
        ]
        
        return "\n".join(lines)
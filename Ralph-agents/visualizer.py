#!/usr/bin/env python3
"""
Workflow Visualizer for Ralph Agents

Generates visual representations of workflows and agent interactions.
"""
import json
from pathlib import Path
from typing import Dict, List, Optional, Set
from dataclasses import dataclass

from workflow import WorkflowDefinition, WorkflowStep


class WorkflowVisualizer:
    """
    Generates visual representations of workflows.
    
    Supports multiple output formats:
    - Mermaid diagrams (for Markdown/HTML)
    - DOT/GraphViz format
    - ASCII art
    - HTML interactive visualization
    """
    
    def __init__(self, output_dir: str = "./visualizations"):
        """
        Initialize visualizer.
        
        Args:
            output_dir: Directory to save visualizations
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    def generate_mermaid(
        self,
        workflow: WorkflowDefinition,
        filename: Optional[str] = None
    ) -> str:
        """
        Generate Mermaid diagram for workflow.
        
        Args:
            workflow: WorkflowDefinition to visualize
            filename: Optional filename to save
            
        Returns:
            Mermaid diagram string
        """
        lines = [
            "```mermaid",
            "graph TD",
            "    %% Workflow: " + workflow.name,
            "    %% " + workflow.description,
            ""
        ]
        
        # Map step IDs to short names
        step_names = {}
        for i, step in enumerate(workflow.steps, 1):
            short_name = f"S{i}"
            step_names[step.step_id] = short_name
            lines.append(f"    {short_name}[\"{step.name}<br/>({step.agent})\"]")
        
        lines.append("")
        
        # Add dependencies
        added_dependencies: Set[tuple] = set()
        for step in workflow.steps:
            for dep in step.dependencies:
                if dep in step_names:
                    from_step = step_names[dep]
                    to_step = step_names[step.step_id]
                    if (from_step, to_step) not in added_dependencies:
                        lines.append(f"    {from_step} --> {to_step}")
                        added_dependencies.add((from_step, to_step))
        
        # Add styling
        lines.extend([
            "",
            "    %% Styling",
            "    classDef ralph fill:#ef4444,stroke:#000,color:#fff",
            "    classDef coder fill:#3b82f6,stroke:#000,color:#fff",
            "    classDef tester fill:#10b981,stroke:#000,color:#fff",
            ""
        ])
        
        # Apply agent colors
        agent_classes = {
            "ralph": "ralph",
            "coder": "coder",
            "tester": "tester"
        }
        
        for step in workflow.steps:
            if step.agent in agent_classes:
                short_name = step_names[step.step_id]
                lines.append(f"    class {short_name} {agent_classes[step.agent]}")
        
        lines.append("```")
        
        mermaid_diagram = "\n".join(lines)
        
        # Save to file
        if filename:
            filepath = self.output_dir / filename
            with open(filepath, 'w') as f:
                f.write(mermaid_diagram)
        
        return mermaid_diagram
    
    def generate_dot(
        self,
        workflow: WorkflowDefinition,
        filename: Optional[str] = None
    ) -> str:
        """
        Generate GraphViz DOT format for workflow.
        
        Args:
            workflow: WorkflowDefinition to visualize
            filename: Optional filename to save
            
        Returns:
            DOT format string
        """
        lines = [
            "digraph Workflow {",
            "    rankdir=TB;",
            "    node [shape=box, style=rounded];",
            "    fontname=\"Arial\";",
            "",
            f'    label="{workflow.name}\\n{workflow.description}";',
            "    labelloc=t;",
            "    fontsize=14;",
            ""
        ]
        
        # Agent colors
        colors = {
            "ralph": "#ef4444",
            "coder": "#3b82f6",
            "tester": "#10b981"
        }
        
        # Map step IDs to short names
        step_names = {}
        for i, step in enumerate(workflow.steps, 1):
            short_name = f"step{i}"
            step_names[step.step_id] = short_name
            
            color = colors.get(step.agent, "#999999")
            lines.append(f'    {short_name} [label="{step.name}\\n({step.agent})", fillcolor="{color}", style="filled,filled,rounded"];')
        
        lines.append("")
        
        # Add dependencies
        added_dependencies: Set[tuple] = set()
        for step in workflow.steps:
            for dep in step.dependencies:
                if dep in step_names:
                    from_step = step_names[dep]
                    to_step = step_names[step.step_id]
                    if (from_step, to_step) not in added_dependencies:
                        lines.append(f"    {from_step} -> {to_step};")
                        added_dependencies.add((from_step, to_step))
        
        lines.append("}")
        
        dot_diagram = "\n".join(lines)
        
        # Save to file
        if filename:
            filepath = self.output_dir / filename
            with open(filepath, 'w') as f:
                f.write(dot_diagram)
        
        return dot_diagram
    
    def generate_ascii(
        self,
        workflow: WorkflowDefinition,
        filename: Optional[str] = None
    ) -> str:
        """
        Generate ASCII art visualization of workflow.
        
        Args:
            workflow: WorkflowDefinition to visualize
            filename: Optional filename to save
            
        Returns:
            ASCII art string
        """
        lines = [
            "=" * 80,
            f"WORKFLOW: {workflow.name}",
            f"{workflow.description}",
            "=" * 80,
            ""
        ]
        
        # Build dependency map
        step_map = {step.step_id: step for step in workflow.steps}
        
        # Find steps with no dependencies (starting points)
        steps_by_level = []
        processed = set()
        current_level = []
        
        # Find starting steps
        for step in workflow.steps:
            if not any(dep in step_map for dep in step.dependencies):
                current_level.append(step)
        
        level = 0
        while current_level:
            steps_by_level.append((level, current_level.copy()))
            processed.update(s.step_id for s in current_level)
            
            # Find next level
            next_level = []
            for step in workflow.steps:
                if (step.step_id not in processed and 
                    all(dep in processed for dep in step.dependencies)):
                    next_level.append(step)
            
            current_level = next_level
            level += 1
        
        # Generate ASCII visualization
        for level, steps in steps_by_level:
            lines.append(f"\nLEVEL {level + 1}:")
            lines.append("-" * 80)
            
            for i, step in enumerate(steps):
                prefix = "    "
                if i == 0 and level == 0:
                    prefix = "START: "
                elif i == len(steps) - 1 and level == len(steps_by_level) - 1:
                    prefix = "END:   "
                else:
                    prefix = "      "
                
                deps_str = f" (deps: {', '.join(step.dependencies)})" if step.dependencies else ""
                
                lines.append(f"{prefix}{step.name} [{step.agent}]{deps_str}")
                
                # Show task description
                lines.append(f"      Task: {step.task[:60]}...")
                lines.append(f"      Iterations: {step.iterations}")
        
        lines.extend([
            "",
            "=" * 80,
            ""
        ])
        
        ascii_diagram = "\n".join(lines)
        
        # Save to file
        if filename:
            filepath = self.output_dir / filename
            with open(filepath, 'w') as f:
                f.write(ascii_diagram)
        
        return ascii_diagram
    
    def generate_html(
        self,
        workflow: WorkflowDefinition,
        filename: Optional[str] = None
    ) -> str:
        """
        Generate HTML interactive visualization of workflow.
        
        Args:
            workflow: WorkflowDefinition to visualize
            filename: Optional filename to save
            
        Returns:
            HTML string
        """
        html = f"""<!DOCTYPE html>
<html>
<head>
    <title>{workflow.name}</title>
    <style>
        body {{
            font-family: Arial, sans-serif;
            margin: 20px;
            background-color: #f5f5f5;
        }}
        .workflow-container {{
            max-width: 1200px;
            margin: 0 auto;
            background: white;
            padding: 20px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        h1 {{
            color: #333;
            border-bottom: 2px solid #ddd;
            padding-bottom: 10px;
        }}
        .workflow-info {{
            color: #666;
            margin-bottom: 20px;
        }}
        .steps-container {{
            display: flex;
            flex-direction: column;
            gap: 20px;
        }}
        .step {{
            padding: 15px;
            border-radius: 8px;
            border-left: 4px solid;
            transition: all 0.3s;
        }}
        .step:hover {{
            transform: translateX(5px);
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        }}
        .step-ralph {{
            background-color: #fef2f2;
            border-color: #ef4444;
        }}
        .step-coder {{
            background-color: #eff6ff;
            border-color: #3b82f6;
        }}
        .step-tester {{
            background-color: #ecfdf5;
            border-color: #10b981;
        }}
        .step-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 10px;
        }}
        .step-name {{
            font-weight: bold;
            font-size: 18px;
        }}
        .step-agent {{
            background: #333;
            color: white;
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 12px;
        }}
        .step-task {{
            color: #555;
            margin-bottom: 8px;
        }}
        .step-details {{
            display: flex;
            gap: 20px;
            font-size: 14px;
            color: #666;
        }}
        .dependencies {{
            background: #fff3cd;
            padding: 8px;
            border-radius: 4px;
            margin-top: 10px;
        }}
    </style>
</head>
<body>
    <div class="workflow-container">
        <h1>{workflow.name}</h1>
        <p class="workflow-info">{workflow.description}</p>
        
        <div class="steps-container">
"""
        
        for i, step in enumerate(workflow.steps, 1):
            agent_class = f"step-{step.agent}"
            deps_html = ""
            
            if step.dependencies:
                deps_html = f"""
                <div class="dependencies">
                    <strong>Dependencies:</strong> {', '.join(step.dependencies)}
                </div>
            """
            
            html += f"""
            <div class="step {agent_class}">
                <div class="step-header">
                    <div class="step-name">{i}. {step.name}</div>
                    <div class="step-agent">{step.agent}</div>
                </div>
                <div class="step-task">{step.task}</div>
                <div class="step-details">
                    <span>Iterations: {step.iterations}</span>
                    <span>On Failure: {step.on_failure}</span>
                </div>
                {deps_html}
            </div>
"""
        
        html += """
        </div>
    </div>
</body>
</html>
"""
        
        # Save to file
        if filename:
            filepath = self.output_dir / filename
            with open(filepath, 'w') as f:
                f.write(html)
        
        return html
    
    def generate_all(
        self,
        workflow: WorkflowDefinition,
        base_filename: str
    ) -> Dict[str, str]:
        """
        Generate all visualization formats.
        
        Args:
            workflow: WorkflowDefinition to visualize
            base_filename: Base filename (without extension)
            
        Returns:
            Dictionary mapping format to filepath
        """
        results = {}
        
        # Generate Mermaid
        mermaid_path = self.generate_mermaid(
            workflow,
            f"{base_filename}_mermaid.md"
        )
        results['mermaid'] = mermaid_path
        
        # Generate DOT
        dot_path = self.generate_dot(
            workflow,
            f"{base_filename}.dot"
        )
        results['dot'] = dot_path
        
        # Generate ASCII
        ascii_path = self.generate_ascii(
            workflow,
            f"{base_filename}_ascii.txt"
        )
        results['ascii'] = ascii_path
        
        # Generate HTML
        html_path = self.generate_html(
            workflow,
            f"{base_filename}.html"
        )
        results['html'] = html_path
        
        return results


def visualize_workflow_file(
    workflow_path: str,
    output_dir: str = "./visualizations",
    formats: List[str] = None
):
    """
    Visualize a workflow from file.
    
    Args:
        workflow_path: Path to workflow JSON file
        output_dir: Output directory for visualizations
        formats: List of formats to generate (default: all)
    """
    from workflow import WorkflowOrchestrator
    from agent_system import RalphAgentSystem
    from collaboration import AgentCollaborator
    from metrics import MetricsCollector
    
    # Load workflow
    system = RalphAgentSystem()
    collaborator = AgentCollaborator(system)
    metrics = MetricsCollector()
    orchestrator = WorkflowOrchestrator(system, collaborator, metrics)
    
    workflow = orchestrator.load_workflow(workflow_path)
    
    # Generate visualizations
    visualizer = WorkflowVisualizer(output_dir)
    base_filename = Path(workflow_path).stem
    
    if formats is None:
        # Generate all formats
        results = visualizer.generate_all(workflow, base_filename)
    else:
        # Generate specific formats
        results = {}
        for fmt in formats:
            if fmt == 'mermaid':
                results['mermaid'] = visualizer.generate_mermaid(
                    workflow, f"{base_filename}_mermaid.md"
                )
            elif fmt == 'dot':
                results['dot'] = visualizer.generate_dot(
                    workflow, f"{base_filename}.dot"
                )
            elif fmt == 'ascii':
                results['ascii'] = visualizer.generate_ascii(
                    workflow, f"{base_filename}_ascii.txt"
                )
            elif fmt == 'html':
                results['html'] = visualizer.generate_html(
                    workflow, f"{base_filename}.html"
                )
    
    print(f"\n[bold green]Visualizations generated:[/bold green]")
    for fmt, path in results.items():
        print(f"  • {fmt.upper()}: {path}")
    
    return results
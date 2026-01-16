#!/usr/bin/env python3
"""
Template Analytics

Provides analytics and insights for workflow templates including usage statistics,
agent distribution, complexity metrics, and recommendations.
"""

import json
from pathlib import Path
from typing import Dict, List, Any, Tuple
from dataclasses import dataclass
from collections import Counter


@dataclass
class TemplateAnalytics:
    """Analytics data for a single template."""
    filename: str
    workflow_id: str
    name: str
    step_count: int
    total_iterations: int
    avg_iterations_per_step: float
    agent_distribution: Dict[str, int]
    agent_percentage: Dict[str, float]
    complexity_score: float
    estimated_time_minutes: float
    dependency_depth: int
    parallel_potential: int
    failure_strategy_distribution: Dict[str, int]


class TemplateAnalyzer:
    """Analyzes workflow templates and provides insights."""

    def __init__(self, templates_dir: Path = None):
        self.templates_dir = templates_dir or (Path(__file__).parent / 'templates')

    def analyze_template(self, template_path: Path) -> TemplateAnalytics:
        """
        Analyze a single template.

        Args:
            template_path: Path to template file

        Returns:
            TemplateAnalytics with comprehensive metrics
        """
        with open(template_path, 'r') as f:
            template = json.load(f)

        steps = template.get('steps', [])

        # Basic metrics
        step_count = len(steps)
        total_iterations = sum(step.get('iterations', 0) for step in steps)
        avg_iterations_per_step = total_iterations / step_count if step_count > 0 else 0

        # Agent distribution
        agents = [step.get('agent') for step in steps]
        agent_counter = Counter(agents)
        agent_percentage = {
            agent: (count / step_count) * 100
            for agent, count in agent_counter.items()
        }

        # Complexity score (0-100)
        complexity_score = self._calculate_complexity(steps)

        # Estimated time (rough estimate: 1 iteration = 2 minutes)
        estimated_time_minutes = total_iterations * 2

        # Dependency analysis
        dependency_depth = self._calculate_dependency_depth(steps)
        parallel_potential = self._calculate_parallel_potential(steps)

        # Failure strategy distribution
        failure_strategies = [step.get('on_failure') for step in steps]
        failure_counter = Counter(failure_strategies)

        return TemplateAnalytics(
            filename=template_path.name,
            workflow_id=template.get('workflow_id'),
            name=template.get('name'),
            step_count=step_count,
            total_iterations=total_iterations,
            avg_iterations_per_step=avg_iterations_per_step,
            agent_distribution=dict(agent_counter),
            agent_percentage=agent_percentage,
            complexity_score=complexity_score,
            estimated_time_minutes=estimated_time_minutes,
            dependency_depth=dependency_depth,
            parallel_potential=parallel_potential,
            failure_strategy_distribution=dict(failure_counter)
        )

    def _calculate_complexity(self, steps: List[Dict]) -> float:
        """Calculate complexity score (0-100)."""
        if not steps:
            return 0.0

        factors = []

        # Step count factor (more steps = more complex)
        step_count = len(steps)
        factors.append(min(step_count / 20, 1.0) * 20)

        # Dependency complexity (more dependencies = more complex)
        total_deps = sum(len(step.get('dependencies', [])) for step in steps)
        factors.append(min(total_deps / (step_count * 2), 1.0) * 20)

        # Agent diversity factor (more agents = more complex)
        unique_agents = len(set(step.get('agent') for step in steps))
        factors.append(min(unique_agents / 5, 1.0) * 15)

        # Iteration factor (more iterations = more complex)
        total_iterations = sum(step.get('iterations', 0) for step in steps)
        avg_iterations = total_iterations / step_count if step_count > 0 else 0
        factors.append(min(avg_iterations / 10, 1.0) * 20)

        # Depth factor (deeper dependency chains = more complex)
        depth = self._calculate_dependency_depth(steps)
        factors.append(min(depth / 10, 1.0) * 15)

        # Parallel complexity (more parallel potential = more complex)
        parallel = self._calculate_parallel_potential(steps)
        factors.append(min(parallel / step_count, 1.0) * 10)

        return sum(factors)

    def _calculate_dependency_depth(self, steps: List[Dict]) -> int:
        """Calculate maximum depth of dependency chain."""
        if not steps:
            return 0

        step_map = {step['step_id']: step for step in steps}
        depths = {step_id: 0 for step_id in step_map}

        def get_depth(step_id: str) -> int:
            if step_id not in step_map:
                return 0

            step = step_map[step_id]
            deps = step.get('dependencies', [])

            if not deps:
                return 1

            max_dep_depth = max(get_depth(dep) for dep in deps if dep in step_map)
            return max_dep_depth + 1

        return max(get_depth(step_id) for step_id in step_map)

    def _calculate_parallel_potential(self, steps: List[Dict]) -> int:
        """Calculate number of steps that can run in parallel."""
        if not steps:
            return 0

        # Count steps with no dependencies
        no_deps = sum(1 for step in steps if not step.get('dependencies'))
        return no_deps

    def analyze_all(self) -> List[TemplateAnalytics]:
        """Analyze all templates in the templates directory."""
        analytics = []

        if not self.templates_dir.exists():
            print(f"Templates directory not found: {self.templates_dir}")
            return analytics

        for template_file in self.templates_dir.glob('*.json'):
            # Skip README if it exists
            if template_file.name == 'README.md':
                continue

            try:
                analytics.append(self.analyze_template(template_file))
            except Exception as e:
                print(f"Error analyzing {template_file.name}: {e}")

        return analytics

    def print_analytics(self, analytics: List[TemplateAnalytics]):
        """Print analytics for all templates."""
        if not analytics:
            print("No analytics to display.")
            return

        print("\n" + "=" * 80)
        print("TEMPLATE ANALYTICS")
        print("=" * 80)

        for idx, template in enumerate(analytics, 1):
            print(f"\n[{idx}] {template.name}")
            print(f"    File: {template.filename}")
            print(f"    Workflow ID: {template.workflow_id}")
            print(f"    Steps: {template.step_count}")
            print(f"    Total Iterations: {template.total_iterations}")
            print(f"    Avg Iterations/Step: {template.avg_iterations_per_step:.1f}")
            print(f"    Estimated Time: {template.estimated_time_minutes:.0f} minutes")
            print(f"    Complexity Score: {template.complexity_score:.1f}/100")
            print(f"    Dependency Depth: {template.dependency_depth}")
            print(f"    Parallel Potential: {template.parallel_potential} steps")

            print("\n    Agent Distribution:")
            for agent, count in template.agent_distribution.items():
                percentage = template.agent_percentage[agent]
                print(f"      - {agent}: {count} steps ({percentage:.1f}%)")

            print("\n    Failure Strategies:")
            for strategy, count in template.failure_strategy_distribution.items():
                print(f"      - {strategy}: {count} steps")

            print("\n    Complexity Breakdown:")
            if template.complexity_score < 30:
                complexity_level = "Low"
            elif template.complexity_score < 60:
                complexity_level = "Medium"
            else:
                complexity_level = "High"
            print(f"      Level: {complexity_level}")

    def print_summary(self, analytics: List[TemplateAnalytics]):
        """Print summary statistics across all templates."""
        if not analytics:
            print("No analytics to display.")
            return

        print("\n" + "=" * 80)
        print("ANALYTICS SUMMARY")
        print("=" * 80)

        total_templates = len(analytics)
        total_steps = sum(t.step_count for t in analytics)
        total_iterations = sum(t.total_iterations for t in analytics)
        avg_complexity = sum(t.complexity_score for t in analytics) / total_templates
        total_time = sum(t.estimated_time_minutes for t in analytics)

        print(f"\nTotal Templates: {total_templates}")
        print(f"Total Steps: {total_steps}")
        print(f"Total Iterations: {total_iterations}")
        print(f"Average Complexity: {avg_complexity:.1f}/100")
        print(f"Total Estimated Time: {total_time:.0f} minutes ({total_time/60:.1f} hours)")

        # Agent usage across all templates
        all_agents = []
        for template in analytics:
            all_agents.extend(template.agent_distribution.keys())

        agent_counter = Counter(all_agents)
        print("\nOverall Agent Usage:")
        for agent, count in agent_counter.most_common():
            percentage = (count / total_steps) * 100
            print(f"  - {agent}: {count} steps ({percentage:.1f}%)")

        # Most complex templates
        sorted_by_complexity = sorted(analytics, key=lambda x: x.complexity_score, reverse=True)
        print("\nMost Complex Templates:")
        for template in sorted_by_complexity[:3]:
            print(f"  - {template.name}: {template.complexity_score:.1f}/100")

        # Longest templates
        sorted_by_time = sorted(analytics, key=lambda x: x.estimated_time_minutes, reverse=True)
        print("\nLongest Templates (Estimated Time):")
        for template in sorted_by_time[:3]:
            print(f"  - {template.name}: {template.estimated_time_minutes:.0f} minutes")

        print("\n" + "=" * 80)

    def get_recommendations(self, template: TemplateAnalytics) -> List[str]:
        """Generate recommendations for a template."""
        recommendations = []

        # Complexity recommendations
        if template.complexity_score > 80:
            recommendations.append(
                "⚠️ High complexity: Consider breaking into smaller workflows"
            )

        # Iteration recommendations
        if template.avg_iterations_per_step > 10:
            recommendations.append(
                "💡 High iteration count: Consider breaking down complex steps"
            )

        # Agent balance recommendations
        if 'ralph' in template.agent_percentage:
            ralph_pct = template.agent_percentage['ralph']
            if ralph_pct > 60:
                recommendations.append(
                    "💡 Consider using more specialized agents (coder, tester)"
                )

        # Dependency recommendations
        if template.dependency_depth > 8:
            recommendations.append(
                "💡 Deep dependency chain: Consider flattening workflow structure"
            )

        # Parallel potential recommendations
        if template.parallel_potential > 3 and template.step_count > 5:
            recommendations.append(
                "✅ Good parallel potential: Many steps can run simultaneously"
            )

        # Failure strategy recommendations
        stop_count = template.failure_strategy_distribution.get('stop', 0)
        if stop_count / template.step_count > 0.7:
            recommendations.append(
                "⚠️ High failure intolerance: Consider using 'continue' for non-critical steps"
            )

        # Time recommendations
        if template.estimated_time_minutes > 180:  # 3 hours
            recommendations.append(
                "💡 Long estimated duration: Consider enabling checkpoints"
            )

        if not recommendations:
            recommendations.append("✅ Template looks well-optimized!")

        return recommendations

    def print_recommendations(self, analytics: List[TemplateAnalytics]):
        """Print recommendations for all templates."""
        print("\n" + "=" * 80)
        print("RECOMMENDATIONS")
        print("=" * 80)

        for idx, template in enumerate(analytics, 1):
            print(f"\n[{idx}] {template.name}")
            recommendations = self.get_recommendations(template)
            for rec in recommendations:
                print(f"    {rec}")

        print("\n" + "=" * 80)


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Analyze Ralph Agents workflow templates"
    )
    parser.add_argument(
        'template',
        nargs='?',
        help="Template file to analyze (analyzes all if not specified)"
    )
    parser.add_argument(
        '--summary', '-s',
        action='store_true',
        help="Show summary statistics only"
    )
    parser.add_argument(
        '--recommendations', '-r',
        action='store_true',
        help="Show recommendations"
    )

    args = parser.parse_args()

    analyzer = TemplateAnalyzer()

    if args.template:
        # Analyze single template
        template_path = Path(args.template)
        if not template_path.is_absolute():
            template_path = analyzer.templates_dir / args.template

        if not template_path.exists():
            print(f"Template not found: {args.template}")
            return

        analytics = analyzer.analyze_template(template_path)
        analyzer.print_analytics([analytics])

        if args.recommendations:
            analyzer.print_recommendations([analytics])

    else:
        # Analyze all templates
        analytics = analyzer.analyze_all()

        if not analytics:
            print("No templates found.")
            return

        if args.summary:
            analyzer.print_summary(analytics)
        else:
            analyzer.print_analytics(analytics)

        if args.recommendations:
            analyzer.print_recommendations(analytics)

        if not args.summary:
            analyzer.print_summary(analytics)


if __name__ == '__main__':
    main()
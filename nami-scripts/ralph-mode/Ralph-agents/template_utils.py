#!/usr/bin/env python3
"""
Template Utilities for Ralph Agents

Provides utilities for comparing, merging, and manipulating workflow templates.
"""

import json
import sys
from pathlib import Path
from typing import Dict, List, Any, Optional, Set
from dataclasses import dataclass
from copy import deepcopy


@dataclass
class TemplateDiff:
    """Represents differences between two templates."""
    workflow_id: str
    added_steps: List[Dict]
    removed_steps: List[Dict]
    modified_steps: List[Dict]
    metadata_diffs: List[str]


class TemplateUtils:
    """Utility functions for working with workflow templates."""

    def __init__(self, templates_dir: Optional[Path] = None):
        self.templates_dir = templates_dir or (Path(__file__).parent / 'templates')

    def load_template(self, template_path: Path) -> Dict[str, Any]:
        """Load a template from file."""
        with open(template_path, 'r') as f:
            return json.load(f)

    def save_template(self, template: Dict[str, Any], output_path: Path):
        """Save a template to file."""
        with open(output_path, 'w') as f:
            json.dump(template, f, indent=2)

    def compare_templates(self, template1_path: Path, template2_path: Path) -> TemplateDiff:
        """
        Compare two templates and return differences.

        Args:
            template1_path: Path to first template
            template2_path: Path to second template

        Returns:
            TemplateDiff with differences
        """
        t1 = self.load_template(template1_path)
        t2 = self.load_template(template2_path)

        workflow_id = f"{t1['workflow_id']} vs {t2['workflow_id']}"

        # Compare metadata
        metadata_diffs = []
        for key in ['name', 'description']:
            if key in t1 and key in t2 and t1[key] != t2[key]:
                metadata_diffs.append(f"{key}: '{t1[key]}' → '{t2[key]}'")

        # Compare steps
        steps1 = {step['step_id']: step for step in t1['steps']}
        steps2 = {step['step_id']: step for step in t2['steps']}

        ids1 = set(steps1.keys())
        ids2 = set(steps2.keys())

        # Added steps (in t2 but not t1)
        added_steps = [steps2[step_id] for step_id in ids2 - ids1]

        # Removed steps (in t1 but not t2)
        removed_steps = [steps1[step_id] for step_id in ids1 - ids2]

        # Modified steps (in both but different)
        modified_steps = []
        for step_id in ids1 & ids2:
            if steps1[step_id] != steps2[step_id]:
                modified_steps.append({
                    'step_id': step_id,
                    'old': steps1[step_id],
                    'new': steps2[step_id]
                })

        return TemplateDiff(
            workflow_id=workflow_id,
            added_steps=added_steps,
            removed_steps=removed_steps,
            modified_steps=modified_steps,
            metadata_diffs=metadata_diffs
        )

    def print_diff(self, diff: TemplateDiff, verbose: bool = False):
        """Print template differences."""
        print(f"\n{'='*60}")
        print(f"COMPARISON: {diff.workflow_id}")
        print(f"{'='*60}")

        if diff.metadata_diffs:
            print("\n📝 Metadata Changes:")
            for change in diff.metadata_diffs:
                print(f"  • {change}")

        if diff.added_steps:
            print(f"\n➕ Added Steps ({len(diff.added_steps)}):")
            for step in diff.added_steps:
                print(f"  • {step['step_id']}: {step['name']}")
                if verbose:
                    print(f"    Task: {step['task'][:80]}...")

        if diff.removed_steps:
            print(f"\n➖ Removed Steps ({len(diff.removed_steps)}):")
            for step in diff.removed_steps:
                print(f"  • {step['step_id']}: {step['name']}")

        if diff.modified_steps:
            print(f"\n✏️  Modified Steps ({len(diff.modified_steps)}):")
            for step in diff.modified_steps:
                print(f"  • {step['step_id']}: {step['old']['name']}")
                if verbose:
                    old_task = step['old']['task'][:60]
                    new_task = step['new']['task'][:60]
                    print(f"    - Task: {old_task}... → {new_task}...")

        if not any([diff.metadata_diffs, diff.added_steps, diff.removed_steps, diff.modified_steps]):
            print("\n✅ Templates are identical!")

    def merge_templates(
        self,
        base_template: Dict[str, Any],
        overlay_template: Dict[str, Any],
        strategy: str = 'overlay'
    ) -> Dict[str, Any]:
        """
        Merge two templates.

        Args:
            base_template: Base template
            overlay_template: Overlay template (changes to apply)
            strategy: Merge strategy ('overlay' or 'append')

        Returns:
            Merged template
        """
        merged = deepcopy(base_template)

        if strategy == 'overlay':
            # Overlay strategy: overlay template values override base
            merged['name'] = overlay_template.get('name', merged['name'])
            merged['description'] = overlay_template.get('description', merged['description'])

            # Merge steps by step_id
            base_steps = {step['step_id']: step for step in merged['steps']}
            overlay_steps = {step['step_id']: step for step in overlay_template['steps']}

            # Overlay steps
            for step_id, step in overlay_steps.items():
                if step_id in base_steps:
                    base_steps[step_id] = step
                else:
                    base_steps[step_id] = step

            merged['steps'] = list(base_steps.values())

        elif strategy == 'append':
            # Append strategy: append steps from overlay to base
            merged['steps'] = merged['steps'] + overlay_template['steps']
            merged['name'] = f"{merged['name']} + {overlay_template['name']}"

        # Reorder steps by dependencies (topological sort)
        merged['steps'] = self._topological_sort(merged['steps'])

        return merged

    def extract_steps(
        self,
        template_path: Path,
        step_ids: List[str],
        output_path: Optional[Path] = None
    ) -> Dict[str, Any]:
        """
        Extract specific steps from a template.

        Args:
            template_path: Source template
            step_ids: List of step IDs to extract
            output_path: Optional path to save extracted template

        Returns:
            Extracted template
        """
        template = self.load_template(template_path)
        step_map = {step['step_id']: step for step in template['steps']}

        extracted_steps = []
        for step_id in step_ids:
            if step_id in step_map:
                extracted_steps.append(step_map[step_id])

        # Remove dependencies to steps that weren't extracted
        extracted_ids = {step['step_id'] for step in extracted_steps}
        for step in extracted_steps:
            step['dependencies'] = [
                dep for dep in step['dependencies'] if dep in extracted_ids
            ]

        extracted_template = {
            'workflow_id': f"{template['workflow_id']}_extracted",
            'name': f"{template['name']} (Extracted)",
            'description': f"Extracted steps from {template['name']}",
            'steps': extracted_steps
        }

        if output_path:
            self.save_template(extracted_template, output_path)
            print(f"Saved extracted template to: {output_path}")

        return extracted_template

    def filter_by_agent(
        self,
        template_path: Path,
        agent_name: str,
        output_path: Optional[Path] = None
    ) -> Dict[str, Any]:
        """
        Filter template to only include steps for a specific agent.

        Args:
            template_path: Source template
            agent_name: Agent to filter by
            output_path: Optional path to save filtered template

        Returns:
            Filtered template
        """
        template = self.load_template(template_path)

        filtered_steps = [
            step for step in template['steps']
            if step.get('agent') == agent_name
        ]

        # Remove dependencies to steps that were filtered out
        filtered_ids = {step['step_id'] for step in filtered_steps}
        for step in filtered_steps:
            step['dependencies'] = [
                dep for dep in step['dependencies'] if dep in filtered_ids
            ]

        filtered_template = {
            'workflow_id': f"{template['workflow_id']}_{agent_name}",
            'name': f"{template['name']} ({agent_name} only)",
            'description': f"Filtered to only {agent_name} steps",
            'steps': filtered_steps
        }

        if output_path:
            self.save_template(filtered_template, output_path)
            print(f"Saved filtered template to: {output_path}")

        return filtered_template

    def _topological_sort(self, steps: List[Dict]) -> List[Dict]:
        """Topologically sort steps by dependencies."""
        step_map = {step['step_id']: step for step in steps}
        visited = set()
        result = []
        temp_visited = set()

        def visit(step_id: str):
            if step_id in temp_visited:
                raise ValueError(f"Circular dependency detected involving '{step_id}'")
            if step_id in visited:
                return

            temp_visited.add(step_id)

            if step_id in step_map:
                step = step_map[step_id]
                for dep in step.get('dependencies', []):
                    if dep in step_map:
                        visit(dep)

            temp_visited.remove(step_id)
            visited.add(step_id)
            if step_id in step_map:
                result.append(step_map[step_id])

        for step in steps:
            if step['step_id'] not in visited:
                visit(step['step_id'])

        return result

    def list_templates(self) -> List[Path]:
        """List all template files in the templates directory."""
        if not self.templates_dir.exists():
            return []

        return list(self.templates_dir.glob('*.json'))

    def get_template_info(self, template_path: Path) -> Dict[str, Any]:
        """Get summary information about a template."""
        template = self.load_template(template_path)

        return {
            'filename': template_path.name,
            'workflow_id': template.get('workflow_id'),
            'name': template.get('name'),
            'description': template.get('description', '')[:100] + '...',
            'step_count': len(template.get('steps', [])),
            'total_iterations': sum(step.get('iterations', 0) for step in template.get('steps', [])),
            'agents': list(set(step.get('agent') for step in template.get('steps', []))),
            'has_cycles': False  # Could implement cycle detection here
        }


def main():
    """Main entry point for CLI usage."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Template utilities for Ralph Agents"
    )
    subparsers = parser.add_subparsers(dest='command', help='Available commands')

    # Compare command
    compare_parser = subparsers.add_parser('compare', help='Compare two templates')
    compare_parser.add_argument('template1', help='First template file')
    compare_parser.add_argument('template2', help='Second template file')
    compare_parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')

    # List command
    list_parser = subparsers.add_parser('list', help='List all templates')

    # Info command
    info_parser = subparsers.add_parser('info', help='Get template information')
    info_parser.add_argument('template', help='Template file')

    # Extract command
    extract_parser = subparsers.add_parser('extract', help='Extract steps from template')
    extract_parser.add_argument('template', help='Template file')
    extract_parser.add_argument('step_ids', nargs='+', help='Step IDs to extract')
    extract_parser.add_argument('--output', '-o', help='Output file path')

    # Filter command
    filter_parser = subparsers.add_parser('filter', help='Filter template by agent')
    filter_parser.add_argument('template', help='Template file')
    filter_parser.add_argument('agent', help='Agent name to filter by')
    filter_parser.add_argument('--output', '-o', help='Output file path')

    args = parser.parse_args()

    utils = TemplateUtils()

    if args.command == 'compare':
        # Resolve template paths
        t1_path = Path(args.template1)
        if not t1_path.is_absolute():
            t1_path = utils.templates_dir / args.template1

        t2_path = Path(args.template2)
        if not t2_path.is_absolute():
            t2_path = utils.templates_dir / args.template2

        diff = utils.compare_templates(t1_path, t2_path)
        utils.print_diff(diff, verbose=args.verbose)

    elif args.command == 'list':
        templates = utils.list_templates()
        print("\nAvailable Templates:")
        print("=" * 60)
        for template_path in templates:
            info = utils.get_template_info(template_path)
            print(f"\n📄 {info['filename']}")
            print(f"   Name: {info['name']}")
            print(f"   Steps: {info['step_count']}")
            print(f"   Agents: {', '.join(info['agents'])}")
            print(f"   Description: {info['description']}")

    elif args.command == 'info':
        template_path = Path(args.template)
        if not template_path.is_absolute():
            template_path = utils.templates_dir / args.template

        info = utils.get_template_info(template_path)
        print(f"\nTemplate Information: {info['filename']}")
        print("=" * 60)
        for key, value in info.items():
            if key != 'filename':
                print(f"{key.replace('_', ' ').title()}: {value}")

    elif args.command == 'extract':
        template_path = Path(args.template)
        if not template_path.is_absolute():
            template_path = utils.templates_dir / args.template

        output_path = Path(args.output) if args.output else None
        extracted = utils.extract_steps(template_path, args.step_ids, output_path)
        print(f"\nExtracted {len(extracted['steps'])} steps")

    elif args.command == 'filter':
        template_path = Path(args.template)
        if not template_path.is_absolute():
            template_path = utils.templates_dir / args.template

        output_path = Path(args.output) if args.output else None
        filtered = utils.filter_by_agent(template_path, args.agent, output_path)
        print(f"\nFiltered to {len(filtered['steps'])} steps for agent '{args.agent}'")

    else:
        parser.print_help()


if __name__ == '__main__':
    main()
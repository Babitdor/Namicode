#!/usr/bin/env python3
"""
Workflow Template Validator

Validates workflow templates against the Ralph Agents schema and checks for common issues.
"""

import json
import sys
from pathlib import Path
from typing import Dict, List, Any, Tuple
from dataclasses import dataclass


@dataclass
class ValidationResult:
    """Result of template validation."""
    is_valid: bool
    errors: List[str]
    warnings: List[str]
    filename: str


class TemplateValidator:
    """Validates workflow templates."""

    # Valid agent names (can be extended from config)
    VALID_AGENTS = {'ralph', 'coder', 'tester'}

    # Valid failure strategies
    VALID_FAILURE_STRATEGIES = {'stop', 'continue', 'retry'}

    # Required top-level fields
    REQUIRED_TOP_LEVEL = {'workflow_id', 'name', 'description', 'steps'}

    # Required step fields
    REQUIRED_STEP_FIELDS = {
        'step_id', 'name', 'agent', 'task', 'dependencies', 'iterations', 'on_failure'
    }

    def __init__(self):
        self.templates_dir = Path(__file__).parent / 'templates'

    def validate_template(self, template_path: Path) -> ValidationResult:
        """
        Validate a single workflow template.

        Args:
            template_path: Path to the template file

        Returns:
            ValidationResult with errors and warnings
        """
        errors = []
        warnings = []

        # Load JSON
        try:
            with open(template_path, 'r') as f:
                template = json.load(f)
        except json.JSONDecodeError as e:
            return ValidationResult(
                is_valid=False,
                errors=[f"Invalid JSON: {e}"],
                warnings=[],
                filename=template_path.name
            )
        except Exception as e:
            return ValidationResult(
                is_valid=False,
                errors=[f"Failed to read file: {e}"],
                warnings=[],
                filename=template_path.name
            )

        # Validate top-level structure
        missing_fields = self.REQUIRED_TOP_LEVEL - set(template.keys())
        if missing_fields:
            errors.append(f"Missing required top-level fields: {missing_fields}")

        # Validate workflow_id
        if 'workflow_id' in template:
            if not template['workflow_id'] or not isinstance(template['workflow_id'], str):
                errors.append("workflow_id must be a non-empty string")

        # Validate name
        if 'name' in template:
            if not template['name'] or not isinstance(template['name'], str):
                errors.append("name must be a non-empty string")

        # Validate description
        if 'description' in template:
            if not template['description'] or not isinstance(template['description'], str):
                errors.append("description must be a non-empty string")

        # Validate steps
        if 'steps' not in template:
            errors.append("Missing 'steps' field")
        else:
            if not isinstance(template['steps'], list):
                errors.append("'steps' must be a list")
            elif len(template['steps']) == 0:
                errors.append("'steps' list cannot be empty")
            else:
                step_errors, step_warnings = self._validate_steps(template['steps'])
                errors.extend(step_errors)
                warnings.extend(step_warnings)

        # Check for cycles in dependencies
        if 'steps' in template and isinstance(template['steps'], list):
            cycle_errors = self._check_cycles(template['steps'])
            errors.extend(cycle_errors)

        is_valid = len(errors) == 0

        return ValidationResult(
            is_valid=is_valid,
            errors=errors,
            warnings=warnings,
            filename=template_path.name
        )

    def _validate_steps(self, steps: List[Dict]) -> Tuple[List[str], List[str]]:
        """Validate all steps in the workflow."""
        errors = []
        warnings = []
        step_ids = set()

        for idx, step in enumerate(steps):
            step_prefix = f"Step {idx} ({step.get('step_id', 'UNKNOWN')})"

            # Check required fields
            missing = self.REQUIRED_STEP_FIELDS - set(step.keys())
            if missing:
                errors.append(f"{step_prefix}: Missing required fields: {missing}")

            # Validate step_id
            if 'step_id' in step:
                if not step['step_id'] or not isinstance(step['step_id'], str):
                    errors.append(f"{step_prefix}: step_id must be a non-empty string")
                elif step['step_id'] in step_ids:
                    errors.append(f"{step_prefix}: Duplicate step_id '{step['step_id']}'")
                else:
                    step_ids.add(step['step_id'])

            # Validate name
            if 'name' in step:
                if not step['name'] or not isinstance(step['name'], str):
                    errors.append(f"{step_prefix}: name must be a non-empty string")

            # Validate agent
            if 'agent' in step:
                if step['agent'] not in self.VALID_AGENTS:
                    warnings.append(
                        f"{step_prefix}: Agent '{step['agent']}' not in known list: {self.VALID_AGENTS}"
                    )

            # Validate task
            if 'task' in step:
                if not step['task'] or not isinstance(step['task'], str):
                    errors.append(f"{step_prefix}: task must be a non-empty string")

            # Validate dependencies
            if 'dependencies' in step:
                if not isinstance(step['dependencies'], list):
                    errors.append(f"{step_prefix}: dependencies must be a list")
                else:
                    for dep in step['dependencies']:
                        if not isinstance(dep, str):
                            errors.append(f"{step_prefix}: dependency '{dep}' must be a string")

            # Validate iterations
            if 'iterations' in step:
                if not isinstance(step['iterations'], int) or step['iterations'] < 0:
                    errors.append(f"{step_prefix}: iterations must be a non-negative integer")

            # Validate on_failure
            if 'on_failure' in step:
                if step['on_failure'] not in self.VALID_FAILURE_STRATEGIES:
                    errors.append(
                        f"{step_prefix}: on_failure must be one of {self.VALID_FAILURE_STRATEGIES}"
                    )

        return errors, warnings

    def _check_cycles(self, steps: List[Dict]) -> List[str]:
        """Check for circular dependencies in steps."""
        errors = []
        step_map = {step['step_id']: step for step in steps if 'step_id' in step}

        def has_cycle(step_id: str, visited: set, rec_stack: set) -> bool:
            """DFS to detect cycles."""
            visited.add(step_id)
            rec_stack.add(step_id)

            step = step_map.get(step_id)
            if step and 'dependencies' in step:
                for dep in step['dependencies']:
                    if dep not in visited:
                        if has_cycle(dep, visited, rec_stack):
                            return True
                    elif dep in rec_stack:
                        return True

            rec_stack.remove(step_id)
            return False

        visited = set()
        for step in steps:
            step_id = step.get('step_id')
            if step_id and step_id not in visited:
                if has_cycle(step_id, visited, set()):
                    errors.append(f"Circular dependency detected involving step '{step_id}'")

        return errors

    def validate_all(self) -> Dict[str, ValidationResult]:
        """Validate all templates in the templates directory."""
        results = {}

        if not self.templates_dir.exists():
            print(f"Error: Templates directory not found: {self.templates_dir}")
            return results

        template_files = list(self.templates_dir.glob('*.json'))
        if not template_files:
            print(f"No template files found in {self.templates_dir}")
            return results

        for template_file in template_files:
            # Skip README.md if it's in the directory
            if template_file.name == 'README.md':
                continue

            result = self.validate_template(template_file)
            results[template_file.name] = result

        return results

    def print_result(self, result: ValidationResult):
        """Print validation result for a single template."""
        status = "✅ VALID" if result.is_valid else "❌ INVALID"
        print(f"\n{status}: {result.filename}")
        print(f"{'='*60}")

        if result.errors:
            print(f"\n❌ Errors ({len(result.errors)}):")
            for error in result.errors:
                print(f"  • {error}")

        if result.warnings:
            print(f"\n⚠️  Warnings ({len(result.warnings)}):")
            for warning in result.warnings:
                print(f"  • {warning}")

        if result.is_valid and not result.warnings:
            print("\n✅ Template is valid with no issues!")

    def print_summary(self, results: Dict[str, ValidationResult]):
        """Print summary of all validation results."""
        total = len(results)
        valid = sum(1 for r in results.values() if r.is_valid)
        invalid = total - valid
        total_errors = sum(len(r.errors) for r in results.values())
        total_warnings = sum(len(r.warnings) for r in results.values())

        print(f"\n{'='*60}")
        print("VALIDATION SUMMARY")
        print(f"{'='*60}")
        print(f"Total templates: {total}")
        print(f"Valid: {valid} ✅")
        print(f"Invalid: {invalid} ❌")
        print(f"Total errors: {total_errors}")
        print(f"Total warnings: {total_warnings}")
        print(f"{'='*60}\n")

        return invalid == 0


def main():
    """Main entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Validate Ralph Agents workflow templates"
    )
    parser.add_argument(
        'template',
        nargs='?',
        help="Template file to validate (validates all if not specified)"
    )
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help="Show detailed output for all templates"
    )

    args = parser.parse_args()

    validator = TemplateValidator()

    if args.template:
        # Validate single template
        template_path = Path(args.template)
        if not template_path.is_absolute():
            # Try relative to templates directory
            template_path = validator.templates_dir / args.template

        if not template_path.exists():
            print(f"❌ Template not found: {args.template}")
            sys.exit(1)

        result = validator.validate_template(template_path)
        validator.print_result(result)
        sys.exit(0 if result.is_valid else 1)

    else:
        # Validate all templates
        results = validator.validate_all()

        if not results:
            print("No templates to validate.")
            sys.exit(1)

        # Print detailed results if verbose
        if args.verbose:
            for result in results.values():
                validator.print_result(result)

        # Always print summary
        all_valid = validator.print_summary(results)
        sys.exit(0 if all_valid else 1)


if __name__ == '__main__':
    main()
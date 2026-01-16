#!/usr/bin/env python3
"""
Template System Tests

Comprehensive tests for workflow templates, validator, and utilities.
"""

import json
import pytest
import tempfile
from pathlib import Path

# Import the classes to test
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from template_validator import TemplateValidator, ValidationResult
from template_utils import TemplateUtils


class TestTemplateValidator:
    """Test the template validator functionality."""

    @pytest.fixture
    def validator(self):
        """Create a validator instance."""
        return TemplateValidator()

    @pytest.fixture
    def valid_template(self):
        """Create a minimal valid template."""
        return {
            "workflow_id": "test_workflow",
            "name": "Test Workflow",
            "description": "A test workflow",
            "steps": [
                {
                    "step_id": "step1",
                    "name": "Step 1",
                    "agent": "ralph",
                    "task": "Test task",
                    "dependencies": [],
                    "iterations": 5,
                    "on_failure": "stop"
                }
            ]
        }

    @pytest.fixture
    def temp_template_file(self, valid_template):
        """Create a temporary template file."""
        temp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
        json.dump(valid_template, temp_file)
        temp_file.close()
        yield Path(temp_file.name)
        # Cleanup
        Path(temp_file.name).unlink(missing_ok=True)

    def test_valid_template(self, validator, temp_template_file):
        """Test that a valid template passes validation."""
        result = validator.validate_template(temp_template_file)
        assert result.is_valid
        assert len(result.errors) == 0

    def test_missing_top_level_fields(self, validator, temp_dir):
        """Test validation of missing top-level fields."""
        incomplete_template = {
            "workflow_id": "test",
            "name": "Test"
            # Missing 'description' and 'steps'
        }

        temp_file = temp_dir / "incomplete.json"
        with open(temp_file, 'w') as f:
            json.dump(incomplete_template, f)

        result = validator.validate_template(temp_file)
        assert not result.is_valid
        assert any('description' in error for error in result.errors)
        assert any('steps' in error for error in result.errors)

    def test_invalid_json(self, validator, temp_dir):
        """Test validation of invalid JSON."""
        temp_file = temp_dir / "invalid.json"
        with open(temp_file, 'w') as f:
            f.write("{{ invalid json }}")

        result = validator.validate_template(temp_file)
        assert not result.is_valid
        assert any('Invalid JSON' in error for error in result.errors)

    def test_duplicate_step_ids(self, validator, temp_dir):
        """Test detection of duplicate step IDs."""
        template_with_duplicates = {
            "workflow_id": "test",
            "name": "Test",
            "description": "Test",
            "steps": [
                {
                    "step_id": "duplicate",
                    "name": "Step 1",
                    "agent": "ralph",
                    "task": "Task 1",
                    "dependencies": [],
                    "iterations": 5,
                    "on_failure": "stop"
                },
                {
                    "step_id": "duplicate",
                    "name": "Step 2",
                    "agent": "coder",
                    "task": "Task 2",
                    "dependencies": [],
                    "iterations": 5,
                    "on_failure": "stop"
                }
            ]
        }

        temp_file = temp_dir / "duplicates.json"
        with open(temp_file, 'w') as f:
            json.dump(template_with_duplicates, f)

        result = validator.validate_template(temp_file)
        assert not result.is_valid
        assert any('Duplicate step_id' in error for error in result.errors)

    def test_circular_dependencies(self, validator, temp_dir):
        """Test detection of circular dependencies."""
        template_with_cycle = {
            "workflow_id": "test",
            "name": "Test",
            "description": "Test",
            "steps": [
                {
                    "step_id": "step1",
                    "name": "Step 1",
                    "agent": "ralph",
                    "task": "Task 1",
                    "dependencies": ["step2"],
                    "iterations": 5,
                    "on_failure": "stop"
                },
                {
                    "step_id": "step2",
                    "name": "Step 2",
                    "agent": "ralph",
                    "task": "Task 2",
                    "dependencies": ["step1"],
                    "iterations": 5,
                    "on_failure": "stop"
                }
            ]
        }

        temp_file = temp_dir / "cycle.json"
        with open(temp_file, 'w') as f:
            json.dump(template_with_cycle, f)

        result = validator.validate_template(temp_file)
        assert not result.is_valid
        assert any('Circular dependency' in error for error in result.errors)

    def test_invalid_agent_name(self, validator, temp_dir):
        """Test validation of invalid agent names."""
        template_with_invalid_agent = {
            "workflow_id": "test",
            "name": "Test",
            "description": "Test",
            "steps": [
                {
                    "step_id": "step1",
                    "name": "Step 1",
                    "agent": "invalid_agent",
                    "task": "Task",
                    "dependencies": [],
                    "iterations": 5,
                    "on_failure": "stop"
                }
            ]
        }

        temp_file = temp_dir / "invalid_agent.json"
        with open(temp_file, 'w') as f:
            json.dump(template_with_invalid_agent, f)

        result = validator.validate_template(temp_file)
        # Invalid agent should be a warning, not an error
        assert any('not in known list' in warning for warning in result.warnings)

    def test_invalid_failure_strategy(self, validator, temp_dir):
        """Test validation of invalid failure strategies."""
        template_with_invalid_strategy = {
            "workflow_id": "test",
            "name": "Test",
            "description": "Test",
            "steps": [
                {
                    "step_id": "step1",
                    "name": "Step 1",
                    "agent": "ralph",
                    "task": "Task",
                    "dependencies": [],
                    "iterations": 5,
                    "on_failure": "invalid_strategy"
                }
            ]
        }

        temp_file = temp_dir / "invalid_strategy.json"
        with open(temp_file, 'w') as f:
            json.dump(template_with_invalid_strategy, f)

        result = validator.validate_template(temp_file)
        assert not result.is_valid
        assert any('on_failure must be one of' in error for error in result.errors)

    def test_validate_all_templates(self, validator):
        """Test validating all templates in the templates directory."""
        if validator.templates_dir.exists():
            results = validator.validate_all()
            # Should find all template files
            assert len(results) > 0

            # Check that basic templates exist and are valid
            basic_templates = [
                'python_package.json',
                'web_application.json',
                'rest_api.json'
            ]
            for template_name in basic_templates:
                if template_name in results:
                    assert results[template_name].is_valid, f"{template_name} should be valid"


class TestTemplateUtils:
    """Test the template utilities functionality."""

    @pytest.fixture
    def utils(self):
        """Create a TemplateUtils instance."""
        return TemplateUtils()

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory."""
        temp_dir = Path(tempfile.mkdtemp())
        yield temp_dir
        # Cleanup
        import shutil
        shutil.rmtree(temp_dir, ignore_errors=True)

    @pytest.fixture
    def template1(self, temp_dir):
        """Create first test template."""
        template = {
            "workflow_id": "template1",
            "name": "Template 1",
            "description": "First template",
            "steps": [
                {
                    "step_id": "step1",
                    "name": "Step 1",
                    "agent": "ralph",
                    "task": "Task 1",
                    "dependencies": [],
                    "iterations": 5,
                    "on_failure": "stop"
                }
            ]
        }
        path = temp_dir / "template1.json"
        with open(path, 'w') as f:
            json.dump(template, f)
        return path

    @pytest.fixture
    def template2(self, temp_dir):
        """Create second test template."""
        template = {
            "workflow_id": "template2",
            "name": "Template 2",
            "description": "Second template",
            "steps": [
                {
                    "step_id": "step2",
                    "name": "Step 2",
                    "agent": "coder",
                    "task": "Task 2",
                    "dependencies": [],
                    "iterations": 10,
                    "on_failure": "continue"
                }
            ]
        }
        path = temp_dir / "template2.json"
        with open(path, 'w') as f:
            json.dump(template, f)
        return path

    def test_load_template(self, utils, template1):
        """Test loading a template from file."""
        template = utils.load_template(template1)
        assert template['workflow_id'] == 'template1'
        assert len(template['steps']) == 1

    def test_save_template(self, utils, temp_dir):
        """Test saving a template to file."""
        template = {
            "workflow_id": "test",
            "name": "Test",
            "description": "Test",
            "steps": []
        }
        output_path = temp_dir / "saved.json"
        utils.save_template(template, output_path)

        assert output_path.exists()

        # Verify content
        loaded = utils.load_template(output_path)
        assert loaded['workflow_id'] == 'test'

    def test_compare_templates(self, utils, template1, template2):
        """Test comparing two templates."""
        diff = utils.compare_templates(template1, template2)

        assert diff.workflow_id
        assert len(diff.added_steps) > 0
        assert len(diff.removed_steps) > 0

    def test_merge_templates_overlay(self, utils, temp_dir):
        """Test merging templates with overlay strategy."""
        merged = utils.merge_templates(
            utils.load_template(template1),
            utils.load_template(template2),
            strategy='overlay'
        )

        assert merged['name'] == 'Template 2'  # Should be overwritten
        assert len(merged['steps']) == 2  # Should have both steps

    def test_merge_templates_append(self, utils, temp_dir):
        """Test merging templates with append strategy."""
        merged = utils.merge_templates(
            utils.load_template(template1),
            utils.load_template(template2),
            strategy='append'
        )

        assert 'Template 1 + Template 2' in merged['name']
        assert len(merged['steps']) == 2

    def test_extract_steps(self, utils, template1, temp_dir):
        """Test extracting specific steps from a template."""
        output_path = temp_dir / "extracted.json"
        extracted = utils.extract_steps(
            template1,
            ['step1'],
            output_path=output_path
        )

        assert len(extracted['steps']) == 1
        assert extracted['steps'][0]['step_id'] == 'step1'
        assert output_path.exists()

    def test_filter_by_agent(self, utils, temp_dir):
        """Test filtering template by agent."""
        # Create template with multiple agents
        template = {
            "workflow_id": "test",
            "name": "Test",
            "description": "Test",
            "steps": [
                {
                    "step_id": "step1",
                    "name": "Step 1",
                    "agent": "ralph",
                    "task": "Task 1",
                    "dependencies": [],
                    "iterations": 5,
                    "on_failure": "stop"
                },
                {
                    "step_id": "step2",
                    "name": "Step 2",
                    "agent": "coder",
                    "task": "Task 2",
                    "dependencies": [],
                    "iterations": 5,
                    "on_failure": "stop"
                },
                {
                    "step_id": "step3",
                    "name": "Step 3",
                    "agent": "coder",
                    "task": "Task 3",
                    "dependencies": [],
                    "iterations": 5,
                    "on_failure": "stop"
                }
            ]
        }

        template_path = temp_dir / "multi_agent.json"
        with open(template_path, 'w') as f:
            json.dump(template, f)

        output_path = temp_dir / "filtered.json"
        filtered = utils.filter_by_agent(
            template_path,
            'coder',
            output_path=output_path
        )

        assert len(filtered['steps']) == 2
        assert all(step['agent'] == 'coder' for step in filtered['steps'])

    def test_get_template_info(self, utils, template1):
        """Test getting template information."""
        info = utils.get_template_info(template1)

        assert info['filename'] == template1.name
        assert info['workflow_id'] == 'template1'
        assert info['name'] == 'Template 1'
        assert info['step_count'] == 1
        assert info['total_iterations'] == 5
        assert 'ralph' in info['agents']

    def test_list_templates(self, utils):
        """Test listing all templates."""
        if utils.templates_dir.exists():
            templates = utils.list_templates()
            assert len(templates) > 0

            # All should be JSON files
            for template in templates:
                assert template.suffix == '.json'


class TestTemplateStructure:
    """Test the structure of actual template files."""

    @pytest.fixture
    def templates_dir(self):
        """Get the templates directory."""
        return Path(__file__).parent.parent / 'templates'

    def test_all_templates_are_valid_json(self, templates_dir):
        """Test that all template files are valid JSON."""
        if not templates_dir.exists():
            pytest.skip("Templates directory not found")

        for template_file in templates_dir.glob('*.json'):
            with open(template_file, 'r') as f:
                try:
                    data = json.load(f)
                    assert isinstance(data, dict)
                except json.JSONDecodeError as e:
                    pytest.fail(f"{template_file.name} is not valid JSON: {e}")

    def test_all_templates_have_required_fields(self, templates_dir):
        """Test that all templates have required top-level fields."""
        if not templates_dir.exists():
            pytest.skip("Templates directory not found")

        required_fields = {'workflow_id', 'name', 'description', 'steps'}

        for template_file in templates_dir.glob('*.json'):
            with open(template_file, 'r') as f:
                data = json.load(f)
                missing = required_fields - set(data.keys())
                assert not missing, f"{template_file.name} missing fields: {missing}"

    def test_all_steps_have_required_fields(self, templates_dir):
        """Test that all steps have required fields."""
        if not templates_dir.exists():
            pytest.skip("Templates directory not found")

        required_step_fields = {
            'step_id', 'name', 'agent', 'task',
            'dependencies', 'iterations', 'on_failure'
        }

        for template_file in templates_dir.glob('*.json'):
            with open(template_file, 'r') as f:
                data = json.load(f)
                for step in data.get('steps', []):
                    missing = required_step_fields - set(step.keys())
                    assert not missing, \
                        f"{template_file.name} step {step.get('step_id')} missing fields: {missing}"

    def test_template_workflow_ids_are_unique(self, templates_dir):
        """Test that all templates have unique workflow_ids."""
        if not templates_dir.exists():
            pytest.skip("Templates directory not found")

        workflow_ids = []

        for template_file in templates_dir.glob('*.json'):
            with open(template_file, 'r') as f:
                data = json.load(f)
                workflow_id = data.get('workflow_id')

                assert workflow_id, f"{template_file.name} has no workflow_id"
                assert workflow_id not in workflow_ids, \
                    f"Duplicate workflow_id '{workflow_id}' in {template_file.name}"
                workflow_ids.append(workflow_id)

    def test_step_ids_are_unique_within_template(self, templates_dir):
        """Test that step IDs are unique within each template."""
        if not templates_dir.exists():
            pytest.skip("Templates directory not found")

        for template_file in templates_dir.glob('*.json'):
            with open(template_file, 'r') as f:
                data = json.load(f)
                step_ids = [step['step_id'] for step in data.get('steps', [])]

                assert len(step_ids) == len(set(step_ids)), \
                    f"{template_file.name} has duplicate step IDs"


# Fixtures
@pytest.fixture
def temp_dir():
    """Create a temporary directory for tests."""
    import tempfile
    import shutil

    temp_dir = Path(tempfile.mkdtemp())
    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == '__main__':
    # Run tests
    pytest.main([__file__, '-v'])
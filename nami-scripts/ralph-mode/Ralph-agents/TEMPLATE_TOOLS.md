# Ralph Agents - Template Tools Guide

Complete guide for working with workflow templates in Ralph Agents.

## Overview

Ralph Agents provides 9 production-ready workflow templates and comprehensive tooling for creating, validating, and managing them.

## Available Templates

### Basic Templates

#### 1. Python Package Development
**File**: `templates/python_package.json`
- **Steps**: 7
- **Iterations**: 28
- **Use Case**: Creating Python packages from scratch
- **Workflow**: Setup → Implementation → Tests → Documentation → Packaging → Review

#### 2. Web Application Development
**File**: `templates/web_application.json`
- **Steps**: 8
- **Iterations**: 36
- **Use Case**: Full-stack web applications
- **Workflow**: Setup → Backend → Frontend → Database → Testing → Deployment

#### 3. REST API Development
**File**: `templates/rest_api.json`
- **Steps**: 8
- **Iterations**: 33
- **Use Case**: API-first development
- **Workflow**: Design → Setup → Models → Endpoints → Auth → Testing → Docs

#### 4. Testing Workflow
**File**: `templates/testing_workflow.json`
- **Steps**: 9
- **Iterations**: 32
- **Use Case**: Comprehensive testing strategy
- **Workflow**: Planning → Setup → Unit → Integration → E2E → Execution → Coverage

#### 5. Documentation Workflow
**File**: `templates/documentation_workflow.json`
- **Steps**: 11
- **Iterations**: 34
- **Use Case**: Complete documentation creation
- **Workflow**: Planning → README → API Docs → Guides → Examples → Tutorials

### Advanced Templates

#### 6. Machine Learning Model Development
**File**: `templates/ml_model.json`
- **Steps**: 11
- **Iterations**: 51
- **Use Case**: End-to-end ML model development
- **Workflow**: Problem Definition → Data Collection → Preprocessing → Feature Engineering → Model Selection → Training → Evaluation → Optimization → Testing → Documentation → Deployment

#### 7. DevOps/CI-CD Pipeline
**File**: `templates/devops_pipeline.json`
- **Steps**: 10
- **Iterations**: 51
- **Use Case**: Infrastructure and CI/CD setup
- **Workflow**: Planning → IaC → Containerization → CI → CD → Monitoring → Security → Backup → Testing → Docs

#### 8. Data Processing Pipeline
**File**: `templates/data_processing.json`
- **Steps**: 10
- **Iterations**: 48
- **Use Case**: ETL and data pipeline development
- **Workflow**: Requirements → Ingestion → Transformation → Validation → Storage → Orchestration → Optimization → Testing → Monitoring → Docs

#### 9. Microservices Architecture
**File**: `templates/microservices.json`
- **Steps**: 12
- **Iterations**: 68
- **Use Case**: Distributed microservices development
- **Workflow**: Architecture Design → API Design → Skeleton → Implementation → Communication → Data → Auth → Observability → Testing → Containerization → Deployment → Docs

## Template Tools

### 1. Template Validator

Validate workflow templates for correctness and completeness.

**Usage:**
```bash
# Validate all templates
python -m template_validator

# Validate single template
python -m template_validator templates/python_package.json

# Validate with verbose output
python -m template_validator --verbose
```

**What it validates:**
- JSON syntax
- Required fields (workflow_id, name, description, steps)
- Step structure (step_id, name, agent, task, dependencies, iterations, on_failure)
- Agent names (ralph, coder, tester)
- Failure strategies (stop, continue, retry)
- No circular dependencies
- No duplicate step IDs

**Output:**
```
============================================================
VALIDATION SUMMARY
============================================================
Total templates: 9
Valid: 9
Invalid: 0
Total errors: 0
Total warnings: 0
============================================================
```

### 2. Template Utilities

Comprehensive tools for managing templates.

#### List Templates
```bash
python -m template_utils list
```

Shows all available templates with metadata:
- Template filename
- Name
- Step count
- Agents used
- Description

#### Get Template Info
```bash
python -m template_utils info python_package.json
```

Displays detailed information:
- Workflow ID
- Name
- Description
- Step count
- Total iterations
- Agents used
- Cycle detection

#### Compare Templates
```bash
python -m template_utils compare template1.json template2.json
python -m template_utils compare python_package.json web_application.json --verbose
```

Shows differences:
- Metadata changes
- Added steps
- Removed steps
- Modified steps

#### Extract Steps
```bash
python -m template_utils extract workflow.json step1 step2 --output extracted.json
```

Extracts specific steps:
- Selects steps by ID
- Removes dependencies to non-extracted steps
- Saves to new file

#### Filter by Agent
```bash
python -m template_utils filter workflow.json coder --output coder_workflow.json
```

Filters template:
- Keeps only steps for specified agent
- Removes dependencies to filtered steps
- Saves to new file

## Template Usage

### Execute a Template Directly

```bash
cd Ralph-agents
python cli.py workflow --execute templates/python_package.json
```

### Copy and Customize

```bash
# Copy template
cp templates/python_package.json my_package.json

# Edit my_package.json to customize
# - Change workflow_id
# - Update name and description
# - Modify step tasks
# - Adjust iterations

# Execute custom template
python cli.py workflow --execute my_package.json
```

### Visualize Before Execution

```bash
# Show workflow structure
python cli.py workflow --show templates/rest_api.json

# Generate visualizations
python -c "
from visualizer import WorkflowVisualizer
from workflow import WorkflowOrchestrator

orchestrator = WorkflowOrchestrator()
workflow = orchestrator.load_workflow('templates/python_package.json')
visualizer = WorkflowVisualizer()
visualizer.generate_all(workflow, 'python_package')
"
```

## Creating Custom Templates

### Method 1: Copy and Modify

```bash
# Start with similar template
cp templates/python_package.json my_custom.json

# Edit to customize
# - Update workflow_id (must be unique)
# - Change name and description
# - Add/remove/modify steps
# - Adjust iterations and dependencies
```

### Method 2: Create from Scratch

Create a JSON file with this structure:

```json
{
  "workflow_id": "unique_id",
  "name": "Workflow Name",
  "description": "Detailed description of what this workflow does",
  "steps": [
    {
      "step_id": "unique_step_id",
      "name": "Step Name",
      "agent": "ralph",
      "task": "Detailed task description",
      "dependencies": [],
      "iterations": 5,
      "on_failure": "stop"
    }
  ]
}
```

**Required Fields:**
- `workflow_id`: Unique identifier
- `name`: Human-readable name
- `description`: Detailed description
- `steps`: Array of workflow steps

**Step Fields:**
- `step_id`: Unique step identifier
- `name`: Step name
- `agent`: Agent to use (ralph, coder, tester)
- `task`: Task description
- `dependencies`: Array of step IDs this depends on
- `iterations`: Max iterations (0 = unlimited)
- `on_failure`: Failure strategy (stop, continue, retry)

### Method 3: Use Template Creation Scripts

```bash
# Create basic templates
python create_templates.py

# Create advanced templates
python create_additional_templates.py
```

## Best Practices

### Template Design

1. **Start Simple**: Begin with minimal steps, add complexity gradually
2. **Use Dependencies**: Define clear dependencies between steps
3. **Set Realistic Iterations**: Don't set too low or too high
4. **Choose Right Agents**: Use agents appropriate for each task
5. **Clear Tasks**: Provide detailed, actionable task descriptions
6. **Test Locally**: Test templates on small tasks first

### Dependency Management

```json
{
  "step_id": "implement",
  "dependencies": ["setup", "design"],
  // This step depends on 'setup' and 'design' completing first
}
```

**Best Practices:**
- Keep dependencies minimal
- Use topological ordering
- Avoid circular dependencies
- Test dependency resolution

### Failure Strategies

```json
{
  "on_failure": "stop"      // Stop workflow on failure
  "on_failure": "continue"  // Continue to next step
  "on_failure": "retry"     // Retry up to 3 times
}
```

**When to use:**
- `stop`: Critical steps where failure means workflow should halt
- `continue`: Non-critical steps where workflow can proceed
- `retry`: Steps that may fail transiently

### Agent Selection

- **ralph**: Planning, documentation, general tasks, setup
- **coder**: Implementation, technical tasks, configuration
- **tester**: Testing, validation, quality assurance, review

## Template Examples

### Example 1: Simple Workflow

```json
{
  "workflow_id": "simple_workflow",
  "name": "Simple Development",
  "description": "A simple development workflow",
  "steps": [
    {
      "step_id": "setup",
      "name": "Setup",
      "agent": "ralph",
      "task": "Set up project structure",
      "dependencies": [],
      "iterations": 2
    },
    {
      "step_id": "implement",
      "name": "Implement",
      "agent": "coder",
      "task": "Implement features",
      "dependencies": ["setup"],
      "iterations": 10
    },
    {
      "step_id": "test",
      "name": "Test",
      "agent": "tester",
      "task": "Write and run tests",
      "dependencies": ["implement"],
      "iterations": 5
    }
  ]
}
```

### Example 2: Parallel Execution

```json
{
  "steps": [
    {
      "step_id": "module_a",
      "name": "Build Module A",
      "agent": "coder",
      "task": "Build module A",
      "dependencies": []
    },
    {
      "step_id": "module_b",
      "name": "Build Module B",
      "agent": "coder",
      "task": "Build module B",
      "dependencies": []
      // No dependencies - runs in parallel with module_a
    },
    {
      "step_id": "integration",
      "name": "Integrate",
      "agent": "coder",
      "task": "Integrate modules",
      "dependencies": ["module_a", "module_b"]
      // Runs after both modules complete
    }
  ]
}
```

### Example 3: Conditional Steps

```json
{
  "steps": [
    {
      "step_id": "optional",
      "name": "Optional Enhancement",
      "agent": "coder",
      "task": "Add optional features",
      "condition": "previous_step.success == true"
      // Executes only if condition is met
    }
  ]
}
```

## Troubleshooting

### Template Validation Fails

1. **Check JSON syntax**: Use a JSON validator
2. **Verify required fields**: All top-level and step fields must be present
3. **Check agent names**: Must be one of (ralph, coder, tester)
4. **Verify dependencies**: No circular dependencies, all referenced steps exist
5. **Run validator**: `python template_validator.py your_template.json`

### Workflow Doesn't Execute

1. **Validate template**: Run validator first
2. **Check workflow_id**: Must be unique
3. **Verify dependencies**: All dependencies must resolve correctly
4. **Review task descriptions**: Must be clear and actionable
5. **Check iterations**: Reasonable number of iterations for each step

### Steps Execute in Wrong Order

1. **Check dependencies**: Dependencies define execution order
2. **Topological sort**: Workflow orchestrator handles this automatically
3. **Visualize workflow**: Use visualizer to see execution graph
4. **Review step IDs**: Ensure dependencies reference correct step IDs

## Integration with CLI

### Workflow Commands

```bash
# List available workflows
python cli.py workflow --list

# Create new workflow from template
python cli.py workflow --create my_workflow --name "My Workflow"

# Execute workflow
python cli.py workflow --execute my_workflow.json

# Show workflow details
python cli.py workflow --show my_workflow.json
```

### Running with Options

```bash
# Execute with custom workspace
python cli.py workflow --execute template.json --workdir ./my-project

# Resume from checkpoint
python cli.py workflow --execute template.json --resume checkpoint_id

# Enable checkpoints during execution
python cli.py workflow --execute template.json --checkpoints --checkpoint-interval 1
```

## Advanced Usage

### Template Composition

```bash
# Extract specific steps from multiple templates
python template_utils.py extract template1.json step1 step2 --output part1.json
python template_utils.py extract template2.json step3 step4 --output part2.json

# Manually merge if needed, or use Python API
from template_utils import TemplateUtils

utils = TemplateUtils()
merged = utils.merge_templates(
    utils.load_template('part1.json'),
    utils.load_template('part2.json'),
    strategy='overlay'
)
utils.save_template(merged, 'combined.json')
```

### Template Filtering

```bash
# Get all tasks for a specific agent
python template_utils.py filter ml_model.json coder --output coder_tasks.json

# Extract only testing steps
python template_utils.py filter web_application.json tester --output testing.json
```

## Performance Tips

1. **Optimize Iterations**: Balance thoroughness with efficiency
2. **Use Parallel Execution**: Independent steps run simultaneously
3. **Enable Checkpoints**: Resume workflows after interruptions
4. **Monitor Progress**: Use metrics to track workflow execution
5. **Validate Before Execution**: Catch issues early

## Further Reading

- **Main README**: System overview and basic usage
- **API Documentation**: Complete API reference
- **Iteration Summaries**: Development history and features

## Support

For issues or questions:
1. Check template validation output
2. Review workflow execution logs
3. Use template utilities for debugging
4. Visualize workflow to understand structure
5. Reference example templates for patterns
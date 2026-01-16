# Ralph Agents Workflow Templates

This directory contains pre-built workflow templates for common development scenarios.

## Available Templates

### 🐍 Python Package Development
**File**: `python_package.json`

Complete workflow for creating a Python package from scratch:
- Project setup and structure
- Code implementation
- Testing
- Documentation
- Packaging

**Usage**:
```bash
# Copy template
cp templates/python_package.json my_package_workflow.json

# Customize the task description
# Then execute
python cli.py workflow --execute my_package_workflow.json
```

### 🌐 Web Application Development
**File**: `web_application.json`

Full-stack web application development workflow:
- Frontend development
- Backend API development
- Database integration
- Testing
- Deployment preparation

### 🔌 REST API Development
**File**: `rest_api.json`

API-first development workflow:
- API design and documentation
- Endpoint implementation
- Authentication
- Testing
- API documentation

### ✅ Testing Workflow
**File**: `testing_workflow.json`

Comprehensive testing workflow:
- Test planning
- Unit test writing
- Integration test writing
- Test execution
- Coverage analysis

### 📚 Documentation Workflow
**File**: `documentation_workflow.json`

Complete documentation creation:
- README creation
- API documentation
- User guides
- Code examples
- Documentation review

## Using Templates

### 1. Copy a Template
```bash
cp templates/python_package.json my_workflow.json
```

### 2. Customize the Template
Edit `my_workflow.json`:
- Change `name` and `description`
- Update task descriptions in each step
- Adjust iteration counts
- Modify agent assignments
- Add or remove steps as needed

### 3. Execute the Workflow
```bash
python cli.py workflow --execute my_workflow.json
```

### 4. Monitor Progress
```bash
# Show workflow visualization
python cli.py workflow --show my_workflow.json

# View real-time progress (if metrics enabled)
tail -f metrics/latest.json
```

## Template Structure

Each template is a JSON file with the following structure:

```json
{
  "workflow_id": "unique_id",
  "name": "Workflow Name",
  "description": "Workflow description",
  "steps": [
    {
      "step_id": "step1",
      "name": "Step Name",
      "agent": "agent_name",
      "task": "Task description",
      "dependencies": [],
      "iterations": 5,
      "condition": null,
      "on_failure": "stop"
    }
  ]
}
```

### Available Fields

- **workflow_id**: Unique identifier (required)
- **name**: Human-readable name (required)
- **description**: Detailed description (required)
- **steps**: Array of workflow steps (required)
  - **step_id**: Unique step identifier (required)
  - **name**: Step name (required)
  - **agent**: Agent to use (ralph, coder, tester) (required)
  - **task**: Task description (required)
  - **dependencies**: Array of step IDs this depends on (optional)
  - **iterations**: Maximum iterations (0 = unlimited) (optional, default: 0)
  - **condition**: Conditional expression (optional)
  - **on_failure**: Failure strategy (stop, continue, retry) (optional, default: "stop")

### Failure Strategies

- **stop**: Stop workflow execution (default)
- **continue**: Continue with next step
- **retry**: Retry the step up to 3 times

### Conditional Execution

Use `condition` to execute steps conditionally:

```json
{
  "condition": "previous_step_success == true"
}
```

## Custom Templates

### Creating a Custom Template

1. Start with an existing template as a base
2. Copy it to your workspace
3. Modify steps, agents, and tasks
4. Save and execute

### Best Practices

1. **Start Simple**: Begin with a minimal workflow and add complexity gradually
2. **Use Dependencies**: Define clear dependencies between steps
3. **Set Realistic Iterations**: Don't set iterations too low or too high
4. **Choose Right Agents**: Use agents appropriate for each task
5. **Test Locally**: Test workflows on small tasks before large projects
6. **Use Checkpoints**: Enable checkpoints for long-running workflows
7. **Monitor Metrics**: Keep metrics enabled to track progress

### Example: Simple Custom Workflow

```json
{
  "workflow_id": "my_custom_workflow",
  "name": "My Custom Workflow",
  "description": "A simple custom workflow",
  "steps": [
    {
      "step_id": "setup",
      "name": "Setup",
      "agent": "ralph",
      "task": "Set up the project structure",
      "dependencies": [],
      "iterations": 2
    },
    {
      "step_id": "implement",
      "name": "Implement",
      "agent": "coder",
      "task": "Implement the core features",
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

## Workflow Examples

### Example 1: Python Package with Tests
```bash
# Use the built-in template
python cli.py workflow --execute templates/python_package.json
```

### Example 2: Sequential Agent Collaboration
```bash
# Use CLI collaborate command
python cli.py collaborate --mode sequential \
  --tasks "ralph:Setup;coder:Implement;tester:Test"
```

### Example 3: Peer Review Workflow
```bash
# Use CLI peer review mode
python cli.py collaborate --mode peer_review \
  --task "Build API" --primary coder --reviewers tester,ralph
```

## Advanced Features

### Parallel Execution
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
    }
  ]
}
```

### Error Handling
```json
{
  "step_id": "risky_step",
  "name": "Risky Step",
  "agent": "coder",
  "task": "Complex implementation",
  "on_failure": "retry"
}
```

### Conditional Steps
```json
{
  "step_id": "optional_step",
  "name": "Optional Step",
  "agent": "coder",
  "task": "Optional enhancement",
  "condition": "previous_step.tokens_used > 1000"
}
```

## Troubleshooting

### Workflow Fails

1. Check logs: `cat ralph.log`
2. Review metrics: `python cli.py metrics --show latest.json`
3. Verify checkpoints: `python cli.py checkpoint --list`
4. Visualize workflow: `python cli.py workflow --show my_workflow.json`

### Agent Gets Stuck

1. Increase iterations
2. Check task clarity
3. Enable checkpoints
4. Monitor real-time metrics

### Workflow Not Progressing

1. Check dependencies are correct
2. Verify agent availability: `python cli.py agents`
3. Review previous step output
4. Check for error conditions

## Contributing

To contribute a new template:

1. Create the template JSON file
2. Add documentation to this README
3. Test the template thoroughly
4. Submit a pull request

Template contributions welcome for:
- New development workflows
- Language-specific templates
- Framework-specific templates
- DevOps workflows
- Documentation workflows
- Testing workflows

## License

Templates follow the same license as Ralph Agents.
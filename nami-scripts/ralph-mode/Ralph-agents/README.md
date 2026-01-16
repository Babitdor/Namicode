# Ralph Agents

A flexible autonomous agent system built on top of Nami-Code DeepAgents. Ralph agents work in iterative loops, using the filesystem and git as persistent memory.

## Features

- **Multiple Agent Profiles**: Pre-configured agents for different tasks (ralph, coder, tester)
- **Iterative Execution**: Agents work in loops, building progress incrementally
- **Configuration-Based**: YAML configuration for easy customization
- **Workspace Management**: Automatic workspace setup and file tracking
- **Flexible Model Support**: Works with any model supported by Nami-Code

## Installation

Ralph Agents is part of Nami-Code. Make sure you have the dependencies installed:

```bash
# From the Nami-Code project root
uv pip install -e .
uv pip install pyyaml
```

## Quick Start

### Using the CLI

```bash
# List available agents
cd Ralph-agents
python agent_system.py --list

# Run a task with the default agent (ralph)
python agent_system.py "Create a Python CLI tool"

# Run with specific agent
python agent_system.py "Build a REST API" --agent coder

# Limit iterations
python agent_system.py "Create a web app" --iterations 5

# Use custom workspace
python agent_system.py "Build a library" --workdir ./my-project
```

### Using the Python API

```python
import asyncio
from agent_system import RalphAgentSystem

async def main():
    system = RalphAgentSystem()
    
    # Run a task
    await system.run_task(
        task="Create a Python package",
        agent_name="ralph",
        max_iterations=10
    )

asyncio.run(main())
```

## Configuration

Edit `config.yaml` to customize your agents:

```yaml
# Add new agents
agents:
  researcher:
    name: "Researcher"
    description: "Research and documentation specialist"
    color: "#8b5cf6"
    system_prompt: |
      You are a researcher specializing in documentation and research.

# Configure task routing
task_categories:
  research: "researcher"
  documentation: "researcher"
```

## Available Agents

### Ralph (Default)
- **Purpose**: General-purpose autonomous agent
- **Color**: Red (#ef4444)
- **Best for**: Multi-step tasks that require iteration and context building

### Coder
- **Purpose**: Code generation and refactoring
- **Color**: Blue (#3b82f6)
- **Best for**: Writing clean code, implementing features, refactoring

### Tester
- **Purpose**: Testing and quality assurance
- **Color**: Green (#10b981)
- **Best for**: Writing tests, finding bugs, validating requirements

## Agent Philosophy

Ralph agents follow these principles:

1. **Filesystem as Memory**: The filesystem stores all progress
2. **Git for Tracking**: Use git to commit progress after each iteration
3. **Fresh Context**: Each iteration starts with a fresh view of the current state
4. **Incremental Progress**: Make small, measurable improvements each loop
5. **Check Before Create**: Always review what exists before creating new files

## Example Workflows

### Building a Python Package

```bash
python agent_system.py \
  "Create a Python package for data processing with pandas" \
  --agent coder \
  --iterations 8
```

### Creating a Web Application

```bash
python agent_system.py \
  "Build a task management web app with React and FastAPI" \
  --agent coder \
  --iterations 15
```

### Testing a Project

```bash
python agent_system.py \
  "Write comprehensive tests for the authentication module" \
  --agent tester \
  --iterations 5
```

## File Structure

```
Ralph-agents/
├── config.yaml          # Agent configuration
├── agent_system.py      # Main agent system
├── example_usage.py     # Usage examples
├── README.md           # This file
└── workspace/          # Default workspace (auto-created)
```

## Advanced Usage

### Custom Agent Profiles

Create your own agent profiles in `config.yaml`:

```yaml
agents:
  my_agent:
    name: "My Agent"
    description: "Custom agent for my specific needs"
    color: "#ff00ff"
    system_prompt: |
      You are a specialized agent for [your domain].
      
      Focus on:
      - [specific goal 1]
      - [specific goal 2]
      - [specific goal 3]
```

### Programmatic Control

```python
from agent_system import RalphAgentSystem
import asyncio

async def run_custom_task():
    system = RalphAgentSystem()
    
    # List agents
    system.list_agents()
    
    # Run with custom parameters
    await system.run_task(
        task="Your task here",
        agent_name="ralph",
        max_iterations=0,  # Unlimited
        work_dir="./custom-workspace"
    )

asyncio.run(run_custom_task())
```

## Troubleshooting

### Agent Not Responding

- Check that Nami-Code dependencies are installed
- Verify your API keys are configured
- Check logs for error messages

### Workspace Issues

- Ensure you have write permissions for the workspace directory
- Try using a custom workdir: `--workdir ./my-workspace`
- Check that there's sufficient disk space

### Configuration Problems

- Verify `config.yaml` is valid YAML
- Check that agent profiles are properly defined
- Use `--list` to verify agents are loaded

## Contributing

To add new features or fix issues:

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request

## License

This project is part of Nami-Code and follows the same license.

## Acknowledgments

- **Ralph Pattern**: Inspired by Geoff Huntley's Ralph autonomous looping pattern
- **Nami-Code**: Built on top of Nami-Code DeepAgents framework
- **Anthropic**: Claude models used for agent intelligence

## Support

For issues, questions, or contributions:
- Check the main Nami-Code repository
- Open an issue on GitHub
- Join the community discussions
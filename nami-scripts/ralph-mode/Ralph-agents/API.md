# Ralph Agents - API Documentation

Complete API reference for Ralph Agents system.

## Table of Contents

- [Agent System](#agent-system)
- [Checkpoint System](#checkpoint-system)
- [Metrics System](#metrics-system)
- [Collaboration System](#collaboration-system)
- [Workflow System](#workflow-system)
- [Communication System](#communication-system)
- [Visualizer](#visualizer)
- [CLI Interface](#cli-interface)

---

## Agent System

### RalphAgentSystem

Main class for managing autonomous Ralph agents.

#### Constructor

```python
RalphAgentSystem(config_path: Optional[str] = None, checkpoint_dir: str = "./checkpoints")
```

**Parameters:**
- `config_path` (Optional[str]): Path to configuration file (default: `./config.yaml`)
- `checkpoint_dir` (str): Directory for checkpoint storage

#### Methods

##### run_task

```python
async def run_task(
    task: str,
    agent_name: str = "ralph",
    max_iterations: int = 0,
    work_dir: Optional[str] = None,
    enable_checkpoints: bool = False,
    checkpoint_interval: int = 1,
    resume_from: Optional[str] = None
)
```

Execute a task with an autonomous agent.

**Parameters:**
- `task` (str): The task description
- `agent_name` (str): Name of the agent profile to use (default: `"ralph"`)
- `max_iterations` (int): Maximum iterations (0 = unlimited, default: `0`)
- `work_dir` (Optional[str]): Custom working directory (default: `None`)
- `enable_checkpoints` (bool): Enable periodic checkpointing (default: `False`)
- `checkpoint_interval` (int): Save checkpoint every N iterations (default: `1`)
- `resume_from` (Optional[str]): Checkpoint ID to resume from (default: `None`)

**Example:**
```python
system = RalphAgentSystem()
await system.run_task(
    task="Create a Python CLI tool",
    agent_name="coder",
    max_iterations=5,
    enable_checkpoints=True,
    checkpoint_interval=2
)
```

##### list_agents

```python
def list_agents()
```

List all available agent profiles.

**Example:**
```python
system = RalphAgentSystem()
system.list_agents()
```

##### list_checkpoints

```python
def list_checkpoints()
```

List all available checkpoints.

**Example:**
```python
system = RalphAgentSystem()
system.list_checkpoints()
```

##### resume_from_checkpoint

```python
def resume_from_checkpoint(checkpoint_id: str, task: str)
```

Resume a task from a checkpoint.

**Parameters:**
- `checkpoint_id` (str): Checkpoint ID to resume from
- `task` (str): Task to continue

**Example:**
```python
system = RalphAgentSystem()
system.resume_from_checkpoint("20240116_120000", "Build API")
```

---

## Checkpoint System

### CheckpointManager

Manages checkpoint creation, loading, and cleanup.

#### Constructor

```python
CheckpointManager(checkpoint_dir: str = "./checkpoints")
```

**Parameters:**
- `checkpoint_dir` (str): Directory to store checkpoints

#### Methods

##### create_checkpoint

```python
def create_checkpoint(
    agent_name: str,
    task: str,
    iteration: int,
    workspace_path: str,
    state: Dict[str, Any],
    tokens_used: int = 0
) -> str
```

Create a checkpoint of the current state.

**Parameters:**
- `agent_name` (str): Name of the agent
- `task` (str): Current task description
- `iteration` (int): Current iteration number
- `workspace_path` (str): Path to workspace directory
- `state` (Dict[str, Any]): Agent state to save
- `tokens_used` (int, optional): Total tokens used so far (default: `0`)

**Returns:**
- `str`: Checkpoint ID (timestamp-based)

**Example:**
```python
manager = CheckpointManager()
checkpoint_id = manager.create_checkpoint(
    agent_name="coder",
    task="Build API",
    iteration=5,
    workspace_path="./workspace",
    state={"iteration": 5},
    tokens_used=10000
)
```

##### load_checkpoint

```python
def load_checkpoint(checkpoint_id: str) -> Optional[Checkpoint]
```

Load a checkpoint by ID.

**Parameters:**
- `checkpoint_id` (str): Checkpoint ID to load

**Returns:**
- `Optional[Checkpoint]`: Checkpoint object or None if not found

**Example:**
```python
checkpoint = manager.load_checkpoint("20240116_120000")
if checkpoint:
    print(f"Resumed from iteration {checkpoint.metadata.iteration}")
```

##### list_checkpoints

```python
def list_checkpoints() -> Dict[str, CheckpointMetadata]
```

List all available checkpoints.

**Returns:**
- `Dict[str, CheckpointMetadata]`: Dict mapping checkpoint IDs to metadata

**Example:**
```python
checkpoints = manager.list_checkpoints()
for checkpoint_id, metadata in checkpoints:
    print(f"{checkpoint_id}: {metadata.task}")
```

##### get_latest_checkpoint

```python
def get_latest_checkpoint() -> Optional[Checkpoint]
```

Get the most recent checkpoint.

**Returns:**
- `Optional[Checkpoint]`: Latest checkpoint or None if no checkpoints exist

**Example:**
```python
latest = manager.get_latest_checkpoint()
if latest:
    print(f"Latest: {latest.metadata.timestamp}")
```

##### delete_checkpoint

```python
def delete_checkpoint(checkpoint_id: str) -> bool
```

Delete a checkpoint.

**Parameters:**
- `checkpoint_id` (str): Checkpoint ID to delete

**Returns:**
- `bool`: True if deleted, False if not found

**Example:**
```python
deleted = manager.delete_checkpoint("20240116_120000")
```

##### clear_all_checkpoints

```python
def clear_all_checkpoints()
```

Delete all checkpoints.

**Example:**
```python
manager.clear_all_checkpoints()
```

---

## Metrics System

### MetricsCollector

Collects and manages metrics for agent execution.

#### Constructor

```python
MetricsCollector(metrics_dir: str = "./metrics")
```

**Parameters:**
- `metrics_dir` (str): Directory to store metrics

#### Methods

##### start_task

```python
def start_task(task: str, agent_name: str)
```

Start tracking a new task.

**Parameters:**
- `task` (str): Task description
- `agent_name` (str): Name of the agent

**Example:**
```python
collector = MetricsCollector()
collector.start_task("Build API", "coder")
```

##### start_iteration

```python
def start_iteration(iteration_number: int)
```

Start tracking a new iteration.

**Parameters:**
- `iteration_number` (int): Current iteration number

**Example:**
```python
collector.start_iteration(1)
```

##### end_iteration

```python
def end_iteration(
    iteration_number: int,
    tokens_used: int = 0,
    success: bool = True,
    error_message: Optional[str] = None
)
```

End tracking for current iteration.

**Parameters:**
- `iteration_number` (int): Current iteration number
- `tokens_used` (int, optional): Tokens used in this iteration (default: `0`)
- `success` (bool, optional): Whether iteration completed successfully (default: `True`)
- `error_message` (Optional[str], optional): Error message if iteration failed (default: `None`)

**Example:**
```python
collector.end_iteration(1, tokens_used=1000, success=True)
```

##### end_task

```python
def end_task(success: bool = True) -> TaskMetrics
```

End tracking for the current task.

**Parameters:**
- `success` (bool, optional): Whether task completed successfully (default: `True`)

**Returns:**
- `TaskMetrics`: Complete task metrics

**Example:**
```python
metrics = collector.end_task(success=True)
print(f"Total tokens: {metrics.total_tokens_used}")
```

##### track_file_created

```python
def track_file_created()
```

Track a file creation event.

**Example:**
```python
collector.track_file_created()
```

##### track_file_modified

```python
def track_file_modified()
```

Track a file modification event.

**Example:**
```python
collector.track_file_modified()
```

##### track_tool_call

```python
def track_tool_call(tool_name: str)
```

Track a tool usage event.

**Parameters:**
- `tool_name` (str): Name of the tool called

**Example:**
```python
collector.track_tool_call("write_file")
```

##### save_metrics

```python
def save_metrics(metrics: TaskMetrics, filename: Optional[str] = None)
```

Save metrics to file.

**Parameters:**
- `metrics` (TaskMetrics): Task metrics to save
- `filename` (Optional[str], optional): Optional filename (default: auto-generated)

**Returns:**
- `Path`: Path to saved file

**Example:**
```python
filepath = collector.save_metrics(metrics, "my_metrics.json")
```

##### generate_report

```python
def generate_report(metrics: TaskMetrics) -> str
```

Generate a human-readable metrics report.

**Parameters:**
- `metrics` (TaskMetrics): Task metrics to report on

**Returns:**
- `str`: Formatted report string

**Example:**
```python
report = collector.generate_report(metrics)
print(report)
```

---

## Collaboration System

### AgentCollaborator

Manages collaboration between multiple agents.

#### Constructor

```python
AgentCollaborator(agent_system: RalphAgentSystem)
```

**Parameters:**
- `agent_system` (RalphAgentSystem): RalphAgentSystem instance to use

#### Methods

##### execute_sequential

```python
async def execute_sequential(
    tasks: List[Dict[str, str]],
    workspace: Optional[str] = None
) -> List[CollaborationResult]
```

Execute tasks sequentially, one agent at a time.

**Parameters:**
- `tasks` (List[Dict[str, str]]): List of `{"agent": "name", "task": "description"}` dicts
- `workspace` (Optional[str], optional): Shared workspace directory (default: `None`)

**Returns:**
- `List[CollaborationResult]`: List of collaboration results

**Example:**
```python
tasks = [
    {"agent": "ralph", "task": "Setup project", "iterations": 2},
    {"agent": "coder", "task": "Implement", "iterations": 5},
]
results = await collaborator.execute_sequential(tasks)
```

##### execute_parallel

```python
async def execute_parallel(
    tasks: List[Dict[str, str]],
    workspace: Optional[str] = None
) -> List[CollaborationResult]
```

Execute tasks in parallel where possible.

**Parameters:**
- `tasks` (List[Dict[str, str]]): List of `{"agent": "name", "task": "description"}` dicts
- `workspace` (Optional[str], optional): Shared workspace directory (default: `None`)

**Returns:**
- `List[CollaborationResult]`: List of collaboration results

**Example:**
```python
tasks = [
    {"agent": "tester", "task": "Test module A"},
    {"agent": "tester", "task": "Test module B"},
]
results = await collaborator.execute_parallel(tasks)
```

##### execute_with_dependencies

```python
async def execute_with_dependencies(
    tasks: List[CollaborationTask],
    workspace: Optional[str] = None
) -> List[CollaborationResult]
```

Execute tasks respecting dependencies.

**Parameters:**
- `tasks` (List[CollaborationTask]): List of CollaborationTask objects
- `workspace` (Optional[str], optional): Shared workspace directory (default: `None`)

**Returns:**
- `List[CollaborationResult]`: List of collaboration results

**Example:**
```python
tasks = [
    CollaborationTask("coder", "Create models", [], 1),
    CollaborationTask("coder", "Create API", ["Create models"], 2),
]
results = await collaborator.execute_with_dependencies(tasks)
```

##### peer_review

```python
async def peer_review(
    task: str,
    primary_agent: str,
    reviewer_agents: List[str],
    workspace: Optional[str] = None
) -> Dict[str, Any]
```

Execute a task with peer review.

**Parameters:**
- `task` (str): Task to execute
- `primary_agent` (str): Agent that does the work
- `reviewer_agents` (List[str]): Agents that review the work
- `workspace` (Optional[str], optional): Workspace directory (default: `None`)

**Returns:**
- `Dict[str, Any]`: Dictionary with results and feedback

**Example:**
```python
result = await collaborator.peer_review(
    task="Build API",
    primary_agent="coder",
    reviewer_agents=["tester", "ralph"]
)
```

##### generate_summary

```python
def generate_summary() -> str
```

Generate a summary of collaboration results.

**Returns:**
- `str`: Formatted summary string

**Example:**
```python
summary = collaborator.generate_summary()
print(summary)
```

---

## Workflow System

### WorkflowOrchestrator

Orchestrates complex workflows with multiple steps and agents.

#### Constructor

```python
WorkflowOrchestrator(
    agent_system: RalphAgentSystem,
    collaborator: AgentCollaborator,
    metrics: Optional[MetricsCollector] = None,
    workflow_dir: str = "./workflows"
)
```

**Parameters:**
- `agent_system` (RalphAgentSystem): RalphAgentSystem instance
- `collaborator` (AgentCollaborator): AgentCollaborator instance
- `metrics` (Optional[MetricsCollector], optional): MetricsCollector instance (default: `None`)
- `workflow_dir` (str, optional): Directory for workflow definitions and state (default: `"./workflows"`)

#### Methods

##### load_workflow

```python
def load_workflow(workflow_path: str) -> WorkflowDefinition
```

Load workflow from JSON file.

**Parameters:**
- `workflow_path` (str): Path to workflow JSON file

**Returns:**
- `WorkflowDefinition`: WorkflowDefinition object

**Example:**
```python
workflow = orchestrator.load_workflow("my_workflow.json")
```

##### save_workflow

```python
def save_workflow(workflow: WorkflowDefinition, filename: Optional[str] = None)
```

Save workflow to JSON file.

**Parameters:**
- `workflow` (WorkflowDefinition): WorkflowDefinition to save
- `filename` (Optional[str], optional): Optional filename (default: workflow_id.json)

**Returns:**
- `Path`: Path to saved file

**Example:**
```python
filepath = orchestrator.save_workflow(workflow, "my_workflow.json")
```

##### execute_workflow

```python
async def execute_workflow(
    workflow: WorkflowDefinition,
    workspace: Optional[str] = None,
    resume_from: Optional[str] = None
) -> WorkflowExecution
```

Execute a workflow.

**Parameters:**
- `workflow` (WorkflowDefinition): WorkflowDefinition to execute
- `workspace` (Optional[str], optional): Workspace directory (default: `None`)
- `resume_from` (Optional[str], optional): Step ID to resume from (default: `None`)

**Returns:**
- `WorkflowExecution`: WorkflowExecution object with results

**Example:**
```python
execution = await orchestrator.execute_workflow(workflow)
```

##### create_template_workflow

```python
def create_template_workflow(
    workflow_id: str,
    name: str,
    description: str
) -> WorkflowDefinition
```

Create a template workflow structure.

**Parameters:**
- `workflow_id` (str): Unique workflow identifier
- `name` (str): Workflow name
- `description` (str): Workflow description

**Returns:**
- `WorkflowDefinition`: WorkflowDefinition with template structure

**Example:**
```python
workflow = orchestrator.create_template_workflow(
    workflow_id="my_app",
    name="My Application",
    description="Build my application"
)
```

##### generate_report

```python
def generate_report(execution: WorkflowExecution) -> str
```

Generate a report for workflow execution.

**Parameters:**
- `execution` (WorkflowExecution): WorkflowExecution to report on

**Returns:**
- `str`: Formatted report string

**Example:**
```python
report = orchestrator.generate_report(execution)
print(report)
```

---

## Communication System

### AgentCommunicationBus

Communication bus for agent-to-agent messaging.

#### Constructor

```python
AgentCommunicationBus()
```

#### Methods

##### start

```python
async def start()
```

Start the communication bus worker.

**Example:**
```python
await bus.start()
```

##### stop

```python
async def stop()
```

Stop the communication bus worker.

**Example:**
```python
await bus.stop()
```

##### register_handler

```python
def register_handler(
    agent_name: str,
    message_types: List[MessageType],
    callback: Callable[[Message], Optional[Message]]
) -> str
```

Register a message handler for an agent.

**Parameters:**
- `agent_name` (str): Name of the agent
- `message_types` (List[MessageType]): Types of messages to handle
- `callback` (Callable[[Message], Optional[Message]]): Function to process messages

**Returns:**
- `str`: Handler ID

**Example:**
```python
def handle_message(message):
    print(f"Received: {message.content}")
    return None

handler_id = bus.register_handler("agent1", [MessageType.NOTIFICATION], handle_message)
```

##### send_message

```python
async def send_message(
    sender: str,
    recipient: str,
    message_type: MessageType,
    content: Dict[str, Any],
    priority: Priority = Priority.NORMAL,
    reply_to: Optional[str] = None,
    correlation_id: Optional[str] = None
) -> str
```

Send a message to another agent.

**Parameters:**
- `sender` (str): Name of the sender
- `recipient` (str): Name of the recipient (or `"*"` for broadcast)
- `message_type` (MessageType): Type of message
- `content` (Dict[str, Any]): Message content
- `priority` (Priority, optional): Message priority (default: `Priority.NORMAL`)
- `reply_to` (Optional[str], optional): If this is a reply, ID of original message (default: `None`)
- `correlation_id` (Optional[str], optional): For request-response correlation (default: `None`)

**Returns:**
- `str`: Message ID

**Example:**
```python
message_id = await bus.send_message(
    sender="agent1",
    recipient="agent2",
    message_type=MessageType.NOTIFICATION,
    content={"text": "Hello!"}
)
```

##### send_request

```python
async def send_request(
    sender: str,
    recipient: str,
    content: Dict[str, Any],
    timeout: float = 30.0
) -> Optional[Message]
```

Send a request and wait for response.

**Parameters:**
- `sender` (str): Name of the sender
- `recipient` (str): Name of the recipient
- `content` (Dict[str, Any]): Request content
- `timeout` (float, optional): Timeout in seconds (default: `30.0`)

**Returns:**
- `Optional[Message]`: Response message or None if timeout

**Example:**
```python
response = await bus.send_request(
    sender="agent1",
    recipient="agent2",
    content={"query": "What's the status?"}
)
if response:
    print(f"Response: {response.content}")
```

##### broadcast

```python
async def broadcast(
    sender: str,
    content: Dict[str, Any],
    message_type: MessageType = MessageType.NOTIFICATION
)
```

Broadcast a message to all agents.

**Parameters:**
- `sender` (str): Name of the sender
- `content` (Dict[str, Any]): Message content
- `message_type` (MessageType, optional): Type of message (default: `MessageType.NOTIFICATION`)

**Example:**
```python
await bus.broadcast(
    sender="agent1",
    content={"alert": "System shutdown"}
)
```

### AgentCommunicator

Helper class for agents to communicate with each other.

#### Constructor

```python
AgentCommunicator(agent_name: str, bus: AgentCommunicationBus)
```

**Parameters:**
- `agent_name` (str): Name of this agent
- `bus` (AgentCommunicationBus): Communication bus instance

#### Methods

##### send

```python
async def send(
    recipient: str,
    content: Dict[str, Any],
    priority: Priority = Priority.NORMAL
) -> str
```

Send a message to another agent.

**Example:**
```python
await communicator.send("agent2", {"text": "Hello!"})
```

##### request

```python
async def request(
    recipient: str,
    content: Dict[str, Any],
    timeout: float = 30.0
) -> Optional[Dict[str, Any]]
```

Send a request and get response.

**Example:**
```python
response = await communicator.request("agent2", {"query": "Status?"})
```

##### broadcast

```python
async def broadcast(content: Dict[str, Any])
```

Broadcast a message to all agents.

**Example:**
```python
await communicator.broadcast({"alert": "Attention!"})
```

##### on_message

```python
def on_message(
    message_types: List[MessageType],
    callback: Callable[[Message], Optional[Message]]
)
```

Register a handler for specific message types.

**Example:**
```python
def handler(message):
    print(f"Got: {message.content}")

communicator.on_message([MessageType.NOTIFICATION], handler)
```

---

## Visualizer

### WorkflowVisualizer

Generates visual representations of workflows.

#### Constructor

```python
WorkflowVisualizer(output_dir: str = "./visualizations")
```

**Parameters:**
- `output_dir` (str, optional): Directory to save visualizations (default: `"./visualizations"`)

#### Methods

##### generate_mermaid

```python
def generate_mermaid(
    workflow: WorkflowDefinition,
    filename: Optional[str] = None
) -> str
```

Generate Mermaid diagram for workflow.

**Parameters:**
- `workflow` (WorkflowDefinition): WorkflowDefinition to visualize
- `filename` (Optional[str], optional): Optional filename to save (default: `None`)

**Returns:**
- `str`: Mermaid diagram string

**Example:**
```python
visualizer = WorkflowVisualizer()
mermaid = visualizer.generate_mermaid(workflow, "workflow.md")
```

##### generate_dot

```python
def generate_dot(
    workflow: WorkflowDefinition,
    filename: Optional[str] = None
) -> str
```

Generate GraphViz DOT format for workflow.

**Parameters:**
- `workflow` (WorkflowDefinition): WorkflowDefinition to visualize
- `filename` (Optional[str], optional): Optional filename to save (default: `None`)

**Returns:**
- `str`: DOT format string

**Example:**
```python
dot = visualizer.generate_dot(workflow, "workflow.dot")
```

##### generate_ascii

```python
def generate_ascii(
    workflow: WorkflowDefinition,
    filename: Optional[str] = None
) -> str
```

Generate ASCII art visualization of workflow.

**Parameters:**
- `workflow` (WorkflowDefinition): WorkflowDefinition to visualize
- `filename` (Optional[str], optional): Optional filename to save (default: `None`)

**Returns:**
- `str`: ASCII art string

**Example:**
```python
ascii = visualizer.generate_ascii(workflow, "workflow.txt")
```

##### generate_html

```python
def generate_html(
    workflow: WorkflowDefinition,
    filename: Optional[str] = None
) -> str
```

Generate HTML interactive visualization of workflow.

**Parameters:**
- `workflow` (WorkflowDefinition): WorkflowDefinition to visualize
- `filename` (Optional[str], optional): Optional filename to save (default: `None`)

**Returns:**
- `str`: HTML string

**Example:**
```python
html = visualizer.generate_html(workflow, "workflow.html")
```

##### generate_all

```python
def generate_all(
    workflow: WorkflowDefinition,
    base_filename: str
) -> Dict[str, str]
```

Generate all visualization formats.

**Parameters:**
- `workflow` (WorkflowDefinition): WorkflowDefinition to visualize
- `base_filename` (str): Base filename (without extension)

**Returns:**
- `Dict[str, str]`: Dictionary mapping format to filepath

**Example:**
```python
results = visualizer.generate_all(workflow, "my_workflow")
# results = {'mermaid': '...', 'dot': '...', 'ascii': '...', 'html': '...'}
```

---

## CLI Interface

### Commands

#### run

Execute a single task with an agent.

```bash
python cli.py run "Task description" --agent coder --iterations 5
```

**Options:**
- `--agent`: Agent to use (default: ralph)
- `--iterations`: Max iterations
- `--workdir`: Working directory
- `--checkpoints`: Enable checkpoints
- `--checkpoint-interval`: Checkpoint interval (default: 1)
- `--resume`: Resume from checkpoint

#### collaborate

Run collaboration tasks.

```bash
# Sequential
python cli.py collaborate --mode sequential --tasks "coder:Task1;tester:Task2"

# Parallel
python cli.py collaborate --mode parallel --tasks "tester:TestA;tester:TestB"

# Peer review
python cli.py collaborate --mode peer_review --task "Build API" --primary coder --reviewers tester,ralph
```

**Options:**
- `--mode`: Collaboration mode (sequential, parallel, peer_review)
- `--tasks`: Tasks (format: agent1:task1;agent2:task2)
- `--task`: Task for peer review mode
- `--primary`: Primary agent for peer review
- `--reviewers`: Comma-separated reviewers
- `--workdir`: Working directory

#### workflow

Manage workflows.

```bash
# List workflows
python cli.py workflow --list

# Create template
python cli.py workflow --create my_workflow --name "My Workflow" --description "Description"

# Execute workflow
python cli.py workflow --execute workflow.json

# Show workflow details
python cli.py workflow --show workflow.json
```

**Options:**
- `--list`: List workflows
- `--create`: Create new workflow template
- `--name`: Workflow name
- `--description`: Workflow description
- `--execute`: Execute workflow file
- `--show`: Show workflow details
- `--resume`: Resume from step
- `--workdir`: Working directory

#### checkpoint

Manage checkpoints.

```bash
# List checkpoints
python cli.py checkpoint --list

# Show checkpoint details
python cli.py checkpoint --info CHECKPOINT_ID

# Delete checkpoint
python cli.py checkpoint --delete CHECKPOINT_ID

# Clear all checkpoints
python cli.py checkpoint --clear
```

**Options:**
- `--list`: List checkpoints
- `--info`: Show checkpoint details
- `--delete`: Delete checkpoint by ID
- `--clear`: Clear all checkpoints

#### metrics

Manage metrics.

```bash
# List metrics
python cli.py metrics --list

# Show metrics from file
python cli.py metrics --show metrics_file.json

# Export metrics
python cli.py metrics --export output.json --format json
```

**Options:**
- `--list`: List metrics
- `--show`: Show metrics from file
- `--export`: Export metrics to file
- `--format`: Export format (json, csv)

#### agents

List available agents.

```bash
python cli.py agents
```

#### interactive

Interactive mode for agent interaction.

```bash
python cli.py interactive
```

---

## Data Classes

### AgentConfig

```python
@dataclass
class AgentConfig:
    name: str
    description: str
    color: str
    system_prompt: str
```

### Checkpoint

```python
@dataclass
class Checkpoint:
    metadata: CheckpointMetadata
    state: Dict[str, Any]
    workspace_snapshot: Dict[str, str]
```

### CheckpointMetadata

```python
@dataclass
class CheckpointMetadata:
    timestamp: str
    agent_name: str
    task: str
    iteration: int
    workspace_path: str
    files_created: int
    tokens_used: int
```

### IterationMetrics

```python
@dataclass
class IterationMetrics:
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
```

### TaskMetrics

```python
@dataclass
class TaskMetrics:
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
```

### CollaborationTask

```python
@dataclass
class CollaborationTask:
    agent_name: str
    task_description: str
    dependencies: List[str]
    priority: int
```

### CollaborationResult

```python
@dataclass
class CollaborationResult:
    agent_name: str
    task: str
    success: bool
    output: str
    metrics: Dict[str, Any]
    duration_seconds: float
```

### WorkflowStep

```python
@dataclass
class WorkflowStep:
    step_id: str
    name: str
    agent: str
    task: str
    dependencies: List[str]
    condition: Optional[str]
    iterations: int = 1
    on_failure: Optional[str] = "stop"
```

### WorkflowDefinition

```python
@dataclass
class WorkflowDefinition:
    workflow_id: str
    name: str
    description: str
    steps: List[WorkflowStep]
    default_workspace: str = "./workspace"
```

### WorkflowExecution

```python
@dataclass
class WorkflowExecution:
    workflow_id: str
    status: WorkflowStatus
    current_step: Optional[str]
    completed_steps: List[str]
    failed_steps: List[str]
    results: Dict[str, Any]
    start_time: str
    end_time: Optional[str]
```

### Message

```python
@dataclass
class Message:
    message_id: str
    sender: str
    recipient: str
    message_type: MessageType
    priority: Priority
    timestamp: str
    content: Dict[str, Any]
    reply_to: Optional[str] = None
    correlation_id: Optional[str] = None
```

---

## Enums

### MessageType

```python
class MessageType(Enum):
    REQUEST = "request"
    RESPONSE = "response"
    NOTIFICATION = "notification"
    BROADCAST = "broadcast"
    ERROR = "error"
```

### Priority

```python
class Priority(Enum):
    LOW = 0
    NORMAL = 1
    HIGH = 2
    URGENT = 3
```

### CollaborationMode

```python
class CollaborationMode(Enum):
    SEQUENTIAL = "sequential"
    PARALLEL = "parallel"
    HIERARCHICAL = "hierarchical"
    PEER_REVIEW = "peer_review"
```

### WorkflowStatus

```python
class WorkflowStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"
```

---

## Quick Reference

### Common Patterns

**Basic Task Execution:**
```python
system = RalphAgentSystem()
await system.run_task("Build a CLI tool", agent_name="coder", max_iterations=5)
```

**With Checkpoints:**
```python
await system.run_task(
    task="Large task",
    enable_checkpoints=True,
    checkpoint_interval=5
)
```

**Parallel Collaboration:**
```python
collaborator = AgentCollaborator(system)
tasks = [{"agent": "tester", "task": "Test A"}]
results = await collaborator.execute_parallel(tasks)
```

**Workflow Execution:**
```python
orchestrator = WorkflowOrchestrator(system, collaborator, metrics)
execution = await orchestrator.execute_workflow(workflow)
```

**Agent Communication:**
```python
bus = AgentCommunicationBus()
await bus.start()
communicator = AgentCommunicator("agent1", bus)
await communicator.send("agent2", {"text": "Hello"})
```

**Workflow Visualization:**
```python
visualizer = WorkflowVisualizer()
mermaid = visualizer.generate_mermaid(workflow, "workflow.md")
```

---

## License

This API documentation is part of Ralph Agents, which is part of Nami-Code.
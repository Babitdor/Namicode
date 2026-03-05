# Evaluation Framework Summary

## Overview

The evaluation framework provides a comprehensive system for testing and benchmarking AI agents on complex terminal-based tasks. It integrates **Harbor** (evaluation orchestration), **Terminal-Bench 2.0** (benchmark tasks), **LangSmith** (tracing/observability), and custom agent wrappers for the Nami Code CLI.

---

## 1. Evaluation Methodology

### Core Components

| Component | Purpose | Technology |
|-----------|---------|------------|
| **Harbor** | Evaluation orchestration framework | Python package (`harbor>=0.1.12`) |
| **Terminal-Bench 2.0** | Benchmark task dataset | 90+ diverse tasks |
| **LangSmith** | Tracing and observability | LangChain ecosystem |
| **Agent Wrappers** | Bridge agents to Harbor | `DeepAgentsWrapper`, `NamiCodeWrapper` |

### Evaluation Flow

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  Harbor Runner  │────▶│  Agent Wrapper  │────▶│  Task Execution │
└─────────────────┘     └─────────────────┘     └─────────────────┘
        │                       │                       │
        ▼                       ▼                       ▼
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  Sandbox Env    │     │  LangSmith      │     │  Verifier       │
│  (Docker/etc)   │     │  Tracing        │     │  (Tests)        │
└─────────────────┘     └─────────────────┘     └─────────────────┘
        │                       │                       │
        └───────────────────────┴───────────────────────┘
                                │
                                ▼
                    ┌─────────────────────┐
                    │  Reward Score       │
                    │  (0.0 - 1.0)        │
                    └─────────────────────┘
```

### Supported Environments

- **Docker** - Local containers (testing, single tasks)
- **Daytona** - Cloud sandboxes (scalable evaluation)
- **Modal** - Cloud compute (parallel tasks)
- **Runloop** - Alternative sandbox environment

---

## 2. Terminal-Bench 2.0 Benchmark

### Task Structure

Each task follows a standardized structure:

```
task-name/
├── task.toml           # Metadata (difficulty, category, timeouts)
├── instruction.md      # Task description for the agent
├── environment/        # Docker environment setup
│   ├── Dockerfile
│   └── task-deps/      # Task-specific dependencies
├── solution/
│   └── solve.sh        # Reference solution (oracle)
└── tests/
    ├── test.sh         # Test runner script
    └── test_outputs.py # Pytest verification
```

### Task Metadata (task.toml)

```toml
version = "1.0"

[metadata]
author_name = "Author Name"
author_email = "author@example.com"
difficulty = "medium"          # easy/medium/hard
category = "games"             # Domain category
tags = []
expert_time_estimate_min = 45.0
junior_time_estimate_min = 180.0

[verifier]
timeout_sec = 900.0            # Test timeout

[agent]
timeout_sec = 900.0            # Agent execution timeout

[environment]
build_timeout_sec = 600.0
docker_image = "registry/image:tag"
cpus = 1
memory = "2G"
storage = "10G"
```

### Task Categories (Sample)

| Category | Example Tasks | Skills Tested |
|----------|---------------|---------------|
| **Games** | `chess-best-move`, `regex-chess` | Game logic, engine usage |
| **Security** | `crack-7z-hash`, `feal-differential-cryptanalysis` | Cryptography, security |
| **Systems** | `build-pmars`, `compile-compcert`, `qemu-alpine-ssh` | Compilation, emulation |
| **Data Science** | `mcmc-sampling-stan`, `portfolio-optimization` | Statistics, optimization |
| **Software Eng** | `fix-git`, `git-multibranch`, `git-leak-recovery` | Version control |
| **Biology** | `dna-assembly`, `protein-assembly` | Bioinformatics |
| **ML/AI** | `gpt2-codegolf`, `hf-model-inference`, `pytorch-model-recovery` | Machine learning |

### Verification System

Tasks use pytest-based verification:

```python
# test_outputs.py
def test_move_correct():
    """Test that the chess engine finds optimal moves."""
    move_file = Path("/app/move.txt")
    move = move_file.read_text().strip().split()
    assert sorted(move) == sorted(["g2g4", "e2e4"]), "File is wrong"
```

**Reward Scoring:**
- `1.0` - All tests pass
- `0.0` - Any test fails
- Partial scores possible for multi-test tasks

---

## 3. Harbor Integration

### Architecture

```
deepagents_harbor/
├── __init__.py              # Package exports
├── backend.py               # HarborSandbox - sandbox operations
├── deepagents_wrapper.py    # DeepAgents agent wrapper
├── namicode_wrapper.py      # Nami Code CLI agent wrapper
└── tracing.py               # LangSmith integration utilities
```

### HarborSandbox Backend

Implements `SandboxBackendProtocol` for Harbor environments:

```python
class HarborSandbox(SandboxBackendProtocol):
    """Sandbox implementation for Harbor environments."""
    
    async def aexecute(self, command: str) -> ExecuteResponse:
        """Execute bash command in task environment."""
        
    async def aread(self, file_path: str, offset: int, limit: int) -> str:
        """Read file with line numbers."""
        
    async def awrite(self, file_path: str, content: str) -> WriteResult:
        """Create new file (base64 encoded for safety)."""
        
    async def aedit(self, file_path: str, old_string: str, new_string: str) -> EditResult:
        """Edit file using perl for reliable string replacement."""
        
    async def als_info(self, path: str) -> list[FileInfo]:
        """List directory contents."""
        
    async def agrep_raw(self, pattern: str, path: str, glob: str) -> list[GrepMatch]:
        """Search files using grep."""
        
    async def aglob_info(self, pattern: str, path: str) -> list[FileInfo]:
        """Find files matching glob pattern."""
```

### Agent Wrappers

#### DeepAgentsWrapper

```python
class DeepAgentsWrapper(BaseAgent):
    """Harbor agent using LangChain DeepAgents SDK."""
    
    def __init__(self, logs_dir: Path, model_name: str, provider: ProviderType):
        # Supports: openai, anthropic, ollama, google
        # Uses ModelManager for consistent configuration
        
    async def run(self, instruction: str, environment: BaseEnvironment, context: AgentContext):
        # 1. Create HarborSandbox backend
        # 2. Format system prompt with directory context
        # 3. Create agent with tools
        # 4. Execute with LangSmith tracing
        # 5. Save trajectory in ATIF format
```

#### NamiCodeWrapper

```python
class NamiCodeWrapper(BaseAgent):
    """Harbor agent using full Nami Code CLI with middleware."""
    
    # Includes all middleware:
    # - FileTrackerMiddleware
    # - AgentMemoryMiddleware
    # - SharedMemoryMiddleware
    # - ShellMiddleware
    
    # Additional tools:
    # - http_request, fetch_url
    # - run_tests_tool
    # - start/stop/list dev servers
```

### Running Evaluations

```bash
# Quick test (1 task, Docker)
make run-terminal-bench-docker

# Scaled evaluation (40 tasks, Daytona)
make run-terminal-bench-daytona

# Run specific task
make run-namicode-task TASK=chess-best-move

# Compare agents
make run-compare
```

---

## 4. Tracing and Analysis

### LangSmith Integration

#### Setup

```bash
# Required environment variables
export LANGSMITH_API_KEY="lsv2_..."
export LANGSMITH_TRACING_V2=true
export LANGSMITH_EXPERIMENT="experiment-name"  # For experiments
```

#### Workflow

```bash
# 1. Create dataset from Harbor tasks
python scripts/harbor_langsmith.py create-dataset terminal-bench --version 2.0

# 2. Create experiment session
python scripts/harbor_langsmith.py create-experiment terminal-bench --name baseline-v1

# 3. Run evaluation with tracing
LANGSMITH_EXPERIMENT="baseline-v1" make run-terminal-bench-daytona

# 4. Add reward feedback to traces
python scripts/harbor_langsmith.py add-feedback jobs/terminal-bench/2025-12-02__16-25-40 \
  --project-name baseline-v1
```

### Trajectory Format (ATIF v1.2)

```json
{
  "schema_version": "ATIF-v1.2",
  "session_id": "unique-session-id",
  "agent": {
    "name": "namicode-harbor",
    "version": "0.1.0",
    "model_name": "claude-3-5-sonnet",
    "extra": {
      "framework": "namicode-cli",
      "middleware": ["FileTrackerMiddleware", "AgentMemoryMiddleware"]
    }
  },
  "steps": [
    {
      "step_id": 1,
      "timestamp": "2025-01-15T10:30:00Z",
      "source": "user",
      "message": "Task instruction..."
    },
    {
      "step_id": 2,
      "timestamp": "2025-01-15T10:30:05Z",
      "source": "agent",
      "message": "I'll analyze the chess position...",
      "tool_calls": [
        {
          "tool_call_id": "call_123",
          "function_name": "execute_in_e2b",
          "arguments": {"code": "python3 -c '...'"}
        }
      ],
      "observation": {
        "results": [
          {"source_call_id": "call_123", "content": "Output..."}
        ]
      }
    }
  ],
  "final_metrics": {
    "total_prompt_tokens": 5000,
    "total_completion_tokens": 2000,
    "total_steps": 15
  }
}
```

### Analysis Script

```bash
# Analyze job results
python scripts/analyze.py --jobs-dir jobs/terminal-bench/2025-12-02__16-25-40
```

**Output includes:**
- Trial status (COMPLETED/FAILED/PENDING)
- Success rate calculation
- Tool usage statistics
- Exception details
- Reference solution comparison

---

## 5. Evaluation Capabilities

### What Gets Evaluated

| Capability | Description | Example Tasks |
|------------|-------------|---------------|
| **Code Generation** | Writing correct, functional code | `build-cython-ext`, `polyglot-c-py` |
| **Debugging** | Finding and fixing bugs | `fix-git`, `custom-memory-heap-crash` |
| **System Administration** | Configuring systems | `configure-git-webserver`, `nginx-request-logging` |
| **Security** | Cryptography, vulnerability analysis | `crack-7z-hash`, `feal-linear-cryptanalysis` |
| **Data Processing** | ETL, transformations | `multi-source-data-merger`, `large-scale-text-editing` |
| **ML/AI** | Model training, inference | `hf-model-inference`, `pytorch-model-recovery` |
| **Scientific Computing** | Simulations, analysis | `mcmc-sampling-stan`, `raman-fitting` |
| **Reverse Engineering** | Understanding unknown code | `path-tracing`, `path-tracing-reverse` |
| **Multi-step Planning** | Complex task decomposition | `install-windows-3.11`, `make-doom-for-mips` |

### Metrics Tracked

1. **Success Rate** - Percentage of tasks completed successfully
2. **Token Usage** - Prompt and completion tokens per task
3. **Step Count** - Number of agent actions per task
4. **Tool Usage** - Frequency of each tool invocation
5. **Time to Completion** - Wall clock time per task
6. **Error Patterns** - Common failure modes

### Common Failure Patterns

| Pattern | Symptom | Fix |
|---------|---------|-----|
| Poor Planning | Jumps to coding without reading | Add upfront planning to prompt |
| Incorrect Tool Usage | Uses `bash cat` instead of `read_file` | Improve tool descriptions |
| No Incremental Testing | Writes 200 lines, tests once | Prompt to test after each unit |
| Hallucinated Paths | Reads non-existent files | Add "always `ls` before read" rule |
| Wrong Model | Fails on complex reasoning | Use more capable model |

---

## 6. Quick Reference

### Key Commands

```bash
# Run single task (Docker, fastest for testing)
make run-terminal-bench-docker

# Run scaled evaluation (Daytona cloud)
make run-terminal-bench-daytona

# Run with Nami Code agent
make run-namicode-docker

# Create LangSmith dataset
python scripts/harbor_langsmith.py create-dataset terminal-bench

# Add feedback scores
python scripts/harbor_langsmith.py add-feedback jobs/terminal-bench/run-dir --project-name exp-name

# Analyze results
python scripts/analyze.py --jobs-dir jobs/terminal-bench/run-dir
```

### Environment Variables

```bash
# Required
ANTHROPIC_API_KEY=sk-ant-...      # For Claude models
LANGSMITH_API_KEY=lsv2_...        # For tracing
LANGSMITH_TRACING_V2=true         # Enable tracing

# Optional
LANGSMITH_EXPERIMENT=name         # Experiment name
LANGSMITH_PROJECT=name            # Project name
DAYTONA_API_KEY=...               # For Daytona environment
```

### File Locations

```
evaluation/
├── deepagents_harbor/           # Agent wrappers
│   ├── backend.py               # HarborSandbox implementation
│   ├── deepagents_wrapper.py    # DeepAgents wrapper
│   ├── namicode_wrapper.py      # Nami Code wrapper
│   └── tracing.py               # LangSmith utilities
├── scripts/
│   ├── analyze.py               # Job result analysis
│   └── harbor_langsmith.py      # LangSmith integration CLI
├── terminal-bench-2/            # Benchmark tasks (90+)
│   ├── task-name/
│   │   ├── task.toml
│   │   ├── instruction.md
│   │   ├── environment/
│   │   ├── solution/
│   │   └── tests/
│   └── ...
├── Makefile                     # Run commands
├── pyproject.toml               # Dependencies
└── README.md                    # Documentation
```

---

## 7. Best Practices

### For Running Evaluations

1. **Start Small** - Test with Docker on 1 task before scaling
2. **Use Experiments** - Create LangSmith experiments for comparison
3. **Monitor Costs** - Track token usage across runs
4. **Analyze Failures** - Use LangSmith to identify patterns
5. **Iterate on Prompts** - Use insights to improve agent prompts

### For Adding New Tasks

1. Create task directory with standard structure
2. Write clear `instruction.md` with specific success criteria
3. Create deterministic tests in `test_outputs.py`
4. Provide reference solution in `solve.sh`
5. Set appropriate timeouts in `task.toml`
6. Test with oracle agent first

### For Analysis

1. Compare tool usage between successful/failed runs
2. Look for patterns in step counts
3. Check token efficiency
4. Review exception traces
5. Use agent-assisted analysis in LangSmith

---

## Summary

The evaluation framework provides a production-ready system for benchmarking AI agents on real-world terminal tasks. It combines:

- **Harbor** for reliable sandboxed execution
- **Terminal-Bench 2.0** for diverse, validated tasks
- **LangSmith** for comprehensive tracing and analysis
- **Custom wrappers** for seamless agent integration

The framework supports iterative improvement through detailed observability, enabling systematic enhancement of agent capabilities.
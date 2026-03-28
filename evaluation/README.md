# Nami Code Evaluation with Harbor & Terminal-Bench 2.0

Runs the Nami Code CLI agent on [Terminal-Bench 2.0](https://github.com/laude-institute/terminal-bench-2) using [Harbor](https://github.com/laude-institute/harbor) as the evaluation harness, with optional [LangSmith](https://smith.langchain.com) tracing.

---

## Prerequisites

- **Python 3.12+** and **[uv](https://docs.astral.sh/uv/)**
- **Docker Desktop** running (required for `--env docker`)
- API keys for your chosen model and (optionally) LangSmith

---

## Setup

```bash
cd evaluation

# Install dependencies
uv sync

# Copy and fill in environment variables
cp .env.example .env   # or create .env manually
```

Minimum `.env` for a local Docker run with an Anthropic model:

```env
ANTHROPIC_API_KEY=sk-ant-...

# Optional — enable LangSmith tracing
LANGSMITH_API_KEY=lsv2_...
LANGSMITH_TRACING_V2=true
```

---

## Running the Evaluation

### Nami Code agent (recommended)

```bash
# 1 task — Docker, local testing
make run-namicode-docker

# 10 tasks — Daytona cloud
make run-namicode-daytona

# 4 tasks — Modal cloud
make run-namicode-modal

# Specific task by name
make run-namicode-task TASK=fix-git

# Compare Nami Code vs DeepAgents on the same task
make run-compare
```

All jobs are written to `jobs/namicode/<timestamp>/`.

### Select a model

Use the `--model` flag when calling Harbor directly:

```bash
# Anthropic Claude
uv run harbor run \
  --agent-import-path deepagents_harbor:NamiCodeWrapper \
  --dataset terminal-bench@2.0 -n 1 \
  --jobs-dir jobs/namicode --env docker \
  --model claude-sonnet-4-6

# OpenAI GPT-4o
uv run harbor run \
  --agent-import-path deepagents_harbor:NamiCodeWrapper \
  --dataset terminal-bench@2.0 -n 1 \
  --jobs-dir jobs/namicode --env docker \
  --model gpt-4o

# Local Ollama (GLM / any local model)
uv run harbor run \
  --agent-import-path deepagents_harbor:NamiCodeWrapper \
  --dataset terminal-bench@2.0 -n 1 \
  --jobs-dir jobs/namicode --env docker \
  --model ollama:glm4
```

> **Note:** Do not use `--ak model_name=...` — pass the model name via `--model` only.

### Run a specific task

```bash
# Via Makefile variable
make run-namicode-task TASK=chess-best-move

# Directly (any task name from terminal-bench-2/)
uv run harbor run \
  --agent-import-path deepagents_harbor:NamiCodeWrapper \
  --dataset terminal-bench@2.0 \
  --task-name chess-best-move -n 1 \
  --jobs-dir jobs/namicode-chess --env docker
```

### DeepAgents baseline agent

```bash
make run-terminal-bench-docker     # 1 task, Docker
make run-terminal-bench-daytona    # 40 tasks, Daytona
make run-terminal-bench-modal      # 4 tasks, Modal
```

---

## Analyzing Results

```bash
# Summarize a completed job run
uv run python scripts/analyze.py --jobs-dir jobs/namicode/<timestamp>

# Example
uv run python scripts/analyze.py --jobs-dir jobs/namicode/2026-03-28__23-52-59
```

Output includes: trial status, reward scores, step counts, tool usage, and exception details.

---

## LangSmith Integration

LangSmith provides per-call tracing across all trials. The workflow:

```
Run evaluation  →  Add reward scores  →  Analyze in LangSmith UI
```

### 1. Create a dataset (one-time)

```bash
uv run python scripts/harbor_langsmith.py create-dataset terminal-bench --version 2.0
```

### 2. Create an experiment session

```bash
uv run python scripts/harbor_langsmith.py create-experiment terminal-bench \
  --name namicode-baseline-v1
```

This prints a session ID and a direct link to the LangSmith comparison view.

### 3. Run with tracing enabled

```bash
# Set the experiment name so traces are grouped
export LANGSMITH_EXPERIMENT="namicode-baseline-v1"

make run-namicode-daytona
# or run harbor directly with --model etc.
```

### 4. Push reward scores to traces

After the run completes, attach Harbor's `harbor_reward` scores (0.0–1.0) to each trace:

```bash
uv run python scripts/harbor_langsmith.py add-feedback \
  jobs/namicode/2026-03-28__23-52-59 \
  --project-name namicode-baseline-v1

# Dry-run first to preview what would be updated
uv run python scripts/harbor_langsmith.py add-feedback \
  jobs/namicode/2026-03-28__23-52-59 \
  --project-name namicode-baseline-v1 \
  --dry-run
```

---

## Project Structure

```
evaluation/
├── deepagents_harbor/
│   ├── backend.py             # HarborSandbox — wraps Docker/Daytona/Modal APIs
│   ├── deepagents_wrapper.py  # DeepAgents baseline wrapper
│   ├── namicode_wrapper.py    # Nami Code CLI wrapper (primary)
│   └── tracing.py             # LangSmith helpers
├── scripts/
│   ├── analyze.py             # Summarize job results locally
│   └── harbor_langsmith.py    # Dataset / experiment / feedback CLI
├── terminal-bench-2/          # Benchmark tasks (90+ tasks)
├── jobs/                      # Output from evaluation runs
├── Makefile                   # All run commands
└── pyproject.toml             # Dependencies (uv)
```

---

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | For Claude models | `sk-ant-...` |
| `OPENAI_API_KEY` | For GPT models | `sk-...` |
| `LANGSMITH_API_KEY` | For tracing | `lsv2_...` |
| `LANGSMITH_TRACING_V2` | For tracing | `true` |
| `LANGSMITH_EXPERIMENT` | Optional | Groups traces by experiment name |
| `LANGSMITH_PROJECT` | Optional | Simpler project-level grouping |
| `DAYTONA_API_KEY` | For `--env daytona` | Daytona cloud API key |

---

## Available Environments

| Flag | Description | Best for |
|---|---|---|
| `--env docker` | Local Docker containers | Quick single-task tests |
| `--env daytona` | Daytona cloud sandboxes | Scaled parallel runs |
| `--env modal` | Modal cloud compute | Medium-scale runs |
| `--env runloop` | Runloop sandboxes | Alternative cloud |

---

## All Makefile Targets

```
make run-namicode-docker          Run 1 task with Nami Code (Docker)
make run-namicode-daytona         Run 10 tasks with Nami Code (Daytona)
make run-namicode-modal           Run 4 tasks with Nami Code (Modal)
make run-namicode-task TASK=name  Run a specific task with Nami Code
make run-compare                  Run Nami Code vs DeepAgents on same task

make run-terminal-bench-docker    Run 1 task with DeepAgents (Docker)
make run-terminal-bench-daytona   Run 40 tasks with DeepAgents (Daytona)
make run-terminal-bench-modal     Run 4 tasks with DeepAgents (Modal)

make test                         Run unit tests
make lint                         Lint source files
make format                       Format source files
```

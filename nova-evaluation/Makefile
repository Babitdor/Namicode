.PHONY: all lint format test help run-hello-world run-terminal-bench-modal run-terminal-bench-docker run-Novacode-docker run-Novacode-daytona run-compare

# Default target executed when no arguments are given to make.
all: help

######################
# TESTING AND COVERAGE
######################

# Define a variable for the test file path.
TEST_FILE ?= tests/unit_tests
INTEGRATION_FILES ?= tests/integration_tests

test:
	uv run pytest --disable-socket --allow-unix-socket $(TEST_FILE)

test_integration:
	uv run pytest $(INTEGRATION_FILES)

test_watch:
	uv run ptw . -- $(TEST_FILE)


######################
# RUN DEEPAGENTS WRAPPER
######################

run-hello-world:
	@mkdir -p jobs/hello-world
	harbor run --agent-import-path deepagents_harbor:DeepAgentsWrapper --dataset hello-world --task-name hello-world -n 1 --jobs-dir tmp/hello-world --env docker

run-terminal-bench-modal:
	@mkdir -p jobs/terminal-bench
	harbor run --agent-import-path deepagents_harbor:DeepAgentsWrapper --dataset terminal-bench@2.0 -n 4 --jobs-dir jobs/terminal-bench --env modal

run-terminal-bench-daytona:
	@mkdir -p jobs/terminal-bench
	harbor run --agent-import-path deepagents_harbor:DeepAgentsWrapper --dataset terminal-bench@2.0 -n 40 --jobs-dir jobs/terminal-bench --env daytona

run-terminal-bench-docker:
	@mkdir -p jobs/terminal-bench
	harbor run --agent-import-path deepagents_harbor:DeepAgentsWrapper --dataset terminal-bench@2.0 -n 1 --jobs-dir jobs/terminal-bench --env docker

run-terminal-bench-runloop:
	@mkdir -p jobs/terminal-bench
	harbor run --agent-import-path deepagents_harbor:DeepAgentsWrapper --dataset terminal-bench@2.0 -n 10 --jobs-dir jobs/terminal-bench --env runloop

######################
# RUN NOVA CODE WRAPPER
######################

# Model used for all Nova Code runs. Override on the CLI, e.g.
#   make run-Novacode-docker MODEL=gpt-4o
# Defaults to a fast, capable cloud model — the wrapper otherwise falls back to
# the configured Ollama model, which is too slow to finish a task before the
# agent timeout (every trial then errors with AgentTimeoutError).
MODEL ?= claude-sonnet-4-6

# Run Nova Code agent on Terminal-Bench with Docker (1 task, local testing)
run-Novacode-docker:
	@mkdir -p jobs/Novacode
	harbor run --agent-import-path deepagents_harbor:NovaCodeWrapper --dataset terminal-bench@2.0 -n 1 --jobs-dir jobs/Novacode --env docker --model $(MODEL)

# Run Nova Code agent on Terminal-Bench with Daytona (10 tasks)
run-Novacode-daytona:
	@mkdir -p jobs/Novacode
	harbor run --agent-import-path deepagents_harbor:NovaCodeWrapper --dataset terminal-bench@2.0 -n 10 --jobs-dir jobs/Novacode --env daytona --model $(MODEL)

# Run Nova Code agent on Terminal-Bench with Modal (4 tasks)
run-Novacode-modal:
	@mkdir -p jobs/Novacode
	harbor run --agent-import-path deepagents_harbor:NovaCodeWrapper --dataset terminal-bench@2.0 -n 4 --jobs-dir jobs/Novacode --env modal --model $(MODEL)

# Run Nova Code agent on specific task (use: make run-Novacode-task TASK=code-from-image)
TASK ?= hello-world
run-Novacode-task:
	@mkdir -p jobs/Novacode-$(TASK)
	harbor run --agent-import-path deepagents_harbor:NovaCodeWrapper --dataset terminal-bench@2.0 --task-name $(TASK) -n 1 --jobs-dir jobs/Novacode-$(TASK) --env docker --model $(MODEL)

# Run comparison: DeepAgents vs Nova Code on same task
run-compare:
	@echo "Running DeepAgents wrapper..."
	@mkdir -p jobs/compare-deepagents
	harbor run --agent-import-path deepagents_harbor:DeepAgentsWrapper --dataset terminal-bench@2.0 -n 1 --jobs-dir jobs/compare-deepagents --env docker
	@echo ""
	@echo "Running Nova Code wrapper..."
	@mkdir -p jobs/compare-Novacode
	harbor run --agent-import-path deepagents_harbor:NovaCodeWrapper --dataset terminal-bench@2.0 -n 1 --jobs-dir jobs/compare-Novacode --env docker --model $(MODEL)

######################
# LINTING AND FORMATTING
######################

# Define a variable for Python and notebook files.
lint format: PYTHON_FILES=deepagents_harbor/ tests/
lint_diff format_diff: PYTHON_FILES=$(shell git diff --relative=. --name-only --diff-filter=d master | grep -E '\.py$$|\.ipynb$$')

lint lint_diff:
	[ "$(PYTHON_FILES)" = "" ] ||	uv run ruff format $(PYTHON_FILES) --diff
	@if [ "$(LINT)" != "minimal" ]; then \
		if [ "$(PYTHON_FILES)" != "" ]; then \
			uv run ruff check $(PYTHON_FILES) --diff; \
		fi; \
	fi
	# [ "$(PYTHON_FILES)" = "" ] || uv run mypy $(PYTHON_FILES)

format format_diff:
	[ "$(PYTHON_FILES)" = "" ] || uv run ruff format $(PYTHON_FILES)
	[ "$(PYTHON_FILES)" = "" ] || uv run ruff check --fix $(PYTHON_FILES)

format_unsafe:
	[ "$(PYTHON_FILES)" = "" ] || uv run ruff format --unsafe-fixes $(PYTHON_FILES)
	

######################
# HELP
######################

help:
	@echo '===================='
	@echo '-- LINTING --'
	@echo 'format                       - run code formatters'
	@echo 'lint                         - run linters'
	@echo '-- TESTS --'
	@echo 'test                         - run unit tests'
	@echo 'test TEST_FILE=<test_file>   - run all tests in file'
	@echo '-- DEEPAGENTS EVALUATION --'
	@echo 'run-terminal-bench-docker    - run 1 task with DeepAgents (Docker)'
	@echo 'run-terminal-bench-daytona   - run 40 tasks with DeepAgents (Daytona)'
	@echo 'run-terminal-bench-modal     - run 4 tasks with DeepAgents (Modal)'
	@echo '-- NOVA CODE EVALUATION --'
	@echo 'run-Novacode-docker          - run 1 task with Nova Code (Docker)'
	@echo 'run-Novacode-daytona         - run 10 tasks with Nova Code (Daytona)'
	@echo 'run-Novacode-modal           - run 4 tasks with Nova Code (Modal)'
	@echo 'run-Novacode-task TASK=name  - run specific task with Nova Code'
	@echo 'run-compare                  - compare DeepAgents vs Nova Code'
	@echo '   (override model on any target: MODEL=gpt-4o)'
	@echo '-- DOCUMENTATION tasks are from the top-level Makefile --'



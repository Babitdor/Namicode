.PHONY: all lint format test help run test_integration test_watch clean

# Default target executed when no arguments are given to make.
all: help

######################
# TESTING AND COVERAGE
######################

# Define variables for test paths
TEST_FILE ?= tests/unit_tests
INTEGRATION_FILES ?= tests/integration_tests

test:
	uv run pytest $(TEST_FILE) \
	  --ignore=tests/unit_tests/test_shell.py \
	  --ignore=tests/unit_tests/test_process_manager.py \
	  --ignore=tests/unit_tests/test_end_to_end.py

test_integration:
	uv run pytest $(INTEGRATION_FILES)

test_all:
	uv run pytest tests/

test_watch:
	uv run ptw . -- $(TEST_FILE)

test_cov:
	uv run pytest --cov=namicode_cli --cov-report=term-missing $(TEST_FILE)

######################
# RUNNING
######################

run:
	uv run nami

run_reinstall:
	uv sync --reinstall && uv run nami

######################
# LINTING AND FORMATTING
######################

# Define Python files to lint/format
PYTHON_FILES = namicode_cli/ tests/

lint:
	@echo "Running ruff format check..."
	uv run ruff format $(PYTHON_FILES) --check
	@echo "Running ruff linter..."
	uv run ruff check $(PYTHON_FILES)

format:
	@echo "Formatting code..."
	uv run ruff format $(PYTHON_FILES)
	@echo "Fixing lint issues..."
	uv run ruff check --fix $(PYTHON_FILES)

######################
# CLEANUP
######################

clean:
	@echo "Cleaning up..."
	-rm -rf .pytest_cache
	-rm -rf __pycache__
	-rm -rf namicode_cli/__pycache__
	-rm -rf tests/__pycache__
	-rm -rf .ruff_cache
	-rm -rf *.egg-info
	-rm -rf dist
	-rm -rf build
	@echo "Done."

######################
# HELP
######################

help:
	@echo '===================='
	@echo 'Nami-Code Makefile'
	@echo '===================='
	@echo ''
	@echo '-- RUNNING --'
	@echo 'run                          - run Nami CLI'
	@echo 'run_reinstall                - reinstall and run Nami CLI'
	@echo ''
	@echo '-- TESTING --'
	@echo 'test                         - run unit tests (excludes subprocess-heavy tests)'
	@echo 'test TEST_FILE=<path>        - run specific test file or directory'
	@echo 'test_integration             - run integration tests'
	@echo 'test_all                     - run all tests (including subprocess-heavy)'
	@echo 'test_watch                   - run tests in watch mode'
	@echo 'test_cov                     - run tests with coverage report'
	@echo ''
	@echo '-- LINTING --'
	@echo 'format                       - run code formatters'
	@echo 'lint                         - run linters'
	@echo ''
	@echo '-- CLEANUP --'
	@echo 'clean                        - remove build artifacts and caches'
	@echo ''

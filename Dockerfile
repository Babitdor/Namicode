FROM python:3.11-slim

WORKDIR /app

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Project metadata + the async agent graphs
COPY pyproject.toml uv.lock* ./
COPY async-agents/ ./async-agents/

# Install project deps, then the LangGraph in-memory dev-server CLI. The CLI is
# NOT a project dependency, so it's added on top of the frozen sync (no lockfile
# churn); `langgraph-cli[inmem]` is what provides the `langgraph dev` server.
RUN uv sync --frozen --no-dev \
    && uv pip install "langgraph-cli[inmem]"

# LangGraph Agent-Protocol API port
EXPOSE 2024

# One server hosts every graph registered in langgraph.json; clients address each
# by graph_id. docker-compose overrides this to ensure the .env file exists first.
# --no-sync: run in the venv as built (which has langgraph-cli). Without it, `uv
# run` reconciles the venv against uv.lock on every start — slow, and it would
# uninstall the langgraph-cli added via `uv pip install` above.
CMD ["uv", "run", "--no-sync", "langgraph", "dev", "--host", "0.0.0.0", "--port", "2024"]

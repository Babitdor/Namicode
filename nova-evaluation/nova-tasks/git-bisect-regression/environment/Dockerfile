FROM python:3.13-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Pre-built git repository (with history) — extracted to /app/repo.
COPY repo.tar.gz /tmp/repo.tar.gz
RUN tar -xzf /tmp/repo.tar.gz -C /app && rm /tmp/repo.tar.gz

COPY tests/ ./tests/

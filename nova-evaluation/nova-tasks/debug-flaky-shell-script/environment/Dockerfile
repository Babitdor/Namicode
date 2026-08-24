FROM python:3.13-slim-bookworm

WORKDIR /app

COPY report.sh /app/report.sh
RUN chmod +x /app/report.sh

COPY tests/ ./tests/

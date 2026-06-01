"""Tracking and observability for Nova Code CLI.

This module provides middleware and utilities for monitoring agent execution:

- File tracking: Track file reads/writes and enforce read-before-edit
- Tool limits: Circuit breaker to prevent infinite tool calling loops
- Run logging: Log agent runs for debugging and analytics
- Tracing: LangSmith/OpenTelemetry integration for observability
- Workspace anchoring: Scan and summarize workspace state for prompts
"""
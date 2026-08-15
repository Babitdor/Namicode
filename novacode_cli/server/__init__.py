"""FastAPI server for the Nova agent.

This package provides a FastAPI-based HTTP/WebSocket backend that wraps the
agent runtime. It exposes the agent through a REST + WebSocket API, emitting
structured JSON events instead of terminal rendering.

Usage:
    python -m novacode_cli.server_main
"""

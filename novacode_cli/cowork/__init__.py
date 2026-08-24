"""Nova Desktop Cowork — a chat-driven workspace app launched via /cowork.

Reuses Nova's existing agent, event stream, and sandbox/broker primitives; the
only new security surface is :mod:`cowork.policy` (the WorkspacePolicy broker),
which is the authoritative enforcement point — the agent is never the boundary.
"""

from novacode_cli.cowork.policy import Decision, Grant, WorkspacePolicy, get_policy

__all__ = ["Decision", "Grant", "WorkspacePolicy", "get_policy"]

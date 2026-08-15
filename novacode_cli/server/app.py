"""FastAPI application for the Nova agent.

Exposes the agent runtime through:
- ``GET /health`` — health check
- ``POST /sessions`` — create a new agent session
- ``DELETE /sessions/{session_id}`` — delete a session
- ``WebSocket /ws/{session_id}`` — streaming agent communication

All agent output is emitted as structured JSON events (see
:mod:`novacode_cli.server.event_adapter`). No terminal rendering is performed.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from contextlib import asynccontextmanager
from functools import partial
from pathlib import Path
from typing import Any, AsyncGenerator

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.store.memory import InMemoryStore

from novacode_cli import ui_events
from novacode_cli.core.agent_loop import iterate_agent_events
from novacode_cli.server.event_adapter import serialize_event
from novacode_cli.server.session_manager import SessionManager

logger = logging.getLogger(__name__)

# ── Session manager (module-level singleton) ──────────────────────────
session_manager = SessionManager()


# ── Agent factory ──────────────────────────────────────────────────────
def _create_server_agent() -> tuple[Any, Any, dict[str, Any]]:
    """Create an agent instance for the server.

    Mirrors the CLI's agent creation (``main.py``) but without CLI-specific
    setup like BootAnimation, voice preloading, or session state.

    Does NOT import ``novacode_cli.main`` to avoid triggering Serena MCP
    startup and other CLI-specific side effects.
    """
    from novacode_cli.config.model_create import create_model

    model = create_model()

    # ── Tools (mirrors the CLI tool list from main.py) ──────────────
    from novacode_cli.tools import (
        docs_search,
        duckduckgo_search,
        fetch_url,
        forget,
        github_trending,
        hacker_news,
        linkedin_jobs,
        list_memories,
        oracle,
        package_info,
        read_memory,
        recall,
        reddit_posts,
        remember,
        skill_manage,
        speak,
        think,
        wiki_read,
        wiki_search,
        wiki_update_index,
        wiki_write,
        write_memory,
    )
    from novacode_cli.tools.plan_mode_tools import (
        ask_user_question,
        enter_plan_mode,
        exit_plan_mode,
    )

    tools = [
        fetch_url,
        ask_user_question,
        enter_plan_mode,
        exit_plan_mode,
        wiki_read,
        wiki_search,
        wiki_update_index,
        wiki_write,
        package_info,
        think,
        speak,
        oracle,
        skill_manage,
        duckduckgo_search,
        docs_search,
        github_trending,
        hacker_news,
        linkedin_jobs,
        reddit_posts,
        write_memory,
        read_memory,
        remember,
        recall,
        list_memories,
        forget,
    ]

    # Conditionally add Semble-powered code search tools
    from novacode_cli.tools import code_search, find_related_code

    if code_search is not None:
        tools.append(code_search)
    if find_related_code is not None:
        tools.append(find_related_code)

    # Conditionally add Tavily web search
    from novacode_cli.config.config import settings

    if settings.has_tavily:
        from novacode_cli.tools import web_search

        tools.append(web_search)

    # File recovery tools
    from novacode_cli.recovery import get_recovery_manager, list_trash, restore_file

    get_recovery_manager(
        session_id="server",
        workspace_root=Path.cwd(),
    )
    tools.extend([list_trash, restore_file])

    # Artifact tools (parity with the TUI agent).
    from novacode_cli.tools.artifact_tools import (
        create_artifact,
        list_artifacts,
        update_artifact,
    )

    tools.extend([create_artifact, update_artifact, list_artifacts])

    # ── Create agent ─────────────────────────────────────────────────
    from novacode_cli.agents.core_agent import create_agent_with_config

    assistant_id = "nova-server"
    store = InMemoryStore()
    checkpointer = InMemorySaver()

    agent, composite_backend = create_agent_with_config(
        model,
        assistant_id,
        tools,
        sandbox=None,
        sandbox_type=None,
        store=store,
        checkpointer=checkpointer,
        is_continuation=False,
        steering_instructions=None,
        exec_sandbox=False,
        session_id="server",
    )

    config = {"configurable": {"thread_id": "server"}}
    return agent, composite_backend, config


# ── Pre-created agent (set by server_main before uvicorn starts) ──
_server_agent: Any = None
_server_backend: Any = None
_server_config: dict[str, Any] = {}


def set_agent(
    agent: Any,
    backend: Any,
    config: dict[str, Any],
) -> None:
    """Set the pre-created agent (called from server_main before startup)."""
    global _server_agent, _server_backend, _server_config
    _server_agent = agent
    _server_backend = backend
    _server_config = config


# ── Lifespan ───────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Startup/shutdown lifecycle."""
    logger.info("Nova server starting")
    yield
    # Shutdown: clean up all sessions
    for sid in list(session_manager._sessions):
        session_manager.delete_session(sid)
    logger.info("Nova server stopped")


app = FastAPI(
    title="Nova Agent API",
    version="1.0.0",
    lifespan=lifespan,
)


# ── Health ─────────────────────────────────────────────────────────────
@app.get("/health")
async def health() -> dict[str, Any]:
    """Health check endpoint."""
    return {
        "status": "ok",
        "sessions_active": session_manager.active_count,
    }


# ── Session management ────────────────────────────────────────────────
@app.post("/sessions")
async def create_session() -> JSONResponse:
    """Create a new agent session.

    Returns the session ID. The caller should connect to
    ``/ws/{session_id}`` to interact with the agent.

    The agent is pre-created at startup and shared across sessions.
    Each session gets its own config with a unique thread_id.
    """
    if _server_agent is None:
        return JSONResponse(
            status_code=503,
            content={"error": "Agent not ready (still initializing)"},
        )

    config = {**_server_config, "configurable": {"thread_id": uuid.uuid4().hex[:12]}}
    info = session_manager.create_session(_server_agent, config)
    logger.info("Created session %s", info.session_id)
    return JSONResponse(
        status_code=201,
        content={"session_id": info.session_id, "created_at": info.created_at},
    )


@app.delete("/sessions/{session_id:str}")
async def delete_session(session_id: str) -> JSONResponse:
    """Delete an agent session and cancel any in-progress run."""
    found = session_manager.delete_session(session_id)
    if not found:
        return JSONResponse(
            status_code=404,
            content={"error": f"Session {session_id} not found"},
        )
    logger.info("Deleted session %s", session_id)
    return JSONResponse(
        status_code=200,
        content={"status": "deleted", "session_id": session_id},
    )


# ── WebSocket streaming ───────────────────────────────────────────────
@app.websocket("/ws/{session_id:str}")
async def websocket_handler(websocket: WebSocket, session_id: str) -> None:
    """WebSocket endpoint for streaming agent communication.

    **Client → Server messages:**
    - ``{"type": "message", "data": {"content": "..."}}`` — send user input
    - ``{"type": "cancel"}`` — cancel the current run
    - ``{"type": "interrupt_response", "data": {...}}`` — respond to an interrupt

    **Server → Client events:**
    - ``assistant_token``, ``assistant_done``, ``tool_started``,
      ``tool_finished``, ``file_changed``, ``status``, ``error``,
      ``cancelled``, ``interrupt``, ``subagent_activity``, etc.
    """
    await websocket.accept()

    info = session_manager.get_session(session_id)
    if info is None:
        await websocket.send_json({"type": "error", "data": {"message": f"Session {session_id} not found"}})
        await websocket.close()
        return

    cancel_event = asyncio.Event()
    info.set_cancel_event(cancel_event)

    try:
        await _handle_websocket(websocket, info, cancel_event)
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected for session %s", session_id)
    except Exception:
        logger.exception("WebSocket error for session %s", session_id)
    finally:
        info.clear_cancel_event()


async def _handle_websocket(
    websocket: WebSocket,
    info: Any,
    cancel_event: asyncio.Event,
) -> None:
    """Main WebSocket message loop."""
    # Queue for interrupt responses from the client
    interrupt_queue: asyncio.Queue[Any] = asyncio.Queue()

    while True:
        raw = await websocket.receive_json()

        msg_type = raw.get("type")
        data = raw.get("data", {})

        if msg_type == "cancel":
            cancel_event.set()
            continue

        if msg_type == "interrupt_response":
            await interrupt_queue.put(data)
            continue

        if msg_type == "message":
            content = data.get("content", "")
            if not content:
                await websocket.send_json({
                    "type": "error",
                    "data": {"message": "Empty message content"},
                })
                continue

            await _run_agent_and_stream(
                websocket, info, content, cancel_event, interrupt_queue,
            )
            continue

        # Unknown message type
        await websocket.send_json({
            "type": "error",
            "data": {"message": f"Unknown message type: {msg_type}"},
        })


async def _run_agent_and_stream(
    websocket: WebSocket,
    info: Any,
    user_input: str,
    cancel_event: asyncio.Event,
    interrupt_queue: asyncio.Queue,
) -> None:
    """Run the agent on user input and stream events over the WebSocket."""
    # Reset cancel event for a new run
    cancel_event.clear()

    # Build messages list
    messages = [{"role": "user", "content": user_input}]

    try:
        async for event in iterate_agent_events(
            agent=info.agent,
            messages=messages,
            config=info.config,
            user_input=user_input,
            session_state=None,
            agent_name="Nova",
            agent_color="cyan",
            is_subagent=False,
            cancel_event=cancel_event,
        ):
            # Handle interrupt requests (need bidirectional communication)
            if isinstance(event, ui_events.InterruptRequest):
                serialized = serialize_event(event)
                if serialized:
                    await websocket.send_json(serialized)

                # Wait for client response
                try:
                    response = await asyncio.wait_for(
                        interrupt_queue.get(),
                        timeout=300.0,  # 5 min timeout for interrupt
                    )
                except asyncio.TimeoutError:
                    event.future.set_exception(TimeoutError("Interrupt response timeout"))
                    cancel_event.set()
                    await websocket.send_json({
                        "type": "error",
                        "data": {"message": "Interrupt response timeout"},
                    })
                    return

                # Resolve the future with the response
                event.future.set_result(response)
                continue

            # Normal event — serialize and send
            serialized = serialize_event(event)
            if serialized is not None:
                await websocket.send_json(serialized)

                # If cancelled, stop streaming
                if isinstance(event, (ui_events.Cancelled, ui_events.Done)):
                    return

    except asyncio.CancelledError:
        await websocket.send_json({"type": "cancelled", "data": {}})
    except Exception:
        logger.exception("Agent run failed")
        await websocket.send_json({
            "type": "error",
            "data": {"message": "Agent run failed"},
        })

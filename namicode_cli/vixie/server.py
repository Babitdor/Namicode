"""Vixie integration server for Nami-Code CLI.

This module provides a WebSocket server that broadcasts Nami-Code state changes
to connected Vixie desktop pet clients, enabling real-time visual feedback.

Key Features:
- WebSocket server that broadcasts state updates
- State tracking for different Nami-Code phases (idle, thinking, working, etc.)
- Event broadcasting for task completion, errors, and user input required
- Configurable port and host settings

State Mapping:
- idle: Pokémon resting
- thinking: Pokémon thinking/reading
- working: Pokémon actively working
- success: Pokémon celebrating
- error: Pokémon looking concerned
- user_input: Pokémon waiting for input

Dependencies:
- websockets: WebSocket server/client library
- asyncio: Async event loop
"""

import asyncio
import json
import logging
import os
import signal
import sys
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

import websockets
from websockets.server import WebSocketServerProtocol

from namicode_cli.config.config import settings

# Configure logging
logger = logging.getLogger(__name__)


class NamiState(Enum):
    """Nami-Code state for Vixie visualization."""
    IDLE = "idle"
    THINKING = "thinking"
    WORKING = "working"
    SUCCESS = "success"
    ERROR = "error"
    USER_INPUT = "user_input"
    PLANNING = "planning"


@dataclass
class NamiEvent:
    """Event broadcast to Vixie clients."""
    event_type: str
    timestamp: datetime = field(default_factory=datetime.now)
    data: dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> dict[str, Any]:
        """Convert event to dictionary for JSON serialization."""
        return {
            "event_type": self.event_type,
            "timestamp": self.timestamp.isoformat(),
            "data": self.data
        }
    
    def to_json(self) -> str:
        """Convert event to JSON string."""
        return json.dumps(self.to_dict())


class VixieServer:
    """WebSocket server for Vixie desktop pet integration.
    
    This server broadcasts Nami-Code state changes to connected Vixie clients,
    enabling real-time visual feedback about the agent's current activity.
    """
    
    def __init__(self, host: str = "127.0.0.1", port: int = 8765):
        """Initialize the Vixie server.
        
        Args:
            host: Host address to bind to (default: 127.0.0.1)
            port: Port to listen on (default: 8765)
        """
        self.host = host
        self.port = port
        self.server: Any = None
        self.clients: set[WebSocketServerProtocol] = set()
        self.current_state = NamiState.IDLE
        self._shutdown_event = asyncio.Event()
        
    async def start(self) -> bool:
        """Start the WebSocket server.
        
        Returns:
            True if server started successfully, False otherwise.
        """
        logger.info(f"Starting Vixie server on {self.host}:{self.port}")
        
        try:
            # Use serve as a context manager that starts immediately
            self.server = await websockets.serve(
                self._handler,
                self.host,
                self.port,
                ping_interval=20,
                ping_timeout=20
            )
            logger.info(f"Vixie server running on ws://{self.host}:{self.port}")
            return True
        except OSError as e:
            if e.errno == 10048 or "address already in use" in str(e).lower():
                logger.warning(
                    f"Vixie server port {self.port} is already in use. "
                    "This is likely from another nami instance. "
                    "Vixie integration will be disabled for this session."
                )
                return False
            raise
            
    async def stop(self) -> None:
        """Stop the WebSocket server."""
        logger.info("Stopping Vixie server...")
        self._shutdown_event.set()
        if self.server:
            self.server.close()
            await self.server.wait_closed()
        logger.info("Vixie server stopped")
        
    async def _handler(self, websocket: WebSocketServerProtocol) -> None:
        """Handle incoming WebSocket connections.
        
        Args:
            websocket: The WebSocket connection
        """
        client_id = id(websocket)
        logger.info(f"Vixie client connected: {client_id}")
        
        # Add client to the set
        self.clients.add(websocket)
        
        try:
            # Send initial state
            await self._send_state(websocket)
            
            # Handle incoming messages
            async for message in websocket:
                await self._handle_message(websocket, message)
                
        except websockets.exceptions.ConnectionClosed:
            logger.info(f"Vixie client disconnected: {client_id}")
        finally:
            self.clients.discard(websocket)
            
    async def _handle_message(self, websocket: WebSocketServerProtocol, message: str) -> None:
        """Handle incoming message from Vixie client.
        
        Args:
            websocket: The WebSocket connection
            message: The received message
        """
        try:
            data = json.loads(message)
            logger.debug(f"Received from Vixie: {data}")
            
            # Handle different message types
            if data.get("type") == "ping":
                await websocket.send(json.dumps({"type": "pong"}))
                
        except json.JSONDecodeError:
            logger.warning(f"Invalid JSON from Vixie: {message}")
            
    async def _send_state(self, websocket: WebSocketServerProtocol) -> None:
        """Send current state to a client.
        
        Args:
            websocket: The WebSocket connection
        """
        event = NamiEvent(
            event_type="state_update",
            data={"state": self.current_state.value}
        )
        await websocket.send(event.to_json())
        
    async def broadcast_state(self, state: NamiState) -> None:
        """Broadcast state update to all connected clients.
        
        Args:
            state: The new state
        """
        self.current_state = state
        
        event = NamiEvent(
            event_type="state_update",
            data={"state": state.value}
        )
        
        logger.warning(f"[VIXIE] Broadcasting state: {state.value} to {len(self.clients)} clients")
        
        if self.clients:
            message = event.to_json()
            logger.warning(f"[VIXIE] Sending message: {message[:100]}...")
            try:
                results = await asyncio.gather(
                    *[client.send(message) for client in self.clients],
                    return_exceptions=True
                )
                logger.warning(f"[VIXIE] Broadcast results: {results}")
            except Exception as e:
                logger.error(f"[VIXIE] Error broadcasting state: {e}")
        else:
            logger.warning(f"[VIXIE] No clients connected, state stored: {state.value}")
            
    async def broadcast_event(self, event_type: str, data: dict[str, Any] | None = None) -> None:
        """Broadcast a custom event to all connected clients.
        
        Args:
            event_type: The event type
            data: Optional event data
        """
        event = NamiEvent(
            event_type=event_type,
            data=data or {}
        )
        
        if self.clients:
            message = event.to_json()
            await asyncio.gather(
                *[client.send(message) for client in self.clients],
                return_exceptions=True
            )
            logger.debug(f"Broadcasted event: {event_type}")


# Global server instance
_server: VixieServer | None = None


def get_server() -> VixieServer:
    """Get or create the global server instance.
    
    Returns:
        The Vixie server instance
    """
    global _server
    if _server is None:
        _server = VixieServer()
    return _server


async def start_vixie_server() -> VixieServer | None:
    """Start the Vixie WebSocket server.
    
    Returns:
        The server instance if started successfully, None if port is in use.
    """
    server = get_server()
    try:
        success = await server.start()
        if success:
            logger.info(f"Vixie server started successfully on port {server.port}")
            return server
        else:
            logger.warning("Vixie server failed to start")
            return None
    except Exception as e:
        logger.warning(f"Failed to start Vixie server: {e}")
        return None


async def stop_vixie_server() -> None:
    """Stop the Vixie WebSocket server."""
    global _server
    if _server:
        await _server.stop()
        _server = None


async def update_vixie_state(state: NamiState) -> None:
    """Update and broadcast the current Nami-Code state.
    
    Args:
        state: The new state
    """
    server = get_server()
    logger.warning(f"[VIXIE] update_vixie_state called: {state.value}, clients: {len(server.clients)}")
    await server.broadcast_state(state)
    logger.warning(f"[VIXIE] update_vixie_state complete: {state.value}")


async def broadcast_vixie_event(event_type: str, data: dict[str, Any] | None = None) -> None:
    """Broadcast a custom event to Vixie clients.
    
    Args:
        event_type: The event type
        data: Optional event data
    """
    server = get_server()
    if server.clients:
        await server.broadcast_event(event_type, data)


# State update functions for different Nami-Code phases
async def set_idle() -> None:
    """Set state to idle."""
    await update_vixie_state(NamiState.IDLE)


async def set_thinking() -> None:
    """Set state to thinking."""
    await update_vixie_state(NamiState.THINKING)


async def set_working() -> None:
    """Set state to working."""
    await update_vixie_state(NamiState.WORKING)


async def set_success() -> None:
    """Set state to success."""
    await update_vixie_state(NamiState.SUCCESS)


async def set_error() -> None:
    """Set state to error."""
    await update_vixie_state(NamiState.ERROR)


async def set_user_input_required() -> None:
    """Set state to user input required."""
    await update_vixie_state(NamiState.USER_INPUT)


async def set_planning() -> None:
    """Set state to planning."""
    await update_vixie_state(NamiState.PLANNING)


# Event broadcasting functions
async def broadcast_task_completed(task_name: str) -> None:
    """Broadcast task completion event.
    
    Args:
        task_name: The name of the completed task
    """
    await broadcast_vixie_event("task_completed", {"task_name": task_name})


async def broadcast_task_failed(task_name: str, error: str) -> None:
    """Broadcast task failure event.
    
    Args:
        task_name: The name of the failed task
        error: The error message
    """
    await broadcast_vixie_event("task_failed", {"task_name": task_name, "error": error})


async def broadcast_user_input_required(prompt: str) -> None:
    """Broadcast user input required event.
    
    Args:
        prompt: The prompt for user input
    """
    await broadcast_vixie_event("user_input_required", {"prompt": prompt})


async def broadcast_error(error_message: str) -> None:
    """Broadcast error event.
    
    Args:
        error_message: The error message
    """
    await broadcast_vixie_event("error", {"message": error_message})

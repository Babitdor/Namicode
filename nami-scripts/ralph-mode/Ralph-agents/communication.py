#!/usr/bin/env python3
"""
Agent Communication System for Ralph Agents

Enables direct agent-to-agent communication and message passing.
"""
import asyncio
import json
from datetime import datetime
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, asdict
from enum import Enum
from collections import defaultdict


class MessageType(Enum):
    """Types of messages agents can send."""
    REQUEST = "request"
    RESPONSE = "response"
    NOTIFICATION = "notification"
    BROADCAST = "broadcast"
    ERROR = "error"


class Priority(Enum):
    """Message priority levels."""
    LOW = 0
    NORMAL = 1
    HIGH = 2
    URGENT = 3


@dataclass
class Message:
    """A message sent between agents."""
    message_id: str
    sender: str
    recipient: str  # "*" for broadcast
    message_type: MessageType
    priority: Priority
    timestamp: str
    content: Dict[str, Any]
    reply_to: Optional[str] = None  # If this is a reply
    correlation_id: Optional[str] = None  # For request-response correlation


@dataclass
class MessageHandler:
    """Handler for processing messages."""
    handler_id: str
    agent_name: str
    message_types: List[MessageType]
    callback: Callable[[Message], Optional[Message]]


class AgentCommunicationBus:
    """
    Communication bus for agent-to-agent messaging.
    
    Features:
    - Direct messaging between agents
    - Broadcast messages
    - Request-response pattern
    - Message priority and queuing
    - Message handlers
    - Message history
    """
    
    def __init__(self):
        """Initialize the communication bus."""
        self.message_queue: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self.handlers: Dict[str, List[MessageHandler]] = defaultdict(list)
        self.message_history: List[Message] = []
        self.pending_requests: Dict[str, asyncio.Future] = {}
        
        self.running = False
        self.worker_task: Optional[asyncio.Task] = None
    
    async def start(self):
        """Start the communication bus worker."""
        if self.running:
            return
        
        self.running = True
        self.worker_task = asyncio.create_task(self._worker())
    
    async def stop(self):
        """Stop the communication bus worker."""
        self.running = False
        if self.worker_task:
            self.worker_task.cancel()
            try:
                await self.worker_task
            except asyncio.CancelledError:
                pass
    
    def register_handler(
        self,
        agent_name: str,
        message_types: List[MessageType],
        callback: Callable[[Message], Optional[Message]]
    ) -> str:
        """
        Register a message handler for an agent.
        
        Args:
            agent_name: Name of the agent
            message_types: Types of messages to handle
            callback: Function to process messages
            
        Returns:
            Handler ID
        """
        handler_id = f"{agent_name}_{datetime.now().timestamp()}"
        handler = MessageHandler(
            handler_id=handler_id,
            agent_name=agent_name,
            message_types=message_types,
            callback=callback
        )
        
        self.handlers[agent_name].append(handler)
        return handler_id
    
    def unregister_handler(self, handler_id: str):
        """
        Unregister a message handler.
        
        Args:
            handler_id: Handler ID to remove
        """
        for agent_name, handlers in self.handlers.items():
            self.handlers[agent_name] = [
                h for h in handlers if h.handler_id != handler_id
            ]
    
    async def send_message(
        self,
        sender: str,
        recipient: str,
        message_type: MessageType,
        content: Dict[str, Any],
        priority: Priority = Priority.NORMAL,
        reply_to: Optional[str] = None,
        correlation_id: Optional[str] = None
    ) -> str:
        """
        Send a message to another agent.
        
        Args:
            sender: Name of the sender
            recipient: Name of the recipient (or "*" for broadcast)
            message_type: Type of message
            content: Message content
            priority: Message priority
            reply_to: If this is a reply, ID of original message
            correlation_id: For request-response correlation
            
        Returns:
            Message ID
        """
        message_id = f"{sender}_{datetime.now().timestamp()}"
        
        message = Message(
            message_id=message_id,
            sender=sender,
            recipient=recipient,
            message_type=message_type,
            priority=priority,
            timestamp=datetime.now().isoformat(),
            content=content,
            reply_to=reply_to,
            correlation_id=correlation_id
        )
        
        # Add to queue (priority reversed for min-heap)
        await self.message_queue.put((4 - priority.value, message))
        
        return message_id
    
    async def send_request(
        self,
        sender: str,
        recipient: str,
        content: Dict[str, Any],
        timeout: float = 30.0
    ) -> Optional[Message]:
        """
        Send a request and wait for response.
        
        Args:
            sender: Name of the sender
            recipient: Name of the recipient
            content: Request content
            timeout: Timeout in seconds
            
        Returns:
            Response message or None if timeout
        """
        correlation_id = f"{sender}_{datetime.now().timestamp()}"
        
        # Create future for response
        future: asyncio.Future[Message] = asyncio.Future()
        self.pending_requests[correlation_id] = future
        
        # Send request
        await self.send_message(
            sender=sender,
            recipient=recipient,
            message_type=MessageType.REQUEST,
            content=content,
            priority=Priority.HIGH,
            correlation_id=correlation_id
        )
        
        # Wait for response
        try:
            response = await asyncio.wait_for(future, timeout=timeout)
            return response
        except asyncio.TimeoutError:
            # Clean up pending request
            self.pending_requests.pop(correlation_id, None)
            return None
    
    async def send_response(
        self,
        sender: str,
        recipient: str,
        content: Dict[str, Any],
        correlation_id: str
    ):
        """
        Send a response to a request.
        
        Args:
            sender: Name of the sender
            recipient: Name of the recipient
            content: Response content
            correlation_id: Correlation ID from original request
        """
        await self.send_message(
            sender=sender,
            recipient=recipient,
            message_type=MessageType.RESPONSE,
            content=content,
            priority=Priority.HIGH,
            correlation_id=correlation_id
        )
    
    async def broadcast(
        self,
        sender: str,
        content: Dict[str, Any],
        message_type: MessageType = MessageType.NOTIFICATION
    ):
        """
        Broadcast a message to all agents.
        
        Args:
            sender: Name of the sender
            content: Message content
            message_type: Type of message
        """
        await self.send_message(
            sender=sender,
            recipient="*",
            message_type=message_type,
            content=content,
            priority=Priority.NORMAL
        )
    
    async def _worker(self):
        """Worker that processes messages from the queue."""
        while self.running:
            try:
                # Get next message from queue
                _, message = await self.message_queue.get()
                
                # Add to history
                self.message_history.append(message)
                
                # Handle response for pending requests
                if (message.message_type == MessageType.RESPONSE 
                    and message.correlation_id 
                    and message.correlation_id in self.pending_requests):
                    
                    future = self.pending_requests[message.correlation_id]
                    if not future.done():
                        future.set_result(message)
                    
                    del self.pending_requests[message.correlation_id]
                
                # Route message to handlers
                recipients = self._get_recipients(message)
                
                for recipient in recipients:
                    handlers = self.handlers.get(recipient, [])
                    
                    for handler in handlers:
                        if message.message_type in handler.message_types:
                            try:
                                # Call handler
                                response = await asyncio.coroutine(handler.callback)(message)
                                
                                # If handler returned a response, send it
                                if response:
                                    await self.message_queue.put((4 - response.priority.value, response))
                                
                            except Exception as e:
                                # Send error message
                                await self.send_message(
                                    sender="communication_bus",
                                    recipient=handler.agent_name,
                                    message_type=MessageType.ERROR,
                                    content={"error": str(e)},
                                    priority=Priority.HIGH
                                )
                
                self.message_queue.task_done()
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"Error processing message: {e}")
    
    def _get_recipients(self, message: Message) -> List[str]:
        """
        Get list of recipients for a message.
        
        Args:
            message: Message to route
            
        Returns:
            List of recipient agent names
        """
        if message.recipient == "*":
            # Broadcast to all registered agents
            return list(self.handlers.keys())
        else:
            # Specific recipient
            return [message.recipient]
    
    def get_history(
        self,
        sender: Optional[str] = None,
        recipient: Optional[str] = None,
        message_type: Optional[MessageType] = None,
        limit: int = 100
    ) -> List[Message]:
        """
        Get message history with optional filtering.
        
        Args:
            sender: Filter by sender
            recipient: Filter by recipient
            message_type: Filter by message type
            limit: Maximum number of messages to return
            
        Returns:
            List of messages
        """
        messages = self.message_history
        
        if sender:
            messages = [m for m in messages if m.sender == sender]
        
        if recipient:
            messages = [m for m in messages if m.recipient == recipient]
        
        if message_type:
            messages = [m for m in messages if m.message_type == message_type]
        
        return messages[-limit:]
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get communication bus statistics.
        
        Returns:
            Dictionary with statistics
        """
        return {
            "total_messages": len(self.message_history),
            "pending_requests": len(self.pending_requests),
            "registered_agents": len(self.handlers),
            "queue_size": self.message_queue.qsize(),
            "by_type": {
                msg_type.value: len([
                    m for m in self.message_history 
                    if m.message_type == msg_type
                ])
                for msg_type in MessageType
            }
        }
    
    def save_history(self, filepath: str):
        """
        Save message history to file.
        
        Args:
            filepath: Path to save history
        """
        with open(filepath, 'w') as f:
            json.dump([asdict(msg) for msg in self.message_history], f, indent=2)


class AgentCommunicator:
    """
    Helper class for agents to communicate with each other.
    
    Provides a simpler interface for agents to send and receive messages.
    """
    
    def __init__(self, agent_name: str, bus: AgentCommunicationBus):
        """
        Initialize agent communicator.
        
        Args:
            agent_name: Name of this agent
            bus: Communication bus instance
        """
        self.agent_name = agent_name
        self.bus = bus
        self.handlers: List[str] = []
    
    async def send(
        self,
        recipient: str,
        content: Dict[str, Any],
        priority: Priority = Priority.NORMAL
    ) -> str:
        """Send a message to another agent."""
        return await self.bus.send_message(
            sender=self.agent_name,
            recipient=recipient,
            message_type=MessageType.NOTIFICATION,
            content=content,
            priority=priority
        )
    
    async def request(
        self,
        recipient: str,
        content: Dict[str, Any],
        timeout: float = 30.0
    ) -> Optional[Dict[str, Any]]:
        """Send a request and get response."""
        response = await self.bus.send_request(
            sender=self.agent_name,
            recipient=recipient,
            content=content,
            timeout=timeout
        )
        return response.content if response else None
    
    async def respond(
        self,
        recipient: str,
        content: Dict[str, Any],
        correlation_id: str
    ):
        """Send a response to a request."""
        await self.bus.send_response(
            sender=self.agent_name,
            recipient=recipient,
            content=content,
            correlation_id=correlation_id
        )
    
    async def broadcast(self, content: Dict[str, Any]):
        """Broadcast a message to all agents."""
        await self.bus.broadcast(
            sender=self.agent_name,
            content=content
        )
    
    def on_message(
        self,
        message_types: List[MessageType],
        callback: Callable[[Message], Optional[Message]]
    ):
        """
        Register a handler for specific message types.
        
        Args:
            message_types: Types of messages to handle
            callback: Handler function
        """
        handler_id = self.bus.register_handler(
            agent_name=self.agent_name,
            message_types=message_types,
            callback=callback
        )
        self.handlers.append(handler_id)
        return handler_id
    
    def cleanup(self):
        """Unregister all handlers."""
        for handler_id in self.handlers:
            self.bus.unregister_handler(handler_id)
        self.handlers.clear()
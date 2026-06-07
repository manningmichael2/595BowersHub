"""
WebSocket connection manager: tracks active connections per user,
broadcasts streaming events, handles disconnects gracefully.
"""

import logging
from typing import Dict, List, Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class StreamEvent:
    """A structured event to send over WebSocket."""

    def __init__(self, type: str, conversation_id: int = 0, data: Any = None):
        self.type = type
        self.conversation_id = conversation_id
        self.data = data

    def dict(self) -> Dict[str, Any]:
        return {
            "type": self.type,
            "conversation_id": self.conversation_id,
            "data": self.data,
        }


class WebSocketManager:
    """
    Manages active WebSocket connections for real-time streaming.
    Each user can have multiple connections (phone + desktop).
    """

    def __init__(self):
        # user_id → list of active WebSocket connections
        self.connections: Dict[int, List[WebSocket]] = {}

    @property
    def active_count(self) -> int:
        """Total number of active WebSocket connections."""
        return sum(len(conns) for conns in self.connections.values())

    async def connect(self, websocket: WebSocket, user_id: int):
        """Register a new WebSocket connection for a user."""
        await websocket.accept()
        self.connections.setdefault(user_id, []).append(websocket)
        logger.info(f"WebSocket connected: user={user_id} (total: {self.active_count})")

    def disconnect(self, websocket: WebSocket, user_id: int):
        """Remove a WebSocket connection."""
        if user_id in self.connections:
            try:
                self.connections[user_id].remove(websocket)
            except ValueError:
                pass
            if not self.connections[user_id]:
                del self.connections[user_id]
        logger.info(f"WebSocket disconnected: user={user_id} (total: {self.active_count})")

    async def stream_to_user(self, user_id: int, event: StreamEvent):
        """Send a streaming event to all of a user's connections."""
        if user_id not in self.connections:
            return

        dead_connections = []
        for ws in self.connections[user_id]:
            try:
                await ws.send_json(event.dict())
            except Exception:
                dead_connections.append(ws)

        # Clean up dead connections
        for ws in dead_connections:
            self.disconnect(ws, user_id)

    async def send_typing(self, user_id: int, conversation_id: int):
        """Send typing indicator."""
        await self.stream_to_user(user_id, StreamEvent(
            type="typing", conversation_id=conversation_id
        ))

    async def send_token(self, user_id: int, conversation_id: int, token: str):
        """Send a single streaming token."""
        await self.stream_to_user(user_id, StreamEvent(
            type="token", conversation_id=conversation_id, data=token
        ))

    async def send_skill_status(self, user_id: int, conversation_id: int, skill_name: str, status: str):
        """Send skill execution status update."""
        await self.stream_to_user(user_id, StreamEvent(
            type="skill_status", conversation_id=conversation_id,
            data={"skill": skill_name, "status": status}
        ))

    async def send_complete(self, user_id: int, conversation_id: int, message: Dict[str, Any]):
        """Send completed message with full metadata."""
        await self.stream_to_user(user_id, StreamEvent(
            type="complete", conversation_id=conversation_id, data=message
        ))

    async def send_context_captured(self, user_id: int, conversation_id: int, facts: List[str]):
        """Send context capture notification."""
        await self.stream_to_user(user_id, StreamEvent(
            type="context_captured", conversation_id=conversation_id, data={"facts": facts}
        ))

    async def send_error(self, user_id: int, conversation_id: int, message: str):
        """Send error message."""
        await self.stream_to_user(user_id, StreamEvent(
            type="error", conversation_id=conversation_id, data={"message": message}
        ))

    async def send_cancelled(self, user_id: int, conversation_id: int, message: str = "Response cancelled."):
        """Notify the client that an in-flight response was cancelled."""
        await self.stream_to_user(user_id, StreamEvent(
            type="cancelled", conversation_id=conversation_id, data={"message": message}
        ))
